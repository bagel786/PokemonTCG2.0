#!/usr/bin/env python3
"""Assemble and red-team the strict allow-list processed release."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "release"
PROCESSED = {
    "paper/data/canonical_results.csv": "canonical_results.csv",
    "paper/data/statistical_summary.json": "statistical_summary.json",
    "paper/data/fresh_cell_summary.csv": "fresh_cell_summary.csv",
    "paper/data/historical_cell_summary.csv": "historical_cell_summary.csv",
    "paper/data/representation_audit.json": "representation_audit.json",
    "paper/data/representation_source_cards.csv": "representation_source_cards.csv",
    "paper/data/heldout_0813_summary.json": "heldout_0813_summary.json",
    "paper/data/negative_results.json": "negative_results.json",
    "paper/data/negative_results.csv": "negative_results.csv",
    "paper/data/ablation/canonical_ablation.csv": "ablation_canonical.csv",
    "paper/data/ablation/summary.json": "ablation_summary.json",
    "paper/data/ablation/contrasts.csv": "ablation_contrasts.csv",
    "paper/data/ablation/training_report.json": "ablation_training_report.json",
}
PROHIBITED_SUFFIXES = {
    ".dylib", ".dll", ".so", ".exe", ".npz", ".pt", ".pth", ".onnx",
    ".tar", ".tgz", ".gz", ".zip", ".png.tmp",
}
PRIVATE_TEAM_TOKENS = {"Dreamer", "GrimmsnaRL", "Mint120", "TMTA", "lollipop947"}
SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]+"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reset_generated(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def copy_required(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def write_environment() -> None:
    python_version = ".".join(map(str, sys.version_info[:3]))
    numpy_version = importlib.metadata.version("numpy")
    matplotlib_version = importlib.metadata.version("matplotlib")
    (RELEASE / "environment.yml").write_text(
        "name: representation-repair-processed\n"
        "channels:\n  - conda-forge\n"
        "dependencies:\n"
        f"  - python={python_version}\n"
        f"  - numpy={numpy_version}\n"
        f"  - matplotlib={matplotlib_version}\n",
        encoding="utf-8",
    )
    (RELEASE / "requirements-lock.txt").write_text(
        f"numpy=={numpy_version}\nmatplotlib=={matplotlib_version}\n",
        encoding="utf-8",
    )


def scan_release() -> dict:
    problems = []
    files = [path for path in RELEASE.rglob("*") if path.is_file()]
    for path in files:
        relative = path.relative_to(RELEASE).as_posix()
        lower = relative.lower()
        if any(lower.endswith(suffix) for suffix in PROHIBITED_SUFFIXES):
            problems.append(f"prohibited binary/archive suffix: {relative}")
        data = path.read_bytes()
        if b"/Users/" in data or b"C:\\Users\\" in data:
            problems.append(f"absolute user path: {relative}")
        text = data.decode("utf-8", errors="ignore")
        for team in PRIVATE_TEAM_TOKENS:
            if team in text:
                problems.append(f"private team token in {relative}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                problems.append(f"secret-like pattern in {relative}")
    if problems:
        raise RuntimeError("release scan failed:\n" + "\n".join(sorted(set(problems))))
    return {"files_scanned": len(files), "problems": 0}


def write_manifest() -> None:
    manifest = RELEASE / "MANIFEST.sha256"
    rows = []
    for path in sorted(item for item in RELEASE.rglob("*") if item.is_file() and item != manifest):
        rows.append(f"{sha256(path)}  {path.relative_to(RELEASE).as_posix()}")
    manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> int:
    for path in (
        RELEASE / "data/processed", RELEASE / "scripts", RELEASE / "figures",
        RELEASE / "generated", RELEASE / "docs/protocols",
    ):
        reset_generated(path)
    for source, destination in PROCESSED.items():
        copy_required(ROOT / source, RELEASE / "data/processed" / destination)
    copy_required(ROOT / "paper/claim_ledger.csv", RELEASE / "docs/claim_ledger.csv")
    for protocol in sorted((ROOT / "paper/protocol").glob("*.md")):
        copy_required(protocol, RELEASE / "docs/protocols" / protocol.name)
    for script in ("build_figures.py", "generate_tables.py"):
        copy_required(ROOT / "paper/scripts" / script, RELEASE / "scripts" / script)
    write_environment()
    subprocess.run([sys.executable, "scripts/generate_tables.py"], cwd=RELEASE, check=True)
    subprocess.run([sys.executable, "scripts/build_figures.py"], cwd=RELEASE, check=True)
    subprocess.run([sys.executable, "evaluation/verify_processed.py"], cwd=RELEASE, check=True)
    scan = scan_release()
    write_manifest()
    # Verify the manifest only after it is complete.
    manifest_lines = (RELEASE / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines()
    for line in manifest_lines:
        expected, relative = line.split("  ", 1)
        if sha256(RELEASE / relative) != expected:
            raise AssertionError(f"manifest mismatch: {relative}")
    print(json.dumps({
        "release": str(RELEASE),
        "manifest_sha256": sha256(RELEASE / "MANIFEST.sha256"),
        "manifest_entries": len(manifest_lines),
        "scan": scan,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
