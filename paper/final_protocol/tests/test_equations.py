"""Independent executable checks for every manuscript equation."""

from __future__ import annotations


def test_trace_disagreement_toy_example() -> None:
    profiles = [
        ("a", "a", "a"),
        ("b", "b", "c"),
        ("d", "d", "d"),
        ("e", "f", "e"),
        ("g", "g", "g"),
    ]
    disagreements = sum(len(set(row)) > 1 for row in profiles)
    assert disagreements == 2
    assert disagreements / len(profiles) == 0.40


def test_paired_difference_directions() -> None:
    assert 1 - 0 == 1
    assert 0 - 1 == -1
    assert 1 - 1 == 0
    assert 0 - 0 == 0


def test_stratified_resampling_toy_example() -> None:
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
