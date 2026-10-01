# agent-harness — extraction and genericization

**Date:** 2026-10-01
**Status:** approved, ready for implementation plan
**Scope:** extract `MOA_AG_Reserach/Schollar_System/` into its own repository named
`agent-harness`, make its container build context self-contained, and replace the
MOA-specific knowledge in its service layer with a payload-declared manifest, so the
harness can run any agent core rather than only MOA-AG Research.

---

## 1. Problem

`Schollar_System/` is the service layer that runs the MOA-AG pipeline headlessly with
Claude Code as the task runner. It is fused to the science repository in three ways:

1. **Build context.** The Dockerfile's context is the *repo root*, not the runner
   directory. It reaches upward with `COPY CLAUDE.md`, `COPY moa_lib/`, `COPY .claude/`,
   and `docker-compose.yml` sets `context: ../..`. The container cannot be built without
   the science repo sitting exactly one level up.
2. **The repo-root `.dockerignore` belongs to the container, not the science project.**
   It is entirely a statement about what the image needs, including an MOA-specific
   exception for a 322 MB reference file.
3. **The service layer hard-codes MOA concepts.** Six of thirteen modules carry MOA
   artifact names, MOA CLI flags, MOA halt files and MOA package names.

The consequence is that the harness — which is genuinely reusable infrastructure — cannot
be pointed at a different agent core without editing its source.

### What is already clean

Nothing under `Schollar_System/` imports `moa_lib`. The boundary rule in CLAUDE.md §8
has held: the service layer references the science only as filenames, paths and
section numbers. `claude_runner.py` (1259 lines — the Claude Agent SDK driver, and by far
the hardest part to write) contains **zero** MOA references and needs no change.

So this is a packaging and configuration problem, not a rewrite.

### Measured coupling

| Module | Lines | MOA-specific content | Shape |
|---|---:|---|---|
| `progress.py` | 135 | 14 `step*.md` milestones + 2 HALT filenames | data table |
| `classify.py` | 256 | halt→reason map, `Bottom Line` heading, QA verdict regex | data + regex |
| `naming.py` | 71 | compound/disease folder rule | template |
| `prompt.py` | 207 | the trigger prompt text | template file |
| `run_once.py` | 644 | `--compounds` / `--disease` flags | input schema |
| `worker.py` | 337 | SQS body field names | input schema |
| `entrypoint.sh` | — | asserts `moa_lib`, `hsa_MTI.csv` | path list |
| `smoke_test.py` | 230 | `moa_lib` import check | path list |
| `claude_runner.py` | 1259 | **none** | — |
| `cloud.py`, `events.py`, `sanitize.py`, `task_protection.py`, `config.py` | — | **none** (config.py: env names only) | — |

Every MOA-specific item is a **table, template or path list** — declarative data, never an
algorithm. That is what makes a manifest sufficient.

### Two latent defects this work fixes

- **The image can only be built on a machine that already downloaded `hsa_MTI.csv`.** The
  file is 322 MB, exceeds GitHub's 100 MB per-file limit, is therefore not in git, and is
  self-provisioned by a script — yet `Dockerfile` and `entrypoint.sh` both hard-fail
  without it. A fresh clone cannot build. This becomes fatal once the core arrives by
  submodule, because a submodule checkout is a clean clone.
- **The module name differs between the two supported run paths.** `app.run_once`
  natively, `service.run_once` in the container, because `app/` is copied to
  `/app/service/`. `runner/README.md` documents this as intentional; it is a wart.

## 2. Decisions

Settled during design review:

| Decision | Choice | Rationale |
|---|---|---|
| Name | **`agent-harness`** | Names what is harnessed (an agent core), not the mechanism. Correct for both the Docker and the native `run_local` path. `Schollar_System` is retired as a name so there are not two names for one thing. |
| Repo topology | Own git repo, sibling directory | The harness is root-level infrastructure; the science repo becomes one payload among others. |
| Product split | One repo | The Schollar web app (`frontend-amplify/`, `backend-handler/`, `infra/`) ships alongside as the reference service that consumes the harness. |
| Core injection | Build-time, from a drop-in directory | Copy any core in; every build packs it into the image. Preserves today's fast, offline, reproducible image. |
| Core slot | Two locations | `cores/slot/` is the gitignored copy-paste slot; `cores/<name>/` holds submodule-pinned cores. A build arg selects one. |
| Pinning | git submodule | `cores/moa-ag/` → `MOA_AG_Reserach`, so an image is traceable to an exact science-core commit. |
| Staging | Big bang | Extraction and genericization ship together, made survivable by golden-output tests written first (§7). |
| Old copy | Kept, frozen | `MOA_AG_Reserach/Schollar_System/` stays as a rollback path, marked dead with `MOVED.md`. |
| Env prefix | `MOA_*` → `HARNESS_*`, hard rename, no aliases | `infra/` is written but never deployed and `frontend-amplify/` is barely started; this is the cheapest it will ever be. |
| AWS resource names | Keep a `schollar-*` prefix, but as a configurable deployment namespace | The harness's name and a deployment's name are different things; one account could host several harness deployments. |

