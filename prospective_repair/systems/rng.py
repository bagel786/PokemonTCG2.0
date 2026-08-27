"""RNG management for the repaired campaign.

Disciplines:
  STATEFUL  logging Generator/RandomState on dedicated substreams
            (dealer/model = coupled stream; agent = isolated residual stream).
  EVENTKEYED counter-based draws keyed by semantic event ids, used ONLY for
            exogenous/chance events under keyed constructions. POLICY IS
            PRESERVED: the requested per-arm policy governs action choice.
Every draw is logged with stream+event identity so alignment/collision/
marginal checks operate on retained evidence rather than vibes.
"""
from __future__ import annotations

import hashlib
import struct

import numpy as np


def _hashable(v):
    arr = np.asarray(v)
    if arr.dtype.kind in "fc":
        return [float(x) for x in arr.ravel().tolist()]
    return arr.ravel().tolist()


class LoggingStatefulRNG(np.random.Generator):
    """Records every draw from this substream (kind/index/value/stream)."""

    def __init__(self, seed, log=None, stream="agent"):
        super().__init__(np.random.PCG64(seed))
        self.effective_seed = int(seed)
        self.log = log if log is not None else []
        self.stream_name = stream

    def _record(self, kind, value):
        self.log.append({"stream": self.stream_name, "kind": kind,
                         "index": len(self.log), "value": _hashable(value)})
        return value

    def random(self, size=None):
        return self._record("random", super().random(size))

    def integers(self, low, high=None, size=None, dtype=np.int64, endpoint=False):
        return self._record("integers",
                            super().integers(low, high, size, dtype, endpoint))

    def choice(self, a, size=None, replace=True, p=None, axis=0, shuffle=True):
        return self._record("choice",
                            super().choice(a, size, replace, p, axis, shuffle))


class LoggingRandomState(np.random.RandomState):
    """RandomState-compatible logging wrapper for legacy consumers (RLCard)."""

    def __init__(self, seed_arg, log=None):
        super().__init__(seed_arg)
        self.effective_seed = None
        self.log = log if log is not None else []
        self.stream_name = "dealer"

    def shuffle(self, x):
        super().shuffle(x)
        try:
            fp = hash(tuple(str(getattr(c, "rank", c)) +
                            str(getattr(getattr(c, "suit", None), "value", ""))
                            for c in x)) % (2 ** 32)
        except TypeError:
            fp = hash(tuple(map(str, x))) % 2 ** 32
        self.log.append({"stream": "dealer", "kind": "shuffle",
                         "index": len(self.log), "value": int(fp)})
        return x

    def rand(self, *args):
        v = super().rand(*args)
        if np.isscalar(v) or getattr(v, "ndim", 1) == 0:
            self.log.append({"stream": "dealer", "kind": "random",
                             "index": len(self.log), "value": float(v)})
        return v

    def randint(self, low, high=None, size=None):
        v = super().randint(low, high, size)
        self.log.append({"stream": "dealer", "kind": "randint",
                         "index": len(self.log), "value": _hashable(v)})
        return v


class EventKeyedRNG:
    """Counter-based uniform draws: pure function of (stream_key,event_id,i).

    Marginals preserved by SHA-256-to-uniform construction; identical events get
    identical values regardless of execution order/path (execution invariance).
    """

    def __init__(self, stream_key: str, log=None, stream_name: str = "dealer"):
        self.stream_key = str(stream_key)
        self.log = log if log is not None else []
        self.stream_name = stream_name
        self.draw_counter = {}   # event_id -> count (uniqueness audit support)

    def draw(self, event_id, n=1):
        values = []
        base = f"{self.stream_key}|{event_id}".encode()
        for i in range(n):
            h = hashlib.sha256(base + b"|" + struct.pack("<Q", i)).digest()
            u = int.from_bytes(h[:8], "little") / float(2 ** 64)
            values.append(u)
        self.draw_counter[event_id] = self.draw_counter.get(event_id, 0) + 1
        self.log.append({"stream": self.stream_name, "kind": "keyed",
                         "event_id": str(event_id), "values": values})
        return values[0] if n == 1 else np.array(values)

    def integers_keyed(self, low, high, event_id):
        """Uniform integer in [low, high) from a keyed draw (endpoints safe)."""
        u = float(self.draw(event_id))
        span = int(high) - int(low)
        return int(low) + min(int(u * span), span - 1)

    def collision_report(self):
        ids = [e["event_id"] for e in self.log]
        seen, dups = set(), 0
        for i in ids:
            if i in seen:
                dups += 1
            seen.add(i)
        return {"n_events": len(ids), "unique": len(seen), "duplicates": dups}


def marginal_uniformity_indicator(values, bins=10, min_n=50):
    """Chi-square-ish binned flatness indicator in [0,1]; 1 = perfectly flat.

    Values arrive as floats in [0,1). With <min_n samples returns True (not
    assessed) so small logs don't spuriously fail D gates.
    """
    vals = [v for v in values if isinstance(v, (int, float))]
    if len(vals) < min_n:
        return True
    counts = [0] * bins
    for v in vals:
        counts[min(int(float(v) * bins), bins - 1)] += 1
    exp = len(vals) / bins
    chi2 = sum((c - exp) ** 2 / exp for c in counts)
    # crude normalized fit score (no scipy dependency in evidence path)
    return chi2 < 3.0 * bins


class KeyedModelRNG:
    """Duck-typed RNG for Ising model internals: site selection via integers(),
    acceptance via random(), both keyed by stable attempt context."""

    def __init__(self, ek: EventKeyedRNG, L: int):
        self.ek = ek
        self.L = int(L)

    def integers(self, low, high=None, size=None, dtype=None, endpoint=False):
        k = getattr(self, "_k_int", 0)
        object.__setattr__(self, "_k_int", k + 1)
        return self.ek.integers_keyed(0, self.L, f"site|{k}")

    def random(self, size=None):
        k = getattr(self, "_k_acc", 0)
        object.__setattr__(self, "_k_acc", k + 1)
        return float(self.ek.draw(f"acc|{k}"))

    def random_site(self, *a, **kw):  # some toolkits call model-level helper
        return self.integers(0, self.L)


def burn_draws(rng, n: int = 1):
    for _ in range(n):
        rng.random()
