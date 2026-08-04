import json
import os
import collections

episodes_path = "artifacts/ladder_55149662/episodes.json"
with open(episodes_path) as f:
    episodes = json.load(f)

lost_episodes = [ep for ep in episodes if not ep["won"]]

print(f"Found {len(lost_episodes)} total lost games.")

status_counts = collections.defaultdict(int)

for ep in lost_episodes:
    ep_id = ep["episode"]
    replay_path = f"data/replays/55149662/episode-{ep_id}-replay.json"
    if not os.path.exists(replay_path):
        continue
        
    with open(replay_path) as f:
        data = json.load(f)
        
    statuses = data.get("statuses", [])
    # Find our index
    info = data.get("info", {})
    team_names = info.get("TeamNames", [])
    our_index = -1
    for i, name in enumerate(team_names):
        if "55149662" in name or name.isdigit():
            # The name is just "55149662" or "poyothon" ?
            pass
            
    # actually the easiest way is to look at the first step
    # or just look if any status is not DONE
    for s in statuses:
        status_counts[s] += 1
        
print("Statuses of all agents in lost games:", dict(status_counts))
