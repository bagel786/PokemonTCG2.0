"""Equation fixtures independent of the production aggregation path."""

import math


def wilson_fixture(x, n, z=1.959964):
    p = x / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, center - half, center + half


def main():
    p, lo, hi = wilson_fixture(38, 40)
    assert abs(p - 0.95) < 1e-12
    assert round(lo, 3) == 0.835
    assert round(hi, 3) == 0.986
    # Sign/indexing fixture for d_i=A_i-B_i and cycle B_(i+1).
    a = [4.0, 3.0, 2.0]
    b = [1.0, 1.5, 1.0]
    paired = [aa - bb for aa, bb in zip(a, b)]
    independent = [a[i] - b[(i + 1) % len(b)] for i in range(len(a))]
    assert paired == [3.0, 1.5, 1.0]
    assert independent == [2.5, 2.0, 1.0]
    print("interval and indexing fixtures: PASS")


if __name__ == "__main__":
    main()
