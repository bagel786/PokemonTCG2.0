#!/usr/bin/env python3
"""Survey what decks the top-N leaderboard teams actually run.

Fully dynamic, nothing read from local corpora:
  1. kaggle competitions leaderboard -d            -> rank, teamId, teamName, score
  2. /competitions/teams/{teamId}/public-submissions -> that team's live submission id
  3. EpisodeService/ListEpisodes {submissionId}    -> its episode ids + seat/team mapping
  4. kaggle competitions replay <ep>               -> streamed through a temp dir, parsed,
                                                      deleted immediately (nothing persists)

    python3 scripts/survey_top_teams.py --top 300 --games-per-team 3

Writes two JSON reports to --out: per-team archetypes and the most-played unique decklists.
"""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import json
import random
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.request
import zipfile
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMP = "pokemon-tcg-ai-battle"
KAGGLE = shutil.which("kaggle") or "/Users/safiullahbaig/Library/Python/3.11/bin/kaggle"
API = "https://api.kaggle.com/v1"
LIST_EPISODES = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"
CARD_CSV = ROOT / "freshstart" / "data" / "EN_Card_Data.csv"
SSL_CTX = ssl._create_unverified_context()

# ---------------------------------------------------------------- card data


def load_cards() -> tuple[dict, dict, dict, dict]:
    name, stage, prev, hp = {}, {}, {}, {}
    for row in csv.DictReader(CARD_CSV.read_text(encoding="utf-8-sig").splitlines()):
        cid = int(row["Card ID"])
        name[cid] = row["Card Name"]
        stage[cid] = row["Stage (Pokémon)/Type (Energy and Trainer)"]
        prev[cid] = row["Previous stage"]
        hp[cid] = int(row["HP"]) if row["HP"].isdigit() else 0
    return name, stage, prev, hp


NAME, STAGE, PREV, HP = load_cards()
SR = {"Basic Pokémon": 0, "Stage 1 Pokémon": 1, "Stage 2 Pokémon": 2}
BY_NAME: dict[str, list[int]] = defaultdict(list)
for _cid, _n in NAME.items():
    BY_NAME[_n].append(_cid)


def family_root(cid: int, depth: int = 0) -> str:
    """Walk Previous stage back to the basic, so Dwebble and Crustle count as one line."""
    p = PREV.get(cid, "n/a")
    if p in ("n/a", "", None) or depth > 3 or p not in BY_NAME:
        return NAME[cid]
    return family_root(BY_NAME[p][0], depth + 1)


def archetype(deck: list[int]) -> str:
    """Name a decklist by its two biggest evolution families."""
    counts = Counter(deck)
    fam: dict[str, list] = defaultdict(lambda: [0, None, -1, -1])  # copies, name, stage, hp
    for cid, n in counts.items():
        if STAGE.get(cid) not in SR:
            continue
        f = fam[family_root(cid)]
        f[0] += n
        if (SR[STAGE[cid]], HP[cid]) > (f[2], f[3]):
            f[1], f[2], f[3] = NAME[cid], SR[STAGE[cid]], HP[cid]
    if not fam:
        return "unknown"
    order = sorted(fam.values(), key=lambda v: (-v[0], -v[2], -v[3]))
    return " / ".join(v[1] for v in order[:2])


# ---------------------------------------------------------------- kaggle api


def auth_header() -> str:
    """credentials.json holds the token the CLI keeps refreshed; kaggle.json goes stale."""
    for fname in ("credentials.json", "kaggle.json"):
        path = Path.home() / ".kaggle" / fname
        if not path.exists():
            continue
        blob = json.loads(path.read_text())
        if "access_token" in blob:
            exp = blob.get("access_token_expiration", "")
            if exp and exp < time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()):
                continue  # expired, try the next file
            return "Bearer " + blob["access_token"]
        if "key" in blob:
            return "Basic " + base64.b64encode(f"{blob['username']}:{blob['key']}".encode()).decode()
    raise SystemExit("no usable kaggle credentials; run `kaggle competitions list` to refresh")


AUTH = auth_header()


_RATE_LOCK = threading.Lock()
_LAST_CALL = [0.0]
MIN_INTERVAL = 0.8  # seconds between API calls, process-wide; set from --api-interval
COOLDOWN = 300.0    # seconds to wait out a 429 window; set from --limit-cooldown


