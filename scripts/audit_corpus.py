import gzip
import json

path = "trace_rl_pilot/rollouts.jsonl.gz"

episode_ids = set()
seeds = set()
wins = 0
losses = 0
draws = 0
total_rows = 0
duplicates = 0
seen_rows = set()
ep_rewards = {}

with gzip.open(path, "rt") as f:
    for line in f:
        row = json.loads(line)
        total_rows += 1
        
        ep_id = row.get("episode_id", "unknown")
        reward = row.get("terminal_reward", 0)
        
        row_str = json.dumps({k:v for k,v in row.items() if k != "old_logprob"})
        if row_str in seen_rows:
            duplicates += 1
        seen_rows.add(row_str)
        
        episode_ids.add(ep_id)
        if ep_id not in ep_rewards:
            ep_rewards[ep_id] = reward

for r in ep_rewards.values():
    if r > 0: wins += 1
    elif r < 0: losses += 1
    else: draws += 1

print(f"Total rows: {total_rows}")
print(f"Unique episode IDs: {len(episode_ids)}")
print(f"Unique seeds: N/A (not recorded in rows)")
print(f"Wins: {wins}")
print(f"Losses: {losses}")
print(f"Draws: {draws}")
print(f"Exact duplicate row count: {duplicates}")
