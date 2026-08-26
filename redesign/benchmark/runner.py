"""Experiment runner: executes the scenario x seed grid on both systems,
collects artifacts, evaluates all methods against construction-known ground
truth, and writes raw JSONL rows (prospective results).

Raw rows are the source-of-truth hierarchy level 1. Nothing here inspects
aggregate outcomes before the frozen analysis plan is committed.
"""

import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.adapters import HoldemAdapter, IsingAdapter, _MODULE_CACHE  # noqa: E402
from benchmark.baselines import BASELINES, FULL_FRAMEWORK  # noqa: E402
from benchmark.classifier import build_bundle, classify_all  # noqa: E402
from benchmark.scenarios import SCENARIOS  # noqa: E402

SCENARIO_ORDER = [f"S{i}" for i in range(11)]


def load_seeds(path):
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Scenario mechanics applied around adapter calls
# ---------------------------------------------------------------------------

def _holdem_budget_action(adapter, state, rng, budget_ms, t_start):
    """Clock-bounded think loop (S4): draws until deadline."""
    legal_ids = [int(a) for a in state["legal_actions"].keys()]
    k = 0
    while (time.perf_counter() - t_start) * 1000.0 < budget_ms:
        _ = float(rng.random())
        k += 1
        if k > 4000:
            break
    u = float(rng.random())
    return legal_ids[min(int(u * len(legal_ids)), len(legal_ids) - 1)]


