import sys, os, json, hashlib
sys.path[:0] = ['scripts', '.', 'vendor']
import generate_p1_causal_labels as gen
from cg.api import to_observation_class, SelectContext, OptionType, SelectType

engine = gen.get_engine()
os.environ['PTCG_GRIM_DAMAGE_SOLVER'] = 'v0'
hero = gen.load_package_policy(gen.R0_PACKAGE, 'policy_first.npz')
opp = gen.load_package_policy(gen.B0_PACKAGE, 'policy_weights.npz')
hero_deck = [int(l) for l in (gen.R0_PACKAGE / 'deck.csv').read_text().splitlines() if l.strip()]
opp_deck = [int(l) for l in (gen.B0_PACKAGE / 'deck.csv').read_text().splitlines() if l.strip()]
seed = 202608160101
hero_seat = seed % 2
order = 'first'
ptr, raw = engine.start(hero_deck, opp_deck, seed)

def canon(d):
    return json.dumps(d, sort_keys=True, default=str)

# walk to first eligible MAIN prompt with >=2 distinct playables
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
    raw = engine.select(ptr, action)

print('harvest at turn', harvest_obs['current']['turn'])
from training.search_teacher import determinize_known_matchup
import random as _r
obs = to_observation_class(harvest_obs)
kwargs = dict(determinize_known_matchup(obs, hero_deck, opp_deck, _r.Random(12345)))
print('kwargs lens:', {k: len(v) for k, v in kwargs.items()})

roots = []
for i in range(3):
    root = engine.search_begin(harvest_obs, **kwargs)
    roots.append(root)
    rid = int(root['searchId'])
    engine.search_release(rid)
print('root obs identical:', canon(roots[0]['observation']['current']) == canon(roots[1]['observation']['current']) == canon(roots[2]['observation']['current']))
# also compare select
print('root select identical:', canon(roots[0]['observation']['select']) == canon(roots[1]['observation']['select']))

# now roll the same branch from two fresh roots, identical forced action
for rep in range(2):
    root = engine.search_begin(harvest_obs, **kwargs)
    rid = int(root['searchId'])
    st = engine.search_step(rid, [0])
    win, steps = gen.rollout_to_terminal(engine, st, hero, opp, hero_seat)
    print('rep', rep, 'win', win, 'steps', steps)
    engine.search_release(rid)
    engine.search_end()
