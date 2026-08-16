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

from training.search_teacher import determinize_known_matchup
import random as _r
lib = engine.lib
lib.SearchSetSeed.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
lib.SearchSetSeed.restype = None


def play(with_forks: bool, fork_seed: int):
    hero.reset()
    ptr, raw = engine.start(hero_deck, opp_deck, seed)
    harvest_obs = None
    forced_oi = None
    trace = []
    for step_i in range(100):
        obsd = raw
        cur = obsd.get('current') or {}
        if cur.get('result', -1) is not None and int(cur['result']) >= 0:
            trace.append(('terminal', int(cur['result']), step_i))
            return trace
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
            trace.append(('opp', ctx, action))
            continue
        action = [int(x) for x in hero.choose(obs)]
        if int(sel['type']) == int(SelectType.MAIN) and ctx == int(SelectContext.MAIN):
            play = gen._play_cards(obs)
            active = [i for i in play if play[i] >= 0]
            distinct = sorted({play[i] for i in active})
            if len(distinct) >= 2 and harvest_obs is None:
                harvest_obs = obsd
                forced_oi = active[0]
                if with_forks:
                    obs_dc = to_observation_class(harvest_obs)
                    kwargs = dict(determinize_known_matchup(obs_dc, hero_deck, opp_deck, _r.Random(12345)))
                    lib.SearchSetSeed(engine.agent_ptr, ctypes.c_uint32(fork_seed).value)
                    root = engine.search_begin(harvest_obs, **kwargs)
                    rid = int(root['searchId'])
                    fork_policy.reset()
                    st = engine.search_step(rid, [forced_oi])
                    win, steps = gen.rollout_to_terminal(engine, st, fork_policy, opp, hero_seat)
                    engine.search_release(rid)
                    engine.search_end()
        trace.append(('hero', ctx, action))
        raw = engine.select(ptr, action)
    trace.append(('cap', -1, step_i))
    return trace


a = play(False, 0)
b = play(True, 777)
same = 0
diverge_at = None
for i, (x, y) in enumerate(zip(a, b)):
    if x == y:
        same += 1
    else:
        diverge_at = i
        break
print('no-fork trace len', len(a), 'with-fork trace len', len(b))
print('identical prefix length', same)
if diverge_at is not None:
    print('first divergence at trace index', diverge_at)
    print('  no-fork:', a[diverge_at])
    print('  with-fork:', b[diverge_at])
    print('  context:', a[diverge_at][1] if len(a[diverge_at]) > 1 else '-')
