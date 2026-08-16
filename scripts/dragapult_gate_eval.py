#!/usr/bin/env python3
"""Run seat-balanced gate evaluation of a Dragapult candidate vs an opponent."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OPPONENTS = {
    "starmie": "artifacts/dragapult_opponents",
    "a2_damage_v0": "artifacts/a2_damage_v0",
    "exp20_punk": "artifacts/final_sprint/exp20_punk_first_only",
    "c0_control": "artifacts/grim_damage_conversion/winner/extracted",
    "dipplin_d1": "artifacts/sprint_870/opponents/dipplin_d1",
    "alakazam_27": "artifacts/sprint_870/opponents/alakazam_2_7",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True, help="candidate npz path")
    parser.add_argument("--opponent", required=True, choices=sorted(OPPONENTS))
    parser.add_argument("--games", type=int, default=60)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--seed", type=int, default=202608161000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    eval_dir = ROOT / "artifacts" / "dragapult_eval"
    link = eval_dir / "direct_policy.npz"
    candidate = (ROOT / args.candidate).resolve()
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(candidate)
    opp = ROOT / OPPONENTS[args.opponent]
    out = ROOT / args.output
    cmd = [
        sys.executable, "-m", "training.evaluate",
        "--deck-a", str(eval_dir / "deck.csv"),
        "--submission-a", str(eval_dir),
        "--deck-b", str(opp / "deck.csv"),
        "--submission-b", str(opp),
        "--games", str(args.games),
        "--workers", str(args.workers),
        "--seed", str(args.seed),
        "--output", str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    sys.stdout.write(result.stdout[-2000:])
    if result.returncode != 0:
        print(result.stderr[-2000:], file=sys.stderr)
        return result.returncode
    try:
        data = json.loads(out.read_text())
    except Exception:
        return 1
    overall = data["overall"]
    seats = data.get("seat_results_a", {})
    print(f"\nCANDIDATE {candidate.name} vs {args.opponent}: "
          f"{overall['wins']}/{overall['games']} = {overall['win_rate']*100:.1f}% "
          f"wilson [{overall['wilson_95'][0]*100:.1f}, {overall['wilson_95'][1]*100:.1f}] "
          f"seat0 {seats.get('0', {}).get('win_rate', 0)*100:.0f}% "
          f"seat1 {seats.get('1', {}).get('win_rate', 0)*100:.0f}% "
          f"hero_err {data.get('hero_policy_errors')} opp_err {data.get('opponent_policy_errors')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
