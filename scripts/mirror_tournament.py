#!/usr/bin/env python3
"""Archive-faithful Grimmsnarl-mirror fast candidate tournament.

Evaluates candidate weights as the router's *mirror specialist* against each
opponent loaded from its OWN packaged code (agent.py/model.py/search.py/
features.py/safety.py + weights + deck), because those files diverge across our
historical submissions and a weight-swap onto current code would be serve-skew.

Hero = the real shipped router: CompetitionAgent(base=v2, mirror=candidate).
In a mirror every game reveals opponent Grimmsnarl, so the router latches to the
candidate specialist (greedy, live search disabled) exactly as it would live.

Gates (per the plan) are applied by report_gates(): aggregate >=52%, Wilson LB
>50%, neither seat <49.5%, no single opponent <49%, zero policy/engine errors,
and a v2.2-vs-v2.2 control within 49-51%.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import multiprocessing as mp
import os
import random
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

GRIM_DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
V2_BASE = ROOT / "artifacts" / "v2_model" / "policy_weights.npz"


# --------------------------------------------------------------------------- #
# Archive-faithful loader for our ptcg_ai + main.agent() submission format.
# --------------------------------------------------------------------------- #
class ArchiveAgent:
    """Load a historical submission dir under an isolated package alias so its
    own Python runs in-process alongside the repo's current code."""

    def __init__(self, directory: str | os.PathLike[str], env: dict | None = None):
        self.directory = Path(directory).resolve()
        self.deck = [
            int(line)
            for line in (self.directory / "deck.csv").read_text().splitlines()
            if line.strip()
        ]
        if len(self.deck) != 60:
            raise ValueError(f"archive deck must contain 60 cards: {self.directory}")
        self.errors = 0
        self._alias = f"_arch_{uuid4().hex}"
        self._agent_callable = self._load(env or {})

    def _load(self, env: dict):
        pkg_dir = self.directory / "ptcg_ai"
        spec = importlib.util.spec_from_file_location(
            self._alias,
            pkg_dir / "__init__.py",
            submodule_search_locations=[str(pkg_dir)],
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load archive package: {pkg_dir}")
        pkg = importlib.util.module_from_spec(spec)
        sys.modules[self._alias] = pkg
        spec.loader.exec_module(pkg)  # internal relative imports bind to the alias

        main_name = f"{self._alias}_main"
        saved_ptcg = sys.modules.get("ptcg_ai")
        saved_env = dict(os.environ)
        saved_cwd = os.getcwd()
        sys.modules["ptcg_ai"] = pkg  # archive main.py does `from ptcg_ai import ...`
        os.environ.update({str(k): str(v) for k, v in env.items()})
        # Kaggle runs an agent with cwd set to its own folder; the archive's
        # `CompetitionAgent()` resolves deck.csv relative to cwd at import time.
        os.chdir(self.directory)
        try:
            mspec = importlib.util.spec_from_file_location(
                main_name, self.directory / "main.py"
            )
            module = importlib.util.module_from_spec(mspec)
            sys.modules[main_name] = module
            mspec.loader.exec_module(module)  # constructs _AGENT with archive code
            return module.agent
        finally:
            os.chdir(saved_cwd)
            if saved_ptcg is not None:
                sys.modules["ptcg_ai"] = saved_ptcg
            else:
                sys.modules.pop("ptcg_ai", None)
            os.environ.clear()
            os.environ.update(saved_env)

    def __call__(self, obs_dict: dict) -> list[int]:
        saved = sys.modules.get("ptcg_ai")
        sys.modules["ptcg_ai"] = sys.modules[self._alias]
        try:
            return self._agent_callable(obs_dict)
        except Exception:
            self.errors += 1
            select = (obs_dict or {}).get("select") or {}
            count = len(select.get("option", []))
            minimum = max(0, int(select.get("minCount", 0)))
            return list(range(min(minimum, count)))
        finally:
            if saved is not None:
                sys.modules["ptcg_ai"] = saved
            else:
                sys.modules.pop("ptcg_ai", None)

    def close(self) -> None:
        """Drop the uniquely-named archive modules so long runs don't leak."""
        prefixes = (self._alias + ".", self._alias + "_main")
        for name in list(sys.modules):
            if name == self._alias or name.startswith(prefixes):
                sys.modules.pop(name, None)


def wilson(wins: int, games: int, z: float = 1.96) -> tuple[float, float]:
    if games == 0:
        return 0.0, 1.0
    p = wins / games
    denom = 1 + z * z / games
    center = (p + z * z / (2 * games)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * games)) / games) / denom
    return center - margin, center + margin


