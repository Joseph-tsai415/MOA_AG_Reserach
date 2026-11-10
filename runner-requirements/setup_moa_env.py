"""Create the `moa` conda env on a blank machine from the pinned lock, then verify it works.

Prerequisites: conda on PATH (Miniforge recommended), internet access. Run from the project root:

    python runner-requirements/setup_moa_env.py                 # create env "moa" + verify
    python runner-requirements/setup_moa_env.py --name moa_new  # different env name
    python runner-requirements/setup_moa_env.py --verify-only   # re-check an existing env

Never overwrites an existing env. Installs the `full` profile (full.txt -> omics.txt -> base.txt) under
constraints-full.txt, with CPU-only PyTorch. Every pip and verify call runs with the user-wide site-packages
disabled (PYTHONNOUSERSITE=1), so the env cannot silently depend on packages outside it.
Exit code 0 = every hard check passed. Details: runner-requirements/README.md.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
NOUSER = {**os.environ, "PYTHONNOUSERSITE": "1", "PYTHONIOENCODING": "utf-8"}
# Full profile installed => the omics/full modules are required, not optional (agent-core.yaml lists them
# WARN-only because a base-tier image lacks them; this env is never base-tier).
FULL_PROFILE_HARD = ["pydeseq2", "scanpy", "anndata", "scvi", "lightning", "arboreto", "GEOparse"]
NOT_ON_WINDOWS = {"vina"}   # no Windows wheel / conda-forge build; see base.txt


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], **kw)


def find_conda():
    exe = os.environ.get("CONDA_EXE") or shutil.which("conda")
    if not exe:
        sys.exit("conda not found on PATH. Install Miniforge (https://conda-forge.org/download/) and re-run.")
    return exe


def env_prefix(conda, name):
    out = subprocess.run([conda, "env", "list", "--json"], capture_output=True, text=True, check=True).stdout
    for p in json.loads(out)["envs"]:
        if Path(p).name == name:
            return Path(p)
    return None


def env_python(prefix):
    return prefix / ("python.exe" if os.name == "nt" else "bin/python")


# --------------------------------------------------------------------------------------------- verify mode
def verify():
    """Runs INSIDE the target env (python -s). Hard checks fail the run; WARN lines do not."""
    import importlib
    import platform
    import warnings
    warnings.filterwarnings("ignore")
    sys.path.insert(0, str(ROOT))
    hard, warn = [], []

    def check(label, fn, required=True):
        try:
            detail = fn()
            print(f"  ok    {label}{'  ' + str(detail) if detail else ''}")
        except Exception as e:
            (hard if required else warn).append(label)
            print(f"  {'FAIL' if required else 'WARN'}  {label}  {type(e).__name__}: {str(e)[:160]}")

    print(f"python {platform.python_version()} at {sys.executable}")
    check("python is 3.12", lambda: None if sys.version_info[:2] == (3, 12) else (_ for _ in ()).throw(RuntimeError(platform.python_version())))

    import yaml
    manifest = yaml.safe_load((ROOT / "agent-core.yaml").read_text(encoding="utf-8"))["python"]
    print("import_check (agent-core.yaml startup gate):")
    for m in manifest["import_check"]:
        check(m, lambda m=m: getattr(importlib.import_module(m), "__version__", ""))
    print("full-profile modules:")
    for m in FULL_PROFILE_HARD:
        check(m, lambda m=m: getattr(importlib.import_module(m), "__version__", ""))
    print("smoke_imports (agent-core.yaml, WARN-only):")
    for m in manifest["smoke_imports"]:
        if os.name == "nt" and m in NOT_ON_WINDOWS:
            print(f"  skip  {m}  not available on Windows (use WSL/Docker for L3 docking)")
            continue
        check(m, lambda m=m: getattr(importlib.import_module(m), "__version__", ""), required=False)

    print("function checks (offline):")
    tmp = Path(tempfile.mkdtemp(prefix="moa_env_check_"))

    def torch_info():
        import torch
        return f"torch {torch.__version__}, CUDA available={torch.cuda.is_available()} (CPU build is expected)"

    def rdkit_draw():
        from rdkit import Chem
        from rdkit.Chem import Descriptors
        try:
            from rdkit.Chem import Draw
        except ImportError as e:   # bare Linux: RDKit's drawing code links against X11 render libs
            raise ImportError(f"{e} -> system package missing: sudo apt-get install -y libxrender1 libxext6") from e
        mw = Descriptors.MolWt(Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O"))      # aspirin
        assert abs(mw - 180.16) < 0.05, mw
        Draw.MolToFile(Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O"), str(tmp / "aspirin.png"))
        assert (tmp / "aspirin.png").read_bytes()[:4] == b"\x89PNG"
        return f"aspirin MW {mw:.2f}, 2D drawing written"

    def plotly_png():
        # In a subprocess with a timeout: kaleido 0.2.1 on Windows hangs forever instead of failing.
        code = ("import plotly.graph_objects as go, sys; go.Figure(go.Sankey(node={'label': ['A', 'B']}, "
                "link={'source': [0], 'target': [1], 'value': [1]})).write_image(sys.argv[1])")
        try:
            p = subprocess.run([sys.executable, "-s", "-c", code, str(tmp / "sankey.png")], capture_output=True,
                               text=True, env=NOUSER, timeout=180)
        except subprocess.TimeoutExpired:
            raise RuntimeError("write_image hung for 180 s (kaleido 0.2.1 on Windows does this; base.txt pins >=1.0 there)")
        png = tmp / "sankey.png"
        if p.returncode != 0 or not png.exists() or png.read_bytes()[:4] != b"\x89PNG":
            hint = " -> no Chrome found? run `plotly_get_chrome -y` in this env" if "hrome" in p.stderr else ""
            raise RuntimeError((p.stderr.strip().splitlines() or ["no PNG written"])[-1][:200] + hint)
        from importlib.metadata import version
        return f"plotly {version('plotly')} + kaleido {version('kaleido')}: Sankey PNG written"

    def scvi_cpu_train():
        import numpy as np, anndata, scvi
        rng = np.random.default_rng(0)
        ad = anndata.AnnData(rng.poisson(2.0, size=(200, 50)).astype(np.float32))   # plumbing check only
        scvi.model.SCVI.setup_anndata(ad)
        m = scvi.model.SCVI(ad, n_latent=4)
        m.train(max_epochs=2, accelerator="cpu", enable_progress_bar=False)
        z = m.get_latent_representation()
        assert z.shape == (200, 4) and np.isfinite(z).all()
        return "SCVI trained 2 epochs on CPU, latent finite"

    def cjk_font():
        from matplotlib import font_manager as fm
        names = {f.name for f in fm.fontManager.ttflist}
        cand = ["Microsoft JhengHei", "Microsoft YaHei", "Noto Sans CJK TC", "Noto Sans CJK SC", "Noto Sans TC",
                "Noto Sans SC", "PingFang TC", "SimHei",
                "Noto Sans CJK JP"]   # Debian/Ubuntu fonts-noto-cjk: matplotlib registers only this face of the .ttc
        hit = [c for c in cand if c in names]
        if not hit:
            raise RuntimeError("no CJK font: Chinese figure labels would render as empty boxes "
                               "(Linux: apt install fonts-noto-cjk, then delete the matplotlib font cache)")
        return hit[0]

    check("torch", torch_info)
    check("rdkit descriptors + 2D drawing", rdkit_draw)
    check("plotly -> PNG via kaleido", plotly_png)
    check("scvi-tools CPU training", scvi_cpu_train)
    check("CJK font for figure labels", cjk_font, required=False)
    p = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True, env=NOUSER)
    check("pip check (no broken requirements)", lambda: None if p.returncode == 0 else (_ for _ in ()).throw(RuntimeError(p.stdout.strip()[:300])))
    shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nRESULT: {'PASS' if not hard else 'FAIL'}  hard failures={len(hard)} {hard}  warnings={len(warn)} {warn}")
    return 0 if not hard else 1


# --------------------------------------------------------------------------------------------- setup mode
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="moa", help="conda env name (default: moa)")
    ap.add_argument("--verify-only", action="store_true", help="only verify an existing env")
    ap.add_argument("--_verify", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a._verify:
        return verify()

    conda = find_conda()
    prefix = env_prefix(conda, a.name)
    if a.verify_only:
        if prefix is None:
            sys.exit(f"env '{a.name}' does not exist")
    else:
        if prefix is not None:
            sys.exit(f"env '{a.name}' already exists at {prefix}; not touching it. Use --name for a new env, "
                     f"or --verify-only to check it.")
        run([conda, "create", "-y", "-n", a.name, "-c", "conda-forge", "--override-channels", "python=3.12", "pip"], check=True)
        prefix = env_prefix(conda, a.name)
        py = env_python(prefix)
        run([py, "-m", "pip", "install", "--progress-bar", "off", "-r", HERE / "full.txt",
             "-c", HERE / "constraints-full.txt", "--extra-index-url", TORCH_INDEX], check=True, env=NOUSER, cwd=ROOT)
    py = env_python(prefix)
    return run([py, "-s", Path(__file__).resolve(), "--_verify"], env=NOUSER, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
