#!/usr/bin/env python3
"""Offline semantic screen: EXP23 vs R1/R2 on mined target winner rows."""
from __future__ import annotations

import gzip
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np

from ptcg_ai.features import DecisionFeatures, MAX_SELECT_COUNT
from ptcg_ai.model import NumpyPolicyModel

OUT = ROOT / "artifacts" / "final_target_residual_20260816"
CONTROL = ROOT / "artifacts" / "final_sprint" / "exp23_identity_trained" / "policy_weights.npz"

IS_FIRST_CTX = 41


def option_key(opt) -> tuple:
    return (
        int(opt.option_type), int(opt.context), int(opt.source_card), int(opt.target_card),
        int(opt.attack_id), int(opt.area), int(opt.in_play_area),
        tuple(round(float(v), 6) for i, v in enumerate(opt.numeric) if i not in (9, 10, 11)),
    )


def semantic_top1(features: DecisionFeatures, ranked: list[int]) -> tuple | None:
    seen = set()
    top = None
    for idx in ranked:
        key = option_key(features.options[idx])
        if key not in seen:
            seen.add(key)
            if top is None:
                top = key
    return top


def semantic_set(features: DecisionFeatures, chosen: list[int]) -> tuple:
    keys = sorted({option_key(features.options[i]) for i in chosen if 0 <= i < len(features.options)})
    return tuple(keys)


def predict_model(model: NumpyPolicyModel, features: DecisionFeatures):
    logits, count_logits, _ = model.predict(features)
    if len(logits) == 0:
        return [], []
    ranked = np.argsort(-logits).astype(int).tolist()
    minimum = int(round(float(features.global_features[28]) * MAX_SELECT_COUNT))
    maximum = int(round(float(features.global_features[29]) * MAX_SELECT_COUNT))
    option_count = len(features.options)
    minimum = max(0, min(minimum, option_count))
    maximum = max(minimum, min(maximum, option_count, len(count_logits) - 1))
    if minimum == maximum:
        desired = maximum
    else:
        desired = minimum + int(np.argmax(count_logits[minimum : maximum + 1]))
    chosen = ranked[:desired]
    return ranked, chosen


def load_rows(path: Path) -> list[dict]:
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            rows.append(row)
    return rows


