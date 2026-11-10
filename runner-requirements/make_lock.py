"""Regenerate constraints-full.txt: exact pins for everything the `full` profile installs.

The profiles (base.txt -> omics.txt -> full.txt) stay the single human-edited spec. This lock is derived from
them; never edit it by hand. Run it from a working `moa` env whenever a profile changes:

    conda activate moa
    python runner-requirements/make_lock.py

How it pins: it asks pip to resolve full.txt (dry run, nothing installed), constrained to the versions in THIS
env, because those are the versions known to work together. A top-level package the env lacks is pinned to its
newest release that satisfies the profile, so pip cannot quietly backtrack it to an old release just to keep an
old env pin (markitdown 0.1.9 needs certifi>=2026.10.19; unpinned, pip silently fell back to markitdown 0.1.0).
A pin that cannot be satisfied or that conflicts is dropped and re-resolved, and is listed in the lock header
so nothing is relaxed silently.

Packages that live only in the user-wide site-packages (AppData/Roaming, ~/.local) are NOT used as pins: they
are not part of the env, and inheriting them is how the env picked up hidden dependencies in the first place.
"""
import datetime
import json
import os
import platform
import re
import site
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILE = HERE / "full.txt"
LOCK = HERE / "constraints-full.txt"
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"   # CPU-only torch (no CUDA); see README.md
MAX_RETRIES = 25


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def env_pins():
    """name -> version for distributions installed in the env itself (user site excluded)."""
    user_site = os.path.normcase(os.path.abspath(site.getusersitepackages()))
    pins = {}
    for d in metadata.distributions():
        name = d.metadata["Name"]
        if not name:
            continue
        loc = os.path.normcase(os.path.abspath(str(d.locate_file(""))))
        if loc.startswith(user_site):
            continue
        pins[norm(name)] = (name, d.version)
    return pins


def profile_reqs(path, all_platforms=False):
    """Top-level requirements of a profile, following -r includes. Markers are evaluated for this platform
    unless all_platforms=True (then every requirement is returned, marker attached)."""
    from packaging.requirements import Requirement
    out = []
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        ln = ln.split(" #")[0].split("\t#")[0].strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("-r"):
            out += profile_reqs(Path(path).parent / ln.split()[1], all_platforms)
            continue
        r = Requirement(ln)
        if all_platforms or r.marker is None or r.marker.evaluate():
            out.append(r)
    return out


def newest_allowed(req):
    """Newest non-prerelease version pip can install here that satisfies the profile's specifier."""
    p = subprocess.run([sys.executable, "-m", "pip", "index", "versions", req.name], capture_output=True,
                       text=True, env={**os.environ, "PYTHONNOUSERSITE": "1"})
    m = re.search(r"Available versions: (.+)", p.stdout)
    if not m:
        return None
    from packaging.version import Version
    vs = [Version(v.strip()) for v in m.group(1).split(",")]
    ok = [v for v in vs if not v.is_prerelease and req.specifier.contains(v)]
    return str(max(ok)) if ok else None


def resolve(pins, dropped):
    with tempfile.TemporaryDirectory() as td:
        cfile, report = Path(td) / "c.txt", Path(td) / "report.json"
        cfile.write_text("".join(f"{n}=={v}\n" for k, (n, v) in sorted(pins.items()) if k not in dropped), encoding="utf-8")
        cmd = [sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed", "--progress-bar", "off",
               "--report", str(report), "-r", str(PROFILE), "-c", str(cfile), "--extra-index-url", TORCH_INDEX]
        p = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "PYTHONNOUSERSITE": "1"})
        if p.returncode == 0:
            return json.loads(report.read_text(encoding="utf-8")), None
        return None, p.stdout + p.stderr


def blamed(err, pins):
    """Constraint names pip says it cannot satisfy or that conflict."""
    hits = set(re.findall(r"\(constraint\) ([A-Za-z0-9_.\-]+)==", err))
    hits |= set(re.findall(r"(?:satisfies the requirement|distribution found for) ([A-Za-z0-9_.\-]+)==", err))
    for group in re.findall(r"Cannot install (.+?) because", err):        # "A==1, B==2 and C==3"
        hits |= set(re.findall(r"([A-Za-z0-9_.\-]+)(?:==|>=|<=|~=|!=|<|>)", group))
    hits |= set(re.findall(r"depends on ([A-Za-z0-9_.\-]+)", err))      # "markitdown 0.1.9 depends on certifi>=..."
    return {norm(h) for h in hits if norm(h) in pins}


