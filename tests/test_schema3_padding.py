import numpy as np
import pytest

from training.schema3 import pad_schema3


def test_padding_adds_exact_zero_row_and_preserves_every_other_array(tmp_path):
    source = tmp_path / "v2.npz"
    destination = tmp_path / "v3.npz"
    arrays = {
        "model_schema_version": np.asarray(2, dtype=np.int16),
        "numeric_w": np.arange(12 * 4, dtype=np.float16).reshape(12, 4),
        "numeric_b": np.arange(4, dtype=np.float16),
        "score_b": np.asarray([7], dtype=np.float16),
    }
    np.savez_compressed(source, **arrays)
    pad_schema3(source, destination)
    with np.load(destination, allow_pickle=False) as migrated:
        assert int(migrated["model_schema_version"]) == 3
        np.testing.assert_array_equal(migrated["numeric_w"][:12], arrays["numeric_w"])
        np.testing.assert_array_equal(migrated["numeric_w"][12], np.zeros(4, dtype=np.float16))
        np.testing.assert_array_equal(migrated["numeric_b"], arrays["numeric_b"])
        np.testing.assert_array_equal(migrated["score_b"], arrays["score_b"])


def test_zero_initialized_new_feature_preserves_policy_logits(tmp_path):
    torch = pytest.importorskip("torch")
    from ptcg_ai.features import DecisionFeatures, OptionFeatures, V2_GLOBAL_SIZE
    from ptcg_ai.model import NumpyPolicyModel
    from training.train_bc import PolicyNet, export_npz

    torch.manual_seed(4)
    v2_path, v3_path = tmp_path / "model2.npz", tmp_path / "model3.npz"
    export_npz(PolicyNet(2), v2_path)
    pad_schema3(v2_path, v3_path)
    common = dict(
        global_features=[0.1] * V2_GLOBAL_SIZE,
        state_tokens=[1, 648],
    )
    v2 = DecisionFeatures(
        **common,
        options=[OptionFeatures(13, 0, 648, 0, 937, 0, 0, [0.2] * 12)],
        feature_version=2,
    )
    v3 = DecisionFeatures(
        **common,
        options=[OptionFeatures(13, 0, 648, 0, 937, 0, 0, [0.2] * 12 + [0.0])],
        feature_version=3,
    )
    old = NumpyPolicyModel(v2_path).predict(v2)
    migrated = NumpyPolicyModel(v3_path).predict(v3)
    for old_value, migrated_value in zip(old, migrated):
        np.testing.assert_allclose(old_value, migrated_value, atol=0, rtol=0)