class GameSystem:
    def __init__(self):
        self.adapter = HoldemAdapter(num_hands=10)
        self.id = "holdem"

    def run_pair(self, seed, scenario, ctx="fresh", process_rank=0, repeats=0):
        """Returns (arm_a, arm_b, repeats_a, context_records)."""
        mech = SCENARIOS[scenario]["mechanics"]
        pol_a, pol_b = ("random", "conservative")

        # Injections S1/S2 target ARM B only; arm A stays on clean mechanics.
        base_scenario = "S0" if scenario in ("S1", "S2", "S7", "S9", "S10") else scenario
        ek = bool(mech.get("event_keyed"))
        qa = (int(process_rank) % 3) if mech.get("queue_order_seeding") else 0
        qb = ((7 * int(process_rank) + 1) % 3) if mech.get(
            "queue_order_seeding") else 0
        kwargs_a = dict(seed=int(seed), policy=pol_a, scenario=base_scenario,
                        context={"worker_state": ctx, "queue_skew": qa},
                        event_keyed=ek)
        kwargs_b = dict(seed=int(seed), policy=pol_b, scenario=scenario,
                        context={"worker_state": ctx, "queue_skew": qb},
                        event_keyed=ek)

        if scenario == "S5" and ctx == "reused":
            _MODULE_CACHE.append(1)

        if scenario in ("S4", "S8"):
            arm_a = self._budgeted_run(seed, pol_a, ctx, process_rank)
            arm_b = self._budgeted_run(seed, pol_b, ctx, process_rank)
        else:
            arm_a = self.adapter.run_arm(**kwargs_a)
            arm_b = self.adapter.run_arm(**kwargs_b)

        reps = []
        for _ in range(max(0, repeats)):
            if scenario in ("S4", "S8"):
                reps.append(self._budgeted_run(seed, pol_a, ctx, process_rank))
            else:
                reps.append(self.adapter.run_arm(
                    seed=int(seed), policy=pol_a, scenario=base_scenario,
                    context={"worker_state": ctx, "queue_skew": qa},
                    event_keyed=ek))

        ctx_rec = []
        for label in ("fresh", "reused"):
            alt_ctx = {"worker_state": label}
            save = list(_MODULE_CACHE)
            if scenario == "S5":
                _MODULE_CACHE.clear() if label == "fresh" else _MODULE_CACHE.append(1)
                ctx_scenario = scenario  # contamination must apply in reused ctx
            else:
                ctx_scenario = base_scenario
            alt_ctx["queue_skew"] = 1 if label == "reused" else 0
            if scenario in ("S4", "S8"):
                r = self._budgeted_run(seed, pol_a, label, 1 - process_rank)
            else:
                r = self.adapter.run_arm(seed=int(seed), policy=pol_a,
                                         scenario=ctx_scenario, context=alt_ctx,
                                         event_keyed=ek)
            _MODULE_CACHE.clear()
            _MODULE_CACHE.extend(save)
            dfp = next((e.get("value") for e in r.draw_log
                        if e.get("source") == "dealer"), None)
            ctx_rec.append({"context_label": f"{ctx}|{label}",
                            "digest": r.projection_digest(),
                            "dealer_fp": dfp})
        return arm_a, arm_b, reps, ctx_rec

    def _budgeted_run(self, seed, policy, ctx, process_rank):
        """Holdem run whose agent spends a wall-clock think budget each step."""
        import hashlib

        budget_ms = 0.30 * (1.0 + 0.75 * ((process_rank + (len(_MODULE_CACHE) > 0)) % 3))
        log = []
        eff = int(seed)
        from benchmark.adapters import LoggingRandomState, LoggingStatefulRNG
        d_child, a_child = np.random.SeedSequence(eff).spawn(2)
        rs = LoggingRandomState(d_child.generate_state(4, dtype=np.uint32), log)
        rs.effective_seed = eff
        agent_rng = LoggingStatefulRNG(
            int(a_child.generate_state(1, dtype=np.uint64)[0]), log=[])
        env = self.adapter.rlcard.make("limit-holdem", config={"seed": 0})
        env.game.np_random = rs
        env.np_random = rs
        traj = []
        chips = 0.0
        perturb = scenario_is("S5") and len(_MODULE_CACHE) > 0
        for h in range(self.adapter.num_hands):
            env.reset()
            step = 0
            while not env.is_over():
                pid = env.get_player_id()
                st = env.get_state(pid)
                ids = [int(a) for a in st["legal_actions"].keys()]
                names = list(st["raw_legal_actions"])
                if perturb and h == 0 and step == 0:
                    a = ids[-1]
                elif policy == "random":
                    t_s = time.perf_counter()
                    k = 0
                    while (time.perf_counter() - t_s) * 1000.0 < budget_ms:
                        _ = float(agent_rng.random())
                        k += 1
                        if k > 3000:
                            break
                    u = float(agent_rng.random())
                    a = ids[min(int(u * len(ids)), len(ids) - 1)]
                else:
                    pick = next((i for i in ids if name_for(names, ids, i) ==
                                 ("call" if "call" in names else "fold")), ids[0])
                    a = pick
                env.step(int(a))
                traj.append((h, step, pid, int(a)))
                step += 1
            chips += float(env.get_payoffs()[0])
        import hashlib as _h
        proj = {"trajectory_hash": _h.sha256(json.dumps(traj).encode()).hexdigest(),
                "terminal_outcome": round(chips, 6), "num_steps": len(traj)}
        from benchmark.adapters import RunArtifact
        return RunArtifact(
            system=self.adapter.system_id, adapter_version=self.adapter.adapter_version,
            adapter_hash=self.adapter.self_hash, declared_seed=int(seed),
            effective_seed=eff, policy=policy, scenario=active_scenario(),
            event_keyed=False, outcome=round(chips, 6),
            declared_projection=proj, draw_log=log[:300], n_draws=log_count(log),
            runtime_s=0.0, bytes_stored=len(json.dumps(proj)))


def name_for(names, ids, i):
    try:
        return names[ids.index(i)]
    except Exception:
        return ""


_ACTIVE = {"scenario": "S0"}


def active_scenario():
    return _ACTIVE["scenario"]


def scenario_is(s):
    return _ACTIVE["scenario"] == s


def log_count(log):
    return min(len(log), 300)