## 3. Target layout

```
D:\Dev\projects\agent-harness\          # own git root = Docker build context
├── CLAUDE.md                           # harness dev manual (NEVER shipped in the image)
├── .claude/                            # harness's own agents/skills (NEVER shipped)
├── .dockerignore                       # generic patterns only
├── .gitmodules
├── harness/                            # the python package (was runner/app/)
│   ├── manifest.py                     # NEW — load + validate agent-core.yaml
│   ├── preflight.py                    # NEW — manifest-driven environment checks
│   ├── claude_runner.py                # unchanged
│   ├── cloud.py · events.py · sanitize.py · task_protection.py   # unchanged
│   ├── config.py                       # HARNESS_* env names + core/manifest paths
│   ├── progress.py · classify.py · naming.py · prompt.py         # tables → manifest
│   ├── run_once.py · worker.py         # inputs → manifest
│   └── smoke_test.py                   # moved into the package: python -m harness.smoke_test
├── container/                          # container assets (was runner/)
│   ├── Dockerfile · docker-compose.yml · entrypoint.sh · run_local.ps1
│   ├── .env.example · watch_run.ps1
│   ├── requirements/platform.txt       # service-layer deps ONLY
│   └── conda · conda-init.sh
├── cores/
│   ├── slot/                           # gitignored copy-paste slot (default)
│   │   └── README.md                   # tracked: "drop any agent core here"
│   ├── moa-ag/                         # git submodule → MOA_AG_Reserach
│   └── hello-core/                     # NEW — trivial core; the genericity proof
├── manifests/                          # sidecar manifests for cores you cannot edit
├── backend-handler/ · infra/ · frontend-amplify/ · doc/
└── tests/                              # NEW — golden-output tests
```

Every `COPY` in the Dockerfile resolves inside this root — `container/`, `harness/`,
`cores/${HARNESS_CORE}/`. Nothing reaches above the build context, which is the structural
property that makes the repo self-contained.

`manifests/` is deliberately **not** inside `cores/`, so it can never be mistaken for a
core named `manifests` when resolving `HARNESS_CORE`.

### In-container paths

| Path | Contents | Why |
|---|---|---|
| `/app/` | **the agent core, verbatim** — `CLAUDE.md`, `.claude/`, payload packages, `results` symlink | Claude's cwd. Keeping it purely the core's means no name can collide with the harness. |
| `/opt/harness/` | the harness package, on `PYTHONPATH` | Today both share `/app`, so a core containing `app/` or `service/` would collide. |
| `/data/results` | run output volume | unchanged; `/app/results` symlinks to it so CLAUDE.md §8 relative paths keep working |

Module name unifies to `harness`: `python -m harness.run_once` both natively and in the
container, retiring the `app.` vs `service.` split.

## 4. The agent-core contract

A core is a directory that describes itself with one file at its root. Resolution order:

1. `<core>/agent-core.yaml`
2. `manifests/<core-name>.yaml` (sidecar, for cores you cannot modify)
3. **fail the build** — a missing manifest is an error, never a silent generic default
   (CLAUDE.md §5, *build essentials in as the single default — no optional variants*).

The manifest lives in the payload so that one copied folder is self-describing, which is
what makes "copy any core in and build" true. It is the core declaring itself, the way a
`pyproject.toml` declares a package.

### Schema (`schema: 1`)

