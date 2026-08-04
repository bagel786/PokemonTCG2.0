import json
from pathlib import Path

from training.run_league import build_round_league

ROOT = Path(__file__).resolve().parents[1]
GRIMMSNARL = {"name": "grimmsnarl_marnie", "deck": "freshstart/decklists/grimmsnarl_marnie.deck.csv"}
GARCHOMP = {"name": "cynthias_garchomp_ex", "deck": "freshstart/decklists/cynthias_garchomp_ex.deck.csv"}
CRUSTLE = {"name": "kangaskhan_crustle", "deck": "freshstart/decklists/kangaskhan_crustle.deck.csv"}


def base_league():
    return json.loads((ROOT / "training/meta_league.json").read_text())


def test_live_models_replace_base_entries_and_snapshots_are_bounded():
    live = {"cynthias_garchomp_ex": Path("live-g.npz"), "grimmsnarl_marnie": Path("live-r.npz")}
    snapshots = [
        {"name": "g_snapshot", "deck": GARCHOMP["deck"], "model": Path("old-g.npz")},
        {"name": "r_snapshot", "deck": GRIMMSNARL["deck"], "model": Path("old-r.npz")},
    ]
    league = build_round_league(base_league(), live, [GRIMMSNARL], snapshots, 30.0, 10.0)
    by_name = {row["name"]: row for row in league["opponents"]}

    assert by_name["grimmsnarl_marnie"]["model"] == "live-r.npz"
    assert by_name["cynthias_garchomp_ex"]["model"] == "live-g.npz"
    assert by_name["live_grimmsnarl_marnie"]["model"] == "live-r.npz"
    assert by_name["live_grimmsnarl_marnie"]["train_weight"] == 30.0
    assert by_name["g_snapshot"]["train_weight"] == 5.0
    assert by_name["r_snapshot"]["train_weight"] == 5.0


def test_live_weight_splits_across_every_cross_play_opponent():
    """With N learners the live budget is shared, not duplicated per opponent."""
    live = {
        "cynthias_garchomp_ex": Path("live-g.npz"),
        "grimmsnarl_marnie": Path("live-r.npz"),
        "kangaskhan_crustle": Path("live-c.npz"),
    }
    league = build_round_league(base_league(), live, [GARCHOMP, CRUSTLE], [], 30.0, 15.0)
    by_name = {row["name"]: row for row in league["opponents"]}

    assert by_name["live_cynthias_garchomp_ex"]["train_weight"] == 15.0
    assert by_name["live_kangaskhan_crustle"]["train_weight"] == 15.0
    # A promoted archetype's base entry must now point at its learned policy,
    # not stay a heuristic (model=None) as it was for every run so far.
    assert by_name["kangaskhan_crustle"]["model"] == "live-c.npz"