def _throttle() -> None:
    """Kaggle 429s aggressively and the retry budget cannot outrun it — pace globally."""
    with _RATE_LOCK:
        wait = MIN_INTERVAL - (time.time() - _LAST_CALL[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[0] = time.time()


def _request(url: str, payload: dict | None = None, tries: int = 8) -> bytes:
    for attempt in range(tries):
        _throttle()
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json", "Authorization": AUTH,
                     "Accept-Encoding": "gzip"},
        )
        try:
            with urllib.request.urlopen(req, timeout=45, context=SSL_CTX) as resp:
                raw = resp.read()
                return gzip.decompress(raw) if resp.headers.get("Content-Encoding") == "gzip" else raw
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503) or attempt == tries - 1:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            hinted = float(retry_after) if retry_after and retry_after.isdigit() else 0.0
            if exc.code == 429:
                # Kaggle's Retry-After is optimistic: obeying it literally burns every
                # retry inside a window that is actually minutes long. Treat it as a floor.
                delay = max(hinted, COOLDOWN)
            else:
                delay = max(hinted, min(2 ** attempt, 30))
            time.sleep(delay + random.random())
    raise RuntimeError("unreachable")


def _kaggle_cli(cmd: list[str], tries: int = 6) -> subprocess.CompletedProcess:
    """The CLI hits the same 429 budget as the raw API, so pace and retry it too."""
    for attempt in range(tries):
        _throttle()
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return res
        if "429" not in (res.stdout + res.stderr) or attempt == tries - 1:
            return res
        time.sleep(COOLDOWN + random.random())
    return res


def leaderboard(top: int) -> list[dict]:
    """Live public leaderboard, rank-ordered."""
    with tempfile.TemporaryDirectory() as tmp:
        res = _kaggle_cli([KAGGLE, "competitions", "leaderboard", COMP, "-d", "-p", tmp, "-q"])
        if res.returncode != 0:
            raise SystemExit(f"leaderboard download failed: {(res.stdout + res.stderr).strip()[:200]}")
        zips = list(Path(tmp).glob("*.zip"))
        if zips:
            with zipfile.ZipFile(zips[0]) as z:
                text = z.read(z.namelist()[0]).decode("utf-8-sig")
        else:
            text = next(Path(tmp).glob("*.csv")).read_text(encoding="utf-8-sig")
    rows = sorted(csv.DictReader(text.splitlines()), key=lambda r: int(r["Rank"]))
    return rows[:top]


def team_submissions(team_id: int) -> list[dict]:
    return json.loads(_request(f"{API}/competitions/teams/{team_id}/public-submissions"))


def list_episodes(submission_id: int) -> dict:
    """One call returns this submission's episodes AND ~60 teams with their submission ids."""
    return json.loads(_request(LIST_EPISODES, {"submissionId": submission_id}))


