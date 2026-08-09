#!/usr/bin/env python3
"""Build immutable authentic opponent directories for the final B-family gate."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_recovery_probes import (
    build_unshielded,
    safe_extract,
    sha256,
)
from training.evaluation_schema import sha256_path

ARCHIVES = {
    "d842": ROOT / "artifacts" / "recovery_probes" / "d842_control_exact.tar.gz",
    "master_v1": ROOT / "artifacts" / "submission_master_v1.tar.gz",
    "replay_refresh": ROOT / "grimmsnarl_replay_refresh_challenger.tar.gz",
    "v2_2": ROOT / "artifacts" / "submission_v2_2.tar.gz",
}
CLONES = {
    "lucario": ROOT / "freshstart" / "decklists" / "mega_lucario_ex.deck.csv",
    "crustle": ROOT / "freshstart" / "decklists" / "kangaskhan_crustle.deck.csv",
    "ogerpon": None,
    "bellibolt": ROOT / "freshstart" / "decklists" / "iono_bellibolt_ex.deck.csv",
    "starmie_froslass": ROOT / "freshstart" / "decklists" / "mega_starmie_froslass.deck.csv",
}


def deck_hash(cards: tuple[int, ...]) -> str:
    return hashlib.sha256("\n".join(map(str, cards)).encode()).hexdigest()


def representative_deck(name: str) -> tuple[tuple[int, ...], dict[str, int]]:
    source = ROOT / "artifacts" / "recovery_behavior_clones" / name / "recent_behavior.jsonl.gz"
    counts: Counter[tuple[int, ...]] = Counter()
    with gzip.open(source, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            deck = tuple(sorted(int(card) for card in row.get("deck", [])))
            if len(deck) == 60:
                counts[deck] += 1
    if not counts:
        raise RuntimeError(f"behavior clone has no certified 60-card deck: {name}")
    deck, decisions = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0]
    return deck, {"distinct_decks": len(counts), "representative_decisions": decisions}


def write_deck(path: Path, cards: tuple[int, ...]) -> None:
    path.write_text("\n".join(map(str, cards)) + "\n", encoding="utf-8")


def reset_stage(stage: Path, output_root: Path) -> None:
    resolved_stage = stage.resolve()
    resolved_root = output_root.resolve()
    if resolved_root not in resolved_stage.parents:
        raise RuntimeError(f"refusing to reset stage outside opponent root: {resolved_stage}")
    if resolved_stage.exists():
        shutil.rmtree(resolved_stage)
    resolved_stage.mkdir(parents=True)


def main() -> int:
    output = ROOT / "artifacts" / "recovery_final" / "opponents"
    packages = ROOT / "artifacts" / "recovery_final" / "opponent_packages"
    output.mkdir(parents=True, exist_ok=True)
    packages.mkdir(parents=True, exist_ok=True)
    manifest = {"grim": {}, "behavior_clones": {}}
    grim_deck = tuple(sorted(
        int(value) for value in (ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv").read_text().splitlines()
        if value.strip()
    ))
    for name, archive in ARCHIVES.items():
        if not archive.exists():
            raise FileNotFoundError(archive)
        stage = output / name
        reset_stage(stage, output)
        safe_extract(archive, stage)
        write_deck(stage / "deck.csv", grim_deck)
        manifest["grim"][name] = {
            "archive": str(archive.resolve()),
            "archive_sha256": sha256(archive),
            "artifact_tree_sha256": sha256_path(stage),
            "deck": str((stage / "deck.csv").resolve()),
            "deck_sha256": deck_hash(grim_deck),
        }

    clone_manifest = json.loads((ROOT / "artifacts" / "recovery_behavior_clones" / "manifest.json").read_text())
    for name, canonical_deck_path in CLONES.items():
        weights = ROOT / clone_manifest[name]["model"]
        package = build_unshielded(f"clone_{name}", weights, packages)
        stage = output / name
        reset_stage(stage, output)
        safe_extract(Path(package["archive"]), stage)
        representative, deck_stats = representative_deck(name)
        if canonical_deck_path is not None:
            canonical = tuple(sorted(int(value) for value in canonical_deck_path.read_text().splitlines() if value.strip()))
            if len(canonical) != 60:
                raise RuntimeError(f"canonical deck is not 60 cards: {canonical_deck_path}")
            # The representative recent list is authoritative for variants;
            # record whether it exactly matches the repository's canonical list.
            canonical_match = canonical == representative
        else:
            canonical_match = None
        write_deck(stage / "deck.csv", representative)
        manifest["behavior_clones"][name] = {
            **package,
            **deck_stats,
            "representative_deck_sha256": deck_hash(representative),
            "canonical_deck_match": canonical_match,
            "artifact_tree_sha256": sha256_path(stage),
            "agent": str(stage.resolve()),
            "deck": str((stage / "deck.csv").resolve()),
        }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
