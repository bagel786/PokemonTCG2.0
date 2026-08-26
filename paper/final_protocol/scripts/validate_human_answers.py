#!/usr/bin/env python3
"""Validate paper/final_protocol/human_answers.yaml (the human answer file).

Fail-closed: every rule below must hold or the validator exits nonzero with a
list of problems. It never infers, defaults, or repairs an answer. The
template is never valid input.

Supported YAML subset: comments; nested mappings by 2-space indent; lists via
"- " items (scalar or inline mapping start); plain/quoted scalars. If PyYAML
is installed it is used instead.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

FINAL = Path(__file__).resolve().parents[1]
ANSWERS = FINAL / "human_answers.yaml"
TEMPLATE = FINAL / "human_answers.template.yaml"

PLACEHOLDER = re.compile(r"^\[.*\]$|^\s*$|TODO|FIXME|<>|RECOMMENDATION:")
ORCID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CREDIT_ROLES = {
    "Conceptualization", "Methodology", "Software", "Validation",
    "Formal_analysis", "Investigation", "Data_curation", "Visualization",
    "Writing_original_draft", "Writing_review_editing", "Supervision",
    "Project_administration", "Funding_acquisition",
}


class MiniYaml:
    """Tiny parser for the constrained template syntax."""

    def __init__(self, text: str) -> None:
        self.lines: list[tuple[int, str]] = []
        for raw in text.splitlines():
            stripped = re.sub(r"(^|\s)#.*$", "", raw).rstrip()
            if not stripped.strip():
                continue
            indent = len(stripped) - len(stripped.lstrip(" "))
            self.lines.append((indent, stripped.strip()))

    def parse(self) -> dict:
        value, _ = self._parse_block(0, 0)
        return value

    def _parse_block(self, index: int, indent: int):
        if index < len(self.lines) and self.lines[index][1].startswith("- "):
            items, index = self._parse_list(index, indent)
            return items, index
        mapping: dict = {}
        while index < len(self.lines):
            line_indent, content = self.lines[index]
            if line_indent < indent or (line_indent == indent and not mapping):
                pass
            if line_indent != indent:
                break
            key, _, rest = content.partition(":")
            key = key.strip().strip('"').strip("'")
            rest = rest.strip()
            index += 1
            if rest:
                mapping[key] = self._scalar(rest)
            else:
                child_indent = self.lines[index][0] if index < len(self.lines) else -1
                if child_indent > line_indent:
                    value, index = self._parse_block(index, child_indent)
                elif child_indent == line_indent and index < len(self.lines) and self.lines[index][1].startswith("- "):
                    value, index = self._parse_list(index, line_indent)
                else:
                    value = ""
                mapping[key] = value
        return mapping, index

    def _parse_list(self, index: int, indent: int):
        items: list = []
        while index < len(self.lines):
            line_indent, content = self.lines[index]
            if line_indent != indent or not content.startswith("- "):
                break
            item_text = content[2:].strip()
            index += 1
            if ":" in item_text and not item_text.startswith(("[", '"', "'")):
                # inline mapping start: rewrite current line as nested mapping
                key, _, rest = item_text.partition(":")
                saved = self.lines[index - 1]
                self.lines[index - 1] = (indent + 2, f"{key.strip()}: {rest.strip()}")
                submap_consumes_list_slot = True
                mapping: dict = {}
                probe_index = index
                first_key = key.strip()
                rest_value = rest.strip()
                if rest_value:
                    mapping[first_key] = self._scalar(rest_value)
                else:
                    child_indent = self.lines[probe_index][0] if probe_index < len(self.lines) else -1
                    if child_indent > indent + 2:
                        mapping[first_key], probe_index = self._parse_block(probe_index, child_indent)
                while probe_index < len(self.lines):
                    li, c = self.lines[probe_index]
                    if li <= indent:
                        break
                    key2, _, rest2 = c.partition(":")
                    key2 = key2.strip()
                    rest2 = rest2.strip()
                    probe_index += 1
                    if rest2:
                        mapping[key2] = self._scalar(rest2)
                    else:
                        ci = self.lines[probe_index][0] if probe_index < len(self.lines) else -1
                        if ci > li:
                            mapping[key2], probe_index = self._parse_block(probe_index, ci)
                        else:
                            mapping[key2] = ""
                index = probe_index
                del submap_consumes_list_slot
                items.append(mapping)
            else:
                items.append(self._scalar(item_text))
        return items, index

    @staticmethod
    def _scalar(token: str):
        token = token.strip()
        if token in ("true", "True"):
            return True
        if token in ("false", "False"):
            return False
        if re.fullmatch(r"-?\d+", token):
            return int(token)
        if (token.startswith('"') and token.endswith('"')) or (
            token.startswith("'") and token.endswith("'")
        ):
            return token[1:-1]
        return token


def load_yaml(path: Path):
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        return MiniYaml(text).parse()


def flat_placeholders(value) -> list[str]:
    problems: list[str] = []

    def walk(node, trail):
        if isinstance(node, dict):
            for key, item in node.items():
                walk(item, f"{trail}.{key}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{trail}[{i}]")
        elif isinstance(node, str) and PLACEHOLDER.match(node.strip()):
            problems.append(f"placeholder/unanswered at {trail}: {node.strip()[:60]!r}")

    walk(value, "$")
    return problems


def main() -> int:
    if not ANSWERS.is_file():
        print(json.dumps({"status": "FAIL", "problems": [
            f"{ANSWERS.name} not found. Copy human_answers.template.yaml to {ANSWERS.name} and fill it."
        ]}))
        return 1
    data = load_yaml(ANSWERS)
    template_data = load_yaml(TEMPLATE)
    problems: list[str] = []

    if data == template_data:
        problems.append("answers file is an unmodified copy of the template")

    problems += [f"meta: {p}" for p in flat_placeholders(data.get("meta", {}))]

    authors = data.get("authors") or []
    if not isinstance(authors, list) or not authors:
        problems.append("authors: at least one author is required")
    names = []
    corresponding = 0
    for i, author in enumerate(authors):
        tag = f"authors[{i}]"
        name = str(author.get("publication_name", "")).strip()
        names.append(name)
        if not name or PLACEHOLDER.match(name):
            problems.append(f"{tag}.publication_name missing/placeholder")
        if not EMAIL.match(str(author.get("email", ""))):
            problems.append(f"{tag}.email missing or invalid (every author needs one)")
        orcid = str(author.get("orcid", "")).strip()
        if orcid.upper() != "DECLINE" and not ORCID.match(orcid):
            problems.append(f"{tag}.orcid must be 16-digit form 0000-0000-0000-0000 or DECLINE")
        for field in ("affiliation", "postal_address", "coauthor_eligibility_basis"):
            value = str(author.get(field, "")).strip()
            if not value or PLACEHOLDER.match(value):
                problems.append(f"{tag}.{field} missing/placeholder")
        if author.get("corresponding_author") is True:
            corresponding += 1
            if orcid.upper() == "DECLINE":
                problems.append(f"{tag}: corresponding author may not DECLINE an ORCID (APS requires it)")
    if corresponding != 1:
        problems.append(f"exactly one corresponding_author required; found {corresponding}")
    orders = [a.get("author_order") for a in authors]
    if sorted(x for x in orders if isinstance(x, int)) != list(range(1, len(authors) + 1)):
        problems.append("author_order must be a permutation of 1..N")

    credit = data.get("credit_roles") or {}
    for role_set in credit.values():
        if isinstance(role_set, list):
            bad = [r for r in role_set if str(r) not in CREDIT_ROLES]
            if bad:
                problems.append(f"credit_roles unknown entries: {bad}")
    if credit.get("confirmation_ai_not_credited") is not True:
        problems.append("credit_roles.confirmation_ai_not_credited must be true")

    for section in ("funding", "conflicts"):
        sec = data.get(section) or {}
        for key, value in sec.items():
            if isinstance(value, str) and PLACEHOLDER.match(value.strip()):
                problems.append(f"{section}.{key} unanswered: {value.strip()[:60]!r}")

    ack = data.get("acknowledgments") or {}
    if ack.get("permission_confirmed") is not True:
        problems.append("acknowledgments.permission_confirmed must be true (or acknowledge NONE and confirm)")

    overlap = data.get("overlap") or {}
    text = str(overlap.get("cover_letter_disclosure_text", "")).strip()
    if not text or PLACEHOLDER.match(text):
        problems.append("overlap.cover_letter_disclosure_text must contain the exact approved disclosure language")

    ai = data.get("ai_use") or {}
    for key in ("codex_confirmation_complete", "chatgpt_confirmation_complete",
                "confidentiality_confirmation", "ip_tool_terms_confirmation",
                "final_disclosure_approval"):
        if ai.get(key) is not True:
            problems.append(f"ai_use.{key} must be explicit true")
    other = str(ai.get("other_tools", "")).strip()
    missing = str(ai.get("missing_historical_uses", "")).strip()
    if PLACEHOLDER.match(other):
        problems.append("ai_use.other_tools unanswered (state NONE explicitly)")
    if PLACEHOLDER.match(missing):
        problems.append("ai_use.missing_historical_uses unanswered (state NONE explicitly)")

    rr = data.get("release_rights") or {}
    owners = rr.get("owner_per_component") or {}
    for key, value in owners.items():
        if isinstance(value, str) and PLACEHOLDER.match(value.strip()):
            problems.append(f"release_rights.owner_per_component.{key} unanswered")
    code_ok = rr.get("code_redistribution_approved") is True
    data_ok = rr.get("processed_data_redistribution_approved") is True
    archive = rr.get("archive_authorized") is True
    code_license = str(rr.get("code_license", "")).strip()
    data_license = str(rr.get("data_docs_license", "")).strip()
    if PLACEHOLDER.match(code_license):
        problems.append("release_rights.code_license must be actively confirmed (not left as a recommendation)")
    if PLACEHOLDER.match(data_license):
        problems.append("release_rights.data_docs_license must be actively confirmed")
    if archive and not (code_ok and data_ok):
        problems.append("archive_authorized=true requires both redistribution approvals true")
    if archive and code_license == "" or archive and data_license == "":
        problems.append("archive_authorized=true requires concrete licenses")
    doi = str(rr.get("doi", "")).strip()
    if doi and not archive:
        problems.append("DOI inserted while archive_authorized is false — blocked")
    creators = str(rr.get("archive_creators", "")).strip()
    maintainer = str(rr.get("maintainer", "")).strip()
    if archive and (not creators or PLACEHOLDER.match(creators)):
        problems.append("archive authorized but archive_creators missing")
    if archive and (not maintainer or PLACEHOLDER.match(maintainer)):
        problems.append("archive authorized but maintainer contact missing")

    d03 = data.get("d03") or {}
    for key in ("positions_never_recorded_confirmed", "actor_counts_recovered_confirmed",
                "timings_recovered_confirmed", "deviation_record_approved"):
        if d03.get(key) is not True:
            problems.append(f"d03.{key} must be explicit true")
    if d03.get("redistribution_approved") is not False and d03.get("redistribution_approved") is not True:
        problems.append("d03.redistribution_approved must be explicit true/false")
    if d03.get("redistribution_approved") != rr.get("recovered_secondary_outputs_approved"):
        problems.append("d03.redistribution_approved must mirror release_rights.recovered_secondary_outputs_approved")
    if not DATE.match(str(d03.get("disposition_date", ""))):
        problems.append("d03.disposition_date must be YYYY-MM-DD (dated disposition required)")
    sig = str(d03.get("signature_text", "")).strip()
    if not sig or PLACEHOLDER.match(sig):
        problems.append("d03.signature_text missing")

    signoff = data.get("scientific_signoff") or {}
    for key, value in signoff.items():
        if not isinstance(value, bool):
            problems.append(f"scientific_signoff.{key} must be an explicit boolean (got {value!r})")

    prose = data.get("prose_review") or {}
    decisions = prose.get("passage_decisions") or {}
    for i in range(1, 9):
        decision = str(decisions.get(f"passage_{i}", "")).strip().upper()
        if decision not in {"ACCEPT", "REWRITE", "DISCUSS"}:
            problems.append(f"prose_review.passage_decisions.passage_{i} must be ACCEPT/REWRITE/DISCUSS")

    das_version = str(data.get("data_availability_version", "")).strip().upper()
    if das_version not in {"A", "B"}:
        problems.append("data_availability_version must be A or B")
    elif das_version == "A":
        if not (rr.get("code_redistribution_approved") and rr.get("processed_data_redistribution_approved")
                and archive and doi):
            problems.append("DAS Version A selected but ownership/license/archive/live-DOI prerequisites unmet")

    reviewers = data.get("suggested_reviewers") or {}
    approved = str(reviewers.get("approved_candidates", "")).strip()
    exclusions = str(reviewers.get("exclusions", "")).strip()
    if PLACEHOLDER.match(approved):
        problems.append("suggested_reviewers.approved_candidates unanswered (may be explicitly 'NONE')")
    if PLACEHOLDER.match(exclusions):
        problems.append("suggested_reviewers.exclusions unanswered (may be explicitly 'NONE')")

    status = "PASS" if not problems else "FAIL"
    print(json.dumps({"status": status, "problem_count": len(problems), "problems": problems}, indent=1))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
