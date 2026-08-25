from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path


FINAL = Path(__file__).resolve().parents[1]
ROOT = FINAL.parents[1]
LEDGER = FINAL / "claim_ledger.csv"
SCOPE_AUDIT = FINAL / "source_data/claim_scope_audit.json"
EXPECTED_FIELDS = [
    "claim_id", "exact_sentence", "manuscript_location", "claim_type",
    "status", "raw_source", "source_sha256", "protocol_commit",
    "analysis_script", "analysis_script_sha256", "command", "analysis_unit",
    "sample_size", "estimate", "interval_or_test", "assumptions",
    "limitations", "prior_work_overlap", "allowed_wording",
    "forbidden_wording", "machine_verified", "human_verified", "notes",
]
ALLOWED = {"VERIFIED", "VERIFIED_WITH_CAVEAT", "DERIVED_BY_CHECKED_SCRIPT"}
BLOCKED = {
    "PENDING", "CONFLICT", "UNSUPPORTED", "INFERRED_WITHOUT_SOURCE",
    "NOVELTY_UNRESOLVED", "RIGHTS_UNRESOLVED",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    value.update(path.read_bytes())
    return value.hexdigest()


def rows() -> tuple[list[str], list[dict[str, str]]]:
    with LEDGER.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or ()), list(reader)


def test_required_schema_and_allowed_statuses() -> None:
    fields, data = rows()
    assert fields == EXPECTED_FIELDS
    assert data
    assert len({row["claim_id"] for row in data}) == len(data)
    assert {row["status"] for row in data} <= ALLOWED
    assert not ({row["status"] for row in data} & BLOCKED)
    assert all(all(row[field].strip() for field in EXPECTED_FIELDS) for row in data)
    assert all(row["human_verified"].startswith("NO") for row in data)


def test_claim_sentences_and_source_hashes_are_bound() -> None:
    _, data = rows()
    manuscript = re.sub(r"\s+", " ", (FINAL / "main.tex").read_text(encoding="utf-8")).strip()
    for row in data:
        assert re.sub(r"\s+", " ", row["exact_sentence"]).strip() in manuscript
        sources = [item.strip() for item in row["raw_source"].split(";")]
        hashes = row["source_sha256"].split(";")
        assert len(sources) == len(hashes)
        assert [digest(ROOT / source) for source in sources] == hashes


def test_checked_scripts_are_hash_bound() -> None:
    _, data = rows()
    for row in data:
        if row["analysis_script"] == "not applicable":
            assert row["analysis_script_sha256"] == "not applicable"
        else:
            assert digest(ROOT / row["analysis_script"]) == row["analysis_script_sha256"]


def test_exhaustive_prose_scope_audit_is_bound_to_ledger() -> None:
    payload = json.loads(SCOPE_AUDIT.read_text(encoding="utf-8"))
    _, data = rows()
    by_id = {row["claim_id"]: row for row in data}
    assert payload["status"] == "PASS"
    assert payload["manuscript_sha256"] == digest(FINAL / "main.tex")
    assert payload["builder_sha256"] == digest(FINAL / "scripts/build_claim_ledger.py")
    assert payload["ledger_sha256"] == digest(LEDGER)
    assert payload["all_in_scope_bound"] is True
    assert payload["all_outside_scope_explained"] is True
    assert payload["counts"]["unique_ledger_rows"] == len(data)
    assert payload["counts"]["human_verified_yes"] == 0
    assert payload["counts"]["prose_sentence_occurrences"] == len(payload["records"])
    assert payload["counts"]["in_scope_occurrences"] == len(payload["records"])
    for record in payload["records"]:
        assert record["scope"] == "IN_SCOPE"
        assert record["claim_id"] in by_id
        assert by_id[record["claim_id"]]["exact_sentence"] == record["exact_sentence"]
        assert record["matched_claim_types"]
        assert set(record["matched_claim_types"]) <= {
            "quantitative", "comparative", "novelty", "procedural", "rights", "contribution",
        }
        assert record["matched_rules"]
    assert payload["excluded_structured_constructs"]
    assert all(item["reason"] for item in payload["excluded_structured_constructs"])
