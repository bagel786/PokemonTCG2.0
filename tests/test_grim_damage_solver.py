from types import SimpleNamespace as NS

from cg.api import AreaType, EnergyType, Option, OptionType, SelectContext

from ptcg_ai.card_ids import MARNIES_GRIMMSNARL_EX, MUNKIDORI
from ptcg_ai.grim_damage_solver import GrimDamageSolver
from ptcg_ai.view import card_table


BATTLE_CAGE = 1264


def card(card_id, serial=1, player_index=0):
    return NS(id=card_id, serial=serial, playerIndex=player_index)


def pokemon(card_id, serial, *, hp=100, max_hp=100, energies=(), player_index=0):
    return NS(
        id=card_id, serial=serial, playerIndex=player_index, hp=hp, maxHp=max_hp,
        appearThisTurn=False, energies=list(energies),
        energyCards=[card(int(e), serial * 10 + i, player_index) for i, e in enumerate(energies)],
        tools=[], preEvolution=[],
    )


def player(*, active=(), bench=(), prize_count=6, **status):
    return NS(
        active=list(active), bench=list(bench), prize=[None] * prize_count,
        hand=[], handCount=0, discard=[], deckCount=40, benchMax=5,
        poisoned=False, burned=False, asleep=status.get("asleep", False),
        paralyzed=status.get("paralyzed", False), confused=status.get("confused", False),
    )


def selection(context, options, effect=None, minimum=1, maximum=1):
    return NS(
        context=context, option=list(options), effect=effect, contextCard=None,
        minCount=minimum, maxCount=maximum, remainDamageCounter=0,
        remainEnergyCost=0, deck=None,
    )


def observation(select, me, opponent, *, turn=5, stadium=()):
    return NS(
        select=select,
        current=NS(
            players=[me, opponent], yourIndex=0, firstPlayer=0, turn=turn,
            turnActionCount=0, supporterPlayed=False, stadiumPlayed=False,
            energyAttached=False, retreated=False, stadium=list(stadium), looking=None,
        ),
        logs=[],
    )


def target_options(opponent):
    options = []
    if opponent.active:
        options.append(Option(OptionType.CARD, area=AreaType.ACTIVE, index=0, playerIndex=1))
    options.extend(
        Option(OptionType.CARD, area=AreaType.BENCH, index=i, playerIndex=1)
        for i in range(len(opponent.bench))
    )
    return options


def grim_ready():
    return player(active=[pokemon(
        MARNIES_GRIMMSNARL_EX, 10, hp=320, max_hp=320,
        energies=(EnergyType.DARKNESS, EnergyType.TEAM_ROCKET),
    )])


def munk_effect():
    return card(MUNKIDORI, 900)


def start_munk(solver, me, opponent, *, turn=5, count=3):
    source = selection(
        SelectContext.REMOVE_DAMAGE_COUNTER,
        [Option(OptionType.CARD, area=AreaType.ACTIVE, index=0, playerIndex=0)],
        munk_effect(),
    )
    assert solver.apply(observation(source, me, opponent, turn=turn), [0], 1)[2] is None
    if count != 1:
        counts = selection(
            SelectContext.REMOVE_DAMAGE_COUNTER_COUNT,
            [Option(OptionType.NUMBER, number=i) for i in range(1, 4)],
            munk_effect(),
        )
        ranked = [count - 1] + [i for i in range(3) if i != count - 1]
        ranked_after, desired, reason = solver.apply(
            observation(counts, me, opponent, turn=turn), ranked, 1
        )
        assert (ranked_after, desired, reason) == (ranked, 1, None)


def solve_shadow(solver, opponent, ranked, me=None):
    select = selection(SelectContext.DAMAGE, target_options(opponent), card(MARNIES_GRIMMSNARL_EX, 10))
    return solver.apply(observation(select, me or grim_ready(), opponent), ranked, 1)


