#!/usr/bin/env python3
"""Blaze veto audit: combined candidate vs base on drag games; fires on non-drag games."""
from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402

COMBINED = str(ROOT / "artifacts" / "final_r1_drag_gate_20260816" / "r1_tree")
BASE = str(ROOT / "artifacts" / "final_sprint" / "exp23_identity_trained")

DRAG_TARGETS = {
    "93755661": ("loss", 55562629, 1),
    "93673237": ("loss", 55556726, 0),
    "93671387": ("loss", 55556726, 1),
    "93730597": ("loss", 55556726, 1),
    "93745631": ("loss", 55562629, 0),
    "93685951": ("loss_struct", 55556726, 0),
    "93699067": ("loss_struct", 55556726, 1),
    "93679642": ("win", 55556726, 0),
}

NON_DRAG = {
    93736000: 55556726, 93715535: 55556726, 93665757: 55556726, 93680533: 55556726,
    93670440: 55556726, 93674154: 55556726, 93693193: 55556726, 93677628: 55556726,
    93668609: 55556726, 93669503: 55556726, 93672319: 55556726, 93675087: 55556726,
    93676003: 55556726, 93676804: 55556726, 93676921: 55556726, 93678750: 55556726,
    93681449: 55556726, 93682335: 55556726, 93683291: 55556726, 93684142: 55556726,
    93685047: 55556726, 93692845: 55556726, 93729859: 55556726, 93745758: 55556726,
    93665870: 55556726, 93666757: 55556726, 93667663: 55556726,
    93738302: 55562629, 93738399: 55562629, 93739304: 55562629, 93740206: 55562629,
    93741076: 55562629, 93741971: 55562629, 93742882: 55562629, 93743797: 55562629,
    93744693: 55562629, 93745625: 55562629, 93746552: 55562629, 93747403: 55562629,
    93748360: 55562629, 93749272: 55562629, 93750153: 55562629, 93751091: 55562629,
    93752006: 55562629, 93752904: 55562629, 93753793: 55562629, 93754722: 55562629,
    93755661: 55562629, 93756544: 55562629, 93757444: 55562629, 93758218: 55562629,
    93758436: 55562629, 93759255: 55562629, 93760161: 55562629, 93761111: 55562629,
}


def walk_episode(path, seat, agent):
    ep = json.loads(path.read_text())
    steps = ep.get("steps") or []
    decisions = 0
    errors = 0
    changed = []
    for step_index in range(len(steps) - 1):
        row = steps[step_index]
        entry = row[seat] if row and seat < len(row) else None
        obs = (entry or {}).get("observation") or {}
        if not obs.get("select") or not obs.get("current"):
            continue
        decisions += 1
        try:
            act = agent(obs)
        except Exception:
            errors += 1
            continue
        changed.append((step_index, [int(i) for i in act]))
    return decisions, errors, changed


def audit_drag(task):
    ep_id, label, sub, seat = task
    path = Path(f"/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight/data/replays/{sub}/episode-{ep_id}-replay.json")
    base = ExternalSubmissionAgent(BASE, {})
    comb = ExternalSubmissionAgent(COMBINED, {})
    try:
        b_dec, b_err, b_act = walk_episode(path, seat, base)
        c_dec, c_err, c_act = walk_episode(path, seat, comb)
    finally:
        base.close()
        comb.close()
    veto = comb.module._AGENT.drag_veto
    fires = [t for t in veto.telemetry if t.get("event") == "veto_fired"]
    changed = [i for i, (b, c) in enumerate(zip(b_act, c_act)) if b != c]
    divergences = []
    for step_index, (b, c) in zip([i for i in range(len(b_act))], zip(b_act, c_act)):
        if b != c:
            divergences.append({"step": step_index, "base": b, "combined": c})
    return {
        "episode": ep_id, "label": label, "decisions": c_dec, "errors": b_err + c_err,
        "veto_fired": len(fires), "fires": fires,
        "changed_decisions": len(changed), "divergences": divergences,
        "telemetry_events": len(veto.telemetry),
    }


def audit_non_drag(ep_id, sub):
    path = Path(f"/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight/data/replays/{sub}/episode-{ep_id}-replay.json")
    if not path.exists():
        return {"episode": ep_id, "missing": True}
    meta = json.loads((path.parent / "episodes_metadata.json").read_text())
    seat = next(i for m in meta if str(m["id"]) == str(ep_id)
                for i, a in enumerate(m["agents"]) if str(a.get("submissionId")) == str(sub))
    comb = ExternalSubmissionAgent(COMBINED, {})
    try:
        decisions, errors, _ = walk_episode(path, seat, comb)
    finally:
        comb.close()
    veto = comb.module._AGENT.drag_veto
    fires = [t for t in veto.telemetry if t.get("event") == "veto_fired"]
    return {"episode": ep_id, "sub": sub, "decisions": decisions, "errors": errors,
            "veto_fired": len(fires), "fires": fires}


def main():
    drag_results = []
    with mp.Pool(8, maxtasksperchild=1) as pool:
        drag_results = pool.map(audit_drag, [(e, v[0], v[1], v[2]) for e, v in DRAG_TARGETS.items()])
    non_drag_results = []
    with mp.Pool(8, maxtasksperchild=1) as pool:
        non_drag_results = pool.starmap(audit_non_drag, NON_DRAG.items())
    out = {"drag": drag_results, "non_drag": non_drag_results}
    Path("artifacts/final_r1_drag_gate_20260816/blaze_audit.json").write_text(json.dumps(out, indent=1))
    for r in drag_results:
        print("DRAG", r["episode"], r["label"], "fires", r["veto_fired"], "changed", r["changed_decisions"], "err", r["errors"], r["divergences"][:2])
    fires = [(r["episode"], r.get("fires")) for r in non_drag_results if r.get("veto_fired")]
    errs = [(r["episode"], r.get("errors")) for r in non_drag_results if r.get("errors")]
    missing = [r["episode"] for r in non_drag_results if r.get("missing")]
    print("NONDRAG", len(non_drag_results), "episodes; fires:", fires, "errors:", errs, "missing:", missing)
    return 0


if __name__ == "__main__":
    sys.exit(main())
