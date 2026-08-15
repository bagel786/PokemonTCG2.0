import base64
import concurrent.futures
import json
import os
import ssl
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
KAGGLE = "/Users/safiullahbaig/Library/Python/3.11/bin/kaggle"
EPISODE_SERVICE = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"

def auth_header() -> str:
    blob = json.loads((Path.home() / ".kaggle" / "kaggle.json").read_text())
    if "access_token" in blob:
        return "Bearer " + blob["access_token"]
    u = blob["username"]
    k = blob["key"]
    pair = f"{u}:{k}".encode()
    return "Basic " + base64.b64encode(pair).decode()

def fetch_episodes(submission_id: int) -> list[dict]:
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        EPISODE_SERVICE,
        data=json.dumps({"submissionId": submission_id}).encode(),
        headers={"Content-Type": "application/json", "Authorization": auth_header()},
    )
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        return json.load(resp).get("episodes", [])

def download_one(ep_id: int, output_dir: Path) -> tuple[int, str]:
    target_file = output_dir / f"{ep_id}.json"
    if target_file.exists() and target_file.stat().st_size > 0:
        return ep_id, "cached"
    command = [KAGGLE, "competitions", "replay", str(ep_id), "-p", str(output_dir)]
    for attempt in range(3):
        res = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if target_file.exists() and target_file.stat().st_size > 0:
            return ep_id, "downloaded"
        time.sleep(1.0 * (attempt + 1))
    return ep_id, "failed"

def main():
    subs = [55358291, 55358290, 55335500, 55323437]
    for sub in subs:
        print(f"Fetching episodes for {sub}...")
        eps = fetch_episodes(sub)
        out_dir = ROOT / "data" / "replays" / str(sub)
        out_dir.mkdir(parents=True, exist_ok=True)
        meta_path = out_dir / "episodes_metadata.json"
        meta_path.write_text(json.dumps(eps))
        
        ep_ids = [e["id"] for e in eps]
        print(f"Found {len(ep_ids)} episodes. Downloading...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futs = [executor.submit(download_one, ep_id, out_dir) for ep_id in ep_ids]
            for f in concurrent.futures.as_completed(futs):
                ep_id, status = f.result()
                if status == "failed":
                    print(f"Failed to download {ep_id}")
                    
        print(f"Finished {sub}")

if __name__ == "__main__":
    main()