```yaml
schema: 1
core:
  name: moa-ag
  display_name: "MOA-AG network pharmacology pipeline"
  version: v11.2                   # free text; surfaced in events and image labels

agent:
  instructions: CLAUDE.md          # the operating manual the agent reads
  setting_sources: [project]       # SDK setting_sources — without it CLAUDE.md is invisible
  run_dir_env: MOA_RUN_DIR         # payload names it, so CLAUDE.md §2 needs no edit
  defaults:
    model: claude-opus-5
    max_turns: 400
    permission_mode: bypassPermissions

python:
  conda_env: moa                   # CLAUDE.md §7 says `conda activate moa` — payload's choice
  package_paths: [moa_lib]         # prepended to PYTHONPATH
  import_check: [moa_lib.citation_grounding, moa_lib.provenance, rdkit, matplotlib_venn]
  requirements:
    base:  runner-requirements/base.txt
    omics: runner-requirements/omics.txt
    full:  runner-requirements/full.txt
  default_profile: omics

inputs:                            # → CLI flags, API schema, prompt variables
  - {name: compounds, type: string_list, required: true, cli: --compounds}
  - {name: disease,   type: string,      required: true, cli: --disease}
  - {name: notes,     type: string,      required: false, cli: --notes}

run_dir:
  template: "{compounds.first|slug}_{disease|slug}"
  fallback: "{disease|slug}"
  session_suffix: "_session{n}"
  probe_base: probe

prompt:
  run:   .agent-core/prompt_run.md
  probe: .agent-core/prompt_probe.md

progress:
  milestones:                      # all 14 from today's progress.py, verbatim
    - {artifact: step0_provenance.md,          phase: provenance,    percent: 5,   label: "Provenance & plausibility gate"}
    - {artifact: step1_target_list_A.md,       phase: targets,       percent: 20,  label: "Compound targets (List A)"}
    - {artifact: step2_disease_genes_B.md,     phase: disease_genes, percent: 35,  label: "Disease genes (List B)"}
    - {artifact: step2_disease_signature.md,   phase: disease_genes, percent: 38,  label: "Data-driven disease signature"}
    - {artifact: step3_hub_targets.md,         phase: intersection,  percent: 45,  label: "Hub targets locked"}
    - {artifact: step4_moa_summary.md,         phase: mechanism,     percent: 60,  label: "Mechanism narrative"}
    - {artifact: step4_moa_table.md,           phase: mechanism,     percent: 65,  label: "MOA overview table"}
    - {artifact: step4_signature_reversal.md,  phase: mechanism,     percent: 68,  label: "L1000 signature reversal"}
    - {artifact: validation_plan.md,           phase: report,        percent: 75,  label: "Validation roadmap"}
    - {artifact: step5_final_report.md,        phase: report,        percent: 80,  label: "Final report drafted"}
    - {artifact: step5_confidence_dashboard.md, phase: report,       percent: 83,  label: "Confidence dashboard"}
    - {artifact: data_integrity_check.md,      phase: report,        percent: 86,  label: "Lineage self-audit"}
    - {artifact: report_qa_review.md,          phase: qa_review,     percent: 90,  label: "Report QA review"}
    - {artifact: result.pdf,                   phase: pdf,           percent: 100, label: "PDF deliverable"}

outcome:
  halts:                           # a halt is a VALID outcome, never a failure
    HALT_provenance.md: provenance_gate
    HALT_no_intersection.md: no_specificity
  success_requires: [step5_final_report.md]
  deliverable: result.pdf
  headline: {artifact: step5_final_report.md, section: "Bottom Line"}
  qa:
    artifact: report_qa_review.md
    verdicts: [SHIP, FIX-FIRST, BLOCK]
    blocking: [BLOCK]              # → status failed

image:
  required_paths: [CLAUDE.md, moa_lib, .claude/skills]
  reference_data:
    - path: .claude/skills/mirna-targets/data/hsa_MTI.csv
      min_bytes: 100000000
      required: true
      provision: "python .claude/skills/mirna-targets/scripts/download_reference_data.py"
  exclude:
    - results/
    - reviews/
    - reviews_archive/
    - Schollar_System/             # defensive: the frozen copy, if a working tree is copied in
    - .claude/settings.local.json
    - ".claude/skills/*/data/"
    - "!.claude/skills/mirna-targets/data/"
  env:
    MOA_CJK_FONT: /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc

artifacts:
  exclude: [_pdf_preview/, geo_tmp/, tool-results/, "**/__pycache__/**"]
```

### `run_dir` resolution — exact semantics

This is the rule Layer 1 pins, so it is stated unambiguously rather than left to the
reader. To render a run directory name:

1. Render `template`. A `|slug` filter lowercases, replaces every run of non-`[a-z0-9]`
   with `_`, and strips leading/trailing `_`. `.first` on a list input takes element 0.
