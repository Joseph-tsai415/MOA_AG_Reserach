# MOVED — this tree is frozen

This directory has been extracted into its own repository:

    D:\Dev\projects\agent-harness   (github.com/Joseph-tsai415/agent-harness)

**Do not edit anything here.** It is retained only as a rollback path: it still
builds the pre-extraction image. The canonical service layer, container and
deployment code live in `agent-harness`, which consumes this repository as an
agent core, copied (not submoduled) into `cores/moa-ag/` there. That copy is
git-ignored in the harness repo and is re-synced by hand, so it can drift from
this repository without anything complaining.

What this repository provides to the harness:

| File | Purpose |
|---|---|
| `agent-core.yaml` | the manifest — how the harness runs this core |
| `.agent-core/prompt_run.md` | the trigger prompt |
| `runner-requirements/*.txt` | the scientific dependency tiers |

**Provenance of the copy at `agent-harness/cores/moa-ag/`:** copied from this
repository at commit `7a00c02` (branch `feat/agent-harness-extraction`) on
2026-10-01. Re-syncing means repeating the `tar` copy described in the harness
repo's extraction task and updating this line and the matching stamp at
`agent-harness/manifests/moa-ag.source`.

Frozen on 2026-10-01.
