"""Stage 6 source-audit outcome classification and decision-table rendering.

The table is generated solely from ``protocol/stage6_source_audit_rules.json``.
Classification is fail closed: unrecognized inputs default to ``UNRESOLVED``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

RULES_SCHEMA_VERSION = "stage6-source-audit-rules-1.0.0"
OUTCOME_ORDER = ("CONTROLLED", "RESIDUAL", "ESTIMAND_CHANGING", "UNAVAILABLE", "UNRESOLVED")
DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "protocol" / "stage6_source_audit_rules.json"


class Stage6RulesError(ValueError):
    """Raised when the stage 6 rules document is malformed."""


def load_rules(path: Path | None = None) -> dict[str, Any]:
    path = Path(path or DEFAULT_RULES_PATH)
    try:
        rules = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stage6RulesError(f"cannot load stage 6 rules: {exc}") from exc
    validate_rules(rules)
    return rules


def validate_rules(rules: Mapping[str, Any]) -> None:
    if rules.get("schema_version") != RULES_SCHEMA_VERSION:
        raise Stage6RulesError("unknown stage 6 rules schema version")
    outcome_ids = [outcome["id"] for outcome in rules.get("outcomes", [])]
    if outcome_ids != list(OUTCOME_ORDER):
        raise Stage6RulesError("stage 6 outcome set drifted")
    priorities = set()
    for rule in rules.get("rules", []):
        priority = rule.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool) or priority in priorities:
            raise Stage6RulesError("stage 6 rule priorities must be unique integers")
        priorities.add(priority)
        if rule.get("outcome") not in OUTCOME_ORDER:
            raise Stage6RulesError(f"rule {rule.get('id')} has unknown outcome")
    if sorted(priorities) != list(range(1, len(priorities) + 1)):
        raise Stage6RulesError("stage 6 rule priorities must be contiguous from 1")


def _hit_satisfied(hit_condition: Mapping[str, Any], hit: Mapping[str, Any]) -> bool:
    for field, expected in hit_condition.items():
        if hit.get(field) != expected:
            return False
    return bool(hit_condition)


def classify(
    *,
    source_access: str,
    inventory_declared: bool,
    hits: Sequence[Mapping[str, Any]] | None,
    rules: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify one audit input; fail closed to UNRESOLVED."""

    rules = rules if rules is not None else load_rules()
    hits = list(hits or [])
    context = {
        "source_access": source_access,
        "inventory_declared": bool(inventory_declared),
        "hits": hits,
    }
    matched_rule_id = None
    outcome = rules["default_outcome"]
    remediation = "Unrecognized audit input; rerun with a complete declared record."
    try:
        for rule in sorted(rules["rules"], key=lambda row: row["priority"]):
            original_when = rule.get("when", {})
            if not isinstance(original_when, dict):
                continue
            hit_condition = original_when.get("any_hit")
            plain = {
                key: value
                for key, value in original_when.items()
                if isinstance(value, (str, bool))
            }
            if any(context[key] != value for key, value in plain.items()):
                continue
            if "any_hit" in original_when:
                if hit_condition is None:
                    if hits:
                        continue
                elif not isinstance(hit_condition, dict):
                    continue
                else:
                    matching_hits = [
                        hit
                        for hit in hits
                        if isinstance(hit, Mapping) and _hit_satisfied(hit_condition, hit)
                    ]
                    if not matching_hits:
                        continue
            matched_rule_id = rule["id"]
            outcome = rule["outcome"]
            remediation = rule["remediation"]
            break
    except (KeyError, TypeError):
        matched_rule_id = None
        outcome = rules["default_outcome"]
        remediation = "Malformed audit input; classification failed closed."
    return {
        "outcome": outcome,
        "matched_rule": matched_rule_id,
        "remediation": remediation,
        "hits_considered": len(hits),
    }


def render_decision_table(rules: Mapping[str, Any] | None = None) -> str:
    """Render the human decision table solely from the validated JSON rules."""

    rules = rules if rules is not None else load_rules()
    lines = [
        "# Stage 6 stochastic-source audit decision rules",
        "",
        "Generated from `protocol/stage6_source_audit_rules.json`; do not edit this "
        "table independently.",
        "",
        "> A static hit does not prove execution dependence; a clean scan does not "
        "> prove determinism.",
        "",
        "## Outcomes",
        "",
        "| Outcome | Meaning | Claim effect |",
        "|---|---|---|",
    ]
    for outcome in rules["outcomes"]:
        meaning = outcome["meaning"].replace("|", "\\|")
        effect = outcome["claim_effect"].replace("|", "\\|")
        lines.append(f"| `{outcome['id']}` | {meaning} | {effect} |")
    lines.extend(
        [
            "",
            "## Ordered decision rules",
            "",
            "| Priority | Rule | Condition summary | Outcome | Required remediation |",
            "|---:|---|---|---|---|",
        ]
    )
    for rule in sorted(rules["rules"], key=lambda row: row["priority"]):
        when = rule.get("when", {})
        parts = []
        for key, value in when.items():
            if key == "any_hit":
                if value is None:
                    parts.append("no hits")
                elif isinstance(value, dict) and value:
                    inner = ", ".join(f"{field}={value_field}" for field, value_field in value.items())
                    parts.append(f"a hit with {inner}")
                else:
                    parts.append("any hit present")
            else:
                parts.append(f"{key}={value}")
        condition = "; ".join(parts) if parts else "default"
        remediation = rule["remediation"].replace("|", "\\|")
        lines.append(
            f"| {rule['priority']} | `{rule['id']}` | {condition} | "
            f"`{rule['outcome']}` | {remediation} |"
        )
    lines.extend(
        [
            "",
            "Fail-closed default: `" + rules["default_outcome"] + "` — " + rules["fail_closed_note"],
            "",
        ]
    )
    return "\n".join(lines) + "\n"
