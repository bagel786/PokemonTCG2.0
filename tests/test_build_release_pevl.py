import csv
import io

from paper.scripts import build_release


def test_release_identifier_atoms_are_canonical_across_json_and_csv():
    raw = {
        "factorial": {
            name: name
            for name in (
                "b0",
                "d842",
                "master",
                "replay",
                "alakazam_no_search",
            )
        },
        "seed_audit": {
            name: name
            for name in (
                "B0",
                "d842-runtime",
                "master-v1",
                "replay-refresh",
                "Alakazam-no-search",
            )
        },
    }
    sanitized = build_release.sanitize_json(raw)
    expected = {"Matched1", "Matched2", "Matched3", "Matched4", "Broader3"}
    assert set(sanitized["factorial"]) == expected
    assert set(sanitized["factorial"].values()) == expected
    assert set(sanitized["seed_audit"]) == expected
    assert set(sanitized["seed_audit"].values()) == expected

    text = "opponent,value\nb0,1\nd842,2\nmaster,3\nreplay,4\nalakazam_no_search,5\n"
    rows = list(csv.DictReader(io.StringIO(build_release.sanitize_csv_text(text))))
    assert {row["opponent"] for row in rows} == expected


def test_frozen_pevl_protocol_matches_declared_git_blob():
    assert build_release.protocol_names() == build_release.PROTOCOL_FILES
