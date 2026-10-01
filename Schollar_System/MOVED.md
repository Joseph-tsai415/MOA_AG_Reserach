# MOVED — this tree is frozen

This directory has been extracted into its own repository:

    D:\Dev\projects\agent-harness   (github.com/Joseph-tsai415/agent-harness)

**Do not edit anything here.** It is retained only as a rollback path: it still
builds the pre-extraction image. The canonical service layer, container and
deployment code live in `agent-harness`, which consumes this repository as an
*agent core* (pinned at `cores/moa-ag/`).

What this repository provides to the harness:

| File | Purpose |
|---|---|
| `agent-core.yaml` | the manifest — how the harness runs this core |
| `.agent-core/prompt_run.md` | the trigger prompt |
| `runner-requirements/*.txt` | the scientific dependency tiers |

Frozen on 2026-10-01.
