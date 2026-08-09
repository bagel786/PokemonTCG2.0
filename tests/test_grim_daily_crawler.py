from types import SimpleNamespace
import gzip
import json

from scripts import crawl_grim_daily as crawler


def episode(deck0, deck1, rewards=(-1, 1)):
    return {
        "rewards": list(rewards),
        "info": {"EpisodeId": 17, "TeamNames": ["grim", "opponent"]},
        "steps": [
            [{}, {}],
            [{"action": list(deck0)}, {"action": list(deck1)}],
        ],
    }


def test_current_archetype_catalog_classifies_required_decks():
    catalog = crawler.load_archetype_catalog(crawler.ROOT / "freshstart" / "decklists")
    for name in (
        "mega_lucario_ex",
        "alakazam_dudunsparce",
        "kangaskhan_crustle",
        "iono_bellibolt_ex",
        "ogerpon",
    ):
        assert crawler.classify(catalog[name], catalog) == name


def test_family_variant_prevents_zero_but_is_excluded_from_exact_training(tmp_path, monkeypatch):
    exact = crawler.canonical_deck([648] + list(range(1, 60)))
    variant = crawler.canonical_deck([648, 648] + list(range(2, 60)))
    opponent = crawler.canonical_deck(range(100, 160))
    path = tmp_path / "episode.json"
    path.write_text("placeholder")
    monkeypatch.setattr(crawler, "load_episode", lambda _path: episode(variant, opponent))
    monkeypatch.setattr(crawler, "iter_decisions", lambda *_args, **_kwargs: [])
    result = crawler.process_episode(path, "2026-08-06", exact, {}, 3)
    assert len(result["units"]) == 1
    assert result["units"][0]["exact_current_deck"] is False
    assert result["rows"] == []


def test_exact_deck_loss_is_retained_with_negative_outcome(tmp_path, monkeypatch):
    exact = crawler.canonical_deck([648] + list(range(1, 60)))
    opponent = crawler.canonical_deck(range(100, 160))
    path = tmp_path / "episode.json"
    path.write_text("placeholder")
    monkeypatch.setattr(crawler, "load_episode", lambda _path: episode(exact, opponent))
    decision = SimpleNamespace(
        seat=0,
        reward=0.0,
        to_json=lambda: {
            "episode_id": "17", "seat": 0, "step": 4, "team": "grim", "reward": 0.0,
            "action": [1], "legal_options": [{"type": 13}],
            "features": {"feature_version": 3, "global": [], "tokens": [], "options": []},
        },
    )
    monkeypatch.setattr(crawler, "iter_decisions", lambda *_args, **_kwargs: [decision])
    result = crawler.process_episode(path, "2026-08-06", exact, {}, 3)
    assert result["rows"][0]["reward"] == 0.0
    assert result["rows"][0]["outcome"] == "loss"


def test_behavior_rows_include_signature_classified_deck_variants(tmp_path, monkeypatch):
    catalog = crawler.load_archetype_catalog(crawler.ROOT / "freshstart" / "decklists")
    exact = crawler.canonical_deck(catalog["grimmsnarl_marnie"])
    variant = list(catalog["mega_starmie_froslass"])
    variant[-1] = 1 if variant[-1] != 1 else 2
    variant = crawler.canonical_deck(variant)
    assert variant != catalog["mega_starmie_froslass"]
    assert crawler.classify(variant, catalog) == "mega_starmie_froslass"
    path = tmp_path / "episode.json"
    path.write_text("placeholder")
    monkeypatch.setattr(crawler, "load_episode", lambda _path: episode(exact, variant))
    decision = SimpleNamespace(
        seat=1,
        reward=1.0,
        to_json=lambda: {
            "episode_id": "17", "seat": 1, "step": 4, "team": "opponent", "reward": 1.0,
            "action": [0], "legal_options": [{"type": 13}],
            "features": {"feature_version": 3, "global": [], "tokens": [], "options": []},
        },
    )
    monkeypatch.setattr(crawler, "iter_decisions", lambda *_args, **_kwargs: [decision])
    result = crawler.process_episode(path, "2026-08-06", exact, catalog, 3)
    assert result["behavior_rows"][0]["behavior_archetype"] == "mega_starmie_froslass"


def test_split_assignment_keeps_mirror_seats_in_one_split(tmp_path):
    output = tmp_path / "v3"
    (output / "manifests").mkdir(parents=True)
    (output / "shards").mkdir()
    (output / "manifests" / "2026-08-06.json").write_text(json.dumps({
        "date": "2026-08-06", "status": "complete", "grim_family_units": 2,
    }))
    rows = [
        {
            "episode_id": "mirror", "seat": seat, "step": 3, "source_date": "2026-08-06",
            "team": f"team-{seat}", "opponent_team": f"team-{1-seat}",
        }
        for seat in (0, 1)
    ]
    with gzip.open(output / "shards" / "2026-08-06.jsonl.gz", "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    manifest = crawler.assign_splits(output, tmp_path / "legacy")
    assert manifest["splits"]["temporal_holdout"]["rows"] == 2
    with gzip.open(output / "splits" / "temporal_holdout.jsonl.gz", "rt", encoding="utf-8") as handle:
        assert {json.loads(line)["seat"] for line in handle} == {0, 1}
