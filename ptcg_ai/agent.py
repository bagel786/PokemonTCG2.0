"""Competition-facing agent with fail-closed behavior."""

from __future__ import annotations

import os
import json
from pathlib import Path

from cg.api import to_observation_class

from .card_ids import CYNTHIAS_GARCHOMP_EX
from .heuristic import GarchompHeuristic, GrimmsnarlHeuristic
from .safety import emergency_selection


LUCARIO_PUBLIC_CARD_IDS = frozenset({677, 678})

# Grimmsnarl mirror: opponent Impidimp (646) -> Morgrem (647) -> Grimmsnarl ex (648).
# Seeing any of these in the OPPONENT's public zones means they are on the mirror deck.
GRIMMSNARL_MIRROR_PUBLIC_CARD_IDS = frozenset({646, 647, 648})


def _public_card_ids(obs) -> set[int]:
    """Return opponent card IDs visible to the acting player."""
    state = obs.current
    opponent = state.players[1 - state.yourIndex]
    result: set[int] = set()

    def add_cards(cards) -> None:
        for card in cards or []:
            if card is not None and getattr(card, "id", None) is not None:
                result.add(int(card.id))

    def add_pokemon(pokemon) -> None:
        for card in pokemon or []:
            if card is None:
                continue
            result.add(int(card.id))
            add_cards(getattr(card, "energyCards", None))
            add_cards(getattr(card, "tools", None))
            add_cards(getattr(card, "preEvolution", None))

    add_pokemon(opponent.active)
    add_pokemon(opponent.bench)
    add_cards(opponent.discard)
    for log in obs.logs or []:
        if log.playerIndex != state.yourIndex and log.cardId is not None:
            result.add(int(log.cardId))
    return result


def lucario_publicly_detected(obs) -> bool:
    """Detect Lucario without consulting either hidden deck list."""
    return bool(_public_card_ids(obs) & LUCARIO_PUBLIC_CARD_IDS)


def grimmsnarl_mirror_publicly_detected(obs, exact_deck: list[int] | None = None) -> bool:
    """Detect a Grimmsnarl mirror from the opponent's public cards only.

    Reads only the opponent's active/bench/discard/attached cards and public
    logs (via ``_public_card_ids``); never inspects a hidden hand or deck.
    """
    visible = _public_card_ids(obs)
    if not visible & GRIMMSNARL_MIRROR_PUBLIC_CARD_IDS:
        return False
    return exact_deck is None or visible <= set(map(int, exact_deck))