# --------------------------------------------------------------------------- #
# Chunk worker: build hero + opponent ONCE, reuse across many games (resetting
# the router latch per game to match live turn-1 behavior). Amortizes the
# expensive isolated archive import over thousands of games.
# --------------------------------------------------------------------------- #
def _reset_latches(agent) -> None:
    for attr in ("lucario_routed", "mirror_routed"):
        if hasattr(agent, attr):
            setattr(agent, attr, False)
    if hasattr(agent, "errors"):
        agent.errors = 0


def run_chunk(task):
    indices, hero_base, hero_mirror, opp_dir, control_dir, seed = task

    from cg.api import to_observation_class
    from cg.game import battle_finish, battle_select, battle_start
    from ptcg_ai.agent import CompetitionAgent

    if control_dir:  # v2.2-vs-v2.2 control: both sides are the same archive
        hero = ArchiveAgent(control_dir)
    else:
        hero = CompetitionAgent(
            deck_path=str(GRIM_DECK),
            model_path=hero_base,
            mirror_model_path=hero_mirror,
        )
    opponent = ArchiveAgent(opp_dir)

    wins = hero_err = opp_err = 0
    seat_games = [0, 0]
    seat_wins = [0, 0]
    try:
        for index in indices:
            random.seed(seed + index)
            try:
                import numpy as np

                np.random.seed((seed + index) % (2**32))
            except ImportError:
                pass
            _reset_latches(hero)
            opp_err_before = getattr(opponent, "errors", 0)

            seat_a = index % 2
            decks = (
                [hero.deck, opponent.deck]
                if seat_a == 0
                else [opponent.deck, hero.deck]
            )
            agents = {seat_a: hero, 1 - seat_a: opponent}
            raw, start = battle_start(decks[0], decks[1])
            if start.errorType != 0:
                raise RuntimeError(f"engine rejected deck: {start.errorType}")
            try:
                while True:
                    obs = to_observation_class(raw)
                    if obs.current is not None and obs.current.result != -1:
                        win = int(obs.current.result == seat_a)
                        break
                    raw = battle_select(agents[obs.current.yourIndex](raw))
            finally:
                battle_finish()
            wins += win
            seat_games[seat_a] += 1
            seat_wins[seat_a] += win
            hero_err += getattr(hero, "errors", 0)
            opp_err += getattr(opponent, "errors", 0) - opp_err_before
    finally:
        for a in (hero, opponent):
            if isinstance(a, ArchiveAgent):
                a.close()
    return {"wins": wins, "seat_games": seat_games, "seat_wins": seat_wins,
            "hero_err": hero_err, "opp_err": opp_err}


