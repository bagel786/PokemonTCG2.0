import sys, os
sys.path[:0] = ['scripts', '.', 'vendor']
import generate_p1_causal_labels as gen
from cg.api import to_observation_class, SelectContext, OptionType, SelectType

engine = gen.SeededSearchEngine(gen.SEEDED_ENGINE)
os.environ['PTCG_GRIM_DAMAGE_SOLVER'] = 'v0'
hero = gen.load_package_policy(gen.R0_PACKAGE, 'policy_first.npz')
opp = gen.load_package_policy(gen.B0_PACKAGE, 'policy_weights.npz')
hero_deck = [int(l) for l in (gen.R0_PACKAGE / 'deck.csv').read_text().splitlines() if l.strip()]
opp_deck = [int(l) for l in (gen.B0_PACKAGE / 'deck.csv').read_text().splitlines() if l.strip()]
seed = 202608160101
hero_seat = seed % 2
order = 'first'
ptr, raw = engine.start(hero_deck, opp_deck, seed)
harvested = 0
for step_i in range(80):
    obsd = raw
    cur = obsd.get('current') or {}
    if cur.get('result', -1) is not None and int(cur['result']) >= 0:
        print('terminal at', step_i)
        break
    sel = obsd.get('select')
    obs = to_observation_class(obsd)
    acting = int(cur['yourIndex'])
    ctx = int(sel['context'])
    st = int(sel['type'])
    if ctx == int(SelectContext.IS_FIRST):
        want_yes = (order == 'first') == (hero_seat == 0)
        types = [(j, int(o.type)) for j, o in enumerate(obs.select.option)]
        chosen = [j for j, t in types if (t == int(OptionType.YES)) == want_yes]
        print('step', step_i, 'IS_FIRST', types, 'chosen', chosen)
        raw = engine.select(ptr, chosen)
        continue
    if acting != hero_seat:
        action = [int(x) for x in opp.choose(obs)]
        raw = engine.select(ptr, action)
        continue
    if st == int(SelectType.MAIN) and ctx == int(SelectContext.MAIN) and harvested < 2:
        play = gen._play_cards(obs)
        active = [i for i in play if play[i] >= 0]
        distinct = sorted({play[i] for i in active})
        print('step', step_i, 'MAIN distinct', distinct, 'harvested', harvested)
        if len(distinct) >= 2:
            harvested += 1
            action = [int(x) for x in hero.choose(obs)]
            chosen_card = None
            for i in action:
                if i in play and play[i] >= 0:
                    chosen_card = play[i]
                    break
            from training.search_teacher import determinize_known_matchup
            import random as _r
            kwargs = dict(determinize_known_matchup(obs, hero_deck, opp_deck, _r.Random(seed * 31)))
            root = engine.search_begin(obsd, **kwargs)
            root_id = int(root['searchId'])
            logits = gen.play_logits(hero, obs)
            alts = [c for c in sorted(distinct, key=lambda c: -max((logits[i] for i in active if play[i] == c), default=-1e9)) if c != chosen_card][:2]
            for card in [c for c in ([chosen_card] if chosen_card else []) + alts]:
                oi = next(i for i in active if play[i] == card)
                st2 = engine.search_step(root_id, [oi])
                win, steps = gen.rollout_to_terminal(engine, st2, hero, opp, hero_seat)
                print('   card', card, 'win', win, 'steps', steps)
            engine.search_release(root_id)
            engine.search_end()
        raw = engine.select(ptr, action)
        continue
    action = [int(x) for x in hero.choose(obs)]
    print('step', step_i, 'hero action', action, 'ctx', ctx)
    raw = engine.select(ptr, action)
print('done ok')
