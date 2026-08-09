from types import SimpleNamespace

from ptcg_ai.director import (
    DeckHypothesis,
    DirectorConfig,
    MirrorEvidenceState,
    RouteStatus,
    TurnDirector,
    enumerate_complete_actions,
    resolve_semantic_action,
    semantic_action,
)


def card(card_id, serial, player=1):
    return SimpleNamespace(
        id=card_id, serial=serial, playerIndex=player,
        energyCards=[], tools=[], preEvolution=[],
    )


def route_observation(cards=(), *, own=0):
    players = [
        SimpleNamespace(active=[], bench=[], discard=[]),
        SimpleNamespace(active=list(cards), bench=[], discard=[]),
    ]
    return SimpleNamespace(
        current=SimpleNamespace(players=players, yourIndex=own, stadium=[]),
        logs=[],
    )


def hypothesis(name="exact", replacement=None):
    deck = [646, 647, 648, 112] + [7] * 56
    if replacement is not None:
        deck[-1] = replacement
    return DeckHypothesis.from_cards(name, deck)


def test_marnie_line_alone_routes_but_munkidori_alone_never_routes():
    hypotheses = (hypothesis(),)
    state = MirrorEvidenceState()
    state.reset(hypotheses)
    assert state.observe(route_observation([card(112, 1)]), hypotheses, 1) == RouteStatus.INACTIVE
    assert state.observe(route_observation([card(646, 2)]), hypotheses, 2) == RouteStatus.COMPATIBLE


def test_variant_hypothesis_survives_then_contradiction_disqualifies_permanently():
    exact = hypothesis()
    variant = hypothesis("variant", replacement=999)
    state = MirrorEvidenceState()
    state.reset((exact, variant))
    assert state.observe(route_observation([card(646, 1), card(999, 2)]), (exact, variant), 4) == RouteStatus.COMPATIBLE
    assert state.compatible_deck_hashes == {variant.deck_sha256}
    assert state.observe(route_observation([card(646, 1), card(999, 2), card(888, 3)]), (exact, variant), 5) == RouteStatus.DISQUALIFIED
    assert state.observe(route_observation([card(646, 1)]), (exact, variant), 6) == RouteStatus.DISQUALIFIED


def test_semantic_cache_is_permutation_invariant_and_mismatch_invalidates():
    options = [
        SimpleNamespace(type=7, number=None, area=None, index=0, playerIndex=0, toolIndex=None, energyIndex=None, count=None, inPlayArea=None, inPlayIndex=None, attackId=None, cardId=None, serial=None, specialConditionType=None),
        SimpleNamespace(type=13, number=None, area=None, index=None, playerIndex=None, toolIndex=None, energyIndex=None, count=None, inPlayArea=None, inPlayIndex=None, attackId=99, cardId=None, serial=None, specialConditionType=None),
    ]
    obs = SimpleNamespace(select=SimpleNamespace(type=0, context=0, minCount=1, maxCount=1, option=options))
    semantic = semantic_action(obs, [1])
    swapped = SimpleNamespace(select=SimpleNamespace(type=0, context=0, minCount=1, maxCount=1, option=list(reversed(options))))
    assert resolve_semantic_action(swapped, semantic) == [0]
    semantic["options"][0]["attackId"] = 100
    assert resolve_semantic_action(swapped, semantic) is None


def test_complete_action_enumerator_keeps_fallback_and_end():
    options = [SimpleNamespace(type=value) for value in (7, 8, 10, 13, 14)]
    for option in options:
        for name in ("number", "area", "index", "playerIndex", "toolIndex", "energyIndex", "count", "inPlayArea", "inPlayIndex", "attackId", "cardId", "serial", "specialConditionType"):
            if not hasattr(option, name):
                setattr(option, name, None)
    obs = SimpleNamespace(select=SimpleNamespace(type=0, context=0, minCount=1, maxCount=1, option=options))
    actions = enumerate_complete_actions(obs, 4, proposals=[[0]])
    assert [0] in actions
    assert [4] in actions


def test_director_consumes_attempt_before_worker_and_never_retries(monkeypatch):
    config = DirectorConfig(hard_timeout_seconds=0.04, cleanup_seconds=0.03, stop_engine_seconds=0.02, stop_expand_seconds=0.01)
    director = TurnDirector([646, 647, 648, 112] + [7] * 56, [hypothesis()], config)
    obs = SimpleNamespace(
        current=SimpleNamespace(turn=3, firstPlayer=0, yourIndex=0),
        select=SimpleNamespace(type=0, context=0, minCount=1, maxCount=1, option=[SimpleNamespace(type=13)]),
    )
    assert director.should_attempt(obs, 2, [[0]])
    director.consumed = True
    assert not director.should_attempt(obs, 3, [[0]])