class IsingSystem:
    def __init__(self):
        self.adapter = IsingAdapter(size=20, sweeps=90, equilibration=20)
        self.id = "ising"

    def run_pair(self, seed, scenario, ctx="fresh", process_rank=0, repeats=0):
        t_a, t_b = 2.269, 2.9
        if scenario == "S10":
            arm_b_seed = int(seed) + 1_000_003
        else:
            arm_b_seed = int(seed)
        base_scenario = "S0" if scenario in ("S1", "S2", "S7", "S9", "S10") else scenario
        mech = SCENARIOS[scenario]["mechanics"]
        ek = bool(mech.get("event_keyed"))
        arm_a = self.adapter.run_arm(seed=int(seed), temperature=t_a,
                                     scenario=base_scenario, event_keyed=ek)
        arm_b = self.adapter.run_arm(seed=arm_b_seed, temperature=t_b,
                                     scenario=scenario, event_keyed=ek)
        reps = [self.adapter.run_arm(seed=int(seed), temperature=t_a,
                                     scenario=base_scenario, event_keyed=ek)
                for _ in range(repeats)]
        ctx_rec = [{"context_label": f"{ctx}|{label}",
                    "digest": self.adapter.run_arm(
                        seed=int(seed), temperature=t_a, scenario=base_scenario,
                        event_keyed=ek).projection_digest()}
                   for label in ("fresh", "reused")]
        return arm_a, arm_b, reps, ctx_rec


SYSTEMS = {"holdem": GameSystem, "ising": IsingSystem}


# ---------------------------------------------------------------------------
# Ground truth scoring
# ---------------------------------------------------------------------------

BRANCH_TO_DIM = {
    "BRANCH_A": "descriptive",
    "BRANCH_B": "paired_inference",
    "BRANCH_C": "replay",
    "BRANCH_D": "crn",
    "BRANCH_E": "event_alignment",
}


def score_cell(decision, gt):
    """-> one of CORRECT, MISSED_FAILURE, FALSE_SUPPRESSION_SOFT,
    FALSE_SUPPRESSION_HARD, DETECTED_WITH_CAVEAT."""
    if gt == "VALID":
        if decision == "ADMIT":
            return "CORRECT"
        if decision == "DOWNGRADE":
            return "FALSE_SUPPRESSION_SOFT"
        return "FALSE_SUPPRESSION_HARD"
    if gt == "INVALID":
        if decision == "SUPPRESS":
            return "CORRECT"
        if decision == "FAIL_CLOSED":
            return "CORRECT"
        if decision == "DOWNGRADE":
            return "DETECTED_WITH_CAVEAT"
        return "MISSED_FAILURE"
    if gt == "DOWNGRADE":
        if decision == "ADMIT":
            return "MISSED_FAILURE"
        if decision == "DOWNGRADE":
            return "CORRECT"
        return "FALSE_SUPPRESSION_HARD"
    if gt == "NOT_APPLICABLE":
        return "NOT_APPLICABLE"
    raise ValueError(gt)


def build_row_bundle(system_name, scenario, seed, arm_a, arm_b, reps, ctx,
                     mech, analysis_meta):
    coupling = "event_keyed" if mech.get("event_keyed") else (
        "stateful_sync" if not mech.get("independent_seeds") else None)
    design = ["randomized_assignment"]  # seeds drawn from documented RNG stream
    if mech.get("repeats_per_seed"):
        design.append("repeated_measures")
    plan = {
        "row_id": f"{system_name}-{scenario}-{seed}",
        "seed": int(seed),
        "condition_a": "A",
        "condition_b": "B",
        "coupling_type": coupling,
        "design_justifications": design,
        "independent_seeds": bool(mech.get("independent_seeds")),
    }
    meta = dict(analysis_meta or {})
    meta["repeats_per_unit"] = max(1, len(reps))
    return build_bundle(plan, arm_a, arm_b, repeats_a=reps, contexts=ctx,
                        rows_present=meta.pop("rows_present", 1),
                        rows_scheduled=meta.pop("rows_scheduled", 1),
                        analysis_meta=meta)


