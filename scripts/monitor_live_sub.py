#!/usr/bin/env python3
"""Poll ListEpisodes (SAFE endpoint) for a submission and log its ladder trajectory."""
from __future__ import annotations

import base64
import json
import ssl
import sys
import urllib.request
from pathlib import Path

EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"


def auth_header() -> str:
    blob = json.loads((Path.home() / ".kaggle" / "kaggle.json").read_text())
    if "access_token" in blob:
        return "Bearer " + blob["access_token"]
    pair = f"{blob['username']}:{blob['key']}".encode()
    return "Basic " + base64.b64encode(pair).decode()


def fetch(submission_id: int) -> list[dict]:
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        EPISODE_SERVICE,
        data=json.dumps({"submissionId": submission_id}).encode(),
        headers={"Content-Type": "application/json", "Authorization": auth_header()},
    )
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        return json.load(resp).get("episodes", [])


def main() -> int:
    sub = int(sys.argv[1])
    eps = fetch(sub)
    done = [e for e in eps if e.get("state") == "COMPLETED"]
    public = [e for e in done if e.get("type") == "EPISODE_TYPE_PUBLIC"]
    wins = 0
    losses = 0
    for e in public:
        me = next((a for a in e["agents"] if a.get("submissionId") == sub), None)
        r = me.get("reward") if me else None
        if r == 1:
            wins += 1
        elif r == -1:
            losses += 1
    draws = len(public) - wins - losses
    print(f"{sub}: {len(public)} rated ({wins}W {losses}L {draws}D)")
    for e in public:
        me = next((a for a in e["agents"] if a.get("submissionId") == sub), None)
        opp = next((a for a in e["agents"] if a.get("submissionId") != sub), None)
        r = me.get("reward") if me else None
        res = "W" if r == 1 else "L" if r == -1 else "D"
        print(f"  ep{e['id']} {res} opp_rtg={opp.get('initialScore') if opp else '?'} "
              f"score_before={me.get('initialScore') if me else '?'} score_after={me.get('updatedScore') if me else '?'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
