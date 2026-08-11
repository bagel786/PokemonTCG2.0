import numpy as np
import pytest

from scripts.interpolate_policy_weights import interpolate


def checkpoint(path, value, *, schema=2):
    np.savez_compressed(
        path,
        model_schema_version=np.asarray(schema, dtype=np.int16),
        score=np.asarray([value, value + 2], dtype=np.float16),
    )


def test_interpolation_preserves_schema_and_blends_arrays(tmp_path):
    anchor = tmp_path / "anchor.npz"
    candidate = tmp_path / "candidate.npz"
    output = tmp_path / "blend.npz"
    checkpoint(anchor, 0)
    checkpoint(candidate, 4)
    manifest = interpolate(anchor, candidate, 0.25, output)
    with np.load(output, allow_pickle=False) as arrays:
        assert int(arrays["model_schema_version"].item()) == 2
        assert arrays["score"].tolist() == pytest.approx([1.0, 3.0])
    assert manifest["output_sha256"]


def test_interpolation_rejects_schema_mismatch(tmp_path):
    anchor = tmp_path / "anchor.npz"
    candidate = tmp_path / "candidate.npz"
    checkpoint(anchor, 0, schema=2)
    checkpoint(candidate, 1, schema=3)
    with pytest.raises(ValueError, match="schema"):
        interpolate(anchor, candidate, 0.5, tmp_path / "bad.npz")