2. Use `fallback` instead of `template` if **either**: a list-typed input referenced by
   `template` has more than one element, **or** any `|slug` in `template` renders empty.
3. If `fallback` also renders empty, **raise** — the caller must transliterate upstream.
4. Append `session_suffix` with `n` = (highest existing session index for this base) + 1,
   where a bare directory equal to the base counts as index 1.

That reproduces today's `naming.base_name` exactly: single compound → `curcumin_atopic_dermatitis`;
two compounds → `atopic_dermatitis`; CJK-only compound (`七白散`) → `atopic_dermatitis`;
CJK-only disease → `ValueError`.

### Core selection

`ARG HARNESS_CORE=slot` → `COPY cores/${HARNESS_CORE}/ /stage/core/`.

- `docker compose build` → `cores/slot/` (the copy-paste slot)
- `HARNESS_CORE=moa-ag docker compose build` → the submodule-pinned core

One path in the Dockerfile, two ways to fill it.

## 5. Service-layer changes

| Module | Change | Logic touched |
|---|---|---|
| `manifest.py` | **NEW.** Load YAML, validate against schema 1, fail with the exact offending key. `pyyaml` + dataclasses; no new heavy dependency. | — |
| `preflight.py` | **NEW.** The checks `entrypoint.sh` hard-codes today, driven by `image.required_paths`, `reference_data`, `python.import_check`. | same checks, declared |
| `progress.py` | `MILESTONES` / `HALT_FILES` become constructor arguments sourced from the manifest. | none |
| `classify.py` | halts, `success_requires`, `headline`, `qa` from manifest. `_INFRA_FAILURES` **stays in the harness** — credit exhaustion, auth failure, rate limiting and overload are platform concerns, not payload concerns. | none |
| `naming.py` | `base_name()` becomes a template renderer over `run_dir`. `slugify()` and the session scan are unchanged. | thin new renderer |
| `prompt.py` | Inline template becomes a load of the manifest's template files with `inputs` substituted. Required-field validation driven by `inputs[].required`. | none |
| `run_once.py` | `argparse` built from `inputs[]`. | arg wiring only |
| `worker.py` | SQS body mapped to `inputs` generically. | arg wiring only |
| `config.py` | `HARNESS_*` env names; adds `core_root`, `manifest_path`, `core` selection. | none |
| `entrypoint.sh` | Hard-coded asserts replaced by `python -m harness.preflight`. | none |
| `smoke_test.py` | Manifest-driven path and import checks. | none |
| `claude_runner.py`, `cloud.py`, `events.py`, `sanitize.py`, `task_protection.py` | **unchanged** | — |

### Requirements split

`container/requirements/platform.txt` holds service-layer dependencies only —
`claude-agent-sdk`, `boto3`, `pyyaml`. The scientific stack moves to the payload at
`MOA_AG_Reserach/runner-requirements/{base,omics,full}.txt`. Today's `base.txt` states it
was "derived by scanning `moa_lib/` and every historical `results/*/scripts/*.py`" — it was
never platform code.

## 6. Build pipeline

Three stages:

1. **`builder`** — micromamba creates a conda env named `python.conda_env`; installs
   `container/requirements/platform.txt` plus the payload's selected tier. `conda` / `mamba`
   shims and the generated micromamba hook as today.
2. **`core-stage` (NEW)** — `COPY cores/${HARNESS_CORE}/` → prune per `image.exclude` →
   provision missing `reference_data` → assert `required_paths` and every `min_bytes`.
3. **`runtime`** — pruned core → `/app/`; harness → `/opt/harness/`; OS packages, CJK and
   symbol fonts, Node, then the Claude Code CLI **last** so a CLI release does not rebuild
   the 2.5 GB conda copy.

### Why a staging stage rather than `.dockerignore` alone

`.dockerignore` is static and context-root-relative; it cannot read a manifest. The two
split by what each is good at:

- `.dockerignore` keeps genuinely huge or universally irrelevant things out of the build
  *context*: `.git`, `results/`, `reviews/`, `reviews_archive/`, `node_modules/`,
  `__pycache__/`, `.venv/`, `*.log`, editor and OS noise.
- `core-stage` does the fine-grained, payload-declared pruning.

### Reference-data provisioning

Resolution order, for each `reference_data` entry:

1. Present in the core and ≥ `min_bytes` → use it. Zero network. This is the normal path
   and matches today's behaviour.
