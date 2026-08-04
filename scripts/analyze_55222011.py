#!/usr/bin/env python3
"""Loss-bucket and rating-band analysis for submission 55222011."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deep_data_analysis import (  # noqa: E402
    ROOT,
    analyze_records,
    load_card_db,
    load_known_decks,
    load_leaderboard,
    process_submission_data,
)

SUB_IDS = [55218277, 55222011]

# Archetypes classify_deck's keyword list misses or under-detects, tagged by
# whether the current training pipeline has an adversary/prior for them.
UNTRAINED_SLUGS = {"mega_lucario_ex", "iono_bellibolt_ex"}


def classify_extra(label: str, slug: str, deck_cards, card_db) -> tuple[str, str]:
    names_str = " ".join(card_db.get(c, "") for c in deck_cards).lower()
    if "lucario" in names_str:
        return "Mega Lucario ex", "mega_lucario_ex"
    if "bellibolt" in names_str or "iono's" in names_str or "iono’s" in names_str:
        return "Iono / Bellibolt ex", "iono_bellibolt_ex"
    return label, slug


def load_and_patch(sub_id: int, card_db, known_decks, leaderboard) -> list[dict]:
    records = process_submission_data(sub_id, card_db, known_decks, leaderboard)
    if not records:
        print(f"No records for {sub_id}. Check data/replays/{sub_id}/episodes_metadata.json")
        return []

    sub_dir = ROOT / "data" / "replays" / str(sub_id)
    for r in records:
        rp = sub_dir / f"episode-{r['episode_id']}-replay.json"
        if not rp.exists():
            continue
        data = json.loads(rp.read_text())
        steps = data.get("steps", [])
        if len(steps) <= 1:
            continue
        opp_seat = 1 - r["our_seat"]
        opp_deck_cards = steps[1][opp_seat].get("action") or [] if opp_seat < len(steps[1]) else []
        new_label, new_slug = classify_extra(r["opp_archetype"], r["opp_archetype_slug"], opp_deck_cards, card_db)
        r["opp_archetype"] = new_label
        r["opp_archetype_slug"] = new_slug
    return records


def print_stats(stats: dict, label: str):
    print(f"=== {label}: {stats['wins']}W-{stats['losses']}L-{stats['ties']}T "
          f"({stats['win_rate']:.1%}) | Rating {stats['first_score']:.1f} -> {stats['last_score']:.1f} "
          f"(peak {stats['peak_score']:.1f}, net {stats['net_rating_delta']:+.1f}) ===\n")

    print("--- Loss bucket by opponent archetype (untrained matchups flagged) ---")
    sorted_opps = sorted(stats["opp_archetypes"].items(), key=lambda x: x[1]["cost"], reverse=True)
    for arch, a in sorted_opps:
        flag = " <-- NO TRAINED ADVERSARY" if arch in {"Mega Lucario ex", "Iono / Bellibolt ex"} else ""
        print(f"  {arch:32s} games={a['games']:3d} wins={a['wins']:3d} losses={a['losses']:3d} "
              f"win_rate={a['win_rate']:.1%} (95% CI {a['ci_95'][0]:.0%}-{a['ci_95'][1]:.0%}) "
              f"cost={a['cost']:.1f} net_elo={a['net_elo_delta']:+.1f}{flag}")

    print("\n--- Win rate by opponent rating band ---")
    for band, b in stats["score_bands"].items():
        if b["games"] == 0:
            continue
        print(f"  {band:28s} games={b['games']:3d} wins={b['wins']:3d} losses={b['losses']:3d} "
              f"win_rate={b['win_rate']:.1%} (95% CI {b['ci_95'][0]:.0%}-{b['ci_95'][1]:.0%}) "
              f"net_delta={b['net_delta']:+.1f}")

    print("\n--- Our archetype(s) piloted ---")
    for arch, a in stats["our_archetypes"].items():
        print(f"  {arch:32s} games={a['games']:3d} win_rate={a['win_rate']:.1%}")

    print("\n--- End reasons ---")
    for reason, cnt in sorted(stats["end_reasons"].items(), key=lambda x: -x[1]):
        print(f"  {reason:50s} {cnt}")
    print()


def main():
    card_db = load_card_db()
    known_decks = load_known_decks()
    leaderboard = load_leaderboard()

    all_records = {}
    for sub_id in SUB_IDS:
        recs = load_and_patch(sub_id, card_db, known_decks, leaderboard)
        all_records[sub_id] = recs
        stats = analyze_records(recs, f"Submission {sub_id}")
        print_stats(stats, f"Submission {sub_id}")

        out_json = ROOT / "artifacts" / "ladder" / f"analysis_{sub_id}.json"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        clean = {k: v for k, v in stats.items() if k != "raw_records"}
        out_json.write_text(json.dumps(clean, indent=2))

    combined = sum(all_records.values(), [])
    stats_combined = analyze_records(combined, "Combined")
    print_stats(stats_combined, "Combined (55218277 + 55222011)")

    print("--- Untrained-adversary matchups only (Lucario, Iono/Bellibolt) ---")
    for arch in ["Mega Lucario ex", "Iono / Bellibolt ex"]:
        a = stats_combined["opp_archetypes"].get(arch)
        if not a:
            print(f"  {arch}: 0 games encountered in this pool")
            continue
        print(f"  {arch:20s} games={a['games']:3d} win_rate={a['win_rate']:.1%} "
              f"(95% CI {a['ci_95'][0]:.0%}-{a['ci_95'][1]:.0%}) net_elo={a['net_elo_delta']:+.1f}")

    out_json = ROOT / "artifacts" / "ladder" / "analysis_55218277_55222011_combined.json"
    clean = {k: v for k, v in stats_combined.items() if k != "raw_records"}
    out_json.write_text(json.dumps(clean, indent=2))
    print(f"\nJSON written per-submission + {out_json}")


if __name__ == "__main__":
    main()
