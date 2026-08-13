import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ptcg_ai.dipplin.cards import EXACT_DECK
from scripts import freeze_dipplin_replay_holdout as freezer
from training.lucario_data import load_deck


HERO_SUBMISSION = 7001
HERO_TEAM = 8001
OPPONENT_SUBMISSION = 7002
OPPONENT_TEAM = 8002
EPISODE_ID = 9001


def selection(*, family="Thwackey / Dipplin"):
    return {
        "episode_id": EPISODE_ID,
        "source_id": "hero",
        "split": "FINAL_HOLDOUT",
        "hero_submission_id": HERO_SUBMISSION,
        "expected_hero_team_id": HERO_TEAM,
        "expected_hero_pilot": "Expert Hero",
        "hero_deck_family": family,
        "expected_expert_reward": 1,
        "expected_opponent_submission_id": OPPONENT_SUBMISSION,
        "expected_opponent_team_id": OPPONENT_TEAM,
    }


def api_episode(*, hero_submission=HERO_SUBMISSION, opponent_submission=OPPONENT_SUBMISSION):
    return {
        "id": EPISODE_ID,
        "createTime": "2026-08-12T12:34:56Z",
        "agents": [
            {
                "id": 11,
                "submissionId": opponent_submission,
                "teamId": OPPONENT_TEAM,
                "reward": -1,
                "initialScore": 987.5,
                "updatedScore": 981.0,
            },
            {
                "id": 12,
                "index": 1,
                "submissionId": hero_submission,
                "teamId": HERO_TEAM,
                "reward": 1,
                "initialScore": 1010.0,
                "updatedScore": 1016.5,
            },
        ],
    }


def opponent_deck():
    return load_deck(freezer.DEFAULT_DECK_DIR / "mega_lucario_ex.deck.csv")


def replay(*, hero_deck=EXACT_DECK):
    return {
        "info": {
            "EpisodeId": EPISODE_ID,
            "TeamNames": ["Opponent Pilot", "Expert Hero"],
        },
        "rewards": [-1, 1],
        "steps": [
            [{"observation": {}}, {"observation": {}}],
            [
                {
                    "action": list(opponent_deck()),
                    "observation": {"current": {"firstPlayer": 0, "result": -1}},
                },
                {
                    "action": list(hero_deck),
                    "observation": {"current": {"firstPlayer": 0, "result": -1}},
                },
            ],
            [
                {
                    # Deliberately malformed non-handshake actions prove the
                    # metadata extractor never tries to interpret decisions.
                    "action": {"must_not_be_read": True},
                    "observation": {"current": {"firstPlayer": 0, "result": 1}},
                },
                {
                    "action": "must-not-be-read",
                    "observation": {"current": {"firstPlayer": 0, "result": 1}},
                },
            ],
        ],
    }


def catalog_and_cards():
    catalog = freezer.load_archetype_catalog(freezer.DEFAULT_DECK_DIR)
    cards = freezer.load_card_name_ids(freezer.DEFAULT_CARD_DATA)
    return catalog, cards


def write_replay(tmp_path: Path, payload=None) -> Path:
    path = tmp_path / f"episode-{EPISODE_ID}-replay.json"
    path.write_text(json.dumps(payload or replay()), encoding="utf-8")
    return path


def test_metadata_only_extraction_verifies_seat_deck_order_result_and_archetype(tmp_path):
    path = write_replay(tmp_path)
    catalog, cards = catalog_and_cards()
    record = freezer.extract_metadata_only(
        path,
        selection(),
        api_episode(),
        catalog,
        cards,
    )

    assert record["episode_id"] == EPISODE_ID
    assert record["expert_result"] == "win"
    assert record["first_player_seat"] == 0
    assert record["hero"]["seat"] == 1
    assert record["hero"]["actual_order"] == "second"
    assert record["hero"]["submission_id"] == HERO_SUBMISSION
    assert record["hero"]["team_id"] == HERO_TEAM
    assert record["hero"]["deck_family"] == "thwackey_dipplin"
    assert record["opponent"]["submission_id"] == OPPONENT_SUBMISSION
    assert record["opponent"]["archetype"] == "mega_lucario_ex"
    assert record["opponent"]["exact_catalog_match"] is True
    assert record["source_timestamp"] == "2026-08-12T12:34:56Z"
    assert record["replay_sha256"] == freezer.sha256_file(path)
    assert "action" not in record
    assert "decisions" not in record


def test_api_submission_and_opponent_identity_mismatches_fail_closed():
    with pytest.raises(freezer.FreezeError, match="seats for hero submission"):
        freezer.normalize_episode_metadata(
            selection(),
            api_episode(hero_submission=HERO_SUBMISSION + 99),
        )
    with pytest.raises(freezer.FreezeError, match="opponent submission mismatch"):
        freezer.normalize_episode_metadata(
            selection(),
            api_episode(opponent_submission=OPPONENT_SUBMISSION + 99),
        )


def test_non_dipplin_hero_handshake_fails_closed(tmp_path):
    path = write_replay(tmp_path, replay(hero_deck=opponent_deck()))
    catalog, cards = catalog_and_cards()
    with pytest.raises(freezer.FreezeError, match="not a full Festival Dipplin family"):
        freezer.extract_metadata_only(
            path,
            selection(),
            api_episode(),
            catalog,
            cards,
        )


