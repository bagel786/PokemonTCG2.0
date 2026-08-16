import sys, json
sys.path[:0] = ['scripts', '.', 'vendor']
import generate_p1_causal_labels as gen
from cg.api import to_observation_class, SelectContext, OptionType

engine = gen.get_engine()
os = __import__('os')
os.environ['PTCG_GRIM_DAMAGE_SOLVER'] = 'v0'
hero = gen.load_package_policy(gen.R0_PACKAGE, 'policy_first.npz')
opp = gen.load_package_policy(gen.R0_PACKAGE, 'policy_second.npz')
deck = [int(l) for l in (gen.R0_PACKAGE / 'deck.csv').read_text().splitlines() if l.strip()]
for seed in (202608160101, 202608160102, 202608160103):
    hero_seat = seed % 2
    order = 'second'  # hero is second
    ptr, raw = engine.start(deck, deck, seed)
    print('=== seed', seed, 'hero seat', hero_seat)
    steps = 0
    while steps < 40:
        obsd = raw
        cur = obsd.get('current') or {}
        if cur.get('result', -1) is not None and int(cur['result']) >= 0:
            print('  terminal turn', cur.get('turn'))
            break
        sel = obsd.get('select')
        obs = to_observation_class(obsd)
        ctx = int(sel['context'])
        if ctx == int(SelectContext.IS_FIRST):
            want_yes = False  # hero (seat X) picks NO -> seat 0 first? careful: order second means seat0 first
            # hero_seat must not be firstPlayer: hero picks NO if hero_seat != 0
            want_yes = (order == 'first') == (hero_seat == 0)
            chosen = [j for j, o in enumerate(obs.select.option) if (o.type == OptionType.YES) == want_yes]
            raw = engine.select(ptr, chosen)
            continue
        acting = int(cur['yourIndex'])
        turn = cur.get('turn')
        if acting == hero_seat:
            print('  hero prompt: turn', turn, 'ctx', ctx, 'seltype', sel['type'])
        policy = hero if acting == hero_seat else opp
        action = [int(x) for x in policy.choose(obs)]
        raw = engine.select(ptr, action)
        steps += 1
