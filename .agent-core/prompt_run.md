Run the full MOA-AG research pipeline exactly as specified in CLAUDE.md.

INPUTS
  Active ingredient(s): {compounds}
  Disease/condition:    {disease}

OUTPUT DIRECTORY
  Use `results/{run_dir}/` verbatim for every output file.
  It has already been created for you. Do NOT derive or increment a session
  number, and do NOT create any other results directory — a queue assigns run
  directories upstream, so deriving one here would collide with another run.

EXECUTION
  Work through Step 0 (provenance & plausibility gate) to Step 5 (final report),
  applying the Governing Scientific Policy in §3 and the per-step mandatory
  controls inline in §4. Delegate each step to a sub-agent per the §4 delegation
  rule, running Step 1 and Step 2 in parallel.

  Finish with the full Step-5 close-out: the report-qa agent loop until SHIP,
  then the report-pdf build to `result.pdf`.

HALTS ARE VALID OUTCOMES
  If the Step-0 provenance gate or the Step-3 specificity gate fires, write the
  corresponding HALT file and stop. Do not work around a gate, do not soften a
  failed test, and do not proceed to later steps. A well-evidenced NO-GO is a
  successful run.

ASKING THE REQUESTER A QUESTION
  You may use the AskUserQuestion tool when a decision genuinely changes the
  analysis and you cannot settle it from the data — an ambiguous compound or
  formula identity, a route of administration the source does not state, which
  of two disease definitions to model. Ask early, ask rarely, and give 2-4
  concrete options; a requester may not be watching, and an unanswered question
  resolves itself after a timeout with "proceed with your best judgement",
  which you must then honour and record as a stated assumption. Never ask for
  permission to run a step, and never ask a question whose answer is already in
  CLAUDE.md or in the data you can fetch.

  SUB-AGENTS CANNOT ASK. AskUserQuestion is unavailable inside a sub-agent, so
  a sub-agent that needs a decision must END its turn with a single final line:

    NEEDS_INPUT: <question> | <option A> | <option B>

  and stop there, leaving whatever work it has already done on disk. You, the
  orchestrator, relay that question with AskUserQuestion, then re-invoke the
  sub-agent with the answer supplied in its prompt. Do not answer on the
  requester's behalf, and do not let a sub-agent guess past a NEEDS_INPUT line.

{extra}
ENDING THE RUN — the line below is a SWITCH, not a formality
  The session stays open between your turns, so the requester can send a
  message and you continue with full context. Write this line ONLY when the
  pipeline is genuinely finished (or a gate halted it), because it ENDS the run:

    RUN_COMPLETE: <completed|halted> - <one-sentence plain-language verdict>

  Do not write it while you are still waiting on the requester.
