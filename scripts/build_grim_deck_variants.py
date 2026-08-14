#!/usr/bin/env python3
"""Build the bounded Grim deck-count screen over immutable A2+Damage V0."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/grim_damage_conversion/candidates/a2_damage_v0/deck.csv"
OUTPUT = ROOT / "artifacts/grim_deck_sprint/decks"
EXPECTED_BASE_SHA256 = "92b92bac9f9163ecff933b3dc39294d2cc154c8684f3c8497877661419ebc59d"

CARD_NAMES = {
    104: "Froslass",
    646: "Marnie's Impidimp",
    647: "Marnie's Morgrem",
    648: "Marnie's Grimmsnarl ex",
    860: "Snorunt",
    1079: "Rare Candy",
    1081: "Enhanced Hammer",
    1097: "Night Stretcher",
    1122: "Pokegear 3.0",
    1123: "Switch",
    1137: "Tool Scrapper",
    1152: "Poke Pad",
    1161: "Handheld Fan",
    1182: "Boss's Orders",
    1197: "Xerosic's Machinations",
    1219: "Team Rocket's Petrel",
    1259: "Spikemuth Gym",
    1260: "Risky Ruins",
}

# Each entry is a tuple of (card removed, card added). The first thirteen stay
# entirely within the incumbent card vocabulary; the last five are narrow tech
# probes and never bypass the same paired confirmation gates.
VARIANTS: dict[str, tuple[tuple[int, int], ...]] = {
    "grim4_minus_tool": ((1137, 648),),
    "candy4_minus_tool": ((1137, 1079),),
    "stretcher4_minus_tool": ((1137, 1097),),
    "boss3_minus_tool": ((1137, 1182),),
    "gear2_minus_tool": ((1137, 1122),),
    "grim4_minus_stretcher": ((1097, 648),),
    "candy4_minus_stretcher": ((1097, 1079),),
    "grim4_candy4_minus_tool_stretcher": ((1137, 648), (1097, 1079)),
    "grim4_minus_morgrem": ((647, 648),),
    "candy4_minus_morgrem": ((647, 1079),),
    "snorunt3_minus_tool": ((1137, 860),),
    "froslass3_minus_tool": ((1137, 104),),
    "froslass_line3_minus_tool_stretcher": ((1137, 860), (1097, 104)),
    "grim4_minus_pokepad": ((1152, 648),),
    "candy4_minus_pokepad": ((1152, 1079),),
    "switch1_minus_tool": ((1137, 1123),),
    "hammer1_minus_tool": ((1137, 1081),),
    "fan1_minus_tool": ((1137, 1161),),
    "xerosic1_minus_petrel": ((1219, 1197),),
    "risky_ruins1_minus_spikemuth": ((1259, 1260),),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if sha256(BASE) != EXPECTED_BASE_SHA256:
        raise RuntimeError("immutable A2+Damage V0 deck hash changed")
    base = [int(line) for line in BASE.read_text().splitlines() if line.strip()]
    if len(base) != 60:
        raise RuntimeError("base Grim deck is not 60 cards")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "base": str(BASE.relative_to(ROOT)),
        "base_sha256": EXPECTED_BASE_SHA256,
        "variants": {},
    }
    for name, swaps in VARIANTS.items():
        counts = Counter(base)
        changes = []
        for removed, added in swaps:
            if counts[removed] <= 0:
                raise RuntimeError(f"{name}: cannot remove absent card {removed}")
            counts[removed] -= 1
            counts[added] += 1
            changes.append(
                {
                    "remove": {"id": removed, "name": CARD_NAMES.get(removed, str(removed))},
                    "add": {"id": added, "name": CARD_NAMES.get(added, str(added))},
                }
            )
        if sum(counts.values()) != 60 or any(
            value < 0 or (card != 7 and value > 4) for card, value in counts.items()
        ):
            raise RuntimeError(f"{name}: illegal deck multiplicities")
        deck = [card for card, count in sorted(counts.items()) for _ in range(count)]
        path = OUTPUT / f"{name}.csv"
        path.write_text("".join(f"{card}\n" for card in deck), encoding="utf-8")
        manifest["variants"][name] = {
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256(path),
            "changes": changes,
        }
    manifest_path = OUTPUT.parent / "variant_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