ANALYSIS_META_DEFAULT = {"analysis_unit": "seed_condition",
                         "model_family": "none"}
ANALYSIS_META_HIER = {"analysis_unit": "seed_condition",
                      "model_family": "hierarchical"}
ANALYSIS_META_PSEUDO = {"analysis_unit": "decision", "model_family": "none"}


def run_grid(systems, scenario_list, seeds, out_path):
    fh = open(out_path, "w")
    t_wall = time.time()

    for system_name in systems:
        system = SYSTEMS[system_name]()
        for sid in scenario_list:
            scen = SCENARIOS[sid]
            mech = dict(scen["mechanics"])
            repeats = int(mech.get("repeats_per_seed", 0)) - 1 \
                if mech.get("repeats_per_seed") else 1
            meta = ANALYSIS_META_DEFAULT
            if sid == "S8":
                meta = ANALYSIS_META_HIER
            if sid == "S9":
                meta = ANALYSIS_META_PSEUDO
            rows_scheduled = len(seeds)
            keep = [i for i in range(rows_scheduled) if not (
                mech.get("drop_rows_mod") and i % mech["drop_rows_mod"]
                == mech["drop_rows_mod"] - 1)]
            rows_present = len(keep)

            for i, seed in enumerate(seeds):
                _ACTIVE["scenario"] = sid
                if mech.get("drop_rows_mod") and i % mech["drop_rows_mod"] \
                        == mech["drop_rows_mod"] - 1:
                    continue  # silently dropped before analysis
                if mech.get("independent_seeds"):
                    pass  # handled inside system for ising; holdem below

                arm_a, arm_b, reps, ctx = system.run_pair(
                    seed, sid, ctx="fresh", process_rank=i % 2, repeats=repeats)
                if system_name == "holdem" and mech.get("independent_seeds"):
                    # rebuild arm B under an independent namespace
                    arm_b = system.adapter.run_arm(
                        seed=int(seed) + 1_000_003,
                        policy="conservative", scenario="S0",
                        context={"worker_state": "fresh"})

                bundle = build_row_bundle(system_name, sid, seed, arm_a, arm_b,
                                          reps, ctx, mech, meta)
                if sid == "S7":
                    bundle["rows_complete"] = rows_present == rows_scheduled
                    bundle["rows_missing"] = rows_scheduled - rows_present

                decisions_by_method = {
                    m: fn(bundle) for m, fn in BASELINES.items()}
                decisions_by_method[FULL_FRAMEWORK] = classify_all(bundle)

                for method, dec in decisions_by_method.items():
                    for branch, decision in dec.items():
                        dim = BRANCH_TO_DIM[branch]
                        gt = scen["gt"][dim]
                        cls = score_cell(decision, gt)
                        fh.write(json.dumps({
                            "level": "decision",
                            "system": system_name, "scenario": sid,
                            "seed": int(seed), "method": method,
                            "branch": branch, "decision": decision,
                            "gt": gt, "score_class": cls,
                        }) + "\n")

                # raw paired outcomes for downstream statistics
                fh.write(json.dumps({
                    "level": "outcome_pair",
                    "system": system_name, "scenario": sid, "seed": int(seed),
                    "outcome_a": arm_a.outcome, "outcome_b": arm_b.outcome,
                    "runtime_a": arm_a.runtime_s, "runtime_b": arm_b.runtime_s,
                    "bytes_a": arm_a.bytes_stored, "bytes_b": arm_b.bytes_stored,
                    "n_draws_a": arm_a.n_draws, "n_draws_b": arm_b.n_draws,
                    "effective_seed_a": int(arm_a.effective_seed),
                    "effective_seed_b": int(arm_b.effective_seed),
                    "declared_seed": int(seed),
                }) + "\n")
        print(f"[{system_name}] done at {time.time()-t_wall:.0f}s", flush=True)
    fh.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    man = load_seeds(args.manifest)
    run_grid(man["systems"], man["scenarios"], man["seeds"], args.out)


if __name__ == "__main__":
    main()
