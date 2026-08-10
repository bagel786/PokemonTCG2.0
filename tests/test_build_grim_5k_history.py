from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import build_grim_5k_history as history


def submission(submission_id: int, position: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        ref=submission_id,
        description=f"listed-{position}",
        date=f"2026-08-{position:02d}",
        public_score=800 + position,
        status="complete",
    )


def episode(submission_id: int, episode_id: int, *, seat: int = 1) -> SimpleNamespace:
    hero = SimpleNamespace(
        submission_id=submission_id,
        index=seat,
        reward=1,
        state="COMPLETE",
        initial_score=None,
        updated_score=None,
        team_name="grim",
    )
    opponent = SimpleNamespace(
        submission_id=42,
        index=1 - seat,
        reward=-1,
        state="COMPLETE",
        initial_score=None,
        updated_score=None,
        team_name="opponent",
    )
    agents = [opponent, hero] if seat == 1 else [hero, opponent]
    return SimpleNamespace(id=episode_id, create_time="2026-08-01", agents=agents)


def write_replay(path: Path, expected: tuple[int, ...], *, seat: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    opponent_deck = list(range(101, 161))
    decks = [opponent_deck, list(expected)] if seat == 1 else [list(expected), opponent_deck]
    payload = {
        "steps": [[
            {
                "action": decks[index],
                "observation": {"current": {"firstPlayer": 0}},
            }
            for index in range(2)
        ]]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class FakeApi:
    def __init__(self, submissions, episodes_by_submission, *, replay_error: Exception | None = None):
        self.submissions = list(submissions)
        self.episodes_by_submission = dict(episodes_by_submission)
        self.replay_error = replay_error
        self.episode_calls: list[int] = []
        self.replay_calls: list[int] = []

    def competition_submissions(self, competition, page_size=100):
        assert competition == history.COMPETITION
        assert page_size == 100
        return self.submissions

    def competition_list_episodes(self, submission_id):
        self.episode_calls.append(int(submission_id))
        return self.episodes_by_submission.get(int(submission_id), [])

    def competition_episode_replay(self, episode_id, path, quiet=True):
        self.replay_calls.append(int(episode_id))
        if self.replay_error is not None:
            raise self.replay_error
        raise AssertionError("test expected the immutable local replay cache to be reused")


def test_explicit_recovery_queries_every_unlisted_lineage_id_and_reuses_cache(tmp_path: Path) -> None:
    expected = tuple(range(1, 61))
    hash_proven = sorted(history.HASH_PROVEN_D842)
    documented = sorted(history.D842_LINEAGE - history.HASH_PROVEN_D842)
    # Reproduce the API shape that motivated recovery: only 15 rows are returned,
    # including the three recent hash-proven controls but none of the 12 older IDs.
    listed = [submission(submission_id, index + 1) for index, submission_id in enumerate(hash_proven)]
    listed.extend(submission(99_000_000 + index, index + 4) for index in range(12))
    assert len(listed) == 15
    recovered_id = documented[0]
    episode_id = 777
    episodes = {recovered_id: [episode(recovered_id, episode_id)]}
    api = FakeApi(listed, episodes)

    cached = tmp_path / "replays" / str(recovered_id) / f"episode-{episode_id}-replay.json"
    write_replay(cached, expected)
    manifest = history.build_history(
        api,
        recent_submissions=35,
        workers=2,
        scope="d842-lineage",
        output=tmp_path,
        recover_missing_lineage=True,
        expected=expected,
        sleep=lambda _seconds: None,
    )

    assert set(api.episode_calls) == set(history.D842_LINEAGE)
    assert len(api.episode_calls) == len(history.D842_LINEAGE)
    assert api.replay_calls == []
    assert manifest["recent_submission_count_requested"] == 35
    assert manifest["recent_submission_count_returned"] == 15
    assert manifest["recovered_lineage_submission_ids"] == documented
    by_id = {row["submission_id"]: row for row in manifest["submissions"]}
    recovered = by_id[recovered_id]
    assert recovered["position"] is None
    assert recovered["description"] is None
    assert recovered["date"] is None
    assert recovered["public_score"] is None
    assert recovered["status"] is None
    assert recovered["submission_listing_metadata"]["status"] == "unavailable"
    assert recovered["policy_lineage"] == "frozen_d842_documented"
    assert recovered["behavior_parity_promotion"] == {
        "status": "pending_replay_reexecution",
        "promoted": False,
        "promotion_target": "frozen_d842_behavior_parity_proven",
        "reference_model_sha256": history.FROZEN_D842_MODEL_SHA256,
        "required_evidence": {
            "method": "sterile_replay_reexecution",
            "comparison": "complete_legal_action_digest",
            "require_all_decisions_equal": True,
        },
        "evidence": None,
    }
    assert recovered["deck_class"] == "exact_original_grim"
    assert recovered["episodes"][0]["replay"].endswith(f"episode-{episode_id}-replay.json")
    # Documentation never gets silently upgraded to archive/model hash proof.
    assert all(
        by_id[submission_id]["policy_lineage"] == "frozen_d842_documented"
        for submission_id in documented
    )
    partial = json.loads((tmp_path / "manifest.partial.json").read_text(encoding="utf-8"))
    assert partial["pending_submission_ids"] == []
    assert partial["processed_submission_ids"] == partial["planned_submission_ids"]


def test_replay_429_fails_fast_but_finishes_explicit_episode_inventory(tmp_path: Path) -> None:
    expected = tuple(range(1, 61))
    first = min(history.HASH_PROVEN_D842)
    api = FakeApi(
        [submission(first)],
        {first: [episode(first, 888)]},
        replay_error=RuntimeError("HTTP 429 Too Many Requests"),
    )
    manifest = history.build_history(
        api,
        recent_submissions=35,
        workers=1,
        scope="d842-lineage",
        output=tmp_path,
        recover_missing_lineage=True,
        expected=expected,
        sleep=lambda _seconds: pytest.fail("HTTP 429 must not sleep/retry"),
    )

    assert api.replay_calls == [888]
    assert set(api.episode_calls) == set(history.D842_LINEAGE)
    assert len(api.episode_calls) == len(history.D842_LINEAGE)
    assert manifest["passed"] is False
    assert manifest["download_errors"][0]["retryable"] is True
    partial = json.loads((tmp_path / "manifest.partial.json").read_text(encoding="utf-8"))
    assert partial["replay_rate_limited"] is True
    assert partial["pending_submission_ids"] == []
    assert any(row["deck_class"] == "pending_replay_probe" for row in partial["submissions"])


def test_non_quota_failures_back_off_but_quota_failure_is_sticky() -> None:
    calls = 0
    sleeps: list[float] = []
    event = threading.Event()

    def transient():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise OSError("temporary")
        return "ok"

    assert history.call_with_backoff(
        transient,
        label="transient",
        rate_limited=event,
        sleep=sleeps.append,
    ) == "ok"
    assert calls == 3
    assert sleeps == [1, 2]

    quota_calls = 0

    def quota():
        nonlocal quota_calls
        quota_calls += 1
        raise RuntimeError("429")

    with pytest.raises(history.ReplayRateLimited):
        history.call_with_backoff(quota, label="quota", rate_limited=event, sleep=sleeps.append)
    with pytest.raises(history.ReplayRateLimited):
        history.call_with_backoff(quota, label="quota", rate_limited=event, sleep=sleeps.append)
    assert quota_calls == 1

