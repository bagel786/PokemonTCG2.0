import json

from scripts.monitor_wave1_live import ReplayFetchBackoff, enrich_replays, is_http_rate_limit


class FakeClock:
    def __init__(self, value=10_000.0):
        self.value = float(value)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += float(seconds)


class RateLimitedApi:
    def __init__(self):
        self.calls = []

    def competition_episode_replay(self, episode_id, **_kwargs):
        self.calls.append(episode_id)
        raise RuntimeError("HTTP 429 Too Many Requests")


def test_replay_fetch_backoff_is_global_across_games(tmp_path):
    clock = FakeClock()
    backoff = ReplayFetchBackoff(base_seconds=60, maximum_seconds=240, clock=clock)
    api = RateLimitedApi()
    games = [
        {"episode_id": 101, "seat": 0},
        {"episode_id": 102, "seat": 0},
    ]

    enrich_replays(api, 55, games, tmp_path, {}, backoff)

    assert api.calls == [101]
    assert all("global HTTP-429 cooldown" in game["replay_pending"] for game in games)
    assert backoff.blocked
    assert backoff.consecutive_rate_limits == 1

    # A later submission in the same four-minute observation shares the
    # breaker and therefore makes no request at all.
    later_games = [{"episode_id": 201, "seat": 1}]
    enrich_replays(api, 56, later_games, tmp_path, {}, backoff)
    assert api.calls == [101]
    assert "global HTTP-429 cooldown" in later_games[0]["replay_pending"]


def test_replay_fetch_backoff_persists_across_watcher_restart(tmp_path):
    clock = FakeClock()
    path = tmp_path / "replay_fetch_backoff.json"
    original = ReplayFetchBackoff(clock=clock)
    original.record_rate_limit(RuntimeError("status=429"))
    original.save(path)

    restored = ReplayFetchBackoff.load(path, clock=clock)
    assert restored.blocked
    assert restored.consecutive_rate_limits == 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["blocked_until_unix"] == restored.blocked_until_unix

    clock.advance(1_801)
    assert not restored.blocked


def test_rate_limit_detection_accepts_kaggle_style_status():
    class KaggleError(Exception):
        status = 429

    assert is_http_rate_limit(KaggleError("Too Many Requests"))
    assert is_http_rate_limit(RuntimeError("HTTP Error 429: Too Many Requests"))
    assert not is_http_rate_limit(RuntimeError("temporary connection failure"))