def run_pair(hero_base, hero_mirror, opp_dir, games, workers, seed, control_dir=""):
    # Distribute game indices round-robin so each worker gets a balanced,
    # seat-balanced slice; agents are constructed once per worker.
    chunks = [[] for _ in range(workers)]
    for i in range(games):
        chunks[i % workers].append(i)
    tasks = [
        (idx, hero_base, hero_mirror, str(opp_dir), str(control_dir), seed)
        for idx in chunks
        if idx
    ]
    wins = hero_err = opp_err = 0
    seat_games = [0, 0]
    seat_wins = [0, 0]
    ctx = mp.get_context("spawn")
    with ctx.Pool(workers) as pool:
        for res in pool.imap_unordered(run_chunk, tasks):
            wins += res["wins"]
            hero_err += res["hero_err"]
            opp_err += res["opp_err"]
            for s in (0, 1):
                seat_games[s] += res["seat_games"][s]
                seat_wins[s] += res["seat_wins"][s]
    lo, hi = wilson(wins, games)
    return {
        "games": games,
        "wins": wins,
        "win_rate": wins / games if games else 0.0,
        "wilson_95": [lo, hi],
        "seat0": {"games": seat_games[0], "wins": seat_wins[0],
                   "win_rate": seat_wins[0] / seat_games[0] if seat_games[0] else 0.0},
        "seat1": {"games": seat_games[1], "wins": seat_wins[1],
                   "win_rate": seat_wins[1] / seat_games[1] if seat_games[1] else 0.0},
        "hero_errors": hero_err,
        "opp_errors": opp_err,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate", required=True, help="candidate mirror-specialist npz")
    ap.add_argument("--base", default=str(V2_BASE), help="hero base (non-mirror) weights")
    ap.add_argument("--opponents", required=True,
                    help="comma-separated name:dir opponent archives")
    ap.add_argument("--games", type=int, default=10000, help="games per opponent")
    ap.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    ap.add_argument("--seed", type=int, default=20260806)
    ap.add_argument("--control", default="", help="archive dir for v2.2-vs-v2.2 control")
    ap.add_argument("--output", help="JSON result path")
    args = ap.parse_args()

    opponents = {}
    for token in args.opponents.split(","):
        name, _, path = token.partition(":")
        opponents[name.strip()] = path.strip()

    result = {"candidate": args.candidate, "base": args.base, "games_per_opp": args.games,
              "opponents": {}}
    for name, path in opponents.items():
        print(f"[{name}] {args.games} games ...", flush=True)
        r = run_pair(args.candidate, args.candidate, path, args.games,
                     args.workers, args.seed)
        result["opponents"][name] = r
        print(f"  {name}: {r['wins']}/{r['games']} ({r['win_rate']*100:.2f}%) "
              f"Wilson[{r['wilson_95'][0]*100:.2f},{r['wilson_95'][1]*100:.2f}] "
              f"seat0={r['seat0']['win_rate']*100:.1f} seat1={r['seat1']['win_rate']*100:.1f} "
              f"err h={r['hero_errors']} o={r['opp_errors']}", flush=True)

    if args.control:
        print(f"[control v2.2-vs-v2.2] {args.games} games ...", flush=True)
        c = run_pair(args.candidate, args.candidate, args.control, args.games,
                     args.workers, args.seed, control_dir=args.control)
        result["control"] = c
        print(f"  control: {c['win_rate']*100:.2f}% (expect ~50)", flush=True)

    # Aggregate + gates
    agg_w = sum(o["wins"] for o in result["opponents"].values())
    agg_g = sum(o["games"] for o in result["opponents"].values())
    lo, hi = wilson(agg_w, agg_g)
    mean_of_means = (sum(o["win_rate"] for o in result["opponents"].values())
                     / max(1, len(result["opponents"])))
    result["aggregate"] = {"wins": agg_w, "games": agg_g,
                            "win_rate": agg_w / agg_g if agg_g else 0.0,
                            "wilson_95": [lo, hi],
                            "equal_weight_mean": mean_of_means}
    result["gates"] = report_gates(result)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["gates"], indent=2))
    return 0


def report_gates(result: dict) -> dict:
    opps = result["opponents"]
    agg = result["aggregate"]
    total_err = sum(o["hero_errors"] + o["opp_errors"] for o in opps.values())
    gates = {
        "aggregate_ge_52": agg["win_rate"] >= 0.52,
        "wilson_lb_gt_50": agg["wilson_95"][0] > 0.50,
        "each_seat_ge_49_5": all(
            o["seat0"]["win_rate"] >= 0.495 and o["seat1"]["win_rate"] >= 0.495
            for o in opps.values()
        ),
        "each_opponent_ge_49": all(o["win_rate"] >= 0.49 for o in opps.values()),
        "zero_errors": total_err == 0,
    }
    if "control" in result:
        c = result["control"]["win_rate"]
        gates["control_49_51"] = 0.49 <= c <= 0.51
    gates["PASS"] = all(gates.values())
    return gates


if __name__ == "__main__":
    raise SystemExit(main())
