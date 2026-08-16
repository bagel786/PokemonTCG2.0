#!/usr/bin/env python3
"""Complete-turn root evaluation for R1 live-loss divergences (fresh processes)."""
from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import to_observation_class  # noqa: E402

OUT = ROOT / "artifacts" / "final_r1_drag_gate_20260816"

POINTS = [
    {"episode": "93755661", "step": 58, "sub": 55562629, "seat": 1, "label": "loss_normal"},
    {"episode": "93673237", "step": 162, "sub": 55556726, "seat": 0, "label": "loss_normal"},
    {"episode": "93685951", "step": 124, "sub": 55556726, "seat": 0, "label": "loss_structural"},
]

GRIM_DECK = [int(x) for x in (ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv").read_text().splitlines() if x.strip()]
E23_MODEL = ROOT / "artifacts" / "final_sprint" / "exp23_identity_trained" / "policy_weights.npz"


def get_decks(path, seat):
    ep = json.loads(path.read_text())
    steps = ep.get("steps") or []
    opp = 1 - seat
    decks = {}
    if len(steps) > 1:
        for s in (seat, opp):
            act = steps[1][s].get("action") or []
            if len(act) == 60:
                decks[s] = [int(c) for c in act]
    return decks


def run_one(point):
    import numpy as np
    from ptcg_ai.features import encode_observation
    from ptcg_ai.model import NumpyPolicyModel
    from ptcg_ai.safety import sanitize_selection
    from training.complete_turn_corrections import CorrectionConfig, evaluate_complete_turn_correction

    ep_id, step, sub, seat = point["episode"], point["step"], point["sub"], point["seat"]
    replay_root = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0-overnight/data/replays") / str(sub)
    path = replay_root / f"episode-{ep_id}-replay.json"
    if not path.exists():
        return {"key": f"{ep_id}:{step}", "error": "replay missing"}
    ep = json.loads(path.read_text())
    decks = get_decks(path, seat)
    opp_deck = decks.get(1 - seat)
    if not opp_deck or len(opp_deck) != 60:
        return {"key": f"{ep_id}:{step}", "error": "opponent deck unavailable"}
    row = ep["steps"][step][seat]
    obs_raw = (row.get("observation") or {})
    if not obs_raw.get("select") or not obs_raw.get("current"):
        return {"key": f"{ep_id}:{step}", "error": "no select at step"}
    gate = json.loads((OUT / "live_divergences.json").read_text())
    rec = next(r for r in gate if r["episode"] == ep_id)
    div = next(d for d in rec["divergences"] if d["step"] == step)
    baseline = [int(i) for i in div["exp23_indices"]]
    candidate = [int(i) for i in div["r1_indices"]]

    model = NumpyPolicyModel(str(E23_MODEL))

    def exp23_action(m, obs):
        features = encode_observation(obs, m.feature_version)
        logits, count_logits, _ = m.predict(features)
        if not len(logits):
            return []
        ranked = np.argsort(-logits).astype(int).tolist()
        minimum = int(obs.select.minCount)
        maximum = min(int(obs.select.maxCount), len(count_logits) - 1, len(ranked))
        desired = maximum if minimum == maximum else minimum + int(
            np.argmax(count_logits[minimum : maximum + 1])
        )
        return sanitize_selection(obs.select, ranked, desired)

    def selector_factory():
        m = model
        return lambda obs: exp23_action(m, obs)

    config = CorrectionConfig(worlds=4, max_turn_steps=64, timeout_seconds=120.0)
    try:
        evaluation = evaluate_complete_turn_correction(
            obs_raw, baseline, candidate, GRIM_DECK, opp_deck, selector_factory, config=config
        )
    except Exception as exc:
        return {"key": f"{ep_id}:{step}", "error": f"{type(exc).__name__}: {exc}"}
    worlds = []
    for w in evaluation.worlds:
        worlds.append({
            "world": w.world_index, "seed": w.seed,
            "baseline": list(w.baseline.values()),
            "candidate": list(w.candidate.values()),
            "baseline_steps": w.baseline_steps,
            "candidate_steps": w.candidate_steps,
        })
    return {
        "key": f"{ep_id}:{step}",
        "episode": ep_id, "step": step, "label": point["label"],
        "admitted": evaluation.admitted,
        "reason": evaluation.reason,
        "coverage": evaluation.coverage,
        "baseline_action": evaluation.baseline_action.to_dict() if evaluation.baseline_action else None,
        "candidate_action": evaluation.candidate_action.to_dict() if evaluation.candidate_action else None,
        "worlds": worlds,
        "errors": list(evaluation.errors),
    }


def main():
    results = []
    with mp.Pool(len(POINTS), maxtasksperchild=1) as pool:
        for res in pool.map(run_one, POINTS):
            results.append(res)
    (OUT / "complete_turn_results.json").write_text(json.dumps(results, indent=1))
    for r in results:
        print(r["key"], "admitted", r.get("admitted"), "reason", r.get("reason"), "coverage", r.get("coverage"), "errors", r.get("errors"), "err", r.get("error", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