def test_rillaboom_dipplin_family_is_supported_from_full_core():
    deck = list(EXACT_DECK)
    trainer_index = deck.index(1080)
    deck[trainer_index] = freezer.RILLABOOM
    cards = freezer.load_card_name_ids(freezer.DEFAULT_CARD_DATA)
    family, counts = freezer.verify_dipplin_family(
        freezer.canonical_deck(deck),
        cards,
    )
    assert family == "rillaboom_dipplin"
    assert counts["rillaboom"] == 1


def test_inventory_rejects_episode_overlap_across_splits():
    source = {
        "submission_id": HERO_SUBMISSION,
        "team_id": HERO_TEAM,
        "pilot": "Expert Hero",
        "deck_family": "Thwackey / Dipplin",
    }
    row = {
        "episode_id": EPISODE_ID,
        "source_id": "hero",
        "expected_expert_reward": 1,
        "expected_opponent_submission_id": OPPONENT_SUBMISSION,
        "expected_opponent_team_id": OPPONENT_TEAM,
    }
    inventory = {
        "schema_version": 1,
        "selection_provenance": {
            "selection_used_outcome": False,
            "excluded_submission_ids": [],
        },
        "sources": {"hero": source},
        "expected_counts": {"VALIDATION": 1, "FINAL_HOLDOUT": 1},
        "splits": {"VALIDATION": [row], "FINAL_HOLDOUT": [dict(row)]},
    }
    with pytest.raises(freezer.FreezeError, match="overlaps"):
        freezer.validate_inventory(inventory)


def test_download_retries_then_immediately_reuses_valid_cache(tmp_path):
    target = tmp_path / "cache" / f"episode-{EPISODE_ID}-replay.json"
    calls = []
    sleeps = []

    def runner(command, **_kwargs):
        calls.append(command)
        if len(calls) == 2:
            output = Path(command[command.index("-p") + 1])
            (output / target.name).write_text(
                json.dumps({"info": {"EpisodeId": EPISODE_ID}}),
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="transient 429")

    assert freezer.download_replay(
        EPISODE_ID,
        target,
        env={},
        retries=3,
        backoff_seconds=0.01,
        sleeper=sleeps.append,
        runner=runner,
        kaggle_command=["kaggle"],
    ) == "downloaded"
    assert target.exists()
    assert len(calls) == 2
    assert sleeps == [0.01]

    assert freezer.download_replay(
        EPISODE_ID,
        target,
        env={},
        runner=lambda *_args, **_kwargs: pytest.fail("cache reuse invoked network"),
    ) == "cached"


def test_metadata_acquisition_caches_only_fixed_rows_and_reuses_offline(tmp_path):
    row = selection()
    unrelated = {**api_episode(), "id": EPISODE_ID + 1}
    calls = []

    def fetcher(submission_id, **_kwargs):
        calls.append(submission_id)
        return [unrelated, api_episode()]

    resolved, sources = freezer.acquire_fixed_episode_metadata(
        [row],
        tmp_path,
        allow_network=True,
        token="synthetic-token",
        fetcher=fetcher,
    )
    assert set(resolved) == {EPISODE_ID}
    assert calls == [HERO_SUBMISSION]
    cache = tmp_path / "episode_metadata" / f"submission-{HERO_SUBMISSION}.json"
    cached_payload = json.loads(cache.read_text(encoding="utf-8"))
    assert [episode["id"] for episode in cached_payload["episodes"]] == [EPISODE_ID]
    assert sources[0]["metadata_cache_sha256"] == freezer.sha256_file(cache)

    offline, offline_sources = freezer.acquire_fixed_episode_metadata(
        [row],
        tmp_path,
        allow_network=False,
        fetcher=lambda *_args, **_kwargs: pytest.fail("offline cache reuse fetched API"),
    )
    assert offline == resolved
    assert offline_sources == sources


def test_frozen_manifest_is_self_hashed_idempotent_and_immutable(tmp_path):
    path = tmp_path / "final_holdout_manifest.json"
    payload = {
        "split": "FINAL_HOLDOUT",
        "sealed": True,
        "inspection_policy": {
            "action_level_inspected": False,
            "replay_regret_executed": False,
        },
        "episodes": [{"episode_id": EPISODE_ID}],
    }
    assert freezer.write_frozen_manifest(path, payload) == "written"
    assert freezer.write_frozen_manifest(path, payload) == "unchanged"
    frozen = json.loads(path.read_text(encoding="utf-8"))
    assert freezer.verify_manifest_digest(frozen)
    with pytest.raises(freezer.FreezeError, match="refusing to overwrite"):
        freezer.write_frozen_manifest(path, {**payload, "episodes": []})


def test_default_cli_is_offline_and_does_not_refresh_metadata():
    args = freezer.parse_args([])
    assert args.acquire is False
    assert args.refresh_metadata is False
    source = Path(freezer.__file__).read_text(encoding="utf-8")
    assert "evaluate_dipplin_replay_regret" not in source


def test_access_token_accepts_cli_export_form(monkeypatch):
    monkeypatch.delenv("KAGGLE_API_TOKEN", raising=False)
    runner = lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0,
        stdout="export KAGGLE_API_TOKEN='secret-token'\n",
        stderr="",
    )
    assert freezer.access_token(runner) == "secret-token"
