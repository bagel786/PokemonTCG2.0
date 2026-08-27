"""Statistical procedure fixtures: Wilson toy example, McNemar hand case,
sign-flip permutation determinism."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.stats import wilson_interval, exact_mcnemar, signflip_permutation_p  # noqa: E402


def test_wilson_toy_matches_frozen_equation():
    p, lo, hi = wilson_interval(38, 40)
    assert round(p, 3) == 0.950
    assert round(lo, 3) == 0.835
    assert round(hi, 3) == 0.986


def test_exact_mcnemar_hand_case():
    # discordant pairs b=1, c=9 -> exact two-sided p = 2*P(X<=1), X~Bin(10,.5)
    p = exact_mcnemar(b=1, c=9)
    assert abs(p - 0.021484375) < 1e-12


def test_signflip_permutation_is_deterministic_and_sane():
    diffs = np.array([5.0, -3.0, 4.4, -2.2, 6.1, -0.7, 8.8, -1.9])
    p1 = signflip_permutation_p(diffs, n_flips=10000, rng_seed=20260827)
    p2 = signflip_permutation_p(diffs, n_flips=10000, rng_seed=20260827)
    assert p1 == p2
    assert 0 <= p1 <= 1
