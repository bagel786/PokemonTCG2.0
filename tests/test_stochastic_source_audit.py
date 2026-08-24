import json
from pathlib import Path

from paper.scripts.audit_stochastic_sources import (
    ARTIFACTS,
    CATEGORY_DEFINITIONS,
    canonical_sha256_path,
    scan_python_package,
)
from training.evaluate_deterministic_crn import sha256_path as evaluator_sha256_path


def test_canonical_tree_hash_matches_evaluator_and_excludes_caches(tmp_path: Path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "weights.bin").write_bytes(b"weights")
    cache = package / "__pycache__"
    cache.mkdir()
    (cache / "main.cpython.pyc").write_bytes(b"first cache")
    (package / "loose.pyc").write_bytes(b"first loose bytecode")

    before = canonical_sha256_path(package)
    assert before == evaluator_sha256_path(package)

    (cache / "main.cpython.pyc").write_bytes(b"changed cache")
    (package / "loose.pyc").write_bytes(b"changed loose bytecode")
    assert canonical_sha256_path(package) == before

    (package / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert canonical_sha256_path(package) != before


def test_static_scanner_finds_each_required_pattern_category(tmp_path: Path):
    package = tmp_path / "safe_fixture"
    package.mkdir()
    (package / "fixture.py").write_text(
        """\
import ctypes
import multiprocessing
import random
import threading
import time

_AGENT = object()
agent_ptr = ctypes.c_void_p()

def choose(deadline):
    global agent_ptr
    lock = threading.Lock()
    worker = multiprocessing.Process(target=lambda: None)
    if time.monotonic() < deadline:
        return random.choice([1, 2]), lock, worker
    return agent_ptr
""",
        encoding="utf-8",
    )

    audit = scan_python_package(package, redistributable_source=True)
    assert audit["status"] == "completed_static_python_ast_scan"
    for category in CATEGORY_DEFINITIONS:
        assert audit["categories"][category]["hit_count"] > 0
        assert audit["categories"][category]["result"] == "explicit_pattern_hits_found"
        assert audit["categories"][category]["evidence"]


def test_restricted_report_redacts_source_locations_and_snippets(tmp_path: Path):
    package = tmp_path / "restricted_fixture"
    package.mkdir()
    (package / "secret_agent.py").write_text(
        "import random\nSECRET_CARD_NAME = 'withheld'\nVALUE = random.choice([1])\n",
        encoding="utf-8",
    )

    audit = scan_python_package(package, redistributable_source=False)
    encoded = json.dumps(audit, sort_keys=True)
    assert audit["source_paths_disclosed"] is False
    assert audit["source_line_numbers_disclosed"] is False
    assert audit["source_snippets_disclosed"] is False
    assert "secret_agent.py" not in encoded
    assert "SECRET_CARD_NAME" not in encoded
    assert "random.choice" not in encoded


def test_no_hit_result_explicitly_disclaims_determinism(tmp_path: Path):
    package = tmp_path / "plain_fixture"
    package.mkdir()
    (package / "plain.py").write_text("VALUE = 1\n", encoding="utf-8")

    audit = scan_python_package(package, redistributable_source=False)
    category = audit["categories"]["process_or_thread_parallelism"]
    assert category["result"] == "no_explicit_pattern_hit_found"
    assert category["hit_count"] == 0
    assert "not evidence" in category["interpretation"]


def test_frozen_inventory_has_exact_requested_roles():
    assert len(ARTIFACTS) == 13
    assert {spec.artifact_id for spec in ARTIFACTS} == {
        "seeded_engine",
        "production_engine",
        "c1",
        "c2",
        "c3",
        "c4",
        "opponent_b0",
        "opponent_d842_runtime",
        "opponent_master_v1",
        "opponent_replay_refresh",
        "opponent_alakazam_no_search",
        "opponent_starmie",
        "opponent_dipplin",
    }
    assert all(len(spec.expected_sha256) == 64 for spec in ARTIFACTS)
