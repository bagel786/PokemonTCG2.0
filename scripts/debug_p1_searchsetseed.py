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

# try to bind SearchSetSeed: possible signatures
lib = engine.lib
results = {}
for argtypes in [
    [ctypes.c_void_p, ctypes.c_uint32],
    [ctypes.c_void_p, ctypes.c_uint64],
    [ctypes.c_uint32],
    [ctypes.c_void_p, ctypes.c_int],
]:
    try:
        lib.SearchSetSeed.argtypes = argtypes
        lib.SearchSetSeed.restype = None
        engine.search_begin(harvest_obs, **kwargs)
        if len(argtypes) == 2:
            lib.SearchSetSeed(engine.agent_ptr, ctypes.c_uint32(777)(0).value if False else 777)
        else:
            lib.SearchSetSeed(777)
        engine.search_end()
        results[str(argtypes)] = 'ok'
    except Exception as exc:
        results[str(argtypes)] = repr(exc)[:80]
print(json.dumps(results, indent=1))
