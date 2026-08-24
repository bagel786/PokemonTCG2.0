import pytest

from paper.release.evaluation import verify_pevl


def factorial_sources():
    return [
        {
            "cell": cell,
            "opponent": opponent,
            "path": f"restricted://factorial/{cell.lower()}_{opponent}.json",
            "sha256": f"{index:064x}",
        }
        for index, (cell, opponent) in enumerate(
            (
                (cell, opponent)
                for cell in sorted(verify_pevl.FACTORIAL_CELLS)
                for opponent in sorted(verify_pevl.RELEASE_FACTORIAL_OPPONENTS)
            ),
            start=1,
        )
    ]


def suppressed_payload(sources):
    return {
        "schema_version": 1,
        "analysis_id": "factorial",
        "status": "SUPPRESSED_CONTROL_PARITY_FAILURE",
        "admission_decision": "suppress_all_factorial_contrasts",
        "protocol_commit": "c" * 40,
        "control_mismatch_units": 1,
        "sources": sources,
    }


def test_control_suppression_accepts_exact_fifteen_source_inventory(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        verify_pevl, "FACTORIAL_UNITS_FILE", tmp_path / "absent.csv"
    )
    status, rows = verify_pevl.validate_factorial(
        suppressed_payload(factorial_sources()), "PASS"
    )
    assert status == "SUPPRESSED_CONTROL_PARITY_FAILURE"
    assert rows == 0


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong_cell"])
def test_factorial_source_inventory_fails_closed(tmp_path, monkeypatch, mutation):
    monkeypatch.setattr(
        verify_pevl, "FACTORIAL_UNITS_FILE", tmp_path / "absent.csv"
    )
    sources = factorial_sources()
    if mutation == "missing":
        sources.pop()
    elif mutation == "duplicate":
        sources[-1] = dict(sources[0])
    else:
        sources[-1]["cell"] = "C1"
    with pytest.raises(verify_pevl.VerificationError, match="factorial"):
        verify_pevl.validate_factorial(suppressed_payload(sources), "PASS")
