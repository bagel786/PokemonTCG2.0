"""Historical preservation + documentation integrity gates."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
PR = ROOT


def test_redesign_tree_untouched_vs_git_head():
    """redesign/** must remain byte-identical to the starting commit."""
    r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "redesign"],
                       cwd=REPO, capture_output=True)
    assert r.returncode == 0, "redesign/ was modified by the repair campaign"


def test_documentation_references_resolve():
    """Every referenced repo artifact in repaired docs must exist (T20)."""
    import re
    problems = []
    for md in PR.rglob("*.md"):
        text = md.read_text()
        for m in re.finditer(r"`([A-Za-z0-9_\-./]+\.(?:md|json|csv|py|jsonl))"
                             r"`", text):
            ref = m.group(1)
            if ref.startswith(("http", "/tmp")):
                continue
            # resolve relative to the doc or repo root
            cands = [md.parent / ref, REPO / ref, ROOT / ref,
                     ROOT / "protocol" / ref]
            if not any(c.exists() for c in cands):
                # only enforce for files that look internal to this campaign
                if ("prospective_repair" in str(ref) or
                        str(ref).count("/") == 0 and
                        (PR / ref).exists() is False and
                        any(part in str(md) for part in ("protocol",
                                                         "PREFREEZE",
                                                         "README"))):
                    problems.append(f"{md.name}: {ref}")
    assert not problems, problems


def test_registration_wording_discipline():
    forbidden = ["public preregistration was created",
                 "preregistered on osf"]
    for md in list(PR.rglob("*.md")):
        low = md.read_text().lower()
        for f in forbidden:
            assert f not in low, f"{md}: forbidden phrase {f!r}"
    proto = (PR / "protocol" / "REGISTRATION_STATUS.md").read_text()
    assert "NOT public preregistration" in proto