def crawl(targets: dict, seeds: list[int], budget: int, log, stall: int = 12,
          save=None, state: tuple[dict, dict] | None = None,
          need_per_team: int = 1) -> tuple[dict, dict]:
    """Snowball ListEpisodes to map teamId -> submissionId and pool episodes in one pass.

    Cheaper than one lookup per team: each reply carries ~60 teams, and top teams mostly
    play each other, so the top of the ladder closes over itself in a few dozen calls.
    Stops on `stall` consecutive calls that resolve nobody new — the tail of the queue
    costs the same rate-limit budget as the productive head but buys almost nothing.
    """
    team_to_sub, ep_agents = state or ({}, {})
    seen: set[int] = set()
    queue: deque[int] = deque(seeds)
    dry = 0
    sub_owner: dict[int, int] = {}       # submissionId -> teamId that owns it
    from_leaderboard: set[int] = set()   # teams whose sub id came from the leaderboard
    pooled_for: Counter = Counter()      # teamId -> episodes already pooled for it
    for _, agents in ep_agents.values():
        for agent in agents:
            if agent.get("teamId") in targets:
                pooled_for[agent["teamId"]] += 1
    while queue and len(seen) < budget and len(team_to_sub) < len(targets):
        if dry >= stall:
            log(f"      stopping crawl: {stall} calls with no new team "
                f"({len(team_to_sub)}/{len(targets)} resolved)")
            break
        sub = queue.popleft()
        if sub in seen:
            continue
        # Skip teams the pool already covers: their games are in hand, so calling their
        # submission buys nothing and each call costs the same rate-limit budget.
        owner = sub_owner.get(sub)
        if owner is not None and pooled_for.get(owner, 0) >= need_per_team:
            continue
        seen.add(sub)
        before = len(team_to_sub)
        try:
            payload = list_episodes(sub)
        except Exception as exc:  # noqa: BLE001 - a dead submission must not stop the crawl
            log(f"      ListEpisodes({sub}) failed: {str(exc)[:60]}")
            continue
        # Leaderboard submission first: an agent id seen in some old episode may be a
        # retired submission, and we want the deck the team is running now.
        for team in payload.get("teams", []):
            tid, psid = team.get("id"), team.get("publicLeaderboardSubmissionId")
            if tid not in targets or not psid:
                continue
            sub_owner[psid] = tid
            if tid not in team_to_sub or tid not in from_leaderboard:
                # A submission id scraped off an old episode may be a retired agent;
                # the leaderboard id is authoritative, so upgrade to it when we see it.
                if team_to_sub.get(tid) != psid:
                    team_to_sub[tid] = psid
                    queue.append(psid)
                from_leaderboard.add(tid)
        for ep in payload.get("episodes", []):
            fresh = ep["id"] not in ep_agents
            ep_agents.setdefault(ep["id"], (ep.get("createTime", ""), ep.get("agents", [])))
            for agent in ep.get("agents", []):
                tid, sid = agent.get("teamId"), agent.get("submissionId")
                if tid not in targets:
                    continue
                if sid:
                    sub_owner[sid] = tid
                if fresh:
                    pooled_for[tid] += 1
                if sid and tid not in team_to_sub:
                    team_to_sub[tid] = sid
                    queue.append(sid)
        dry = 0 if len(team_to_sub) > before else dry + 1
        log(f"      call {len(seen)}: {len(team_to_sub)}/{len(targets)} teams · "
            f"{len(ep_agents)} episodes · {len(queue)} queued")
        if save and len(seen) % 10 == 0:  # survive a kill without redoing the crawl
            save(team_to_sub, ep_agents)
    if save:
        save(team_to_sub, ep_agents)
    return team_to_sub, ep_agents


