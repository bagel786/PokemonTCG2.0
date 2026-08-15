# Kaggle API Rate Limits — Memory File

**Last updated: 2026-08-14 (~20:00 local). Read this before ANY script that touches the Kaggle API.**

## The incident

On 2026-08-14 the replay-download endpoint was exhausted and stayed blocked for hours.

- `GetEpisodeReplay` returned `429 RESOURCE_EXHAUSTED` with `Retry-After: 16725` (~4h39m) at ~19:50 local. First request in the batch was already 429 — the bucket was gone before this session tried.
- Consequence: loss/archetype analysis for subs 55513649, 55513642, 55491471, 55491464 was blocked all evening. Reset ~00:30 local.

## Who exhausted it

Cannot be pinned to one process with certainty, but the evidence:

- `data/replays/55491464/episode-*-replay.json` — 8 files, mtime 16:16 local (successful replay downloads today).
- `data/meta/replay_progress.json` — mtime 16:12, built by a crawler that maps teamId -> decks (no repo script references this file; it was an external session).
- Metadata refreshes for 55171235/55171237/55180215/55180261 at 19:02-19:03 (ListEpisodes, safe endpoint).
- `~/.zsh_history` has zero `competitions replay` entries -> downloads came from a non-interactive session (opencode/pipeline), not a manual shell.

Suspect pattern: a replay-crawling session that hammers `kaggle competitions replay` per episode with tight retry loops. `scripts/fetch_4_recent.py` does exactly this (3 retries, 1-3s sleeps, no Retry-After handling, imports `concurrent.futures`). Do not run it, or any of the ~29 scripts that call the replay endpoint, without reading this file.

## What is and isn't rate limited (empirical, 2026-08-14)

| Endpoint | Status |
|---|---|
| `competitions.EpisodeService/ListEpisodes` (episode metadata) | SAFE. 15+ calls today, zero 429s. |
| `api.kaggle.com/v1/competitions.CompetitionApiService/GetEpisodeReplay` | STRICTLY LIMITED. Quota exhausted for hours after heavy use. |
| Kaggle datasets API (`kaggle datasets download <daily-episode-dataset>`) | SEPARATE bucket. Bulk archive = 1 request. This is the quota-safe path for full replay data. |
| Public leaderboard CSV | Public GET, fine. |

## Rules — never screw this up again

1. **Never** download per-episode replays via `GetEpisodeReplay` in a loop unless:
   - `scripts/fetch_replays_honor_retry.py` is used (honors Retry-After, paces 6s, skips existing files), AND
   - the batch is small (<= 30) or spread over hours.
2. **Honor `Retry-After` on 429.** Stop the whole run on the FIRST 429. Sleep the full amount (or reschedule). Never retry into a 429 (each probe can extend the window). Never use 1-3s retry loops (see `fetch_4_recent.py` as the anti-pattern).
3. **Prefer the official daily episode datasets** for any bulk replay need:
   `python scripts/fetch_public_data.py --date 2026-08-13 --limit 0`
   One bulk request downloads the whole public day dump (~700MB). Extract, then read the episode files by ID from disk. Zero `GetEpisodeReplay` calls.
   - Daily datasets publish the next day ~00:05 UTC (e.g. the 2026-08-14 dump appeared ~00:17 UTC on 08-15). The index dataset (`kaggle/pokemon-tcg-ai-battle-episodes-index`) maps episode ID -> dataset.
4. **Cache episode metadata locally first.** ListEpisodes is safe; always persist to `data/replays/<sub_id>/episodes_metadata.json` before any replay work, so analysis can proceed offline even if replay downloads are blocked.
5. **Idempotency:** always check the target file exists before requesting (the honor-retry script does this). Re-runs must not re-request what is cached.
6. **Estimate quota before big jobs:** ~200+ episodes in one session is exactly what exhausts the replay endpoint. If you need that much, use the daily dataset (rule 3), not the replay API.
7. When a 429 happens, write down: time, endpoint, `Retry-After` value, computed reset time — and do not re-probe before the reset.

## Current status / pending work

- Blocked until ~00:30 local 2026-08-15: per-episode replay downloads.
- Unblocked now (safe): ListEpisodes metadata (already cached for all 4 live subs), daily dataset bulk downloads, leaderboard CSVs.
- Pending: resume replay downloads after reset via `scripts/download_replays_4subs.py` (skips cached), or skip it entirely and mine the 08-13/08-14 daily dumps for the same episodes.