def test_shadow_converts_exact_one_prize_ko():
    opponent = player(active=[pokemon(MUNKIDORI, 20, hp=100, player_index=1)], bench=[
        pokemon(MUNKIDORI, 21, hp=50, player_index=1),
        pokemon(MUNKIDORI, 22, hp=30, player_index=1),
    ])
    ranked, desired, reason = solve_shadow(GrimDamageSolver(), opponent, [1, 2])
    assert (ranked[0], desired, reason) == (2, 1, "shadow_exact_conversion")


def test_shadow_converts_exact_two_prize_ko():
    opponent = player(active=[pokemon(MUNKIDORI, 20, player_index=1)], bench=[
        pokemon(MUNKIDORI, 21, hp=30, player_index=1),
        pokemon(MARNIES_GRIMMSNARL_EX, 22, hp=30, max_hp=320, player_index=1),
    ])
    ranked, _, reason = solve_shadow(GrimDamageSolver(), opponent, [1, 2])
    assert ranked[0] == 2
    assert reason == "shadow_exact_conversion"


def test_munk_concentrates_for_shadow_instead_of_spreading():
    me = grim_ready()
    me.active[0].hp = 290
    opponent = player(active=[pokemon(MUNKIDORI, 20, hp=250, max_hp=250, player_index=1)], bench=[
        pokemon(MUNKIDORI, 21, hp=30, player_index=1),
        pokemon(MARNIES_GRIMMSNARL_EX, 22, hp=60, max_hp=320, player_index=1),
    ])
    solver = GrimDamageSolver()
    start_munk(solver, me, opponent)
    select = selection(SelectContext.DAMAGE_COUNTER, target_options(opponent), munk_effect())
    ranked, _, reason = solver.apply(observation(select, me, opponent), [1, 2, 0], 1)
    assert ranked[0] == 2
    assert reason == "munk_exact_conversion"


def test_shadow_avoids_overkill_when_prizes_are_equal():
    opponent = player(active=[pokemon(MUNKIDORI, 20, player_index=1)], bench=[
        pokemon(MUNKIDORI, 21, hp=10, player_index=1),
        pokemon(MUNKIDORI, 22, hp=30, player_index=1),
    ])
    ranked, _, reason = solve_shadow(GrimDamageSolver(), opponent, [1, 2])
    assert ranked[0] == 2
    assert reason == "shadow_exact_conversion"


def test_shadow_does_not_value_attached_energy_over_prizes():
    low = pokemon(MUNKIDORI, 21, hp=30, energies=(EnergyType.DARKNESS,) * 3, player_index=1)
    high = pokemon(MARNIES_GRIMMSNARL_EX, 22, hp=30, max_hp=320, player_index=1)
    opponent = player(active=[pokemon(MUNKIDORI, 20, player_index=1)], bench=[low, high])
    ranked, _, _ = solve_shadow(GrimDamageSolver(), opponent, [1, 2])
    assert ranked[0] == 2


def test_shadow_avoids_protected_tera_bench():
    tera_id = next(card.cardId for card in card_table().values() if card.tera)
    opponent = player(active=[pokemon(MUNKIDORI, 20, player_index=1)], bench=[
        pokemon(tera_id, 21, hp=10, player_index=1),
        pokemon(MUNKIDORI, 22, hp=30, player_index=1),
    ])
    ranked, _, reason = solve_shadow(GrimDamageSolver(), opponent, [1, 2])
    assert ranked[0] == 2
    assert reason == "shadow_exact_conversion"


def test_munk_respects_battle_cage_counter_prevention():
    me = player(active=[pokemon(MUNKIDORI, 10, hp=70, max_hp=110)])
    opponent = player(active=[pokemon(MUNKIDORI, 20, hp=100, player_index=1)], bench=[
        pokemon(MUNKIDORI, 21, hp=10, player_index=1),
    ])
    solver = GrimDamageSolver()
    start_munk(solver, me, opponent)
    select = selection(SelectContext.DAMAGE_COUNTER, target_options(opponent), munk_effect())
    ranked, _, reason = solver.apply(
        observation(select, me, opponent, stadium=[card(BATTLE_CAGE)]), [1, 0], 1
    )
    assert ranked[0] == 0
    assert reason == "munk_exact_conversion"


