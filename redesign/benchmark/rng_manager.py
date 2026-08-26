"""RNG management for the CSVF benchmark.

Three draw disciplines:
  STATEFUL   numpy PCG64 Generator seeded once (the common default practitioners assume).
  EXTRA_DRAW like STATEFUL but one arm consumes an extra draw at init (scenario S2).
  EVENTKEYED counter-based draws keyed by semantic event id (Philox), used by S3 repair
             and by B6-style white-box coupling.

Wrappers log every draw so the harness can emit event logs and verify alignment.
"""

import hashlib
import struct

import numpy as np


class LoggingStatefulRNG(np.random.Generator):
    """A Generator subclass that records (call_site_tag, value) tuples.

    Subclassing keeps the interface identical for the systems under test.
    """

    def __init__(self, seed, log=None):
        bit_gen = np.random.PCG64(seed)
        super().__init__(bit_gen)
        self.effective_seed = seed
        self.log = log if log is not None else []
        self._tag = "default"

    def tag(self, site):
        self._tag = site
        return self

    def _record(self, kind, value):
        self.log.append({
            "site": self._tag,
            "kind": kind,
            "index": len(self.log),
            "value": _hashable(value),
        })
        return value

    def random(self, size=None):
        v = super().random(size)
        self._record("random", v)
        return v

    def integers(self, low, high=None, size=None, dtype=np.int64, endpoint=False):
        v = super().integers(low, high, size, dtype, endpoint)
        self._record("integers", v)
        return v

    def choice(self, a, size=None, replace=True, p=None, axis=0, shuffle=True):
        v = super().choice(a, size, replace, p, axis, shuffle)
        self._record("choice", v)
        return v


class TruncatedSeedRNG(LoggingStatefulRNG):
    """Declares one seed but actually runs from a truncated seed (S1)."""

    def __init__(self, declared_seed, truncation_bits=32):
        mask = (1 << truncation_bits) - 1
        effective = int(declared_seed) & mask
        super().__init__(effective)
        self.declared_seed = int(declared_seed)


def _hashable(v):
    arr = np.asarray(v)
    if arr.dtype.kind in "fc":
        return [float(x) for x in arr.ravel().tolist()]
    return arr.ravel().tolist()


class EventKeyedRNG:
    """Counter-based RNG: draws are pure functions of (stream_key, event_id, draw_index).

    Same semantic event -> same quantities regardless of execution order or path.
    Marginals preserved because Philox outputs are uniform.
    """

    def __init__(self, stream_key, log=None):
        self.stream_key = str(stream_key)
        self.log = log if log is not None else []

    def draw(self, event_id, n=1):
        values = []
        base = f"{self.stream_key}|{event_id}".encode()
        for i in range(n):
            # SHA-256 counter block: standard hash-to-uniform construction.
            h = hashlib.sha256(base + b"|" + struct.pack("<Q", i)).digest()
            u = int.from_bytes(h[:8], "little") / float(2 ** 64)
            values.append(u)
        self.log.append({"event_id": event_id, "values": values})
        return values[0] if n == 1 else np.array(values)

    # Generator-like helpers used by adapters -------------------------------
    def integers(self, low, high, event_id="anon"):
        u = self.draw(event_id)
        return int(low + u * (high - low))


def extra_draw_burn(rng, n=1):
    """Consume n draws to simulate an arm that spends randomness before the
    compared computation begins (S2 stateful draw shift)."""
    for _ in range(n):
        rng.random()


def event_alignment_violations(log_a, log_b, ontology_keys):
    """Count semantic events whose recorded draw values differ across arms."""
    a = {e["event_id"]: e["values"] for e in log_a}
    b = {e["event_id"]: e["values"] for e in log_b}
    mismatched = 0
    compared = 0
    for k in ontology_keys:
        if k in a and k in b:
            compared += 1
            if a[k] != b[k]:
                mismatched += 1
    return {"compared": compared, "mismatched": mismatched}
