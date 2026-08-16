#!/usr/bin/env python3
"""Corpus-level Lucario veto evaluation (equivalent to runtime MAIN-level audit).

For each Lucario WIN row (teacher = winning Grim player):
- EXP-23 predicted action + ranked list from the model
- veto fires iff base action is a single MAIN PLAY of a vetoed card AND an
  ATTACK option exists in the ranked list
- rule action = first ATTACK in ranked
- compare teacher (recorded) vs rule vs EXP-23.
Split by target team: discovery vs heldout (frozen crc32%3 split).
"""
from __future__ import annotations

import gzip
import json
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import torch

from training.train_bc import PolicyNet, collate, load_npz_weights
from training.replay_refresh import _decision

VETO_PLAYS = {1152, 1097, 860, 646}
PLAY_TYPE = 7
ATTACK_TYPE = 13


def semantic_set(action, options):
    return frozenset(a for a in action if a < len(options))


def main() -> int:
    model = PolicyNet(2)
    load_npz_weights(model, "/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/final_sprint/exp23_identity_trained/policy_weights.npz")
    model.eval()

    split = json.load(open("artifacts/anti_meta_20260816/luc_team_split.json"))
    held = set(split["held"])

    rows = []
    with gzip.open("artifacts/anti_meta_20260816/corpus_lucario_family.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("result") == "grim_win":
                rows.append(row)

    buckets = {"dev": Counter(), "held": Counter()}
    per_team = defaultdict(lambda: defaultdict(Counter))
    detail = {"dev": [], "held": []}
    batch_size = 64
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        batch = collate(chunk)
        with torch.no_grad():
            logits, count_logits, _ = model(batch)
        for j, row in enumerate(chunk):
            team = str(row.get("target_team", ""))
            bucket_name = "held" if team in held else "dev"
            bucket = buckets[bucket_name]
            options = row["features"]["options"]
            if not options or options[0].get("context") != 0:
                continue
            teacher = semantic_set(row["action"], options)
            ranked = [int(x) for x in _decision_ranked(logits, count_logits, batch, j)]
            pred = set(_decision(logits, count_logits, batch, j))
            bucket["all_main"] += 1
            if len(pred) != 1:
                continue
            idx = next(iter(pred))
            if idx >= len(options) or options[idx].get("option_type") != PLAY_TYPE:
                continue
            card = int(options[idx].get("source_card", 0))
            if card not in VETO_PLAYS:
                continue
            bucket["eligible"] += 1
            attack_choice = None
            for candidate in ranked:
                if candidate < len(options) and options[candidate].get("option_type") == ATTACK_TYPE:
                    if candidate != idx:
                        attack_choice = candidate
                    break
            if attack_choice is None:
                bucket["eligible_no_attack"] += 1
                continue
            bucket["fired"] += 1
            rule_action = {attack_choice}
            side = None
            if teacher == rule_action:
                side = "rule"
            elif teacher == pred:
                side = "exp23"
            else:
                side = "neither"
            bucket[side] += 1
            per_team[bucket_name][team][side] += 1
            turn = int(row.get("turn", 0))
            phase = "early" if turn <= 3 else ("mid" if turn <= 7 else "late")
            bucket[f"phase_{phase}"] += 1
            detail[bucket_name].append({
                "episode_id": str(row.get("episode_id")),
                "team": team,
                "turn": turn,
                "side": side,
                "play_card": card,
            })

    def approve(stats: Counter) -> dict:
        decisive = stats["rule"] + stats["exp23"]
        return {
            "rule": stats["rule"],
            "exp23": stats["exp23"],
            "neither": stats["neither"],
            "fired": stats["fired"],
            "eligible": stats["eligible"],
            "approval": stats["rule"] / max(1, decisive),
            "decisive": decisive,
        }

    for name, bucket in buckets.items():
        stats = defaultdict(Counter)
        for key, value in bucket.items():
            if key in ("rule", "exp23", "neither"):
                stats["total"][key] = value
        print(name.upper(), "all_main:", bucket["all_main"], "| eligible:", bucket["eligible"],
              "| fired:", bucket["fired"], "| no_attack:", bucket["eligible_no_attack"])
        print("  verdict:", {k: bucket[k] for k in ("rule", "exp23", "neither")},
              "| approval:", round(bucket["rule"] / max(1, bucket["rule"] + bucket["exp23"]), 3))
        print("  phases:", {k.replace("phase_", ""): v for k, v in bucket.items() if k.startswith("phase_")})
        teams_report = {t: dict(v) for t, v in per_team[name].items() if sum(v.values())}
        print("  per-team sides:", json.dumps(teams_report)[:600])

    out = {
        "dev": {"counts": {k: v for k, v in buckets["dev"].items() if isinstance(v, int)},
                "detail": detail["dev"][:50]},
        "held": {"counts": {k: v for k, v in buckets["held"].items() if isinstance(v, int)},
                 "detail": detail["held"]},
    }
    Path("artifacts/anti_meta_20260816/luc_veto_semantic.json").write_text(json.dumps(out, indent=2))
    return 0


def _decision_ranked(logits, count_logits, batch, record_index):
    start, end = batch["record_options"][record_index]
    ranked = torch.argsort(logits[start:end], descending=True).cpu().tolist()
    return ranked


if __name__ == "__main__":
    raise SystemExit(main())