def test_munk_abstains_when_active_ko_has_uncertain_promotion():
    me = player(active=[pokemon(MUNKIDORI, 10, hp=70, max_hp=110)])
    opponent = player(active=[pokemon(MUNKIDORI, 20, hp=30, player_index=1)], bench=[
        pokemon(MUNKIDORI, 21, hp=100, player_index=1),
    ])
    solver = GrimDamageSolver()
    start_munk(solver, me, opponent)
    select = selection(SelectContext.DAMAGE_COUNTER, target_options(opponent), munk_effect())
    assert solver.apply(observation(select, me, opponent), [1, 0], 1) == ([1, 0], 1, None)


def test_option_permutation_selects_same_semantic_serial():
    weak = pokemon(MUNKIDORI, 21, hp=30, player_index=1)
    ex = pokemon(MARNIES_GRIMMSNARL_EX, 22, hp=30, max_hp=320, player_index=1)
    active = pokemon(MUNKIDORI, 20, player_index=1)
    first = player(active=[active], bench=[weak, ex])
    second = player(active=[active], bench=[ex, weak])
    r1, _, _ = solve_shadow(GrimDamageSolver(), first, [1, 2])
    r2, _, _ = solve_shadow(GrimDamageSolver(), second, [2, 1])
    assert first.bench[r1[0] - 1].serial == second.bench[r2[0] - 1].serial == 22


def test_pending_source_uses_stable_serial_and_clears_if_it_disappears():
    source = pokemon(MUNKIDORI, 10, hp=70, max_hp=110)
    me = player(active=[source])
    opponent = player(active=[pokemon(MUNKIDORI, 20, hp=100, player_index=1)], bench=[
        pokemon(MUNKIDORI, 21, hp=30, player_index=1),
    ])
    solver = GrimDamageSolver()
    start_munk(solver, me, opponent)
    me.active = [pokemon(MUNKIDORI, 99, hp=70, max_hp=110)]
    select = selection(SelectContext.DAMAGE_COUNTER, target_options(opponent), munk_effect())
    assert solver.apply(observation(select, me, opponent), [0, 1], 1) == ([0, 1], 1, None)


def test_pending_state_clears_on_turn_and_game_reset():
    me = player(active=[pokemon(MUNKIDORI, 10, hp=70, max_hp=110)])
    opponent = player(active=[pokemon(MUNKIDORI, 20, player_index=1)], bench=[
        pokemon(MUNKIDORI, 21, hp=30, player_index=1),
    ])
    select = selection(SelectContext.DAMAGE_COUNTER, target_options(opponent), munk_effect())
    solver = GrimDamageSolver()
    start_munk(solver, me, opponent, turn=5)
    assert solver.apply(observation(select, me, opponent, turn=7), [0, 1], 1)[2] is None
    start_munk(solver, me, opponent, turn=9)
    solver.reset()
    assert solver.apply(observation(select, me, opponent, turn=9), [0, 1], 1)[2] is None


def test_malformed_and_unrelated_prompts_fail_closed_without_illegal_indices():
    solver = GrimDamageSolver()
    me, opponent = grim_ready(), player()
    unrelated = selection(SelectContext.MAIN, [Option(OptionType.END)])
    assert solver.apply(observation(unrelated, me, opponent), [0], 1) == ([0], 1, None)

    malformed = selection(
        SelectContext.DAMAGE,
        [Option(OptionType.CARD, area=AreaType.BENCH, index=99, playerIndex=1)],
        card(MARNIES_GRIMMSNARL_EX),
    )
    ranked, desired, reason = solver.apply(observation(malformed, me, opponent), [0], 1)
    assert ranked == [0] and desired == 1 and reason is None
    assert all(0 <= index < len(malformed.option) for index in ranked)
