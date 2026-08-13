#!/usr/bin/env python3
"""B takeover parity: drive R0 and B packages through authentic replays.

Both agents are stateful per game, so each episode is fed in order including
the initial select-None observation (which triggers _reset).  Expected: the B
candidate differs from R0 ONLY at hero in-game prompts inside the takeover
window (engine turns 2-4) of actual-second games.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections import Counter
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from cg.api import SelectContext, to_observation_class  # noqa: E402

_AGENT_CACHE: dict[tuple[str, str], object] = {}


def load_package_agent(package_dir: Path, takeover: bool) -> object:
    key = (str(package_dir), str(takeover))
    if key in _AGENT_CACHE:
        return _AGENT_CACHE[key]
    token = uuid4().hex
    package_name = f"_b_pkg_{token}"
    package_spec = importlib.util.spec_from_file_location(
        package_name,
        package_dir / "ptcg_ai" / "__init__.py",
        submodule_search_locations=[str(package_dir / "ptcg_ai")],
    )
    package = importlib.util.module_from_spec(package_spec)
    sys.modules[package_name] = package
    package_spec.loader.exec_module(package)
    router_module = importlib.import_module(package_name + ".order_router")
    os.environ["PTCG_TEMPORAL_TAKEOVER"] = "1" if takeover else "0"
    previous_cwd = Path.cwd()
    os.chdir(package_dir)
    try:
        agent = router_module.ActualOrderAgent()
    finally:
        os.chdir(previous_cwd)
    _AGENT_CACHE[key] = agent
    return agent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control", type=Path, default="/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/candidates/a2_damage_v0")
    parser.add_argument("--candidate", type=Path, default="/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_temporal_takeover/candidates/b_takeover")
    parser.add_argument("--replays", type=Path, default="/Users/safiullahbaig/Projects/pokemonTCG2.0/data/replays/55399728")
    parser.add_argument("--submission-id", type=int, default=55399728)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/b_takeover_parity.json")
    args = parser.parse_args()

    os.environ["PTCG_GRIM_DAMAGE_SOLVER"] = "v0"
    control_agent = load_package_agent(args.control, takeover=False)
    candidate_agent = load_package_agent(args.candidate, takeover=True)

    metadata = json.loads((args.replays / "episodes_metadata.json").read_text())
    episode_meta = {int(row["id"]): row for row in metadata}
    diffs = []
    total = 0
    window_prompts = 0
    window_diffs = 0
    orders = Counter()
    for path in sorted(args.replays.glob("episode-*-replay.json")):
        episode_id = int(path.stem.split("-")[1])
        meta = episode_meta[episode_id]
        hero = next(i for i, agent in enumerate(meta["agents"]) if int(agent.get("submissionId", -1)) == args.submission_id)
        replay = json.loads(path.read_text())
        control_agent({"select": None, "current": None})
        candidate_agent({"select": None, "current": None})
        for step_index, step in enumerate(replay["steps"]):
            if hero >= len(step):
                continue
            raw = step[hero]
            if raw.get("status") and str(raw.get("status", "")).upper() != "ACTIVE":
                continue
            obs_dict = raw.get("observation") or {}
            if not obs_dict.get("select") or not obs_dict.get("current"):
                continue
            total += 1
            control_action = control_agent(obs_dict)
            candidate_action = candidate_agent(obs_dict)
            obs = to_observation_class(obs_dict)
            turn = int(obs.current.turn)
            first = int(obs.current.firstPlayer)
            yours = int(obs.current.yourIndex)
            order = "first" if first == yours else "second"
            orders[order] += 1
            in_window = order == "second" and 2 <= turn <= 4 and obs.select.context != SelectContext.IS_FIRST
            if in_window:
                window_prompts += 1
            if control_action != candidate_action:
                record = {
                    "episode": episode_id,
                    "step": step_index,
                    "turn": turn,
                    "order": order,
                    "context": int(obs.select.context),
                    "in_window": in_window,
                    "before": control_action,
                    "after": candidate_action,
                }
                diffs.append(record)
                if in_window:
                    window_diffs += 1

    non_window_diffs = [d for d in diffs if not d["in_window"]]
    report = {
        "prompts": total,
        "orders": dict(orders),
        "window_prompts": window_prompts,
        "window_diffs": window_diffs,
        "window_intervention_rate": window_diffs / window_prompts if window_prompts else 0.0,
        "non_window_diffs": len(non_window_diffs),
        "non_window_examples": non_window_diffs[:10],
        "diff_contexts_in_window": Counter(d["context"] for d in diffs if d["in_window"]),
        "diff_turns_in_window": Counter(d["turn"] for d in diffs if d["in_window"]),
        "candidate_errors": int(getattr(candidate_agent, "errors", 0)),
        "control_errors": int(getattr(control_agent, "errors", 0)),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(bool(non_window_diffs))


if __name__ == "__main__":
    raise SystemExit(main())
