import numpy as np

from paper.scripts.analyze_pevl import (
    binary_bootstrap,
    exact_mcnemar,
    factorial_bootstrap,
)


def test_exact_mcnemar_handles_balanced_and_one_direction_discordance():
    assert exact_mcnemar(0, 0) == 1.0
    assert exact_mcnemar(5, 5) == 1.0
    assert exact_mcnemar(10, 0) == 2 / (2**10)


def test_binary_bootstrap_is_seeded_and_cluster_based():
    first = binary_bootstrap([0, 0, 1, 1], seed=17, draws=2_000)
    second = binary_bootstrap([0, 0, 1, 1], seed=17, draws=2_000)
    assert first == second
    assert first["clusters"] == 4
    assert first["estimate"] == 0.5
    assert first["bootstrap_95_ci"] == [0.0, 1.0]


def test_factorial_bootstrap_preserves_paired_four_cell_structure():
    matrix = np.zeros((200, 4), dtype=np.float64)
    matrix[:, 3] = 1.0
    arrays = {f"stratum-{index}": matrix.copy() for index in range(10)}
    result = factorial_bootstrap(arrays, draws=500, seed=23)
    assert result["primary_c4_minus_c1"]["bootstrap_95_ci"] == [1.0, 1.0]
    assert result["representation_main"]["bootstrap_95_ci"] == [0.5, 0.5]
    assert result["training_main"]["bootstrap_95_ci"] == [0.5, 0.5]
    assert result["interaction"]["bootstrap_95_ci"] == [1.0, 1.0]
