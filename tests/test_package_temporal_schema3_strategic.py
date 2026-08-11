import json
import tarfile

import numpy as np
import pytest

from ptcg_ai.external import ExternalSubmissionAgent
from scripts.package_temporal_schema3_strategic import (
    DEFAULT_D842,
    DEFAULT_FROZEN_V2,
    DEFAULT_TEMPORAL,
    EXPECTED_FROZEN_V2_SHA256,
    build_package,
    model_schema,
    require_model_schema,
    sha256_file,
)


def test_temporal_and_fallback_schema_contracts(tmp_path):
    assert model_schema(DEFAULT_TEMPORAL) == 3
    assert model_schema(DEFAULT_D842) == 2
    require_model_schema(DEFAULT_TEMPORAL, 3)
    require_model_schema(DEFAULT_D842, 2)

    wrong = tmp_path / "wrong.npz"
    np.savez_compressed(wrong, model_schema_version=np.asarray(2, dtype=np.int64))
    with pytest.raises(ValueError, match="schema 2, expected schema 3"):
        require_model_schema(wrong, 3)


def test_builds_schema3_controller_package_without_touching_frozen_v2(tmp_path):
    frozen_before = sha256_file(DEFAULT_FROZEN_V2)
    assert frozen_before == EXPECTED_FROZEN_V2_SHA256

    manifest = build_package(output_dir=tmp_path / "candidate")
    extracted = tmp_path / "candidate" / "extracted"
    archive = tmp_path / "candidate" / "grimmsnarl_temporal_schema3_corrected_strategic.tar.gz"
    candidate_hash = sha256_file(DEFAULT_TEMPORAL)

    assert sha256_file(DEFAULT_FROZEN_V2) == frozen_before
    assert manifest["source_artifacts"]["frozen_v2"]["preserved"] is True
    assert manifest["source_artifacts"]["temporal_policy"]["schema_version"] == 3
    assert manifest["packaged_hashes"]["policy_a2"] == candidate_hash
    assert manifest["packaged_hashes"]["policy_weights"] == candidate_hash
    assert model_schema(extracted / "policy_a2.npz") == 3
    assert model_schema(extracted / "policy_weights.npz") == 3
    assert model_schema(extracted / "policy_d842.npz") == 2

    config = json.loads((extracted / "strategic_config.json").read_text(encoding="utf-8"))
    assert config["architecture"] == "corrected_strategic_controller_over_temporal_schema3"
    assert config["enable_build_commitments"] is False
    assert config["enable_count_overrides"] is False
    assert config["enable_one_prize_hypotheses"] is False

    with tarfile.open(archive, "r:gz") as handle:
        names = handle.getnames()
    assert len(names) == len(set(names))
    assert "policy_a2.npz" in names
    assert "policy_weights.npz" in names
    assert "ptcg_ai/strategic_playbook.py" in names

    agent = ExternalSubmissionAgent(extracted)
    try:
        inner = agent.module._AGENT
        assert len(agent.deck) == 60
        assert inner.policy.model.feature_version == 3
        assert inner.errors == 0
    finally:
        agent.close()
