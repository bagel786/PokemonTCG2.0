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
harvest_active = None
harvest_play = None
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
            harvest_play = play
            harvest_active = active
    raw = engine.select(ptr, action)

from training.search_teacher import determinize_known_matchup
import random as _r
obs = to_observation_class(harvest_obs)
logits = gen.play_logits(hero, obs)
distinct = sorted({harvest_play[i] for i in harvest_active})
chosen_card = None
for index in [int(x) for x in hero.choose(obs)]:
    if index in harvest_play and harvest_play[index] >= 0:
        chosen_card = harvest_play[index]
        break
alternatives = [c for c in sorted(distinct, key=lambda c: -max((logits[i] for i in harvest_active if harvest_play[i] == c), default=-1e9)) if c != chosen_card][:2]
cards_to_test = [c for c in ([chosen_card] if chosen_card is not None else []) + alternatives]
print('cards_to_test:', cards_to_test)


def branch(det_seed, card):
    fork_policy.reset()
    kwargs = dict(determinize_known_matchup(obs, hero_deck, opp_deck, _r.Random(det_seed)))
    engine.search_set_seed(det_seed)
    root = engine.search_begin(harvest_obs, **kwargs)
    root_id = int(root['searchId'])
    option_index = next(i for i in harvest_active if harvest_play[i] == card)
    state = engine.search_step(root_id, [option_index])
    hero_win, steps = gen.rollout_to_terminal(engine, state, fork_policy, opp, hero_seat)
    engine.search_release(root_id)
    engine.search_end()
    return hero_win, steps


det_seed = seed * 31 + 0
card = cards_to_test[0]
print('original:', branch(det_seed, card))
for other in cards_to_test[1:]:
    print('other card', other, ':', branch(det_seed, other))
print('probe1:', branch(det_seed, card))
print('probe2:', branch(det_seed, card))
