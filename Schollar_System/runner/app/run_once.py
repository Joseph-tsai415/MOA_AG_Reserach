"""One-shot CLI: run a single MOA job to completion.

    python -m service.run_once --compounds Curcumin --disease "Atopic Dermatitis"
    python -m service.run_once --kind probe            # infrastructure probe

This is the unit the queue worker will call. Keeping it a standalone entry
point means the container can be tested end-to-end with no AWS at all — which
is exactly how you should measure cost and wall-clock before sizing anything.

Exit codes
    0    completed  — report + PDF produced
   10    halted     — a CLAUDE.md §3 gate fired. A VALID scientific outcome.
    1    failed
  124    timed out
  130    cancelled (SIGINT/SIGTERM)
   78    configuration error
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Callable

from . import classify as classify_mod
from . import task_protection
from .claude_runner import answer_timeout_response, run_pipeline
from .config import settings
from .events import QUESTION_MESSAGE_MAX_CHARS, EventEmitter, file_sink, stdout_sink
from .naming import next_probe_dir, next_session_dir
from .progress import ProgressWatcher
from .prompt import (
    PROBE_MAX_COST_USD,
    PROBE_MAX_TURNS,
    PROBE_MODEL,
    PROBE_TIMEOUT_SECONDS,
    build_probe_prompt,
    build_prompt,
)

EXIT_CODES = {
    classify_mod.STATUS_COMPLETED: 0,
    classify_mod.STATUS_HALTED: 10,
    classify_mod.STATUS_FAILED: 1,
    classify_mod.STATUS_TIMED_OUT: 124,
    classify_mod.STATUS_CANCELLED: 130,
}

_cancelled = False


def _install_signal_handlers() -> None:
    def _handler(signum, _frame):
        global _cancelled
        _cancelled = True
        print(f"[run_once] signal {signum} — finishing current step, then classifying", file=sys.stderr)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass  # not on the main thread, or unsupported platform


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_once",
        description="Run one MOA-AG pipeline job headlessly via Claude Code.",
    )
    p.add_argument("--kind", choices=("moa", "probe"), default="moa",
                   help="'moa' = full CLAUDE.md pipeline; 'probe' = short infrastructure check "
                        "(doc/VERIFY_CONTRACT.md §3)")
    p.add_argument("--prompt", default="", help="probe only: task text (<= 2000 chars); default file task if empty")
    p.add_argument("--compounds", default="",
                   help="Comma-separated active ingredient(s), e.g. 'Curcumin' or 'Gallic acid,Phellopterin'")
    p.add_argument("--disease", default="", help="Disease/condition, e.g. 'Atopic Dermatitis'")
    p.add_argument("--run-id", default=None, help="External run id for event correlation (default: run dir name)")
    p.add_argument("--run-dir", default=os.environ.get("MOA_RUN_DIR") or None,
                   help="Run directory name under results/. Assigned upstream in service mode; "
                        "derived by scanning results/ when omitted (LOCAL ONLY — races under a queue).")
    p.add_argument("--extra", default="", help="Additional requester context (never relaxes a gate)")
    p.add_argument("--model", default=None, help=f"default: {settings.model} (probe: {PROBE_MODEL})")
    p.add_argument("--max-turns", type=int, default=None)
    p.add_argument("--timeout", type=int, default=None, help="Wall-clock seconds")
    p.add_argument("--max-cost", type=float, default=None, help="USD soft cap; 0 disables")
    p.add_argument("--resume", default=None, help="Resume a crashed run from its agent session id")
    p.add_argument("--idle-wait", type=float, default=None,
                   help="Seconds to stay parked after a turn ends, waiting for the user's next "
                        "message, instead of finishing (default: MOA_IDLE_WAIT_SECONDS, 0 = off). "
                        "Needs a message source, so it only has an effect under the worker.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the resolved run dir and prompt, then exit without calling Claude")
    return p


def split_values(raw: str) -> list[str]:
    """Comma-separated CLI value -> list. Lifted verbatim from main_async's
    `[c.strip() for c in (args.compounds or "").split(",") if c.strip()]` so the
    conversion has one definition and can be pinned by a test."""
    return [v.strip() for v in (raw or "").split(",") if v.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = build_parser()
    args = p.parse_args(argv)
    if args.kind == "moa" and not (args.compounds.strip() and args.disease.strip()):
        p.error("--compounds and --disease are required for --kind moa")
    apply_kind_defaults(args)
    return args


def apply_kind_defaults(args: argparse.Namespace) -> argparse.Namespace:
    """Fill unset model/limits from the job kind. Probes get the contract's
    small defaults (VERIFY_CONTRACT §2) and a hard PROBE_MAX_COST_USD ceiling."""
    probe = getattr(args, "kind", "moa") == "probe"
    if not getattr(args, "model", None):
        args.model = PROBE_MODEL if probe else settings.model
    if not getattr(args, "max_turns", None):
        args.max_turns = PROBE_MAX_TURNS if probe else settings.max_turns
    if not getattr(args, "timeout", None):
        args.timeout = PROBE_TIMEOUT_SECONDS if probe else settings.timeout_seconds
    if getattr(args, "max_cost", None) is None or (probe and not args.max_cost):
        args.max_cost = PROBE_MAX_COST_USD if probe else settings.max_cost_usd
    if probe:
        args.max_cost = min(float(args.max_cost), PROBE_MAX_COST_USD)
    if getattr(args, "idle_wait", None) is None:
        args.idle_wait = settings.idle_wait_seconds
    return args


ANSWER_POLL_SECONDS = 2.0


def question_summary(questions: list) -> str:
    """One line for the event message: the first question, headers for the rest."""
    if not questions:
        return "Claude asked a question"
    first = questions[0] or {}
    text = str(first.get("question") or first.get("header") or "").strip()
    line = text or "Claude asked a question"
    if len(questions) > 1:
        extra = ", ".join(
            str((q or {}).get("header") or "?").strip() for q in questions[1:]
        )
        line = f"{line} (+{len(questions) - 1}: {extra})"
    return line[:QUESTION_MESSAGE_MAX_CHARS]


def build_question_handler(
    run_id: str,
    emitter: EventEmitter,
    answer_source: Any,
    *,
    timeout_seconds: int,
    poll_seconds: float = ANSWER_POLL_SECONDS,
    protect_minutes: int | None = None,
):
    """The AskUserQuestion handler (doc/VERIFY_CONTRACT.md §12.3).

    Emit `agent.question` → park the run on `waiting_input` → poll the run
    record every `poll_seconds` for an answer that matches THIS questionId →
    emit `agent.answer` → put the run back to `running`. Returns the answer
    payload, or None on timeout (the caller turns that into the contract's
    proceed-anyway response). The run's wall-clock deadline is shifted by the
    wait in `claude_runner.run_pipeline`; ECS task protection is re-armed here,
    because the original grant was sized for a run that was not going to sit
    idle waiting for a human.

    `answer_source` is a small blocking object (publish/poll/resume) — the
    worker passes `cloud.DynamoAnswerSource`. Every call goes through
    `asyncio.to_thread` so boto3 never blocks the agent's event loop, and every
    call is guarded: a broken mailbox degrades to the timeout path, it never
    kills a paid run.

    The handler also takes the live `inbox` (VERIFY_CONTRACT §15) when
    `run_pipeline` has one. While this question is pending the message injector
    is paused, and this loop drains the inbox FIRST on every tick: a message
    typed while the run says `waiting_input` IS this question's free-text
    answer, not a separate turn. One input, one meaning — the alternative is
    the answer and the message racing each other into the same session.
    """

    async def _safe(fn, *fn_args) -> Any:
        try:
            return await asyncio.to_thread(fn, *fn_args)
        except Exception as exc:
            print(f"[run_once] answer source {getattr(fn, '__name__', fn)} failed: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return None

    async def _from_inbox(inbox: Any) -> dict | None:
        """A message typed while this question is pending, as its answer."""
        if inbox is None:
            return None
        try:
            messages = await inbox.take_for_question()
        except Exception as exc:
            print(f"[run_once] inbox drain failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return None
        if not messages:
            return None
        return {
            "response": "\n".join(m["text"] for m in messages),
            "messageIds": [m["messageId"] for m in messages],
        }

    async def handler(input_data: dict, inbox: Any = None) -> dict | None:
        questions = list((input_data or {}).get("questions") or [])
        question_id = f"q_{run_id}_{emitter.peek_next_seq()}"

        emitter.emit(
            "agent.question",
            question_summary(questions),
            questionId=question_id,
            questions=questions,
            timeoutSeconds=int(timeout_seconds),
        )
        # timeout_seconds travels with the pending question: askedAt +
        # timeoutSeconds is what the UI counts down from, and the window is an
        # operator setting that can differ between runs.
        await _safe(answer_source.publish, question_id, questions, int(timeout_seconds))

        deadline = time.monotonic() + float(timeout_seconds)
        answer: dict | None = None
        # Anything the injector claimed but had not yet sent when the question
        # opened is carried over — drain before the first sleep so it is not
        # stranded for a whole poll interval.
        answer = await _from_inbox(inbox)
        while answer is None and time.monotonic() < deadline:
            await asyncio.sleep(poll_seconds)
            # Inbox first: a message typed now is meant as the reply.
            answer = await _from_inbox(inbox)
            if answer:
                break
            answer = await _safe(answer_source.poll, question_id)
            if answer:
                break

        if answer:
            emitter.emit(
                "agent.answer",
                _answer_summary(answer),
                questionId=question_id,
                answers=answer.get("answers") or None,
                response=answer.get("response") or None,
                fromMessageIds=answer.get("messageIds") or None,
            )
        else:
            emitter.emit(
                "agent.answer",
                answer_timeout_response(timeout_seconds),
                questionId=question_id,
                timedOut=True,
                response=answer_timeout_response(timeout_seconds),
            )

        await _safe(answer_source.resume)
        # Re-arm scale-in protection: the first grant was sized for the run's
        # wall clock, and the wait just spent some of it. No-op off Fargate.
        if protect_minutes:
            try:
                task_protection.acquire(expires_in_minutes=protect_minutes)
            except Exception as exc:
                print(f"[run_once] task protection re-acquire failed: "
                      f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return answer

    return handler


def build_idle_handler(
    run_id: str,
    emitter: EventEmitter,
    answer_source: Any = None,
    *,
    cancel_check: Any = None,
    poll_seconds: float = ANSWER_POLL_SECONDS,
    protect_minutes: int | None = None,
):
    """The between-turns idle wait — what turns a run into a conversation.

    A run used to end the moment the agent stopped talking. A probe told to
    "write these files, then wait for my next instruction" wrote the files and
    went `run.completed` 24 seconds later: the window in which a message could
    be typed had already closed, so §15's inbox had nothing to deliver into.

    So: on a clean turn end, emit `agent.idle`, park the run record on
    `waiting_input` with NO pendingQuestion (a bare `waiting_input` means "say
    anything"; with a question it means "pick one"), then poll the inbox. The
    first message returns its text, which the caller feeds to `client.query()`
    — another turn on the SAME session, with the whole run's context.

    Returns the resuming text, or None to finish the run. None means one of
    three things, and all three are normal: nobody spoke within the window, the
    run was cancelled, or the mailbox is broken. Every failure degrades to
    "finish the run", never to a hang — this is the path an unattended job
    takes, and it must always terminate.
    """

    async def _safe(fn, *fn_args) -> Any:
        if fn is None:
            return None
        try:
            return await asyncio.to_thread(fn, *fn_args)
        except Exception as exc:
            print(f"[run_once] idle source {getattr(fn, '__name__', fn)} failed: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return None

    async def handler(inbox: Any, wait_seconds: float) -> str | None:
        seconds = int(wait_seconds)
        emitter.emit(
            "agent.idle",
            f"Waiting up to {seconds}s for your next message",
            waitSeconds=seconds,
        )
        await _safe(getattr(answer_source, "park_idle", None))

        deadline = time.monotonic() + float(wait_seconds)
        text: str | None = None
        cancelled = False
        while time.monotonic() < deadline:
            # Inbox first, so a message already waiting resumes the session
            # without paying a poll interval for it.
            try:
                messages = await inbox.take_for_idle()
            except Exception as exc:
                print(f"[run_once] idle inbox drain failed: {type(exc).__name__}: {exc}",
                      file=sys.stderr)
                messages = []
            if messages:
                text = "\n".join(m["text"] for m in messages)
                break
            # Checked every tick, not every heartbeat: a cancelled run must not
            # sit parked for the rest of its idle window burning a worker slot.
            if cancel_check is not None and await _safe(cancel_check):
                cancelled = True
                break
            await asyncio.sleep(poll_seconds)

        if text is not None:
            await _safe(getattr(answer_source, "resume", None))
            # The wait was the human's; the grant made at run start assumed a
            # session that would not sit idle. Re-arm before the next turn.
            if protect_minutes:
                try:
                    task_protection.acquire(expires_in_minutes=protect_minutes)
                except Exception as exc:
                    print(f"[run_once] task protection re-acquire failed: "
                          f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return text

        emitter.emit(
            "agent.activity",
            "Cancellation requested — ending the session."
            if cancelled else
            f"No further messages within {seconds}s — finishing the run.",
        )
        # Back to `running` so the run is not left advertising `waiting_input`
        # while it classifies and writes its summary; the terminal event lands
        # moments later.
        await _safe(getattr(answer_source, "resume", None))
        return None

    return handler


def _answer_summary(answer: dict) -> str:
    answers = answer.get("answers")
    if isinstance(answers, dict) and answers:
        parts = []
        for value in answers.values():
            parts.append(", ".join(str(v) for v in value) if isinstance(value, list) else str(value))
        return " · ".join(parts)[:QUESTION_MESSAGE_MAX_CHARS]
    return str(answer.get("response") or "answered")[:QUESTION_MESSAGE_MAX_CHARS]


async def main_async(
    args: argparse.Namespace,
    *,
    extra_sinks: list | None = None,
    artifact_sync_factory: Callable[[str, Path, EventEmitter], Any] | None = None,
    answer_source: Any = None,
    message_source: Any = None,
    cancel_check: Any = None,
) -> int:
    """Run one job.

    `extra_sinks` lets the queue worker add a DynamoDB sink so events reach the
    frontend live, and `artifact_sync_factory(run_id, run_dir, emitter)` lets it
    attach the live S3 sync — both without this module importing boto3. The
    sync object needs `start()` and an idempotent `stop()` that does a final
    sync; it is stopped after run_summary.json is written and before the
    terminal event, so the summary is in S3 by the time the run reads terminal.

    `answer_source` (publish/poll/resume) makes the session interactive. It is
    supplied only by the worker, which has a run record to use as the mailbox:
    run_once on its own stays headless, so AskUserQuestion resolves immediately
    with the proceed-anyway text instead of waiting for an answer that can
    never arrive.

    `message_source` (an async callable returning new `{messageId, text}`
    entries) makes the run *reachable* mid-flight — the worker passes
    `cloud.DynamoInboxSource`. Also worker-only, and independent of
    `answer_source`: a run may have neither, either, or both.

    `cancel_check` (a blocking predicate, the worker passes
    `cloud.cancel_requested`) is polled every tick of an idle wait, so a
    cancelled run stops parking immediately instead of holding a worker slot
    for the rest of its idle window.
    """
    apply_kind_defaults(args)
    kind = getattr(args, "kind", "moa") or "moa"
    if kind not in ("moa", "probe"):
        print(f"[run_once] unknown job kind {kind!r}", file=sys.stderr)
        return 78
    probe = kind == "probe"

    compounds = split_values(args.compounds)
    disease = (args.disease or "").strip()
    if not probe and not compounds:
        print("[run_once] --compounds resolved to an empty list", file=sys.stderr)
        return 78

    results_root = settings.results_root
    if probe:
        run_dir_name = args.run_dir or next_probe_dir(results_root)
    else:
        run_dir_name = args.run_dir or next_session_dir(results_root, compounds, disease)
    run_dir = results_root / run_dir_name
    run_id = args.run_id or run_dir_name

    if probe:
        prompt = build_probe_prompt(run_dir_name, getattr(args, "prompt", "") or None)
    else:
        prompt = build_prompt(compounds, disease, run_dir_name, extra_instructions=args.extra)

    if args.dry_run:
        print(json.dumps({
            "run_id": run_id, "run_dir": run_dir_name, "kind": kind,
            "abs_path": str(run_dir), "model": args.model,
        }, indent=2))
        print("\n--- prompt ---\n" + prompt)
        return 0

    # The agent is told the directory already exists; make that true.
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "scripts").mkdir(exist_ok=True)
    (run_dir / "data").mkdir(exist_ok=True)
    (run_dir / "figures").mkdir(exist_ok=True)

    emitter = EventEmitter(
        run_id,
        sinks=[stdout_sink, file_sink(run_dir / "_events.jsonl"), *(extra_sinks or [])],
    )
    start_phase = "probe" if probe else "provenance"
    emitter.emit(
        "run.started",
        "Infrastructure probe" if probe else f"{', '.join(compounds)} × {disease}",
        phase=start_phase, percent=0,
        kind=kind, compounds=compounds, disease=disease,
        run_dir=run_dir_name, model=args.model,
        max_turns=args.max_turns, timeout_seconds=args.timeout,
        max_cost_usd=args.max_cost or None,
    )

    sync = None
    if artifact_sync_factory is not None:
        try:
            sync = artifact_sync_factory(run_id, run_dir, emitter)
            sync.start()
        except Exception as exc:  # live sync is observability; never block the run on it
            print(f"[run_once] live artifact sync failed to start: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            sync = None

    try:
        # Milestone files are MOA-specific; a probe has no pipeline phases.
        watcher = None if probe else ProgressWatcher(run_dir, emitter, poll_seconds=settings.poll_seconds)
        if watcher:
            watcher.start()
        started = time.time()

        # Interactive only when there is somewhere for an answer to come from.
        answer_timeout = settings.answer_timeout_seconds
        question_handler = None
        if answer_source is not None:
            question_handler = build_question_handler(
                run_id, emitter, answer_source,
                timeout_seconds=answer_timeout,
                protect_minutes=int(args.timeout / 60) + 15,
            )

        # Idle continuation needs somewhere for a message to come FROM; with no
        # message source a park could only ever time out, so don't park at all.
        idle_wait = float(getattr(args, "idle_wait", None) or settings.idle_wait_seconds or 0.0)
        idle_handler = None
        if message_source is not None and idle_wait > 0:
            idle_handler = build_idle_handler(
                run_id, emitter, answer_source,
                cancel_check=cancel_check,
                poll_seconds=settings.inbox_poll_seconds,
                protect_minutes=int(args.timeout / 60) + 15,
            )

        try:
            agent = await run_pipeline(
                prompt,
                repo_root=settings.repo_root,
                emitter=emitter,
                model=args.model,
                max_turns=args.max_turns,
                permission_mode=settings.permission_mode,
                permission_mode_explicit=settings.permission_mode_explicit,
                timeout_seconds=args.timeout,
                max_cost_usd=args.max_cost,
                tool_event_every=settings.tool_event_every,
                resume_session_id=args.resume,
                question_handler=question_handler,
                answer_timeout_seconds=answer_timeout,
                message_source=message_source,
                inbox_poll_seconds=settings.inbox_poll_seconds,
                idle_handler=idle_handler,
                idle_wait_seconds=idle_wait if idle_handler else 0.0,
                idle_budget_seconds=settings.idle_budget_seconds,
            )
        finally:
            if watcher:
                watcher.stop()

        elapsed = round(time.time() - started, 1)
        if probe:
            outcome = classify_mod.classify_probe(
                run_dir,
                timed_out=agent.timed_out,
                cancelled=_cancelled,
                budget_exceeded=agent.budget_exceeded,
                agent_error=agent.error,
                agent_subtype=agent.subtype,
                got_result=agent.subtype is not None,
            )
        else:
            outcome = classify_mod.classify(
                run_dir,
                timed_out=agent.timed_out,
                cancelled=_cancelled,
                agent_error=agent.error or agent.final_text,
            )

        summary = {
            "run_id": run_id,
            "run_dir": run_dir_name,
            "kind": kind,
            "compounds": compounds,
            "disease": disease,
            "status": outcome.status,
            "reason": outcome.reason,
            "verdict": outcome.verdict,
            "qa_verdict": outcome.qa_verdict,
            "detail": outcome.detail,
            "elapsed_seconds": elapsed,
            "agent": {
                "session_id": agent.session_id,
                "model": args.model,
                "cost_usd": round(agent.cost_usd, 4),
                "input_tokens": agent.input_tokens,
                "output_tokens": agent.output_tokens,
                "num_turns": agent.num_turns,
                "tool_uses": agent.tool_uses,
                "budget_exceeded": agent.budget_exceeded,
                "timed_out": agent.timed_out,
                "error": agent.error,
                "subtype": agent.subtype,
                "permission_mode": agent.permission_mode,
                "questions_asked": agent.questions_asked,
                # Time the run spent parked on a question — excluded from the
                # wall clock, so elapsed_seconds and the timeout differ by it.
                "answer_wait_seconds": round(agent.deadline_shift_seconds, 1),
                # Mid-run messages that reached the live session, and how many
                # of those landed as a pending question's free-text answer
                # rather than as their own turn (VERIFY_CONTRACT §15).
                "messages_injected": agent.messages_injected,
                "messages_as_answer": agent.messages_as_answer,
                # The session's shape: how many times it parked waiting for the
                # user, and how many of those parks a message woke into another
                # turn. idle_waits > turns_from_messages means it waited and
                # nobody spoke — which is how a conversational run ends.
                "idle_waits": agent.idle_waits,
                "turns_from_messages": agent.turns_from_messages,
                # Total parked time, and whether the run ended because the
                # idle budget ran out rather than because nobody replied.
                "idle_seconds": round(agent.idle_seconds, 1),
                "idle_budget_exhausted": agent.idle_budget_exhausted,
            },
            "artifacts": outcome.artifacts,
        }
        # run_summary.json is the worker's machine-readable handoff: the queue
        # worker reads exactly this to update DynamoDB. Written for probes too.
        (run_dir / "run_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Final sync BEFORE the terminal event: when the frontend sees the run
        # go terminal, every artifact (incl. run_summary.json) is already in S3.
        if sync is not None:
            sync.stop()

        terminal_type = {
            classify_mod.STATUS_COMPLETED: "run.completed",
            classify_mod.STATUS_HALTED: "run.halted",
        }.get(outcome.status, "run.failed")

        phase = start_phase if watcher is None else watcher.phase
        last_percent = 0 if watcher is None else watcher.percent
        emitter.emit(
            terminal_type,
            outcome.verdict or outcome.detail,
            phase=phase,
            percent=100 if outcome.is_deliverable else last_percent,
            kind=kind,
            status=outcome.status, reason=outcome.reason,
            qa_verdict=outcome.qa_verdict,
            cost_usd=round(agent.cost_usd, 4), elapsed_seconds=elapsed,
            artifact_count=len(outcome.artifacts),
        )
    finally:
        if sync is not None:
            # Idempotent. On the normal path this only re-uploads the tail of
            # _events.jsonl (the terminal event); on an exception path it is
            # the final sync that keeps partial work.
            sync.stop()

    print(
        f"\n[run_once] {outcome.status.upper()} · {elapsed}s · ${agent.cost_usd:.2f} · "
        f"{len(outcome.artifacts)} artifacts · {run_dir}",
        file=sys.stderr,
    )
    return EXIT_CODES.get(outcome.status, 1)


def main(argv: list[str] | None = None) -> int:
    _install_signal_handlers()
    try:
        return asyncio.run(main_async(parse_args(argv)))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
