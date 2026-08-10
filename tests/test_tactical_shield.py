from types import SimpleNamespace
from unittest.mock import patch

from cg.api import OptionType, SelectContext, SelectType

from ptcg_ai.tactical_shield import apply_tactical_shield


def observation(
    option_types,
    *,
    context=SelectContext.MAIN,
    select_type=SelectType.MAIN,
    minimum=0,
    maximum=1,
):
    options = [SimpleNamespace(type=kind, attackId=index + 1) for index, kind in enumerate(option_types)]
    return SimpleNamespace(
        select=SimpleNamespace(
            option=options,
            context=context,
            type=select_type,
            minCount=minimum,
            maxCount=maximum,
        )
    )


def test_setup_requires_a_basic_when_model_selects_zero():
    obs = observation([OptionType.CARD], context=2, minimum=0, maximum=5)
    with patch("ptcg_ai.tactical_shield.option_source_card", return_value=SimpleNamespace(basic=True)):
        ranked, desired, reason = apply_tactical_shield(obs, [0], 0)
    assert (ranked, desired, reason) == ([0], 1, "setup_bench_basic")


def test_setup_resolves_basic_status_from_current_card_data():
    obs = observation([OptionType.CARD], context=2, minimum=0, maximum=5)
    card = SimpleNamespace(id=646)
    with (
        patch("ptcg_ai.tactical_shield.option_source_card", return_value=card),
        patch("ptcg_ai.tactical_shield.card_table", return_value={646: SimpleNamespace(basic=True)}),
    ):
        _, desired, reason = apply_tactical_shield(obs, [0], 0)
    assert desired == 1
    assert reason == "setup_bench_basic"


def test_nullified_attack_is_rejected_for_productive_attack():
    obs = observation([OptionType.ATTACK, OptionType.ATTACK, OptionType.END], minimum=1)
    with patch(
        "ptcg_ai.tactical_shield.attack_nullified",
        side_effect=lambda _obs, option: option.attackId == 1,
    ):
        ranked, desired, reason = apply_tactical_shield(obs, [0, 1, 2], 1)
    assert ranked[0] == 1
    assert desired == 1
    assert reason == "nullified_attack"


def test_end_is_rejected_for_highest_ranked_productive_attack():
    obs = observation([OptionType.END, OptionType.ATTACK, OptionType.ATTACK], minimum=0)
    with patch("ptcg_ai.tactical_shield.attack_nullified", return_value=False):
        ranked, _, reason = apply_tactical_shield(obs, [0, 2, 1], 1)
    assert ranked[0] == 2
    assert reason == "end_with_productive_attack"


def test_legitimate_end_is_unchanged_without_productive_attack():
    obs = observation([OptionType.END, OptionType.ATTACK], minimum=0)
    with patch("ptcg_ai.tactical_shield.attack_nullified", return_value=True):
        ranked, desired, reason = apply_tactical_shield(obs, [0, 1], 1)
    assert (ranked, desired, reason) == ([0, 1], 1, None)


def test_attack_effect_prompt_is_not_mistaken_for_main_attack_choice():
    obs = observation(
        [OptionType.ATTACK, OptionType.ATTACK],
        context=SelectContext.DISABLE_ATTACK,
        select_type=SelectType.ATTACK,
        minimum=1,
    )
    with patch("ptcg_ai.tactical_shield.attack_nullified", return_value=True):
        ranked, desired, reason = apply_tactical_shield(obs, [0, 1], 1)
    assert (ranked, desired, reason) == ([0, 1], 1, None)
