import json
import glob
for f in sorted(glob.glob("eval_authentic100_*.json")):
    name = f.replace("eval_authentic100_", "").replace(".json", "")
    d = json.load(open(f))
    f_res = d.get("first_player_results_a", {})
    first = f_res.get("first", {})
    second = f_res.get("second", {})
    print(f"--- {name} ---")
    print(f"First : {first.get('wins',0)}/{first.get('games',0)} ({first.get('win_rate',0):.3f})")
    print(f"Second: {second.get('wins',0)}/{second.get('games',0)} ({second.get('win_rate',0):.3f})")