def fetch_replay(episode_id: int) -> dict | None:
    """Download into a temp dir, parse, drop the file. Peak disk = workers x ~4MB."""
    with tempfile.TemporaryDirectory() as tmp:
        res = _kaggle_cli([KAGGLE, "competitions", "replay", str(episode_id), "-p", tmp, "-q"], tries=3)
        files = list(Path(tmp).glob("*.json"))
        if res.returncode != 0 or not files:
            return None
        try:
            return json.loads(files[0].read_text())
        except json.JSONDecodeError:
            return None


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=300)
    ap.add_argument("--games-per-team", type=int, default=3)
    ap.add_argument("--workers", type=int, default=8, help="replay download threads")
    ap.add_argument("--api-interval", type=float, default=1.5,
                    help="min seconds between Kaggle API calls, process-wide")
    ap.add_argument("--crawl-budget", type=int, default=200, help="max ListEpisodes calls")
    ap.add_argument("--crawl-stall", type=int, default=12,
                    help="stop crawling after this many calls resolve no new team")
    ap.add_argument("--cache-floor", type=float, default=0.95,
                    help="skip the crawl when the cache already covers this fraction of teams")
    ap.add_argument("--limit-cooldown", type=float, default=300.0,
                    help="seconds to wait out a 429 window before retrying")
    ap.add_argument("--seed-submission", type=int, action="append", default=[],
                    help="submission id to start the crawl from (repeatable)")
    ap.add_argument("--top-decks", type=int, default=30)
    ap.add_argument("--api-parallel", type=int, default=4,
                    help="concurrent gap-fill lookups; request starts stay globally paced")
    ap.add_argument("--report-only", action="store_true",
                    help="rebuild reports from checkpoints without downloading any replay")
    ap.add_argument("--skip-gapfill", action="store_true",
                    help="don't look up teams the crawl missed; use pooled episodes only")
    ap.add_argument("--bands", default="50,150,200,300",
                    help="cumulative rank bands to break the meta down by")
    ap.add_argument("--out", default="data/meta")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    global MIN_INTERVAL, COOLDOWN
    MIN_INTERVAL = args.api_interval
    COOLDOWN = args.limit_cooldown

    def log(msg: str) -> None:
        print(msg, flush=True)

    log(f"[1/4] leaderboard: top {args.top}")
    board = leaderboard(args.top)
    targets = {int(r["TeamId"]): {"rank": int(r["Rank"]), "name": r["TeamName"],
                                  "score": float(r["Score"])} for r in board}
    log(f"      {len(targets)} teams · #1 {board[0]['TeamName']} ({board[0]['Score']})")

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    cache_path = out / "crawl_cache.json"
    cached_teams: dict[int, int] = {}
    cached_eps: dict[int, tuple] = {}
    if cache_path.exists():
        blob = json.loads(cache_path.read_text())
        # Ranks shift between runs, so a cached team may have dropped out of the top N.
        cached_teams = {int(k): v for k, v in blob.get("team_to_sub", {}).items()}
        cached_eps = {int(k): (v[0], v[1]) for k, v in blob.get("episodes", {}).items()}

    def save_crawl(team_to_sub: dict, ep_agents: dict) -> None:
        cache_path.write_text(json.dumps({
            "team_to_sub": {str(k): v for k, v in team_to_sub.items()},
            "episodes": {str(k): [v[0], v[1]] for k, v in ep_agents.items()},
        }))

    lock = threading.Lock()
    covered = {t for t in targets if t in cached_teams}
    if len(covered) >= len(targets) * args.cache_floor and cached_eps:
        log(f"[2/4] reusing cached crawl: {len(covered)}/{len(targets)} teams · "
            f"{len(cached_eps)} episodes (no API calls)")
        team_to_sub, ep_agents = dict(cached_teams), dict(cached_eps)
    else:
        seeds = args.seed_submission or [
            int(p.name) for p in (ROOT / "data" / "replays").glob("*") if p.name.isdigit()
        ]
        if not seeds:
            log("      no seed submission to crawl from; pass --seed-submission <id>")
            return 1
        log(f"[2/4] crawling ListEpisodes from {len(seeds)} seed(s), "
            f"budget {args.crawl_budget} calls")
        team_to_sub, ep_agents = crawl(targets, seeds, args.crawl_budget, log,
                                       stall=args.crawl_stall, save=save_crawl,
                                       state=(dict(cached_teams), dict(cached_eps)),
                                       need_per_team=args.games_per_team)
    log(f"      {len(team_to_sub)}/{len(targets)} teams resolved · {len(ep_agents)} episodes pooled")

    # Teams run two active submissions at once and the leaderboard id is not always the
    # stronger one. Episode agents carry the live rating, so pick the best-rated submission
    # per team from data already in hand -- no extra API calls.
    sub_rating: dict[int, tuple[str, float]] = {}   # submissionId -> (latest episode time, score)
    sub_team: dict[int, int] = {}
    for created, agents in ep_agents.values():
        for agent in agents:
            sid, tid = agent.get("submissionId"), agent.get("teamId")
            score = agent.get("updatedScore", agent.get("initialScore"))
            if not sid or tid not in targets or score is None:
                continue
            sub_team[sid] = tid
            if sid not in sub_rating or created > sub_rating[sid][0]:
                sub_rating[sid] = (created, float(score))

    best_sub: dict[int, int] = {}
    for sid, (_, score) in sub_rating.items():
        tid = sub_team[sid]
        if tid not in best_sub or score > sub_rating[best_sub[tid]][1]:
            best_sub[tid] = sid
    upgraded = 0
    for tid, sid in best_sub.items():
        current = team_to_sub.get(tid)
        current_score = sub_rating.get(current, (None, None))[1]
        if current != sid and (current_score is None or sub_rating[sid][1] > current_score):
            team_to_sub[tid] = sid
            upgraded += 1
    log(f"      picked higher-rated submission for {upgraded} teams "
        f"({len(sub_rating)} submissions rated from episode scores)")

    log("[3/4] filling gaps via per-team submission lookup")
    gaps = [] if args.skip_gapfill else [t for t in targets if t not in team_to_sub]
    if args.skip_gapfill:
        log("      skipped (--skip-gapfill); pooled episodes already cover most teams")
    gap_done = [0]

    def fill(tid: int) -> None:
        """ListEpisodes returns a submission's whole history (multi-MB), so latency, not
        the rate limit, dominates here. Overlap the downloads; _throttle still paces starts."""
        try:
            subs = team_submissions(tid)
        except Exception as exc:  # noqa: BLE001 - one dead team must not kill the run
            log(f"      team {tid} lookup failed: {str(exc)[:60]}")
            return
        if not subs:
            return
        sub = max(subs, key=lambda s: float(s.get("publicScore") or 0))["id"]
        try:
            eps = list_episodes(sub).get("episodes", [])
        except Exception as exc:  # noqa: BLE001
            log(f"      episodes for team {tid} failed: {str(exc)[:60]}")
            eps = []
        with lock:
            team_to_sub[tid] = sub
            for ep in eps:
                ep_agents.setdefault(ep["id"], (ep.get("createTime", ""), ep.get("agents", [])))
            gap_done[0] += 1
            if gap_done[0] % 10 == 0:
                save_crawl(team_to_sub, ep_agents)  # checkpoint: gap-fill is the slow phase
                log(f"      {gap_done[0]}/{len(gaps)} gap teams · {len(ep_agents)} episodes pooled")

    if gaps:
        with ThreadPoolExecutor(max_workers=args.api_parallel) as pool:
            list(pool.map(fill, gaps))
    save_crawl(team_to_sub, ep_agents)
    log(f"      {len(team_to_sub)}/{len(targets)} teams · {len(ep_agents)} distinct episodes")

    # One replay reveals BOTH seats, so prefer episodes where two target teams meet;
    # break ties toward recent games so we report the deck a team runs now.
    need = Counter({tid: args.games_per_team for tid in team_to_sub})
    newest_first = sorted(ep_agents.items(), key=lambda kv: kv[1][0], reverse=True)
    ordered = [(ep_id, agents) for ep_id, (_, agents) in newest_first]
    ordered.sort(key=lambda kv: -sum(1 for a in kv[1] if a.get("teamId") in targets))  # stable

    progress_path = out / "replay_progress.json"
    team_decks: dict[int, Counter] = defaultdict(Counter)
    team_records: dict[int, list] = defaultdict(lambda: [0, 0])
    deck_teams: dict[str, set] = defaultdict(set)
    deck_lists: dict[str, list] = {}
    done = [0]
    relaxed = [False]

    if progress_path.exists():  # resume: replays already parsed are not worth re-fetching
        blob = json.loads(progress_path.read_text())
        for tid_s, archs in blob.get("team_decks", {}).items():
            tid = int(tid_s)
            if tid not in targets:  # dropped out of the top N since the cache was written
                continue
            team_decks[tid] = Counter(archs)
            need[tid] = max(0, args.games_per_team - sum(archs.values()))
        for tid_s, rec in blob.get("team_records", {}).items():
            team_records[int(tid_s)] = rec
        deck_lists.update({k: v for k, v in blob.get("deck_lists", {}).items()})
        for digest, tids in blob.get("deck_teams", {}).items():
            kept = {t for t in tids if t in targets}
            if kept:
                deck_teams[digest] = kept
        log(f"      resuming: {len(team_decks)} teams already covered")

    def save_progress() -> None:
        progress_path.write_text(json.dumps({
            "team_decks": {str(k): dict(v) for k, v in team_decks.items()},
            "team_records": {str(k): v for k, v in team_records.items()},
            "deck_lists": deck_lists,
            "deck_teams": {k: sorted(v) for k, v in deck_teams.items()},
        }))

    def handle(item) -> None:
        ep_id, agents = item
        with lock:
            if not any(need[a["teamId"]] > 0 for a in agents if a.get("teamId") in team_to_sub):
                return
        replay = fetch_replay(ep_id)
        if not replay:
            return
        try:
            step1 = replay["steps"][1]
        except (KeyError, IndexError):
            return
        for agent in agents:
            tid = agent.get("teamId")
            if tid not in targets:
                continue
            # Only count a game played by the team's current (highest-rated) submission,
            # unless we are in the relaxed sweep for teams that had no such episode.
            if not relaxed[0] and agent.get("submissionId") != team_to_sub.get(tid):
                continue
            deck = (step1[agent.get("index", 0)] or {}).get("action") or []
            if len(deck) != 60:
                continue
            sig = sorted(deck)
            digest = hashlib.sha256(json.dumps(sig).encode()).hexdigest()[:12]
            with lock:
                team_decks[tid][archetype(deck)] += 1
                team_records[tid][0 if (agent.get("reward") or 0) > 0 else 1] += 1
                deck_teams[digest].add(tid)
                deck_lists.setdefault(digest, sig)
                need[tid] -= 1
        with lock:
            done[0] += 1
            if done[0] % 25 == 0:
                save_progress()
                log(f"      {done[0]} replays parsed · {len(team_decks)} teams covered")

    if args.report_only:
        log("[4/4] report-only: building reports from replay_progress.json, no downloads")
    else:
        log(f"[4/4] streaming replays (<={args.games_per_team} per team, files deleted on read)")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(handle, ordered))

    stragglers = [] if args.report_only else [
        t for t in team_to_sub if t in targets and not team_decks[t]]
    if stragglers:  # no episode from their current submission — fall back to any game
        log(f"      relaxed sweep for {len(stragglers)} teams with no current-submission game")
        relaxed[0] = True
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(handle, ordered))
    save_progress()

    teams_report = {
        str(tid): {**targets[tid], "submission": team_to_sub.get(tid),
                   "record": f"{team_records[tid][0]}-{team_records[tid][1]}",
                   "archetypes": dict(c.most_common())}
        for tid, c in sorted(team_decks.items(), key=lambda kv: targets[kv[0]]["rank"])
    }
    (out / "top_team_archetypes.json").write_text(
        json.dumps(teams_report, ensure_ascii=False, indent=1))

    ranked = sorted(deck_teams.items(),
                    key=lambda kv: (-len(kv[1]), min(targets[t]["rank"] for t in kv[1])))
    decks_report = []
    for digest, tids in ranked[: args.top_decks]:
        cards = deck_lists[digest]
        by_rank = sorted(tids, key=lambda t: targets[t]["rank"])
        decks_report.append({
            "id": digest,
            "archetype": archetype(cards),
            "teams": len(tids),
            "best_rank": targets[by_rank[0]]["rank"],
            "team_names": [targets[t]["name"] for t in by_rank][:15],
            "cards": [f"{n}x {name}" for name, n in
                      Counter(NAME.get(c, str(c)) for c in cards).most_common()],
            "card_ids": cards,
        })
    (out / "top_decklists.json").write_text(json.dumps(decks_report, ensure_ascii=False, indent=1))

    bands = [int(b) for b in args.bands.split(",")]
    band_report: dict[str, dict] = {}
    for band in bands:
        in_band = [t for t in team_decks if targets[t]["rank"] <= band]
        counts = Counter()
        for tid in in_band:
            for a in team_decks[tid]:
                counts[a] += 1
        band_report[f"top{band}"] = {
            "teams_covered": len(in_band),
            "unique_decklists": len({d for d, ts in deck_teams.items()
                                     if any(targets[t]["rank"] <= band for t in ts)}),
            "archetypes": dict(counts.most_common()),
        }
    (out / "rank_bands.json").write_text(json.dumps(band_report, ensure_ascii=False, indent=1))

    log(f"\ncovered {len(team_decks)}/{len(targets)} teams · {len(deck_teams)} unique decklists")
    header = "".join(f"{'top'+str(b):>12}" for b in bands)
    log(f"\n{'archetype':<44}{header}")
    overall = Counter()
    for c in team_decks.values():
        for a in c:
            overall[a] += 1
    for arch, _ in overall.most_common(25):
        cells = ""
        for band in bands:
            n = band_report[f"top{band}"]["archetypes"].get(arch, 0)
            total = band_report[f"top{band}"]["teams_covered"] or 1
            cells += f"{n:>5} {n/total*100:>5.1f}%"
        log(f"{arch[:43]:<44}{cells}")
    log(f"\n{'teams covered':<44}" + "".join(
        f"{band_report['top'+str(b)]['teams_covered']:>12}" for b in bands))
    log(f"{'unique decklists':<44}" + "".join(
        f"{band_report['top'+str(b)]['unique_decklists']:>12}" for b in bands))
    log(f"\nwrote {out/'top_team_archetypes.json'} and {out/'top_decklists.json'}")
    return 0


def selftest() -> int:
    """Seat attribution and archetype naming must not silently drift."""
    replay = {"steps": [None, [{"action": [93] * 60}, {"action": [7] * 60}]]}
    agents = [{"teamId": 1, "index": 0}, {"teamId": 2, "index": 1}]
    seats = {a["teamId"]: replay["steps"][1][a.get("index", 0)]["action"][0] for a in agents}
    assert seats == {1: 93, 2: 7}, seats
    label = archetype([93] * 4 + [42] * 4 + [7] * 52)
    assert "Dipplin" in label, label
    assert family_root(91) == "Grookey", family_root(91)  # Rillaboom -> Thwackey -> Grookey
    print("selftest ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
