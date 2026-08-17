#!/usr/bin/env python3
"""Live-diff of the two final subs: veto tree (55565454) vs dip_b base (55565462).

Replays every arena game of both submissions offline through the packaged
submission modules, records veto fires / decision divergences vs the dip_b
base, and correlates with live win/loss.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402

VETO_TREE = str(ROOT / "artifacts" / "final_r1_drag_gate_20260816" / "r1_tree")
DIP_B = "/var/folders/d8/k9njndpd09nfsv4y2_dgs1z40000gp/T/opencode/dip_b"
REPLAYS = ROOT / "data" / "replays"

DRAG_IDS = {119, 120, 121}


def classify_opp(deck_action: list) -> str:
    ids = [int(i) for i in deck_action if isinstance(i, int)]
    if any(i in DRAG_IDS for i in ids):
        return "drag"
    joined = " ".join(str(i) for i in ids)
    return "other"


def walk_episode(path: Path, seat: int, agent):
    ep = json.loads(path.read_text())
    steps = ep.get("steps") or []
    decisions = 0
    errors = 0
    actions = []
    select_steps = []
    for step_index in range(len(steps) - 1):
        row = steps[step_index]
        entry = row[seat] if row and seat < len(row) else None
        obs = (entry or {}).get("observation") or {}
        if not obs.get("select") or not obs.get("current"):
            continue
        decisions += 1
        select_steps.append(step_index)
        try:
            act = agent(obs)
            actions.append([int(i) for i in act])
        except Exception:
            errors += 1
            actions.append(None)
    return decisions, errors, actions, select_steps


def analyze_task(task):
    sub_id, ep_id, result, seat, opp_sub, opp_deck, opp_score = task
    replay = REPLAYS / str(sub_id) / f"episode-{ep_id}-replay.json"
    out = {
        "episode": ep_id, "sub": sub_id, "result": result, "seat": seat,
        "opp_sub": opp_sub, "opp_deck": opp_deck, "opp_score": opp_score,
    }
    dip = ExternalSubmissionAgent(DIP_B, {})
    try:
        d_dec, d_err, d_act, d_steps = walk_episode(replay, seat, dip)
    finally:
        dip.close()
    out["dip_decisions"] = d_dec
    out["dip_errors"] = d_err

    if sub_id == 55565454:
        comb = ExternalSubmissionAgent(VETO_TREE, {})
        try:
            c_dec, c_err, c_act, c_steps = walk_episode(replay, seat, comb)
        finally:
            try:
                veto = comb.module._AGENT.drag_veto
                out["veto_fires"] = [t for t in veto.telemetry if t.get("event") == "veto_fired"]
                out["veto_events"] = [t.get("event") for t in veto.telemetry]
            except Exception:
                out["veto_fires"] = []
                out["veto_events"] = []
            comb.close()
        out["veto_decisions"] = c_dec
        out["veto_errors"] = c_err
        divergences = []
        for i, (b, c) in enumerate(zip(d_act, c_act)):
            if b != c:
                divergences.append({"step": d_steps[i], "base": b, "veto": c})
        out["divergences"] = divergences
        # live parity: replay action vs veto module action
        ep = json.loads(replay.read_text())
        steps = ep.get("steps") or []
        mismatches = 0
        live = []
        for i in range(len(steps) - 1):
            row = steps[i]
            entry = row[seat] if row and seat < len(row) else None
            obs = (entry or {}).get("observation") or {}
            if not obs.get("select") or not obs.get("current"):
                continue
            live.append([int(x) for x in (entry.get("action") or [])])
        for i, (l, c) in enumerate(zip(live, c_act)):
            if l != c:
                mismatches += 1
        out["live_mismatches"] = mismatches
        out["live_actions"] = len(live)
    else:
        out["divergences"] = []
    return out


def main() -> int:
    tasks = []
    for sub_id in (55565454, 55565462):
        meta = json.loads((REPLAYS / str(sub_id) / "episodes_metadata.json").read_text())
        for ep in meta:
            us = next((a for a in ep["agents"] if a["submissionId"] == sub_id), None)
            opp = next((a for a in ep["agents"] if a["submissionId"] != sub_id), None)
            if us is None or opp is None:
                continue
            replay = REPLAYS / str(sub_id) / f"episode-{ep['id']}-replay.json"
            if not replay.exists():
                continue
            rp = json.loads(replay.read_text())
            steps = rp.get("steps") or []
            opp_deck = "unknown"
            seat = next(i for i, a in enumerate(ep["agents"]) if a["submissionId"] == sub_id)
            if len(steps) > 1 and seat < len(steps[1]):
                opp_deck = classify_opp(steps[1][1 - seat].get("action") or [])
            tasks.append((sub_id, ep["id"], us.get("reward"), seat,
                          opp.get("submissionId"), opp_deck, opp.get("initialScore")))

    with mp.Pool(8, maxtasksperchild=1) as pool:
        results = pool.map(analyze_task, tasks)

    out_path = ROOT / "artifacts" / "final_r1_drag_gate_20260816" / "veto_vs_dipb_live.json"
    out_path.write_text(json.dumps(results, indent=1))

    for sub_id in (55565454, 55565462):
        rs = [r for r in results if r["sub"] == sub_id]
        w = sum(1 for r in rs if r["result"] == 1)
        l = sum(1 for r in rs if r["result"] == -1)
        drag = [r for r in rs if r["opp_deck"] == "drag"]
        dw = sum(1 for r in drag if r["result"] == 1)
        dl = sum(1 for r in drag if r["result"] == -1)
        nd = [r for r in rs if r["opp_deck"] == "other"]
        nw = sum(1 for r in nd if r["result"] == 1)
        nl = sum(1 for r in nd if r["result"] == -1)
        print(f"sub {sub_id}: {w}W-{l}L overall | drag {dw}W-{dl}L | other {nw}W-{nl}L")

    veto_rs = [r for r in results if r["sub"] == 55565454]
    fires = [r for r in veto_rs if r.get("veto_fires")]
    print(f"\nveto fired in {len(fires)}/{len(veto_rs)} games:")
    for r in fires:
        divs = r.get("divergences") or []
        print(f"  ep {r['episode']}: result {'W' if r['result']==1 else 'L'}, "
              f"opp={r['opp_deck']} (sub {r['opp_sub']}, {r['opp_score']:.0f}), "
              f"fires={len(r['veto_fires'])}, divergences={len(divs)}")
        for f in r["veto_fires"]:
            print(f"      {f}")
        for d in divs[:6]:
            print(f"      step {d['step']}: base={d['base']} veto={d['veto']}")
    errs = [r for r in veto_rs if r.get("veto_errors") or r.get("dip_errors")]
    print(f"\nerrors: {[(r['episode'], r['veto_errors'], r['dip_errors']) for r in errs]}")
    mm = [r for r in veto_rs if r.get("live_mismatches")]
    print(f"live action mismatches: {[(r['episode'], r['live_mismatches']) for r in mm]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
