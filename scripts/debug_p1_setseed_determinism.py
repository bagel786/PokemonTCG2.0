import sys, os, json, ctypes
sys.path[:0] = ['scripts', '.', 'vendor']
import generate_p1_causal_labels as gen
from cg.api import to_observation_class, SelectContext, OptionType, SelectType

engine = gen.get_engine()
os.environ['PTCG_GRIM_DAMAGE_SOLVER'] = 'v0'
hero = gen.load_package_policy(gen.R0_PACKAGE, 'policy_first.npz')
fork_policy = gen.load_package_policy(gen.R0_PACKAGE, 'policy_first.npz', cache_tag='fork')
opp = gen.load_package_policy(gen.B0_PACKAGE, 'policy_weights.npz')
hero_deck = [int(l) for l in (gen.R0_PACKAGE / 'deck.csv').read_text().splitlines() if l.strip()]
opp_deck = [int(l) for l in (gen.B0_PACKAGE / 'deck.csv').read_text().splitlines() if l.strip()]
seed = 202608160101
hero_seat = seed % 2
order = 'first'
ptr, raw = engine.start(hero_deck, opp_deck, seed)

harvest_obs = None
forced_oi = None
for step_i in range(80):
    obsd = raw
    cur = obsd.get('current') or {}
    if cur.get('result', -1) is not None and int(cur['result']) >= 0:
        break
    sel = obsd.get('select')
    obs = to_observation_class(obsd)
    acting = int(cur['yourIndex'])
    ctx = int(sel['context'])
    if ctx == int(SelectContext.IS_FIRST):
        want_yes = (order == 'first') == (hero_seat == 0)
        chosen = [j for j, o in enumerate(obs.select.option) if (o.type == OptionType.YES) == want_yes]
        raw = engine.select(ptr, chosen)
        continue
    if acting != hero_seat:
        action = [int(x) for x in opp.choose(obs)]
        raw = engine.select(ptr, action)
        continue
    action = [int(x) for x in hero.choose(obs)]
    if int(sel['type']) == int(SelectType.MAIN) and ctx == int(SelectContext.MAIN):
        play = gen._play_cards(obs)
        active = [i for i in play if play[i] >= 0]
        distinct = sorted({play[i] for i in active})
        if len(distinct) >= 2 and harvest_obs is None:
            harvest_obs = obsd
            forced_oi = active[0]
    raw = engine.select(ptr, action)

from training.search_teacher import determinize_known_matchup
import random as _r
obs = to_observation_class(harvest_obs)
kwargs = dict(determinize_known_matchup(obs, hero_deck, opp_deck, _r.Random(12345)))
lib = engine.lib
lib.SearchSetSeed.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
lib.SearchSetSeed.restype = None


def run_once():
    fork_policy.reset()
    root = engine.search_begin(harvest_obs, **kwargs)
    rid = int(root['searchId'])
    lib.SearchSetSeed(engine.agent_ptr, ctypes.c_uint32(777).value)
    st = engine.search_step(rid, [forced_oi])
    steps = 0
    root_id = int(st['searchId'])
    while steps < 500:
        obsd = st['observation']
        cur = obsd.get('current') or {}
        if cur.get('result', -1) is not None and int(cur['result']) >= 0:
            engine.search_release(root_id)
            return int(cur['result']) == hero_seat, steps
        sel = obsd.get('select')
        obs = to_observation_class(obsd)
        acting = int(cur['yourIndex'])
        policy = fork_policy if acting == hero_seat else opp
        action = [int(x) for x in policy.choose(obs)]
        nxt = engine.search_step(int(st['searchId']), action)
        if int(st['searchId']) != root_id:
            engine.search_release(int(st['searchId']))
        st = nxt
        steps += 1
    return -1, steps


for trial in range(4):
    r1 = run_once()
    engine.search_end()
    r2 = run_once()
    engine.search_end()
    print('trial', trial, 'run1', r1, 'run2', r2, 'SAME' if r1 == r2 else 'DIFF')
