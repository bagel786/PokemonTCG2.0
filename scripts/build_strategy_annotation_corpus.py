#!/usr/bin/env python3
"""Build the STRATEGY_RESEARCH_V1 §9 decisive-turn annotation corpus.

Reads the mined loss-bucket report (anchored decisive turns) and the development
trajectory metrics, maps each bucket to one of the five strategic decision
families, and emits a stratified >=100-position corpus (JSONL) carrying every
mechanical field. The strategic-annotation fields (both plans, principal line,
acceptable alternatives, causal chain) are left empty for reasoning-layer fill,
except the worked seed turns which are pre-filled.

Not an implementation of the reasoner; a research/benchmark data artifact.
"""
from __future__ import annotations
import json, argparse
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parents[1]

# bucket prefix -> (decision family index, family label)
BUCKET_FAMILY = {
    "B1": (4, "damage-investment/pressure/forced-response"),
    "B2a": (5, "recovery/comeback/passing/non-greedy"),
    "B2b": (5, "recovery/comeback/passing/non-greedy"),
    "B3": (1, "setup/resource->attacker conversion"),   # dead-active-no-attacker = development symptom
    "B4": (2, "tempo & prize-route trades"),            # bench-snipe = targeting/tempo (anti-pattern)
}
# development-trajectory exemplars populate family 1 and family 3 targeting.

def family_of(bucket: str) -> tuple[int, str]:
    key = bucket.split("_")[0]
    return BUCKET_FAMILY.get(key, (3, "threat/engine-denial/targeting"))

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=str(ROOT/"artifacts/grim_loss_buckets/report.json"))
    ap.add_argument("--development", default=str(ROOT/"artifacts/grim_loss_buckets/development.json"))
    ap.add_argument("--out", default=str(ROOT/"docs/strategy/annotation_corpus.jsonl"))
    ap.add_argument("--min-per-clean-bucket", type=int, default=8)
    ap.add_argument("--target", type=int, default=120)
    args = ap.parse_args()

    report = json.loads(Path(args.report).read_text())
    per_ep = report["per_episode"]

    # collect all anchored decisive turns
    rows = []
    for ep in per_ep:
        for det in ep.get("details", []):
            fam_idx, fam = family_of(det["bucket"])
            rows.append({
                "submission_id": ep["submission_id"],
                "episode_id": ep["episode_id"],
                "seat": ep["seat"],
                "outcome": "win" if ep["outcome"] > 0 else "loss",
                "turn": det["turn"],
                "step": det["step"],
                "bucket": det["bucket"],
                "family_index": fam_idx,
                "family": fam,
            })

    # stratified selection: guarantee coverage of the rare "clean" buckets first,
    # then fill with B3 development-symptom turns spread across episodes.
    by_bucket = defaultdict(list)
    for r in rows:
        by_bucket[r["bucket"].split("_")[0]].append(r)

    selected = []
    seen = set()
    def add(r):
        key = (r["episode_id"], r["turn"], r["step"])
        if key in seen: return
        seen.add(key); selected.append(r)

    # prioritise decision-relevant buckets (rare, high-skew): B1,B2b,B2a,B4, then B3
    order = ["B1", "B2b", "B2a", "B4", "B3"]
    # take losses first (the instructive cases), balanced across submissions
    for b in order:
        cand = by_bucket.get(b, [])
        losses = [r for r in cand if r["outcome"] == "loss"]
        wins = [r for r in cand if r["outcome"] == "win"]
        # spread across episodes
        losses.sort(key=lambda r: (r["submission_id"], r["episode_id"], r["turn"]))
        wins.sort(key=lambda r: (r["submission_id"], r["episode_id"], r["turn"]))
        take = losses[: max(args.min_per_clean_bucket, 0)]
        # for B4 (anti-pattern) also include a couple of wins to show the contrast
        if b == "B4":
            take = losses[:6] + wins[:6]
        for r in take:
            add(r)

    # fill to target with B3 turns >=7 (late dead-active = the loss signature), spread across episodes
    b3_late = sorted(
        [r for r in by_bucket.get("B3", []) if r["turn"] >= 7 and r["outcome"] == "loss"],
        key=lambda r: (r["submission_id"], r["episode_id"], r["turn"]),
    )
    i = 0
    while len(selected) < args.target and i < len(b3_late):
        add(b3_late[i]); i += 1

    # annotate seed turns (worked in STRATEGY_RESEARCH_V1 §9)
    SEED = {(91427733, 1): "A1-setup-forced-END(T1)", (91427733, 9): "A2-B2b-recovery-CERTIFIED"}
    for r in selected:
        tag = SEED.get((r["episode_id"], r["turn"]))
        r["seed_annotation"] = tag
        # empty reasoning-layer fields to be filled by the strategic reasoner / adjudicator
        r["annotation"] = {
            "hero_plan": None, "opponent_plan": None,
            "principal_line": None, "acceptable_alternatives": None,
            "causal_explanation": None, "verdict": None,
            "source_tier": 5, "confidence": None,
        }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for r in selected:
            fh.write(json.dumps(r) + "\n")

    # summary
    fam_counts = Counter((r["family_index"], r["family"]) for r in selected)
    buck_counts = Counter(r["bucket"].split("_")[0] for r in selected)
    print(f"wrote {len(selected)} positions to {out}")
    print("by family:", {f"F{k[0]} {k[1]}": v for k, v in sorted(fam_counts.items())})
    print("by bucket:", dict(buck_counts))
    print("by outcome:", dict(Counter(r["outcome"] for r in selected)))
    print("distinct episodes:", len({r["episode_id"] for r in selected}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
