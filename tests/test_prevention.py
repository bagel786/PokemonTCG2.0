from types import SimpleNamespace

from ptcg_ai.prevention import attack_nullified, places_counters
from ptcg_ai.view import attack_table

GRIMMSNARL_EX = 648  # Marnie's Grimmsnarl ex, attack 937 Shadow Bullet 180
FROSLASS = 104  # non-ex, attack 131 Frost Smash 60
MUNKIDORI = 112  # non-ex, attack 141 Mind Bend 60
CRUSTLE = 345  # Mysterious Rock Inn: prevents damage from Pokemon ex only
ARTICUNO_TR = 414  # Repelling Veil: blocks effects on Basic Team Rocket mons
ALAKAZAM = 743  # attack 1072 Powerful Hand places counters
POWERFUL_HAND = 1072


def observation(attacker_id, defender_id, *, energies=(), stadium=(), opponent_bench=()):
    def mon(card_id, attached=()):
        return SimpleNamespace(
            id=card_id,
            energyCards=[SimpleNamespace(id=e) for e in attached],
            tools=[],
        )

    return SimpleNamespace(
        current=SimpleNamespace(
            yourIndex=0,
            stadium=[SimpleNamespace(id=s) for s in stadium],
            players=[
                SimpleNamespace(active=[mon(attacker_id)], bench=[]),
                SimpleNamespace(
                    active=[mon(defender_id, energies)],
                    bench=[mon(b) for b in opponent_bench],
                ),
            ],
        )
    )


def attack_option(attack_id):
    return SimpleNamespace(attackId=attack_id)


def test_grimmsnarl_ex_is_blanked_by_crustle():
    """The trap: Shadow Bullet is real damage from an ex, so Crustle zeroes it."""
    obs = observation(GRIMMSNARL_EX, CRUSTLE)
    assert attack_nullified(obs, attack_option(937))


def test_froslass_pierces_crustle():
    """The line the policy never takes: non-ex damage ignores Mysterious Rock Inn."""
    obs = observation(FROSLASS, CRUSTLE)
    assert not attack_nullified(obs, attack_option(131))
    obs = observation(MUNKIDORI, CRUSTLE)
    assert not attack_nullified(obs, attack_option(141))


def test_counters_and_damage_are_blocked_by_opposite_families():
    """Powerful Hand skips CalcDamage, so Crustle misses it but Repelling Veil catches it."""
    assert places_counters(attack_table()[POWERFUL_HAND])
    assert not attack_nullified(observation(ALAKAZAM, CRUSTLE), attack_option(POWERFUL_HAND))
    veiled = observation(ALAKAZAM, ARTICUNO_TR)
    assert attack_nullified(veiled, attack_option(POWERFUL_HAND))
    # ...while ordinary ex damage goes straight through Repelling Veil.
    assert not attack_nullified(observation(GRIMMSNARL_EX, ARTICUNO_TR), attack_option(937))


def test_mist_energy_blocks_counters_only():
    mist = observation(ALAKAZAM, FROSLASS, energies=(11,))
    assert attack_nullified(mist, attack_option(POWERFUL_HAND))
    assert not attack_nullified(observation(GRIMMSNARL_EX, FROSLASS, energies=(11,)), attack_option(937))
