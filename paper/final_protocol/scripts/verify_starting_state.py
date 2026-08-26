#!/usr/bin/env python3
"""Verify the immutable starting-state record and its evidence digests."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve()
FINAL = SCRIPT.parents[1]
ROOT = SCRIPT.parents[3]
STATE_PATH = FINAL / "STARTING_STATE.json"
# Branches on which this frozen starting-state record remains verifiable.
ALLOWED_BRANCHES = {
    "paper/apsos-submission-closeout-20260825",
    "paper/apsos-machine-finalization-20260826",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def raw_tree_digest(directory: Path) -> tuple[int, str]:
    paths = sorted(path for path in directory.rglob("*") if path.is_file())
    lines = "".join(
        f"{sha256(path)}  {path.relative_to(ROOT).as_posix()}\n"
        for path in paths
    )
    return len(paths), sha256_bytes(lines.encode("utf-8"))


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if state.get("schema_version") != "apsos-starting-state-v1":
        raise ValueError("starting-state schema drift")
    if not state.get("initial_worktree_status", {}).get("clean"):
        raise ValueError("recorded source worktree was not clean")
    if git("rev-parse", state["source_branch"]) != state["source_commit"]:
        raise ValueError("source branch no longer resolves to the recorded source commit")
    if git("branch", "--show-current") not in ALLOWED_BRANCHES:
        raise ValueError("verification is not running on a recorded finalization branch")
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", state["source_commit"], "HEAD"],
        cwd=ROOT,
        check=False,
    )
    if ancestry.returncode != 0:
        raise ValueError("HEAD is not a descendant of the frozen source commit")

    for relative, expected in state["relevant_source_hashes"].items():
        path = ROOT / relative
        if not path.is_file() or path.is_symlink() or sha256(path) != expected:
            raise ValueError(f"relevant source hash drift: {relative}")

    for relative, expected in state["raw_acquisition_tree_hashes"].items():
        if relative == "method":
            continue
        count, observed = raw_tree_digest(ROOT / relative)
        if count != expected["files"] or observed != expected["sha256"]:
            raise ValueError(f"raw acquisition tree drift: {relative}")

    audit = json.loads((ROOT / "paper/data/stochastic_source_audit.json").read_text(encoding="utf-8"))
    by_id = {row["artifact_id"]: row for row in audit["inventory"]}
    for artifact_id, expected in state["frozen_artifact_hashes"].items():
        row = by_id.get(artifact_id)
        if row is None:
            raise ValueError(f"frozen artifact missing from audit: {artifact_id}")
        if row.get("local_path") != expected["path"] or row.get("artifact_kind") != expected["kind"]:
            raise ValueError(f"frozen artifact identity drift: {artifact_id}")
        if row.get("observed_sha256") != expected["sha256"] or row.get("hash_match") is not True:
            raise ValueError(f"frozen artifact hash drift: {artifact_id}")

    print(json.dumps({
        "status": "PASS",
        "source_commit": state["source_commit"],
        "target_branch": state["target_branch"],
        "source_files_verified": len(state["relevant_source_hashes"]),
        "raw_trees_verified": len(state["raw_acquisition_tree_hashes"]) - 1,
        "frozen_artifacts_verified": len(state["frozen_artifact_hashes"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