def main():
    pins = env_pins()
    newest = {}
    for r in profile_reqs(PROFILE):
        k = norm(r.name)
        if k not in pins:
            v = newest_allowed(r)
            if v:
                pins[k] = newest[k] = (r.name, v)
    print(f"{len(pins) - len(newest)} env pins + {len(newest)} newest pins for packages the env lacks: "
          + ", ".join(f"{n}=={v}" for n, v in newest.values()))
    dropped = {}
    for _ in range(MAX_RETRIES):
        rep, err = resolve(pins, dropped)
        if rep is not None:
            break
        bad = blamed(err, pins) - set(dropped)
        if not bad:
            sys.exit("pip could not resolve full.txt and named no env pin to relax:\n" + err[-3000:])
        for b in sorted(bad):
            dropped[b] = pins[b][1]
            kind = "newest-release pin" if b in newest else "env pin"
            print(f"  relaxing {kind} {pins[b][0]}=={pins[b][1]} (pip could not satisfy it or it conflicts)")
    else:
        sys.exit(f"gave up after {MAX_RETRIES} relaxations")

    rows = sorted(((i["metadata"]["name"], i["metadata"]["version"]) for i in rep["install"]), key=lambda x: norm(x[0]))
    env_only = {k: p for k, p in pins.items() if k not in newest}
    from_env = sum(1 for n, v in rows if env_only.get(norm(n), (None, None))[1] == v)

    # Platform markers. A constraint applies on every platform, so a pin for a top-level requirement that the
    # profile restricts with a marker must carry that marker, or it would fight the other platform's
    # requirement (kaleido: ==0.2.1 on Linux, >=1.0 on Windows). Requirements excluded on THIS platform are
    # pinned to their newest allowed release under their own marker, so they do not float elsewhere (vina).
    markers = {}
    for r in profile_reqs(PROFILE, all_platforms=True):
        if r.marker is not None:
            markers.setdefault(norm(r.name), []).append(r)
    lines, other_platform = [], []
    for n, v in rows:
        rs = markers.get(norm(n))
        here = [r for r in rs or [] if r.marker.evaluate()]
        lines.append(f"{n}=={v} ; {here[0].marker}" if here else f"{n}=={v}")
    locked = {norm(n) for n, _ in rows}
    for k, rs in sorted(markers.items()):
        for r in rs:
            if not r.marker.evaluate() and k not in locked:
                v = newest_allowed(r)
                if v:
                    lines.append(f"{r.name}=={v} ; {r.marker}")
                    other_platform.append(f"{r.name}=={v} ({r.marker})")
    head = [
        "# GENERATED by runner-requirements/make_lock.py -- do not edit by hand; edit the profiles and re-run.",
        f"# Generated {datetime.date.today().isoformat()} on {platform.system()} {platform.machine()}, "
        f"Python {platform.python_version()}, from {PROFILE.name} (+ omics.txt, base.txt).",
        f"# {len(rows)} packages: {from_env} pinned to the version in the working moa env, "
        f"{len(rows) - from_env} newest-compatible (not in that env).",
        f"# Resolved with {platform.system()} markers: pins for packages only this platform needs (e.g. pywin32) are",
        "# ignored elsewhere; profile requirements with a platform marker keep that marker on their pin; a dependency",
        "# only another platform needs resolves unpinned there. Use as a CONSTRAINTS file, never as requirements:",
        f"#   pip install -r runner-requirements/full.txt -c runner-requirements/constraints-full.txt --extra-index-url {TORCH_INDEX}",
    ]
    if dropped:
        head.append("# Pins relaxed because pip could not satisfy them or they conflicted (was -> now): "
                    + ", ".join(f"{pins[k][0]} {v} -> {dict((norm(n), x) for n, x in rows).get(k, 'not installed')}"
                                for k, v in sorted(dropped.items())))
    if other_platform:
        head.append("# Pinned for another platform only (newest allowed release, not test-installed here): "
                    + ", ".join(other_platform))
    LOCK.write_text("\n".join(head) + "\n" + "".join(f"{ln}\n" for ln in lines), encoding="utf-8")
    print(f"wrote {LOCK.name}: {len(rows)} pins ({from_env} from env, {len(rows) - from_env} new), {len(dropped)} relaxed, "
          f"{len(other_platform)} other-platform: {other_platform}")


if __name__ == "__main__":
    main()