class CompetitionAgent:
    def __init__(
        self,
        deck_path: str | os.PathLike[str] | None = None,
        model_path: str | os.PathLike[str] | None = None,
        specialist_model_path: str | os.PathLike[str] | None = None,
        mirror_model_path: str | os.PathLike[str] | None = None,
    ):
        self.deck_path = Path(deck_path) if deck_path else self._find("deck.csv")
        self.deck = [int(line) for line in self.deck_path.read_text().splitlines() if line.strip()]
        if len(self.deck) != 60:
            raise ValueError(f"deck must contain exactly 60 cards, got {len(self.deck)}")
        fallback = GarchompHeuristic() if CYNTHIAS_GARCHOMP_EX in self.deck else GrimmsnarlHeuristic()
        prior_path = self._optional_find("elite_prior.json")
        if prior_path is not None:
            from .elite_prior import ElitePriorHeuristic

            fallback = ElitePriorHeuristic(prior_path, fallback)
        self.fallback = fallback
        model_path = Path(model_path) if model_path else self._optional_find("policy_weights.npz")
        residual_manifest = self._optional_find("residual_manifest.json")
        direct_path = self._optional_find("direct_policy.npz")
        mirror_direct_path = self._optional_find("mirror_direct.npz")
        policy_mode = os.environ.get("PTCG_POLICY", "auto").lower()
        search_mode = os.environ.get("PTCG_SEARCH", "1").lower()
        if residual_manifest is not None and direct_path is None and policy_mode != "heuristic":
            from .relational import ResidualEnsemblePolicy

            self.policy = ResidualEnsemblePolicy(residual_manifest, fallback)
            self.specialist = None
            if mirror_direct_path is not None:
                from .direct import DirectPolicy

                self.mirror_specialist = DirectPolicy(mirror_direct_path, fallback)
            else:
                self.mirror_specialist = None
        elif direct_path is not None and policy_mode != "heuristic":
            from .direct import DirectPolicy
            direct_fallback = fallback
            if residual_manifest is not None:
                from .relational import ResidualEnsemblePolicy

                direct_fallback = ResidualEnsemblePolicy(residual_manifest, fallback)

            self.policy = DirectPolicy(direct_path, direct_fallback)
            self.specialist = None
            self.mirror_specialist = (
                DirectPolicy(mirror_direct_path, fallback)
                if mirror_direct_path is not None else None
            )
        elif model_path is not None and policy_mode != "heuristic":
            from .model import NeuralPolicy
            
            search_policy = None
            if search_mode not in ("0", "false", "off", "no"):
                try:
                    from .search import OnePlySearchPolicy
                    search_policy = OnePlySearchPolicy(
                        model=None,  # set below after model init or inside NeuralPolicy
                        hero_deck=self.deck,
                    )
                except Exception:
                    search_policy = None

            self.policy = NeuralPolicy(model_path, fallback, search_policy=search_policy)
            if search_policy is not None:
                search_policy.model = self.policy.model

            specialist_model_path = (
                Path(specialist_model_path)
                if specialist_model_path
                else self._optional_find("lucario_specialist.npz")
            )
            self.specialist = (
                NeuralPolicy(specialist_model_path, fallback)
                if specialist_model_path is not None
                else None
            )

            # Grimmsnarl-mirror specialist: greedy, search DISABLED (no search_policy
            # passed), legality sanitization + setup-bench floor retained by NeuralPolicy,
            # emergency fallback via __call__. Dormant when no mirror_specialist.npz is
            # bundled, which keeps non-mirror behavior byte-identical to v2.2.
            mirror_model_path = (
                Path(mirror_model_path)
                if mirror_model_path
                else self._optional_find("mirror_specialist.npz")
            )
            self.mirror_specialist = (
                NeuralPolicy(mirror_model_path, fallback)
                if mirror_model_path is not None
                else None
            )
        else:
            self.policy = fallback
            self.specialist = None
            self.mirror_specialist = None
        self.lucario_routed = False
        self.mirror_routed = False
        self.mirror_evidence = None
        self.director = None
        self.routed_fallback = self.policy
        self.director_proposers = []
        director_config_path = self._optional_find("director_config.json")
        if director_config_path is not None:
            from .director import DirectorConfig, MirrorEvidenceState, TurnDirector, load_hypotheses

            raw_config = json.loads(director_config_path.read_text(encoding="utf-8"))
            trial_arm = os.environ.get("PTCG_DIRECTOR_ARM", "treatment").strip().lower()
            if trial_arm not in {"treatment", "control"}:
                raise ValueError(f"invalid PTCG_DIRECTOR_ARM: {trial_arm}")
            if trial_arm == "control":
                raw_config["enabled"] = False
            if os.environ.get("PTCG_DIRECTOR_TRIGGER"):
                raw_config["trigger"] = os.environ["PTCG_DIRECTOR_TRIGGER"]
            if os.environ.get("PTCG_DIRECTOR_HORIZON"):
                raw_config["horizon"] = os.environ["PTCG_DIRECTOR_HORIZON"]
            allowed = set(DirectorConfig.__dataclass_fields__)
            config = DirectorConfig(**{key: value for key, value in raw_config.items() if key in allowed})
            hypothesis_path = self._optional_find("marnie_hypotheses.json")
            hypotheses = load_hypotheses(hypothesis_path, self.deck)
            self.mirror_evidence = MirrorEvidenceState()
            self.mirror_evidence.reset(hypotheses)
            fallback_weights = self._optional_find("director_fallback.npz")
            secondary_weights = self._optional_find("director_secondary.npz")
            if os.environ.get("PTCG_DIRECTOR_SWAP_FALLBACK", "0").lower() in {"1", "true", "yes"}:
                fallback_weights, secondary_weights = secondary_weights, fallback_weights
            if fallback_weights is not None:
                from .model import NeuralPolicy

                self.routed_fallback = NeuralPolicy(fallback_weights, fallback)
            if secondary_weights is not None:
                from .model import NeuralPolicy

                self.director_proposers.append(NeuralPolicy(secondary_weights, fallback))
            hashes = {str(key): str(value) for key, value in raw_config.get("artifact_hashes", {}).items()}
            self.director = TurnDirector(self.deck, hypotheses, config, hashes)
        self.errors = 0
        self.route_telemetry = {
            "mirror_activations": 0,
            "mirror_activation_step": None,
            "mirror_evidence": [],
        }

    @staticmethod
    def _find(filename: str) -> Path:
        root = Path(__file__).resolve().parent.parent
        candidates = [
            Path(filename),
            root / filename,
            Path(__file__).resolve().parent / filename,
            Path("/kaggle_simulations/agent") / filename,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise FileNotFoundError(filename)

    @staticmethod
    def _optional_find(filename: str) -> Path | None:
        root = Path(__file__).resolve().parent.parent
        candidates = [
            Path(filename),
            root / filename,
            Path(__file__).resolve().parent / filename,
            Path("/kaggle_simulations/agent") / filename,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def __call__(self, obs_dict: dict) -> list[int]:
        if not obs_dict or obs_dict.get("select") is None:
            self.errors = 0
            self.lucario_routed = False
            self.mirror_routed = False
            if getattr(self, "mirror_evidence", None) is not None:
                self.mirror_evidence.reset(self.director.hypotheses)
            if getattr(self, "director", None) is not None:
                self.director.reset()
            self.route_telemetry = {
                "mirror_activations": 0,
                "mirror_activation_step": None,
                "mirror_evidence": [],
            }
            for policy in (self.policy, self.specialist, self.mirror_specialist, getattr(self, "routed_fallback", None), *getattr(self, "director_proposers", [])):
                if policy is not None and hasattr(policy, "reset"):
                    policy.reset()
            return list(self.deck)
        obs = to_observation_class(obs_dict)
        try:
            if getattr(self, "director", None) is not None and getattr(self, "mirror_evidence", None) is not None:
                from .director import RouteStatus

                base_action = self.policy.choose(obs)
                step = int(obs_dict.get("step", obs.current.turnActionCount if obs.current else 0) or 0)
                status = self.mirror_evidence.observe(obs, self.director.hypotheses, step)
                self.mirror_routed = status == RouteStatus.COMPATIBLE
                self.route_telemetry = self.mirror_evidence.telemetry()
                self.route_telemetry["director"] = self.director.telemetry()
                if status == RouteStatus.COMPATIBLE:
                    routed_action = self.routed_fallback.choose(obs)
                    proposals = [base_action, routed_action]
                    for proposer in self.director_proposers:
                        proposals.append(proposer.choose(obs))
                    turn = int(obs.current.turn)
                    first = int(obs.current.firstPlayer)
                    own = int(obs.current.yourIndex)
                    own_turn_ordinal = (turn + 1) // 2 if own == first else turn // 2
                    action = self.director.choose(obs_dict, routed_action, proposals, own_turn_ordinal)
                    self.route_telemetry["director"] = self.director.telemetry()
                    return action
                if status == RouteStatus.DISQUALIFIED:
                    return base_action
            # Grimmsnarl-mirror specialist takes precedence once the mirror is
            # publicly revealed; the latch holds for the rest of the game and is
            # reset above during the deck-handshake observation.
            mirror_detected = (
                not self.mirror_routed
                and self.mirror_specialist is not None
                and grimmsnarl_mirror_publicly_detected(obs, self.deck)
            )
            if mirror_detected:
                visible = sorted(_public_card_ids(obs))
                self.route_telemetry = {
                    "mirror_activations": 1,
                    "mirror_activation_step": int(obs_dict.get("step", 0) or 0),
                    "mirror_evidence": visible,
                }
            if self.mirror_specialist is not None and (self.mirror_routed or mirror_detected):
                self.mirror_routed = True
                return self.mirror_specialist.choose(obs)
            if self.specialist is not None and (
                self.lucario_routed or lucario_publicly_detected(obs)
            ):
                self.lucario_routed = True
                return self.specialist.choose(obs)
            return self.policy.choose(obs)
        except Exception:
            self.errors += 1
            try:
                return self.fallback.choose(obs)
            except Exception:
                return emergency_selection(obs.select)
