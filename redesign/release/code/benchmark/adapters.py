"""System adapters: RLCard limit-holdem (game) and Ising 2D Monte Carlo (science).

Each adapter executes ONE arm under one schedule row and returns a RunArtifact
containing artifact identity, a declared trace projection, a logged draw/event
stream, the terminal outcome, and runtime/storage accounting.

Verified against installed versions (2026-08-26):
  rlcard==1.2.0   env.seed(seed) -> game.np_random (RandomState) -> dealer.shuffle
                  loop: env.reset(); env.get_player_id(); env.get_state(pid);
                        env.step(a); env.is_over(); env.get_payoffs()
  ising-toolkit@main (MIT) MetropolisSampler(model, seed); model.set_seed(seed);
                  sampler.use_fast_sweep=False -> model.random_site() +
                  sampler.rng.random() acceptance, scalar draws.
"""

import hashlib
import json
import platform
import time

import numpy as np

from .rng_manager import EventKeyedRNG, LoggingStatefulRNG, extra_draw_burn


def _file_hash(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


class RunArtifact:
    def __init__(self, **kw):
        self.__dict__.update(kw)
    def projection_digest(self):
        blob = json.dumps(self.declared_projection, sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()

    def compact(self):
        d = dict(self.__dict__)
        return d


class LoggingRandomState(np.random.RandomState):
    """RandomState subclass recording every dealer-stream call (RLCard legacy API)."""

    def __init__(self, seed, log=None):
        super().__init__(seed)
        self.effective_seed = None  # set by caller when int
        self.log = log if log is not None else []

    def shuffle(self, x):
        super().shuffle(x)
        try:
            fp = hash(tuple(str(getattr(c, "rank", c)) + str(
                getattr(getattr(c, "suit", None), "value", "")) for c in x)) % (2 ** 32)
        except TypeError:
            fp = hash(tuple(map(str, x))) % (2 ** 32)
        self.log.append({"kind": "shuffle", "index": len(self.log),
                         "value": int(fp), "source": "dealer"})
        return x


def _rs_seed_arg(seed_sequence_child):
    """RandomState accepts arrays of uint32 (legacy seeding contract)."""
    state = seed_sequence_child.generate_state(4, dtype=np.uint32)
    return state


# ---------------------------------------------------------------------------
# Game adapter
# ---------------------------------------------------------------------------

class HoldemAdapter:
    system_id = "rlcard_limit_holdem"
    adapter_version = "1.0.0"

    def __init__(self, num_hands=12):
        import rlcard
        self.rlcard = rlcard
        self.num_hands = num_hands
        self.self_hash = _file_hash(__file__)

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _action_maps(state):
        ids = [int(a) for a in state["legal_actions"].keys()] if hasattr(
            state["legal_actions"], "keys") else [int(a) for a in state["legal_actions"]]
        names = list(state["raw_legal_actions"])
        return {i: n for i, n in zip(ids, names)}, ids

    def _policy_action(self, policy, state, rng, tag):
        name_of, ids = self._action_maps(state)
        if policy == "random":
            u = float(rng.random_sample()) if isinstance(rng, np.random.RandomState) \
                else float(rng.random())
            idx = min(int(u * len(ids)), len(ids) - 1)
            return ids[idx]
        if policy == "conservative":
            for want in ("call", "check", "fold"):
                for i in ids:
                    if name_of[i] == want:
                        return i
            return ids[0]
        raise ValueError(policy)

    # -- main -----------------------------------------------------------------
    def run_arm(self, seed, policy, scenario="S0", event_keyed=False,
                context=None, clock_budget_ms=None):
        t0 = time.perf_counter()
        context = context or {}
        log = []
        eff_seed = int(seed)

        if scenario == "S1":  # namespace conversion at 16-bit boundary
            eff_seed = int(seed) & 0xFFFF

        # Substream separation: dealer and agent randomness derive from
        # independent children of the declared seed (SeedSequence.spawn), so
        # agent trajectory length cannot desync future deals across arms.
        ss = np.random.SeedSequence(eff_seed)
        dealer_child, agent_child = ss.spawn(2)

        if event_keyed:
            ek = EventKeyedRNG(stream_key=f"holdem-{seed}", log=log)
            rs = None
            agent_rng = None
        else:
            rs = LoggingRandomState(_rs_seed_arg(dealer_child), log=log)
            rs.effective_seed = eff_seed
            agent_rng = LoggingStatefulRNG(
                int(agent_child.generate_state(1, dtype=np.uint64)[0]), log=[])

        env = self.rlcard.make("limit-holdem", config={"seed": 0})
        if event_keyed:
            env.game.np_random = _KeyedShuffleAdapter(ek, self.num_hands)
            env.np_random = env.game.np_random
        else:
            env.game.np_random = rs
            env.np_random = rs

        traj = []
        chip_total = 0.0
        perturb = (scenario == "S5" and context.get("worker_state") == "reused")
        # S6 queue-order skew: deterministic per-arm draw tax from enqueue order
        queue_skew = int(context.get("queue_skew", 0)) if scenario == "S6" else 0
        s2_shift = (scenario == "S2")
        for h in range(self.num_hands):
            if perturb:
                rs.random()
            if s2_shift:
                rs.random()          # recurring one-draw shift, every hand
            for _q in range(queue_skew):
                rs.random()          # queue-order draw tax, every hand
            env.reset()
            step = 0
            while not env.is_over():
                pid = env.get_player_id()
                st = env.get_state(pid)
                key = f"h{h}|s{step}|p{pid}"
                if event_keyed:
                    a = self._eventkeyed_action(ek, st, key)
                else:
                    a = self._policy_action(policy, st, agent_rng, key)
                env.step(int(a))
                traj.append((h, step, pid, int(a)))
                step += 1
            chip_total += float(env.get_payoffs()[0])

        elapsed = time.perf_counter() - t0
        declared_projection = {
            "trajectory_hash": hashlib.sha256(
                json.dumps(traj, sort_keys=True).encode()).hexdigest(),
            "terminal_outcome": round(chip_total, 6),
            "num_steps": len(traj),
        }
        return RunArtifact(
            system=self.system_id,
            adapter_version=self.adapter_version,
            adapter_hash=self.self_hash,
            python=platform.python_version(),
            numpy=np.__version__,
            declared_seed=int(seed),
            effective_seed=int(getattr(rs, "effective_seed", seed)) if rs else int(seed),
            policy=policy,
            scenario=scenario,
            event_keyed=event_keyed,
            outcome=round(chip_total, 6),
            declared_projection=declared_projection,
            draw_log=log[:300],
            n_draws=len(log),
            runtime_s=elapsed,
            bytes_stored=int(
                len(json.dumps(declared_projection))
                + sum(len(json.dumps(e)) for e in log[:300])
            ),
        )

    def _eventkeyed_action(self, ek, state, key):
        name_of, ids = self._action_maps(state)
        u = ek.draw(event_id=f"{key}|act")
        idx = min(int(u * len(ids)), len(ids) - 1)
        return ids[idx]


class _KeyedShuffleAdapter:
    """Duck-typed stand-in exposing shuffle() driven by event-keyed draws.

    Deck order for hand h is a pure function of (stream_key, h): identical
    across arms regardless of execution path (Branch E construction).
    """

    def __init__(self, ek, n_hands):
        self.ek = ek
        self.n_hands = n_hands
        self.hand_counter = 0
        self.k_other = 0

    def randint(self, low, high=None, size=None):
        u = self.ek.draw(event_id=f"misc|{self.k_other}")
        self.k_other += 1
        if size is not None:
            import numpy as np
            return np.array([low + int(u * max(1, (high or low + 1) - low))] * size)
        return low + int(u * max(1, (high or low + 1) - low))

    def shuffle(self, deck):
        h = self.hand_counter
        self.hand_counter += 1
        n = len(deck)
        for i in range(n - 1, 0, -1):
            u = self.ek.draw(event_id=f"hand{h}|shuffle|{i}")
            j = int(u * (i + 1))
            deck[i], deck[j] = deck[j], deck[i]


# ---------------------------------------------------------------------------
# Ising adapter
# ---------------------------------------------------------------------------

class IsingAdapter:
    system_id = "ising2d_metropolis"
    adapter_version = "1.0.0"

    def __init__(self, size=32, sweeps=600, equilibration=100):
        self.size = size
        self.sweeps = sweeps
        self.equilibration = equilibration
        from ising_toolkit.models import Ising2D  # noqa: F401
        self.self_hash = _file_hash(__file__)

    def run_arm(self, seed, temperature, scenario="S0", event_keyed=False,
                context=None, clock_budget_ms=None):
        from ising_toolkit.models import Ising2D
        from ising_toolkit.samplers import MetropolisSampler

        t0 = time.perf_counter()
        log = []
        eff_seed = int(seed)
        if scenario == "S1":
            eff_seed = int(seed) & 0xFFFF

        model = Ising2D(size=self.size, temperature=float(temperature),
                        use_numba=False)
        if event_keyed:
            ek = EventKeyedRNG(stream_key=f"ising-{seed}", log=log)
            sampler = MetropolisSampler(model, seed=None)
            model._rng = _KeyedModelRNG(ek, self.size)
        else:
            model.set_seed(eff_seed)
            sampler = MetropolisSampler(model, seed=eff_seed)
            rs = LoggingStatefulRNG(eff_seed, log=log)
            if scenario == "S2":
                extra_draw_burn(rs, n=1)
            model._rng = rs

        mags = []
        total_steps = self.equilibration + self.sweeps
        for s in range(total_steps):
            sampler.step()
            if s >= self.equilibration and (s - self.equilibration) % 10 == 0:
                mags.append(float(model.get_magnetization()))

        elapsed = time.perf_counter() - t0
        arr = np.asarray(mags)
        declared_projection = {
            "mag_trajectory_hash": hashlib.sha256(
                np.round(arr, 8).tobytes()).hexdigest(),
            "terminal_abs_mag": round(float(abs(arr[-1])), 8),
            "n_measurements": int(arr.size),
        }
        return RunArtifact(
            system=self.system_id,
            adapter_version=self.adapter_version,
            adapter_hash=self.self_hash,
            declared_seed=int(seed),
            effective_seed=eff_seed,
            temperature=float(temperature),
            scenario=scenario,
            event_keyed=event_keyed,
            outcome=float(np.mean(np.abs(arr))),
            declared_projection=declared_projection,
            draw_log=log[:200],
            n_draws=len(log),
            runtime_s=elapsed,
            bytes_stored=int(
                len(json.dumps(declared_projection))
                + sum(len(json.dumps(e)) for e in log[:200])
            ),
        )


class _KeyedModelRNG:
    """Duck-typed RNG exposing integers() and random() via event-keyed draws.

    Replaces model._rng: site selection uses integers(0, L); Metropolis
    acceptance inside the pure-Python sweep uses random(). Event ids embed a
    monotonically increasing counter per call type.
    """

    def __init__(self, ek, L):
        self.ek = ek
        self.L = L
        self.k_int = 0
        self.k_float = 0

    def integers(self, low, high=None, size=None, dtype=None, endpoint=False):
        u = self.ek.draw(event_id=f"site|{self.k_int}")
        self.k_int += 1
        return int(u * self.L) % self.L

    def random(self, size=None):
        u = self.ek.draw(event_id=f"acc|{self.k_float}")
        self.k_float += 1
        return u


# Process-global mutable state used by scenario S5 (worker-reuse detection).
# Entries persist across run_arm calls within one process; a non-empty cache
# deterministically perturbs the next run's first action when the caller opts
# in (context='reused' under S5), emulating module-state contamination.
_MODULE_CACHE = []


def reset_module_cache():
    _MODULE_CACHE.clear()
