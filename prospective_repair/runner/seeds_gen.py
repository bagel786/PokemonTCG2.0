"""Deterministic seed-bank generation with enforced disjointness.

Banks: pilot_mechanics(16) dev(12) final(80) repeats(not seeds—derived from
final bank) cost(50). Zero overlap among banks AND zero overlap with every V1
(redesign) seed (checked against redesign/protocol/SEED_MANIFEST.json values).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent

BANKS = [("pilot_mechanics", 16), ("dev", 12), ("final", 80), ("cost", 50)]


def _bank_seeds(bank: str, n: int):
    rng = np.random.default_rng(
        int.from_bytes(hashlib.sha256(
            f"prospective-repair-{bank}-v1".encode()).digest()[:16], "little"))
    seen = set()
    out = []
    while len(out) < n:
        v = int(rng.integers(2 ** 20, 2 ** 40))
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return sorted(out)


def generate() -> dict:
    banks = {name: _bank_seeds(name, n) for name, n in BANKS}
    # cross-bank disjointness
    allv = [v for vals in banks.values() for v in vals]
    if len(allv) != len(set(allv)):
        raise RuntimeError("seed collision across banks")
    v1 = json.loads((REPO / "redesign/protocol/SEED_MANIFEST.json").read_text())
    v1_vals = set(v1["pilot"]["values"]) | set(v1["final"]["values"])
    overlap = v1_vals & set(allv)
    if overlap:
        raise RuntimeError(f"V1 seed overlap: {sorted(overlap)[:5]}…")
    return {
        "kind": "SEED_MANIFEST",
        "campaign": "prospective-repair",
        "derivation": ("numpy default_rng(SHA256('prospective-repair-<bank>-v1')"
                       "[:16]); integers [2^20, 2^40), deduplicated; "
                       "banks pairwise disjoint; disjoint from ALL redesign/V1 "
                       "seeds by construction check"),
        "banks": {k: {"count": len(v), "values": v} for k, v in banks.items()},
        "v1_disjointness_verified": True,
    }


if __name__ == "__main__":
    man = generate()
    out = ROOT / "protocol" / "SEED_MANIFEST.json"
    if not out.exists():
        out.write_text(json.dumps(man, indent=2) + "\n")
        print(f"wrote {out}")
    else:
        existing = json.loads(out.read_text())
        if existing != man:
            raise SystemExit("REGISTRY MISMATCH: existing SEED_MANIFEST differs "
                             "from regeneration — inspect before overwrite.")
        print("SEED_MANIFEST stable under regeneration")
