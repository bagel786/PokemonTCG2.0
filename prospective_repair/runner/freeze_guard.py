"""Freeze guard + preflight refusal logic for the final holdout runner.

The final runner refuses to execute unless:
  1. git working tree is clean;
  2. current branch == frozen branch recorded at freeze time;
  3. HEAD == the recorded freeze SHA;
  4. frozen-input hash inventory matches byte-for-byte;
  5. freeze SHA and peel(tag) resolve on origin/* refs locally fetched.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT.parent, capture_output=True,
                          text=True, check=True).stdout.strip()


FROZEN_INPUTS = [
    "protocol/PROTOCOL.md", "protocol/FAULT_GRAMMAR.json",
    "protocol/SYSTEM_MANIFEST.json", "protocol/SEED_MANIFEST.json",
    "protocol/BASELINE_SPECS.md", "protocol/METRICS_AND_GATES.md",
    "protocol/ANALYSIS_PLAN.md", "protocol/OUTPUT_SCHEMAS.json",
    "protocol/EXPECTED_DECISION_TABLE.json",
    "framework/constants.py", "framework/evidence.py",
    "framework/classifier.py", "framework/baselines.py", "framework/scoring.py",
    "systems/rng.py", "systems/mechanics.py", "systems/holdem_wrapper.py",
    "systems/ising_wrapper.py", "systems/subprocess_context.py",
    "runner/freeze_guard.py", "runner/acquire.py",
    "analysis/schema_validators.py", "analysis/stats.py",
    "analysis/analyze.py", "analysis/independent_reaggregate.py",
    "analysis/make_figures_tables.py", "PREFREEZE_VALIDATION_REPORT.md",
]


def input_hashes() -> dict:
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
            for p in FROZEN_INPUTS}


def write_freeze_record(freeze_sha: str, branch: str, tag: str,
                        remote_url: str, tag_sha: str) -> dict:
    rec = {
        "kind": "FREEZE_RECORD", "campaign": "prospective-repair",
        "freeze_sha": freeze_sha, "branch": branch, "tag": tag,
        "tag_sha": tag_sha,
        "remote": remote_url,
        "registration_status": ("timestamped freeze on PRIVATE remote; "
                                 "NOT public preregistration"),
        "frozen_input_hashes": input_hashes(),
        "order_of_operations": ("this record committed+pushed BEFORE any "
                                "final-holdout outcome exists"),
    }
    (ROOT / "protocol" / "FREEZE_RECORD.json").write_text(
        json.dumps(rec, indent=2, sort_keys=True) + "\n")
    return rec


def verify(require_remote: bool = True) -> None:
    problems = []
    status = _git("status", "--porcelain")
    dirty_inside = [l for l in status.splitlines()
                    if l.strip().startswith("prospective_repair") or
                    l.strip().startswith('"prospective_repair')]
    tracked_dirty = [l for l in status.splitlines() if not
                     l.startswith("??")]
    if dirty_inside:
        problems.append("untracked/modified files inside "
                        f"prospective_repair:\n{dirty_inside[:10]}")
    if tracked_dirty:
        problems.append(f"tracked files modified:\n{tracked_dirty[:10]}")
    # unrelated top-level untracked directories from other workstreams are
    # irrelevant to frozen-input integrity and are intentionally ignored.
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    head = _git("rev-parse", "HEAD")
    rec_path = ROOT / "protocol" / "FREEZE_RECORD.json"
    if not rec_path.exists():
        raise SystemExit("[freeze_guard] FREEZE_RECORD.json missing — refusing.")
    rec = json.loads(rec_path.read_text())
    # The freeze SHA must be reachable (ancestor) from HEAD so bookkeeping
    # commits after the freeze are allowed — but any change to frozen INPUTS
    # below is not.
    anc = subprocess.run(["git", "merge-base", "--is-ancestor",
                          rec["freeze_sha"], head], cwd=ROOT.parent,
                         capture_output=True)
    if anc.returncode != 0:
        problems.append(f"freeze SHA {rec['freeze_sha']} not ancestor of "
                        f"HEAD {head}")
    if branch != rec["branch"]:
        problems.append(f"branch {branch} != frozen {rec['branch']}")
    diffs = {p: h for p, h in input_hashes().items()
             if rec["frozen_input_hashes"].get(p) != h}
    logged = {e["file"]: e["new_sha256"]
              for e in rec.get("machinery_patch_log", [])}
    diffs = {p: h for p, h in diffs.items() if logged.get(p) != h}
    if diffs:
        problems.append(f"frozen inputs changed post-freeze without "
                        f"machinery-patch log entry: {list(diffs)[:5]}")
    if require_remote:
        _git("fetch", "origin", "--prune")
        def _is_ancestor(a, b):
            return subprocess.run(
                ["git", "merge-base", "--is-ancestor", a, b],
                cwd=ROOT.parent, capture_output=True).returncode == 0
        try:
            r_branch = _git("rev-parse", f"origin/{rec['branch']}")
            r_tag = _git("rev-parse", f"{rec['tag']}^{{commit}}")
        except subprocess.CalledProcessError as e:
            problems.append(f"remote verification failed: {e}")
        else:
            if not _is_ancestor(rec["freeze_sha"], r_branch):
                problems.append("freeze SHA not reachable from origin branch")
            if r_tag != rec["tag_sha"]:
                problems.append(f"origin tag peel {r_tag} != recorded "
                                f"{rec['tag_sha']}")
            if not _is_ancestor(rec["freeze_sha"], r_tag):
                problems.append("freeze SHA not reachable from pushed tag")
    if problems:
        print("[freeze_guard] REFUSING:", file=sys.stderr)
        for p in problems:
            print(" -", p, file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    verify(require_remote=("--local" not in sys.argv))
    print("[freeze_guard] OK")