2. Absent → run `provision` into a BuildKit `--mount=type=cache`, so a retry after an
   upstream 504 does not re-download 322 MB. (`awi.cuhk.edu.cn` is unreliable enough that
   this matters — it is why the file was baked in originally.)
3. Still absent and `required: true` → **the build fails.** No warn-and-continue: a
   silently degraded miRNA-cargo run produces output that looks complete, which is the
   worst available failure mode.

This makes `git clone && git submodule update --init && docker compose build` work on a
fresh machine, which it currently does not.

## 7. Verification

Four layers. Layers 1–3 cost nothing; layer 4 costs real money.

### Layer 1 — golden-output tests, written BEFORE anything moves

The regression gate, and the entire safety argument for shipping extraction and
genericization together. Pytest fixtures pinning today's exact behaviour:

- **`naming`** — `base_name` for single compound, multi-compound, CJK-only compound
  (→ disease-only fallback), CJK-only disease (→ raises `ValueError`); `_next_for_base`
  session increment including the bare-`base` (no suffix) case.
- **`classify`** — fixture run directories for completed, `HALT_provenance.md`,
  `HALT_no_intersection.md`, failed, and a `BLOCK` QA verdict; plus `extract_bottom_line`
  across `#`–`####` heading depths and mixed case, and `extract_qa_verdict` tail-then-head
  scan order.
- **`progress`** — all 14 milestones fire once each, `phase.started` emitted once per
  phase, percent monotonic under out-of-order artifact writes.
- **`prompt`** — rendered output **byte-identical** to today's for both run and probe.
- **`run_once`** — today's exact CLI invocation still parses to the same values.

These tests must pass **unchanged** after the tables move into the manifest.

### Layer 2 — the `$0` smoke profile

`docker compose --profile smoke run --rm smoke`, extended and manifest-driven:

- core at `/app`, harness at `/opt/harness`, `PYTHONPATH` correct
- conda env exists under the name the manifest declares
- every `image.required_paths` entry present
- every `reference_data` entry present and ≥ `min_bytes`
- every `python.import_check` module imports
- SDK option contract intact, especially `setting_sources` — without it `CLAUDE.md` and
  `.claude/skills/` are invisible and a run silently degrades to chat
- **the harness's own `CLAUDE.md` and `.claude/` are absent from the image**

### Layer 3 — the genericity proof: a second core

The only test that actually demonstrates the harness is not MOA-specific.
`cores/hello-core/` is deliberately trivial: its own short `CLAUDE.md`, one input, two
milestones, one halt file, **no python package and no reference data**.

```bash
HARNESS_CORE=hello-core docker compose --profile smoke run --rm smoke
HARNESS_CORE=hello-core docker compose run --rm runner --topic "anything" --dry-run
```

If that passes without touching harness code, the genericization is real. If `hello-core`
requires a code change, it is not — and that is a build failure, not a README note.

### Layer 4 — one paid end-to-end

`--compounds Curcumin --disease "Atopic Dermatitis"` against the new image, with the event
stream diffed against a prior session for phase and percent parity. The only way to catch
an integration break the earlier layers cannot see. Budget for it explicitly.

### Rollback

The frozen `MOA_AG_Reserach/Schollar_System/` copy still builds. `MOVED.md` is added there
so nobody edits the dead tree.

## 8. Env variable rename

`MOA_*` → `HARNESS_*`, hard rename, no aliases.

| Today | New |
|---|---|
| `MOA_REPO_ROOT` | `HARNESS_CORE_ROOT` (`/app`) |
| `MOA_RESULTS_ROOT` | `HARNESS_RESULTS_ROOT` |
| `MOA_MODEL` | `HARNESS_MODEL` |
| `MOA_MAX_TURNS` | `HARNESS_MAX_TURNS` |
| `MOA_TIMEOUT_SECONDS` | `HARNESS_TIMEOUT_SECONDS` |
| `MOA_MAX_COST_USD` | `HARNESS_MAX_COST_USD` |
| `MOA_PERMISSION_MODE` | `HARNESS_PERMISSION_MODE` |
| `MOA_ANSWER_TIMEOUT_SECONDS` | `HARNESS_ANSWER_TIMEOUT_SECONDS` |
| `MOA_INBOX_POLL_SECONDS` | `HARNESS_INBOX_POLL_SECONDS` |
| `MOA_IDLE_WAIT_SECONDS` | `HARNESS_IDLE_WAIT_SECONDS` |
| `MOA_IDLE_BUDGET_SECONDS` | `HARNESS_IDLE_BUDGET_SECONDS` |
| `MOA_TOOL_EVENT_EVERY` | `HARNESS_TOOL_EVENT_EVERY` |
| `MOA_PROGRESS_POLL_SECONDS` | `HARNESS_PROGRESS_POLL_SECONDS` |
| `MOA_BUILD_PROFILE` | `HARNESS_PROFILE` |
| `MOA_MEM_LIMIT` / `MOA_CPUS` | `HARNESS_MEM_LIMIT` / `HARNESS_CPUS` |
| `MOA_WORKER_DRY_RUN` | `HARNESS_DRY_RUN` |
| — | `HARNESS_CORE` *(new — which core to build and run)* |
| **`MOA_RUN_DIR`** | **unchanged — payload-owned** via `agent.run_dir_env` |
| **`MOA_CJK_FONT`** | **unchanged — payload-owned** via `image.env` |