def scored(row: dict) -> bool:
    feats = row.get("features") or {}
    options = (row.get("legal_options") or [])
    if not options:
        return False
    g = feats.get("global") or []
    if len(g) < 30:
        return False
    minc = int(round(float(g[28]) * MAX_SELECT_COUNT))
    maxc = int(round(float(g[29]) * MAX_SELECT_COUNT))
    if len(options) == 1:
        return False
    if minc == maxc == len(options):
        return False
    ctx = int(feats.get("options", [{}])[0].get("context", 0))
    if ctx == IS_FIRST_CTX:
        return False
    return True


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "dev"
    path = OUT / ("target_wins_dev.jsonl.gz" if which == "dev" else "target_wins_holdout.jsonl.gz")
    names = [p.name.replace(".npz", "") for p in (OUT).glob("*.npz")]
    models = {"EXP23": NumpyPolicyModel(str(CONTROL))}
    for name in sorted(names):
        models[name] = NumpyPolicyModel(str(OUT / f"{name}.npz"))
    rows = load_rows(path)
    bucket = {name: Counter() for name in models}
    for row in rows:
        feats = DecisionFeatures.from_json(row["features"])
        if not scored(row):
            continue
        elite = [int(x) for x in row.get("action") or []]
        elite_key = semantic_set(feats, elite)
        results = {}
        for name, model in models.items():
            ranked, chosen = predict_model(model, feats)
            results[name] = (ranked, chosen)
        e23_ranked, e23_chosen = results["EXP23"]
        e23_top = semantic_top1(feats, e23_ranked)
        e23_chosen_key = semantic_set(feats, e23_chosen)
        base = bucket["EXP23"]
        base["scored"] += 1
        base["exact"] += int(set(e23_chosen) == set(elite))
        base["count"] += int(len(e23_chosen) == len(elite))
        if len(elite) == 1 and 0 <= elite[0] < len(feats.options):
            base["single"] += 1
            base["single_top1"] += int(e23_ranked[0] == elite[0])
        for name in models:
            if name == "EXP23":
                continue
            ranked, chosen = results[name]
            top = semantic_top1(feats, ranked)
            chosen_key = semantic_set(feats, chosen)
            b = bucket[name]
            b["scored"] += 1
            b["exact"] += int(set(chosen) == set(elite))
            b["count"] += int(len(chosen) == len(elite))
            b["divergent"] += int(top != e23_top or chosen_key != e23_chosen_key)
            if len(elite) == 1 and 0 <= elite[0] < len(feats.options):
                b["single"] += 1
                b["single_top1"] += int(ranked[0] == elite[0])
                # base top-k rank of candidate's semantic top-1 label
                label_key = option_key(feats.options[elite[0]])
                if label_key == top:
                    b["cand_top1_is_elite"] += 1
            if elite_key == chosen_key and elite_key != e23_chosen_key:
                b["decisive_cand"] += 1
                b.setdefault("detail", []).append({
                    "episode": str(row.get("episode_id", "?")),
                    "context": int(feats.options[0].context),
                    "order": str(row.get("hero_order", "?")),
                    "decisive": 1, "cand_approval": 1,
                })
            elif elite_key == e23_chosen_key and elite_key != chosen_key:
                b["decisive_exp23"] += 1
                b.setdefault("detail", []).append({
                    "episode": str(row.get("episode_id", "?")),
                    "context": int(feats.options[0].context),
                    "order": str(row.get("hero_order", "?")),
                    "decisive": 1, "cand_approval": 0,
                })
            else:
                b["neither_or_tie"] += 1
    out = {}
    for name, b in bucket.items():
        scored_n = b["scored"]
        out[name] = {
            "scored": scored_n,
            "exact_rate": round(b["exact"] / scored_n, 6) if scored_n else None,
            "count_acc": round(b["count"] / scored_n, 6) if scored_n else None,
            "single": b["single"],
            "single_top1_rate": round(b["single_top1"] / b["single"], 6) if b["single"] else None,
        }
        if name != "EXP23":
            out[name]["semantic_divergence"] = round(b["divergent"] / scored_n, 6) if scored_n else None
            dec = b["decisive_cand"] + b["decisive_exp23"]
            out[name]["decisive"] = dec
            out[name]["decisive_cand"] = b["decisive_cand"]
            out[name]["decisive_exp23"] = b["decisive_exp23"]
            out[name]["cand_approval"] = round(b["decisive_cand"] / dec, 6) if dec else None
            out[name]["cand_top1_is_elite"] = b["cand_top1_is_elite"]

    # breakdowns for all non-EXP23 models
    for cand_name in [n for n in models if n != "EXP23"]:
        b = bucket[cand_name]
        if not b.get("detail"):
            continue
        ep_approvals = Counter()
        ctx_dec = Counter(); ctx_app = Counter()
        order_dec = Counter(); order_app = Counter()
        for d in b["detail"]:
            ep_approvals[d["episode"]] += d["cand_approval"]
            if d["decisive"]:
                ctx_dec[d["context"]] += 1
                ctx_app[d["context"]] += d["cand_approval"]
                order_dec[d["order"]] += 1
                order_app[d["order"]] += d["cand_approval"]
        out[cand_name]["by_context"] = {str(k): {"decisive": ctx_dec[k], "approval": round(ctx_app[k] / ctx_dec[k], 4)} for k in sorted(ctx_dec)}
        out[cand_name]["by_order"] = {str(k): {"decisive": order_dec[k], "approval": round(order_app[k] / order_dec[k], 4)} for k in sorted(order_dec)}
        out[cand_name]["episode_approval_share"] = round(max(ep_approvals.values()) / max(1, sum(ep_approvals.values())), 4)
        out[cand_name]["episodes_with_decisive"] = len(ep_approvals)
    dest = OUT / ("development_screen.json" if which == "dev" else "sealed_holdout_screen.json")
    dest.write_text(json.dumps(out, indent=1, sort_keys=True))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
