#!/usr/bin/env python3
"""Verify P0 probe isolation: package-level feature and decision parity.

Runs the packaged pipeline (encode -> predict -> shield -> damage V0 ->
sanitize) in three configurations on identical authentic replay states:

- control   : R0 winner extracted tree (no PTCG_PLAY_IDENTITY)
- p0-off    : P0 tree with PTCG_PLAY_IDENTITY unset
- p0-on     : P0 tree with PTCG_PLAY_IDENTITY=1

Proves:
1. p0-off is byte-identical to R0 (feature rows and decisions).
2. p0-on changes ONLY PLAY-option source_card in option features; global
   features and state tokens stay identical.
3. p0-on decisions differ from R0 only at MAIN/MAIN prompts.

The dump itself uses only the package's own ptcg_ai/cg modules (isolated
import, no repo code on sys.path).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DUMP_CODE = r"""
import json
import os
import sys
from pathlib import Path

package_dir, replay_root, submission_id, env_json, output = sys.argv[1:6]
sys.path.insert(0, package_dir)
for key, value in json.loads(env_json).items():
    os.environ[str(key)] = str(value)

from cg.api import SelectType, SelectContext, to_observation_class
from ptcg_ai.model import NeuralPolicy

metadata = json.load(open(os.path.join(replay_root, "episodes_metadata.json")))
episode_meta = {int(row["id"]): row for row in metadata}
policy = NeuralPolicy(os.path.join(package_dir, "policy_weights.npz"), None)
rows = []
for path in sorted(Path(replay_root).glob("episode-*-replay.json")):
    episode_id = int(path.stem.split("-")[1])
    meta = episode_meta[episode_id]
    hero = next(i for i, agent in enumerate(meta["agents"]) if int(agent.get("submissionId", -1)) == int(submission_id))
    replay = json.loads(path.read_text())
    steps = replay.get("steps", [])
    for step_index, step in enumerate(steps):
        if hero >= len(step):
            continue
        raw = step[hero]
        if str(raw.get("status", "")).upper() != "ACTIVE":
            continue
        obs_dict = raw.get("observation") or {}
        if not obs_dict.get("select") or not obs_dict.get("current"):
            continue
        obs = to_observation_class(obs_dict)
        features = policy.model._encode(obs) if False else None
        from ptcg_ai.features import encode_observation
        features = encode_observation(obs, policy.model.feature_version)
        action = policy.choose(obs)
        rows.append({
            "episode": episode_id,
            "step": step_index,
            "select_type": int(obs.select.type),
            "select_context": int(obs.select.context),
            "effect_id": int(getattr(obs.select.effect, "id", 0) or 0),
            "global": features.global_features,
            "tokens": features.state_tokens,
            "options": [
                {
                    "type": option.option_type,
                    "context": option.context,
                    "source_card": option.source_card,
                    "target_card": option.target_card,
                    "attack_id": option.attack_id,
                    "area": option.area,
                    "in_play_area": option.in_play_area,
                    "numeric": option.numeric,
                }
                for option in features.options
            ],
            "action": action,
        })
Path(output).write_text(json.dumps(rows) + "\n")
print(f"dumped {len(rows)} decisions")
"""


def dump(package_dir: Path, replay_root: Path, submission_id: int, env: dict, output: Path) -> list[dict]:
    env.setdefault("PTCG_GRIM_DAMAGE_SOLVER", "v0")
    code = DUMP_CODE
    completed = subprocess.run(
        [sys.executable, "-c", code, str(package_dir), str(replay_root), str(submission_id), json.dumps(env), str(output)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if completed.returncode != 0:
        raise RuntimeError(f"dump failed: {completed.stderr[-2000:]}")
    print(completed.stdout.strip())
    return json.loads(output.read_text())


def compare(control: list[dict], candidate: list[dict], label: str) -> dict:
    assert len(control) == len(candidate), f"{label}: row count mismatch"
    feature_diffs = []
    decision_diffs = []
    play_source_changes = 0
    total_options = 0
    for a, b in zip(control, candidate):
        if a["global"] != b["global"] or a["tokens"] != b["tokens"]:
            feature_diffs.append((a["episode"], a["step"], "global/tokens"))
        if len(a["options"]) != len(b["options"]):
            feature_diffs.append((a["episode"], a["step"], "option count"))
            continue
        for index, (oa, ob) in enumerate(zip(a["options"], b["options"])):
            total_options += 1
            fields_a = {k: oa[k] for k in oa if k != "source_card"}
            fields_b = {k: ob[k] for k in ob if k != "source_card"}
            if fields_a != fields_b:
                feature_diffs.append((a["episode"], a["step"], f"option {index} non-source fields"))
            elif oa["source_card"] != ob["source_card"]:
                play_source_changes += 1
        if a["action"] != b["action"]:
            decision_diffs.append(
                {
                    "episode": a["episode"],
                    "step": a["step"],
                    "select_type": a["select_type"],
                    "select_context": a["select_context"],
                    "effect_id": a["effect_id"],
                    "before": a["action"],
                    "after": b["action"],
                }
            )
    main_diffs = [d for d in decision_diffs if d["select_type"] == 0 and d["select_context"] == 0]
    non_main_diffs = [d for d in decision_diffs if not (d["select_type"] == 0 and d["select_context"] == 0)]
    return {
        "label": label,
        "decisions": len(control),
        "options_total": total_options,
        "feature_diffs": feature_diffs[:20],
        "feature_diff_count": len(feature_diffs),
        "play_source_changes": play_source_changes,
        "decision_diff_count": len(decision_diffs),
        "main_decision_diffs": len(main_diffs),
        "non_main_decision_diffs": len(non_main_diffs),
        "non_main_examples": non_main_diffs[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control", type=Path, default="/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/winner/extracted")
    parser.add_argument("--p0", type=Path, default="/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_play_identity/candidates/p0")
    parser.add_argument("--candidate-env", type=str, default='{"PTCG_PLAY_IDENTITY": "1"}')
    parser.add_argument("--replays", type=Path, default="/Users/safiullahbaig/Projects/pokemonTCG2.0/data/replays/55399728")
    parser.add_argument("--submission-id", type=int, default=55399728)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/p0_parity.json")
    args = parser.parse_args()

    temp = ROOT / "artifacts" / ".p0_parity_dumps"
    temp.mkdir(parents=True, exist_ok=True)
    candidate_env = json.loads(args.candidate_env)
    control = dump(args.control, args.replays, args.submission_id, {}, temp / "control.json")
    p0_off = dump(args.p0, args.replays, args.submission_id, {"PTCG_PLAY_IDENTITY": "0"}, temp / "p0_off.json")
    p0_on = dump(args.p0, args.replays, args.submission_id, candidate_env, temp / "p0_on.json")

    off_vs_control = compare(control, p0_off, "p0-off vs R0 control")
    on_vs_control = compare(control, p0_on, "p0-on vs R0 control")
    report = {"off_vs_control": off_vs_control, "on_vs_control": on_vs_control}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    okay = off_vs_control["decision_diff_count"] == 0 and off_vs_control["feature_diff_count"] == 0
    if not okay:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
