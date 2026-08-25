"""Independent executable checks for every manuscript equation."""

from __future__ import annotations

import pytest


REQUIRED_PROFILES = ("serial_forward", "serial_reverse", "parallel_forward")


def cluster_disagrees(
    projections: dict[str, tuple[str, int]],
    required_profiles: tuple[str, ...] = REQUIRED_PROFILES,
) -> bool:
    """Implement Eq. 1 on complete (digest, byte-count) profile records."""
    if set(projections) != set(required_profiles):
        raise ValueError("required trace-projection profile is missing or unexpected")
    return len({projections[profile] for profile in required_profiles}) > 1


def test_trace_disagreement_toy_example() -> None:
    profiles = [
        dict.fromkeys(REQUIRED_PROFILES, ("a", 10)),
        {
            "serial_forward": ("b", 20),
            "serial_reverse": ("b", 20),
            "parallel_forward": ("c", 20),
        },
        dict.fromkeys(REQUIRED_PROFILES, ("d", 30)),
        {
            "serial_forward": ("e", 40),
            "serial_reverse": ("e", 41),
            "parallel_forward": ("e", 40),
        },
        dict.fromkeys(REQUIRED_PROFILES, ("g", 50)),
    ]
    disagreements = sum(cluster_disagrees(row) for row in profiles)
    assert disagreements == 2
    assert disagreements / len(profiles) == 0.40


def test_trace_disagreement_detects_byte_count_only_change() -> None:
    profiles = dict.fromkeys(REQUIRED_PROFILES, ("same-digest", 100))
    profiles["parallel_forward"] = ("same-digest", 101)
    assert cluster_disagrees(profiles)


def test_trace_disagreement_missing_profile_fails_closed() -> None:
    with pytest.raises(ValueError, match="required trace-projection profile"):
        cluster_disagrees(
            {
                "serial_forward": ("same-digest", 100),
                "serial_reverse": ("same-digest", 100),
            }
        )


def test_paired_difference_directions() -> None:
    assert 1 - 0 == 1
    assert 0 - 1 == -1
    assert 1 - 1 == 0
    assert 0 - 0 == 0


def test_stratified_paired_unit_reweighting_toy_example() -> None:
    differences = [1, 0, -1]
    sampled_one_based_indices = [1, 1, 2]
    replicate = sum(differences[index - 1] for index in sampled_one_based_indices) / 3
    assert replicate == 2 / 3


def test_factorial_signs_and_directions() -> None:
    mu_00, mu_10, mu_01, mu_11 = 0.50, 0.52, 0.51, 0.54
    total = mu_11 - mu_00
    representation = ((mu_10 - mu_00) + (mu_11 - mu_01)) / 2
    training = ((mu_01 - mu_00) + (mu_11 - mu_10)) / 2
    interaction = mu_11 - mu_10 - mu_01 + mu_00
    assert round(total, 12) == 0.04
    assert round(representation, 12) == 0.025
    assert round(training, 12) == 0.015
    assert round(interaction, 12) == 0.01
