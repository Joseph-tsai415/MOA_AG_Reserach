# Python environment (`moa`)

How to build the `moa` conda env that the pipeline runs in (CLAUDE.md §7), on any machine, from pinned
versions.

| File | What it is | Edit it? |
|---|---|---|
| `base.txt` → `omics.txt` → `full.txt` | **The spec.** What an MOA run imports, in three tiers. `full` = `omics` + scvi-tools + arboreto. | Yes, by hand |
| `constraints-full.txt` | **The lock.** The exact version of every package `full.txt` installs (direct and indirect). | No. Regenerate it with `make_lock.py` |
| `make_lock.py` | Regenerates the lock from a working `moa` env | — |
| `setup_moa_env.py` | Builds the env on a blank machine, then verifies it | — |

Not these:

- `requirements.txt` at the repo root lists every package any of the ~170 skills *might* use (208 entries,
  unpinned). It is a catalogue, not an install recipe.
- `Schollar_System/runner/requirements/` is the runner image's copy of the three profiles.

## Blank machine

Prerequisites: `git`, [Miniforge](https://conda-forge.org/download/) (or any conda), internet, and about
2.5 GB of free disk (the test build on Windows came to 2.4 GB).

```bash
git clone <repo-url> MOA_AG_Reserach && cd MOA_AG_Reserach
python runner-requirements/setup_moa_env.py      # Windows: run from the "Miniforge Prompt"
conda activate moa
```

The script creates the env `moa` with Python 3.12, installs the `full` profile under the lock (CPU-only
PyTorch), then verifies it. It never overwrites an existing env: use `--name` for another name. It finishes
with `RESULT: PASS` (exit 0) or names every failed check.

What the verification runs:

- the `import_check` startup gate from `agent-core.yaml`, plus the full-profile modules (scanpy, pydeseq2,
  scvi-tools, …): any failure is **FAIL**
- the `smoke_imports` list from `agent-core.yaml`: a failure is **WARN**
- offline function checks: RDKit descriptors + 2D drawing, plotly → PNG via kaleido, 2 epochs of scvi-tools
  training on CPU, `pip check` (all **FAIL** on error), and a CJK font for Chinese figure labels (**WARN**)
- everything with the user-wide site-packages switched off (`PYTHONNOUSERSITE=1`, `python -s`), so the env
  cannot quietly depend on packages installed outside it

Re-check an existing env at any time: `python runner-requirements/setup_moa_env.py --verify-only`.

## Platform differences

Measured 2026-11-10 by building from scratch with the command above: Windows 11 (new conda env) and Linux
(fresh `condaforge/miniforge3` Ubuntu container). Both ended with `RESULT: PASS`, 0 failures, 0 warnings.

| | Windows 11 | Linux (Ubuntu) |
|---|---|---|
| Install + verify time | 10–21 min (two builds) | 5–7 min (four builds) |
| System packages first | none | `sudo apt-get install -y libxrender1 libxext6 fonts-noto-cjk` |
| plotly → PNG | kaleido 1.x, drives an installed **Google Chrome** | kaleido 0.2.1, no Chrome needed |
| L3 docking (`vina`) | **not available**: run docking under WSL or Docker | included (1.2.7) |
| CJK font for figures | Microsoft JhengHei (preinstalled) | "Noto Sans CJK JP" (from `fonts-noto-cjk`) |
| PyTorch | 2.10.0 CPU build, no GPU needed | same |

Why each difference exists (all found by the test builds, not assumed):

- **Linux system packages.** Without `libxrender1`, RDKit's drawing module fails to import
  (`libXrender.so.1: cannot open shared object file`), which breaks every structure figure. Without
  `fonts-noto-cjk`, Chinese labels render as empty boxes. pip cannot install either.
- **kaleido.** 0.2.1 hangs forever in `write_image` on Windows (10+ min, ~0 CPU). 1.x works there but needs
  Chrome. On a Windows machine without Chrome, run `plotly_get_chrome -y` inside the env. That path is
  untested here, because the test machine has Chrome.
- **vina.** No Windows wheel on PyPI and no win-64 build on conda-forge. The source build needs Boost and a
  C++ compiler.
- **Noto Sans CJK JP.** `fonts-noto-cjk` ships one collection file, and matplotlib only sees its first face.
  That face covers all Han characters, but a few render in Japanese glyph forms (see the matplotlib skill,
  section 7).

**macOS** is untested, and the lock's `torch==2.10.0+cpu` pin has no macOS wheel. Treat it as unsupported until
someone builds it there.

**GPU** (optional, only faster for scvi-tools on large datasets): after setup, reinstall torch from a CUDA index,
e.g. `pip install --force-reinstall --no-deps torch==2.10.0 --index-url https://download.pytorch.org/whl/cu126`.
This is untested here.

## Changing the environment

1. Edit a profile (`base.txt`, `omics.txt` or `full.txt`). Never edit the lock by hand.
2. In a working `moa` env, run `python runner-requirements/make_lock.py`. Pins come from that env's
   versions; packages it lacks get the newest compatible version; any pin pip cannot satisfy is relaxed and
   listed in the lock header.
3. Prove it builds: `python runner-requirements/setup_moa_env.py --name moa_lockcheck`, then
   `conda env remove -n moa_lockcheck`.
4. Commit the profile and the lock together.

To bring an existing env in line with the lock:

```bash
conda activate moa
PYTHONNOUSERSITE=1 python -m pip install -r runner-requirements/full.txt \
    -c runner-requirements/constraints-full.txt --extra-index-url https://download.pytorch.org/whl/cpu
python runner-requirements/setup_moa_env.py --verify-only
```

On Windows (Miniforge Prompt / cmd), set the variable with `set PYTHONNOUSERSITE=1` on its own line first.