The last two staying `MOA_*` is the point of the manifest: CLAUDE.md §2 already reads
`MOA_RUN_DIR`, so **the science repo's CLAUDE.md needs no edit at all**.

### Downstream files to rewire

- `infra/stacks/compute-fargate.yaml` (13 refs), `infra/config.yaml`,
  `infra/scripts/push-image.sh`, `infra/scripts/verify.sh`, `infra/scripts/validate_iam.py`,
  `infra/template.yaml`, `infra/stacks/data.yaml`, `infra/NEXT_STEPS.md`
- `backend-handler/config/index.js`, `backend-handler/utils/runQueue.js`,
  `backend-handler/utils/runStore.js`
- `doc/ARCHITECTURE.md`, `doc/API_PROTOCOL.md`, `doc/EVENT_SCHEMA.md`,
  `doc/VERIFY_CONTRACT.md`, `doc/DEPLOY_EC2.md`, `doc/LOCAL_SETUP.md`
- `container/run_local.ps1`, `container/docker-compose.yml`, `.env.example`, `watch_run.ps1`
- **NEW** `doc/ADDING_A_CORE.md` — how to write a manifest and drop in a core

AWS resource names (`schollar-moa-runs.fifo`, `schollar_moa_runs`,
`schollar-moa-artifacts`) keep a `schollar-*` prefix but become a configurable deployment
namespace in `infra/config.yaml` rather than hard-coded strings.

## 9. Risks

| Risk | Mitigation |
|---|---|
| A template renderer gets an edge case wrong where a hard-coded `if` could not | Layer 1 tests written first, and must pass unchanged afterwards |
| Two `CLAUDE.md` files now exist; the harness's shipping by accident would silently corrupt every run | Asserted absent in Layer 2 smoke |
| 322 MB download on a fresh build, against an unreliable upstream | Prefer-local, BuildKit cache mount, fail hard if required and unobtainable |
| Big bang: one failing build has two possible causes | Layer 1 runs before any file moves, so extraction and refactor stay separable in the test record |
| The frozen MOA copy drifts from the new repo | `MOVED.md`; the copy is untracked, so it cannot be committed to by accident |
| A core omits a required manifest key (e.g. `conda_env`) | Build fails loudly with the offending key named — no silent default |
| Submodule checkout lacks `hsa_MTI.csv` | Handled by the provisioning stage (§6) |

## 10. Out of scope

- Deploying `infra/` to AWS. It remains written-and-not-deployed; this work does not change
  that status.
- Any change to the science: `moa_lib/`, `CLAUDE.md` §1–§8 content, the pipeline's
  methodology. The science repo **gains** exactly these, and loses nothing:

  | Added to `MOA_AG_Reserach/` | Why |
  |---|---|
  | `agent-core.yaml` | the core declares itself (§4) |
  | `.agent-core/prompt_run.md` · `.agent-core/prompt_probe.md` | the trigger prompts, moved out of harness code because the text is MOA-specific |
  | `runner-requirements/{base,omics,full}.txt` | the scientific dependency tiers, moved out of `container/requirements/` for the same reason |
  | `Schollar_System/MOVED.md` | marks the frozen rollback copy as dead |

  `CLAUDE.md` itself is **not edited** — `MOA_RUN_DIR` and `MOA_CJK_FONT` stay payload-owned
  via `agent.run_dir_env` and `image.env` precisely so that stays true.
- Building a third core beyond `hello-core`.
- Deleting `MOA_AG_Reserach/Schollar_System/`. It stays frozen as a rollback path; removing
  it is a separate decision for later.
