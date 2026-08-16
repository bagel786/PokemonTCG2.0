from __future__ import annotations

from scripts.build_grim_variance_candidates import build_candidates
from scripts.build_grim_guardrail_candidate import (
    FROZEN_MODEL_SHA256,
    FROZEN_RAW_DECK_SHA256,
    sha256_file,
)


def test_materializes_distinct_b0_b1_b2_b3_trees_without_archives(tmp_path):
    manifest = build_candidates(output=tmp_path / "candidates")
    assert set(manifest["candidates"]) == {"B0", "B1", "B2", "B3"}
    assert manifest["candidates"]["B0"]["runtime"] == "exact frozen d842"
    assert manifest["candidates"]["B1"]["runtime"]["variance_config"] == {
        "punk_up_floor": False,
        "dead_active_escape": False,
    }
    assert manifest["candidates"]["B2"]["runtime"]["variance_config"] == {
        "punk_up_floor": True,
        "dead_active_escape": False,
    }
    assert manifest["candidates"]["B3"]["runtime"]["variance_config"] == {
        "punk_up_floor": True,
        "dead_active_escape": True,
    }
    for variant, payload in manifest["candidates"].items():
        directory = payload["directory"]
        assert sha256_file(f"{directory}/policy_weights.npz") == FROZEN_MODEL_SHA256
        assert sha256_file(f"{directory}/deck.csv") == FROZEN_RAW_DECK_SHA256
    assert not (tmp_path / "candidates" / "B0.tar.gz").exists()
