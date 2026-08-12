"""Isolated runtime coordinator for the frozen Grimmsnarl d842 ranking.

This module contains no model or archive loading.  A caller supplies the exact
d842-ranked legal option indices and desired selection count.  The coordinator
then applies the narrow layers in one fixed order:

1. preserve d842's exact sanitized action as the global fallback;
2. apply ``GrimGuardrailDirector``;
3. admit only tactical shield's attack invariants (never its generic setup rule);
4. sanitize and commit that actual setup action exactly once; and
5. offer the committed action to ``RuntimeProofDirector``.

No option index is retained after the call.  Guardrail/coordinator failures fall
back to d842; proof failures fall back to the already-sanitized guardrail action.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from cg.api import SelectContext, to_observation_class

from .grim_guardrails import GrimGuardrailDirector
from .safety import sanitize_selection
from .tactical_shield import apply_tactical_shield


_ATTACK_TACTICAL_REASONS = frozenset(
    {
        "nullified_attack",
        "end_with_productive_attack",
    }
)
_SETUP_CONTEXTS = frozenset(
    {
        int(SelectContext.SETUP_ACTIVE_POKEMON),
        int(SelectContext.SETUP_BENCH_POKEMON),
    }
)
SEARCH_DISABLED_RATIONALE = (
    "development_native_audit:0_terminal_branches_of_100;"
    "nondeterministic_classifications"
)


def _integer(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_setup_prompt(obs: Any) -> bool:
    select = getattr(obs, "select", None)
    return select is not None and _integer(getattr(select, "context", None)) in _SETUP_CONTEXTS


def _proof_reason(proof: Any) -> str | None:
    """Read only a named in-memory reason from a proof component, if exposed."""

    payload = getattr(proof, "telemetry", None)
    if callable(payload):
        payload = payload()
    if not isinstance(payload, Mapping):
        return None
    last = payload.get("last")
    if not isinstance(last, Mapping):
        return None
    reason = last.get("reason")
    return str(reason) if reason is not None else None


class SearchDisabledProof:
    """Packaged no-op proof used when native runtime search is not admitted."""

    def reset(self) -> None:
        self._calls = 0

    def choose(self, _obs: Any, baseline_action: Sequence[int]) -> list[int]:
        self._calls += 1
        return list(baseline_action)

    @property
    def telemetry(self) -> dict[str, Any]:
        return {
            "phase": "runtime_proof",
            "calls": int(self._calls),
            "last": {
                "status": "disabled",
                "reason": SEARCH_DISABLED_RATIONALE,
            },
        }


class GrimRuntimePolicy:
    """Coordinate narrow guardrails, attack invariants, and terminal proof."""

    def __init__(
        self,
        hero_deck: Sequence[int] | None = None,
        *,
        guardrail: Any | None = None,
        proof: Any | None = None,
        proof_config: Any | None = None,
        tactical: Callable[[Any, list[int], int], tuple[list[int], int, str | None]]
        | None = None,
    ) -> None:
        self.guardrail = guardrail if guardrail is not None else GrimGuardrailDirector()
        if proof is None:
            if hero_deck is None:
                raise ValueError("hero_deck is required when no proof component is supplied")
            # Lazy import keeps search code and native search dependencies out of
            # explicitly search-disabled candidate packages.
            from .runtime_proof_director import RuntimeProofDirector

            proof = RuntimeProofDirector(hero_deck, config=proof_config)
        self.proof = proof
        self._tactical = tactical if tactical is not None else apply_tactical_shield
        self.reset()

    def reset(self) -> None:
        """Reset coordinator telemetry and both stateful child components."""

        self._calls = 0
        self._outcomes: Counter[str] = Counter()
        self._reasons: Counter[str] = Counter()
        self._last: dict[str, Any] = {
            "status": "reset",
            "source": "none",
            "guardrail_reason": None,
            "tactical_reason": None,
            "suppressed_tactical_reason": None,
            "proof_reason": None,
            "commit_attempted": False,
            "error_stage": None,
            "error_type": None,
        }
        errors: list[Exception] = []
        for component in (self.guardrail, self.proof):
            try:
                component.reset()
            except Exception as exc:
                errors.append(exc)
        if errors:
            self._last["status"] = "reset_error"
            self._last["error_stage"] = "reset"
            self._last["error_type"] = type(errors[0]).__name__
            raise RuntimeError("Grim runtime component reset failed") from errors[0]

    def telemetry(self) -> dict[str, Any]:
        """Return named in-memory telemetry; actions and option indices are omitted."""

        guardrail_telemetry = getattr(self.guardrail, "telemetry", None)
        if callable(guardrail_telemetry):
            guardrail_telemetry = guardrail_telemetry()
        if not isinstance(guardrail_telemetry, Mapping):
            guardrail_telemetry = {}
        return {
            "calls": int(self._calls),
            "outcomes": dict(sorted(self._outcomes.items())),
            "reasons": dict(sorted(self._reasons.items())),
            "guardrail": dict(guardrail_telemetry),
            "last": dict(self._last),
        }

    def _record(
        self,
        *,
        status: str,
        source: str,
        guardrail_reason: str | None = None,
        tactical_reason: str | None = None,
        suppressed_tactical_reason: str | None = None,
        proof_reason: str | None = None,
        commit_attempted: bool = False,
        error_stage: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self._outcomes[status] += 1
        for reason in (
            guardrail_reason,
            tactical_reason,
            f"suppressed:{suppressed_tactical_reason}"
            if suppressed_tactical_reason is not None
            else None,
            proof_reason,
            f"error:{error_stage}" if error_stage is not None else None,
        ):
            if reason is not None:
                self._reasons[str(reason)] += 1
        self._last = {
            "status": status,
            "source": source,
            "guardrail_reason": guardrail_reason,
            "tactical_reason": tactical_reason,
            "suppressed_tactical_reason": suppressed_tactical_reason,
            "proof_reason": proof_reason,
            "commit_attempted": bool(commit_attempted),
            "error_stage": error_stage,
            "error_type": None if error is None else type(error).__name__,
        }

    def choose(
        self,
        obs_or_dict: Any,
        d842_ranked: Sequence[int],
        desired_count: int | None,
    ) -> list[int]:
        """Return the coordinated action while preserving stage-specific fallthroughs."""

        self._calls += 1
        obs = to_observation_class(obs_or_dict) if isinstance(obs_or_dict, dict) else obs_or_dict
        ranked = list(d842_ranked)
        # This immutable-by-convention copy is the exact d842 safety boundary and
        # is never replaced by a later layer's output.
        d842_action = sanitize_selection(obs.select, ranked, desired_count)
        normalized_desired = len(d842_action)
        committed = False

        def commit_once(action: Sequence[int]) -> None:
            nonlocal committed
            if committed:
                raise RuntimeError("setup action commit attempted more than once")
            committed = True
            self.guardrail.commit(obs, list(action))

        try:
            try:
                guarded_ranked, guarded_desired, guardrail_reason = self.guardrail.apply(
                    obs,
                    list(ranked),
                    normalized_desired,
                )
            except Exception as exc:
                try:
                    commit_once(d842_action)
                except Exception:
                    pass
                self._record(
                    status="d842_fallthrough",
                    source="d842",
                    commit_attempted=committed,
                    error_stage="guardrail",
                    error=exc,
                )
                return list(d842_action)

            try:
                proposed_ranked, proposed_desired, proposed_reason = self._tactical(
                    obs,
                    list(guarded_ranked),
                    int(guarded_desired),
                )
            except Exception as exc:
                try:
                    commit_once(d842_action)
                except Exception:
                    pass
                self._record(
                    status="d842_fallthrough",
                    source="d842",
                    guardrail_reason=guardrail_reason,
                    commit_attempted=committed,
                    error_stage="tactical",
                    error=exc,
                )
                return list(d842_action)

            tactical_reason: str | None = None
            suppressed_reason: str | None = None
            if proposed_reason in _ATTACK_TACTICAL_REASONS:
                final_ranked = list(proposed_ranked)
                final_desired = int(proposed_desired)
                tactical_reason = str(proposed_reason)
            else:
                # In particular, setup_bench_basic is never admitted.  Unknown
                # future shield rules are suppressed by the same allowlist.
                final_ranked = list(guarded_ranked)
                final_desired = int(guarded_desired)
                if proposed_reason is not None:
                    suppressed_reason = str(proposed_reason)

            guarded_action = sanitize_selection(obs.select, final_ranked, final_desired)
            commit_once(guarded_action)

            try:
                proof_output = list(self.proof.choose(obs, list(guarded_action)))
                # RuntimeProofDirector is restricted away from setup.  Enforce
                # that boundary here too, because commit necessarily precedes it.
                if _is_setup_prompt(obs) and proof_output != guarded_action:
                    raise ValueError("proof attempted to alter a committed setup action")
                proof_action = sanitize_selection(obs.select, proof_output, len(proof_output))
                if proof_action != proof_output:
                    raise ValueError("proof returned an invalid selection")
            except Exception as exc:
                fallback_source = (
                    "tactical"
                    if tactical_reason is not None
                    else "guardrail"
                    if guarded_action != d842_action
                    else "d842"
                )
                self._record(
                    status="proof_fallthrough",
                    source=fallback_source,
                    guardrail_reason=guardrail_reason,
                    tactical_reason=tactical_reason,
                    suppressed_tactical_reason=suppressed_reason,
                    proof_reason="proof_error",
                    commit_attempted=committed,
                    error_stage="proof",
                    error=exc,
                )
                return list(guarded_action)

            proof_reason = _proof_reason(self.proof)
            if proof_action != guarded_action:
                status = "proof_override"
                source = "proof"
            elif tactical_reason is not None:
                status = "tactical_action"
                source = "tactical"
            elif guarded_action != d842_action:
                status = "guardrail_action"
                source = "guardrail"
            else:
                status = "d842_action"
                source = "d842"
            self._record(
                status=status,
                source=source,
                guardrail_reason=guardrail_reason,
                tactical_reason=tactical_reason,
                suppressed_tactical_reason=suppressed_reason,
                proof_reason=proof_reason,
                commit_attempted=committed,
            )
            return proof_action
        except Exception as exc:
            if not committed:
                try:
                    commit_once(d842_action)
                except Exception:
                    pass
            self._record(
                status="d842_fallthrough",
                source="d842",
                commit_attempted=committed,
                error_stage="coordinator",
                error=exc,
            )
            return list(d842_action)


__all__ = ["GrimRuntimePolicy", "SEARCH_DISABLED_RATIONALE", "SearchDisabledProof"]
