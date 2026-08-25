#!/usr/bin/env python3
"""Fail-closed verification of the Protocol Article research audits.

This verifier does not perform a literature search.  It checks that the dated
research-audit artifacts are structurally complete, internally consistent, and
bound to the cited bibliography and the exact manuscript wording they claim to
support.  Any malformed, missing, or unverified cited record is a failure.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Callable


SCRIPT = Path(__file__).resolve()
FINAL = SCRIPT.parents[1]

CHOSEN_TITLE = (
    "A Protocol for Validating Pairing Assumptions in Seed-Matched Evaluations of "
    "Black-Box Game-Playing Agents"
)

NOVELTY_MATRIX_FIELDS = [
    "source_id",
    "exact_title",
    "authors",
    "year",
    "venue_or_status",
    "doi_or_identifier",
    "primary_source",
    "research_problem",
    "method",
    "artifact_type",
    "validation",
    "overlap_with_this_work",
    "difference_from_this_work",
    "remaining_novelty",
    "manuscript_sentence_supported",
    "verified",
    "notes",
]

REFERENCE_AUDIT_FIELDS = [
    "bibkey",
    "exact_title",
    "all_authors",
    "year",
    "venue",
    "volume",
    "pages_or_article",
    "doi_or_canonical_identifier",
    "publication_status",
    "primary_source",
    "exact_manuscript_sentence_supported",
    "verified",
    "notes",
]

SEARCH_LOG_TOP_LEVEL_FIELDS = {
    "audit_date",
    "timezone",
    "cutoff_statement",
    "source_policy",
    "title_candidates",
    "resolved_close_records",
    "searches",
    "citing_and_forward_searches",
    "aps_policy_checks",
    "unresolved_records_retained",
    "fatal_novelty_test",
}

REQUIRED_CLOSE_BIBKEYS = {
    "sharma2025pairedseeds",
    "buffalo2026eventkeyed",
    "masters2026rolloutcards",
    "paduraru2026traceassurance",
    "anand2026aeval",
}

REQUIRED_CLOSE_IDENTIFIERS = {
    "arXiv:2605.12131",
    "10.5220/0014840300004015",
    "arXiv:2607.16345",
    "arXiv:2603.11084",
}


class AuditFailure(ValueError):
    """Raised when an audit artifact fails a closed-world check."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditFailure(message)


def reject_json_constant(value: str) -> None:
    raise AuditFailure(f"non-finite JSON constant prohibited: {value}")


def parse_finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise AuditFailure(f"non-finite JSON number prohibited: {value}")
    return result


def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuditFailure(f"duplicate JSON key prohibited: {key}")
        result[key] = value
    return result


def load_json_strict(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_json_constant,
            parse_float=parse_finite_float,
            object_pairs_hook=reject_duplicate_pairs,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditFailure(f"cannot load strict JSON {path.name}: {exc}") from exc


def nonempty_string(value: Any, context: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{context} must be a nonempty string")
    return value.strip()


def string_list(value: Any, context: str, *, allow_empty: bool = False) -> list[str]:
    require(isinstance(value, list), f"{context} must be a list")
    if not allow_empty:
        require(bool(value), f"{context} must not be empty")
    for index, item in enumerate(value):
        nonempty_string(item, f"{context}[{index}]")
    return value


def read_csv_exact(path: Path, expected_fields: list[str]) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            require(reader.fieldnames == expected_fields, (
                f"{path.name} columns differ: expected {expected_fields!r}, "
                f"observed {reader.fieldnames!r}"
            ))
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise AuditFailure(f"cannot load CSV {path.name}: {exc}") from exc
    require(bool(rows), f"{path.name} must contain at least one data row")
    for number, row in enumerate(rows, 2):
        require(None not in row, f"{path.name}:{number} contains excess columns")
        require(all(value is not None for value in row.values()), f"{path.name}:{number} is malformed")
    return rows


def strip_tex_comments(text: str) -> str:
    return re.sub(r"(?m)(?<!\\)%.*$", "", text)


def canonical_prose(text: str) -> str:
    """Normalize only TeX/Markdown presentation, not substantive wording."""

    text = strip_tex_comments(text)
    text = re.sub(
        r"\\(?:cite|citep|citet|citealp|citeauthor|citeyear|nocite)\w*"
        r"(?:\s*\[[^\]]*\])*\s*\{[^{}]*\}",
        "",
        text,
    )
    text = text.replace("---", "-").replace("--", "-")
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = text.replace("~", " ").replace("``", '"').replace("''", '"')
    text = re.sub(r"\\([%&_#$])", r"\1", text)
    text = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", "", text)
    text = text.replace("{", "").replace("}", "")
    # Preserve literal underscores because machine-readable decision tokens use
    # them (for example, NOT_READY_DO_NOT_SUBMIT).  The audited prose does not
    # rely on underscore-delimited Markdown emphasis.
    text = re.sub(r"\*\*|[*`]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text


def assert_sentence_present(sentence: str, manuscript_canonical: str, context: str) -> None:
    supported = canonical_prose(sentence)
    require(bool(supported), f"{context} has an empty support sentence")
    require(supported in manuscript_canonical, f"{context} support sentence is absent from main.tex: {sentence!r}")


def citation_keys(tex: str) -> set[str]:
    text = strip_tex_comments(tex)
    pattern = re.compile(
        r"\\(?:cite|citep|citet|citealp|citeauthor|citeyear|nocite)\w*"
        r"(?:\s*\[[^\]]*\])*\s*\{([^{}]+)\}"
    )
    keys: set[str] = set()
    for match in pattern.finditer(text):
        for raw in match.group(1).split(","):
            key = raw.strip()
            require(bool(key) and key != "*", f"invalid or wildcard citation key: {raw!r}")
            require(re.fullmatch(r"[A-Za-z0-9_.:+/-]+", key) is not None, f"malformed citation key: {key!r}")
            keys.add(key)
    require(bool(keys), "main.tex contains no parsed bibliography citations")
    return keys


def balanced_value(text: str, start: int) -> tuple[str, int]:
    if start >= len(text) or text[start] not in '{"':
        raise AuditFailure("BibTeX field value must start with a brace or quote")
    opener = text[start]
    if opener == '"':
        index = start + 1
        while index < len(text):
            if text[index] == '"' and text[index - 1] != "\\":
                return text[start + 1:index], index + 1
            index += 1
        raise AuditFailure("unterminated quoted BibTeX value")
    depth = 1
    index = start + 1
    while index < len(text):
        if text[index] == "{" and text[index - 1] != "\\":
            depth += 1
        elif text[index] == "}" and text[index - 1] != "\\":
            depth -= 1
            if depth == 0:
                return text[start + 1:index], index + 1
        index += 1
    raise AuditFailure("unterminated braced BibTeX value")


def bib_entries(text: str) -> dict[str, dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}
    starts = list(re.finditer(r"@([A-Za-z]+)\s*\{\s*([^,\s]+)\s*,", text))
    require(bool(starts), "references.bib contains no BibTeX entries")
    for position, match in enumerate(starts):
        key = match.group(2)
        require(key not in entries, f"duplicate BibTeX key prohibited: {key}")
        end = starts[position + 1].start() if position + 1 < len(starts) else len(text)
        body = text[match.end():end]
        fields: dict[str, str] = {}
        for field_match in re.finditer(r"(?m)^\s*([A-Za-z][A-Za-z0-9_]*)\s*=\s*", body):
            field = field_match.group(1).lower()
            require(field not in fields, f"duplicate BibTeX field {field!r} in {key}")
            value_start = field_match.end()
            while value_start < len(body) and body[value_start].isspace():
                value_start += 1
            value, _ = balanced_value(body, value_start)
            fields[field] = value.strip()
        require("title" in fields and "year" in fields and "author" in fields, f"BibTeX entry {key} lacks title, year, or author")
        entries[key] = fields
    return entries


def canonical_title(text: str) -> str:
    text = text.replace("{", "").replace("}", "")
    text = text.replace("---", "-").replace("--", "-")
    return re.sub(r"\s+", " ", text).strip()


class ResearchAuditVerifier:
    def __init__(self, final: Path = FINAL) -> None:
        self.final = final.resolve()
        self.checks: list[dict[str, Any]] = []
        self.failures: list[str] = []

    def check(self, check_id: str, operation: Callable[[], dict[str, Any] | None]) -> None:
        try:
            detail = operation() or {}
        except Exception as exc:  # fail closed, including unexpected parser errors
            message = f"{check_id}: {type(exc).__name__}: {exc}"
            self.checks.append({"check_id": check_id, "status": "FAIL", "message": str(exc)})
            self.failures.append(message)
        else:
            self.checks.append({"check_id": check_id, "status": "PASS", **detail})

    def verify_matrix_and_references(self) -> dict[str, Any]:
        matrix_path = self.final / "NOVELTY_MATRIX.csv"
        reference_path = self.final / "REFERENCE_AUDIT.csv"
        manuscript_path = self.final / "main.tex"
        bib_path = self.final / "references.bib"

        matrix = read_csv_exact(matrix_path, NOVELTY_MATRIX_FIELDS)
        references = read_csv_exact(reference_path, REFERENCE_AUDIT_FIELDS)
        tex = manuscript_path.read_text(encoding="utf-8")
        manuscript = canonical_prose(tex)
        cited = citation_keys(tex)
        bib = bib_entries(bib_path.read_text(encoding="utf-8"))

        reference_keys = [row["bibkey"].strip() for row in references]
        require(len(reference_keys) == len(set(reference_keys)), "REFERENCE_AUDIT.csv contains duplicate bibkeys")
        require(set(reference_keys) == cited, (
            f"reference-audit/citation mismatch: missing audit rows={sorted(cited - set(reference_keys))}, "
            f"uncited audit rows={sorted(set(reference_keys) - cited)}"
        ))
        require(set(bib) == cited, (
            f"bibliography/citation mismatch: missing BibTeX entries={sorted(cited - set(bib))}, "
            f"uncited BibTeX entries={sorted(set(bib) - cited)}"
        ))

        references_by_key = {row["bibkey"].strip(): row for row in references}
        for number, row in enumerate(references, 2):
            context = f"REFERENCE_AUDIT.csv:{number} ({row['bibkey']})"
            for field in REFERENCE_AUDIT_FIELDS:
                if field != "volume":
                    nonempty_string(row[field], f"{context}.{field}")
            require(row["verified"] == "TRUE", f"{context} is not strictly verified TRUE")
            require(re.fullmatch(r"\d{4}", row["year"].strip()) is not None, f"{context} has an invalid year")
            require(row["primary_source"].startswith("https://"), f"{context} lacks an HTTPS primary source")
            assert_sentence_present(row["exact_manuscript_sentence_supported"], manuscript, context)
            entry = bib[row["bibkey"].strip()]
            require(canonical_title(entry["title"]) == canonical_title(row["exact_title"]), f"{context} title disagrees with references.bib")
            require(canonical_title(entry["year"]) == row["year"].strip(), f"{context} year disagrees with references.bib")

        matrix_keys = [row["source_id"].strip() for row in matrix]
        require(len(matrix_keys) == len(set(matrix_keys)), "NOVELTY_MATRIX.csv contains duplicate source_ids")
        require(REQUIRED_CLOSE_BIBKEYS <= set(matrix_keys), f"NOVELTY_MATRIX.csv lacks required close works: {sorted(REQUIRED_CLOSE_BIBKEYS - set(matrix_keys))}")
        require(set(matrix_keys) <= set(reference_keys), f"NOVELTY_MATRIX.csv contains unaudited source IDs: {sorted(set(matrix_keys) - set(reference_keys))}")
        for number, row in enumerate(matrix, 2):
            context = f"NOVELTY_MATRIX.csv:{number} ({row['source_id']})"
            for field in NOVELTY_MATRIX_FIELDS:
                nonempty_string(row[field], f"{context}.{field}")
            require(row["verified"] == "TRUE", f"{context} is not strictly verified TRUE")
            require(re.fullmatch(r"\d{4}", row["year"].strip()) is not None, f"{context} has an invalid year")
            require(row["primary_source"].startswith("https://"), f"{context} lacks an HTTPS primary source")
            assert_sentence_present(row["manuscript_sentence_supported"], manuscript, context)
            reference = references_by_key[row["source_id"].strip()]
            for matrix_field, reference_field in (
                ("exact_title", "exact_title"),
                ("authors", "all_authors"),
                ("year", "year"),
                ("doi_or_identifier", "doi_or_canonical_identifier"),
                ("manuscript_sentence_supported", "exact_manuscript_sentence_supported"),
            ):
                require(row[matrix_field] == reference[reference_field], f"{context}.{matrix_field} disagrees with REFERENCE_AUDIT.csv")

        return {
            "matrix_rows": len(matrix),
            "reference_rows": len(references),
            "cited_bibkeys": len(cited),
            "verified_close_works": sorted(REQUIRED_CLOSE_BIBKEYS),
        }

    def verify_search_log(self) -> dict[str, Any]:
        log = load_json_strict(self.final / "NOVELTY_SEARCH_LOG.json")
        require(isinstance(log, dict), "NOVELTY_SEARCH_LOG.json top level must be an object")
        require(set(log) == SEARCH_LOG_TOP_LEVEL_FIELDS, (
            f"NOVELTY_SEARCH_LOG.json top-level fields differ: missing={sorted(SEARCH_LOG_TOP_LEVEL_FIELDS - set(log))}, "
            f"extra={sorted(set(log) - SEARCH_LOG_TOP_LEVEL_FIELDS)}"
        ))
        audit_date = nonempty_string(log["audit_date"], "audit_date")
        require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", audit_date) is not None, "audit_date must use YYYY-MM-DD")
        nonempty_string(log["timezone"], "timezone")
        nonempty_string(log["cutoff_statement"], "cutoff_statement")

        policy = log["source_policy"]
        require(isinstance(policy, dict) and set(policy) == {"admitted", "excluded_as_authority", "fail_closed"}, "source_policy has an invalid schema")
        string_list(policy["admitted"], "source_policy.admitted")
        string_list(policy["excluded_as_authority"], "source_policy.excluded_as_authority")
        nonempty_string(policy["fail_closed"], "source_policy.fail_closed")

        candidates = log["title_candidates"]
        require(isinstance(candidates, list) and len(candidates) == 3, "title_candidates must contain exactly A, B, and C")
        candidate_fields = {"label", "exact_title", "exact_authoritative_collision", "near_collision", "near_collision_primary_source", "disposition"}
        by_label: dict[str, dict[str, Any]] = {}
        for index, candidate in enumerate(candidates):
            require(isinstance(candidate, dict) and set(candidate) == candidate_fields, f"title_candidates[{index}] has an invalid schema")
            label = nonempty_string(candidate["label"], f"title_candidates[{index}].label")
            require(label not in by_label, f"duplicate title candidate label {label}")
            nonempty_string(candidate["exact_title"], f"title_candidates[{index}].exact_title")
            require(isinstance(candidate["exact_authoritative_collision"], bool), f"title candidate {label} collision flag is not Boolean")
            for optional in ("near_collision", "near_collision_primary_source"):
                require(candidate[optional] is None or isinstance(candidate[optional], str), f"title candidate {label}.{optional} must be string or null")
            nonempty_string(candidate["disposition"], f"title_candidates[{index}].disposition")
            by_label[label] = candidate
        require(set(by_label) == {"A", "B", "C"}, "title candidate labels must be exactly A, B, and C")
        require(by_label["B"]["exact_title"] == CHOSEN_TITLE, "title candidate B is not the frozen title")
        require(by_label["B"]["exact_authoritative_collision"] is False, "title candidate B reports an authoritative collision")
        require("freeze" in by_label["B"]["disposition"].lower(), "title candidate B disposition does not freeze it")

        close_records = log["resolved_close_records"]
        require(isinstance(close_records, list) and bool(close_records), "resolved_close_records must be a nonempty list")
        common_close_fields = {"identifier", "exact_title", "canonical_primary_source", "version_checked", "status"}
        close_identifiers: set[str] = set()
        for index, record in enumerate(close_records):
            require(isinstance(record, dict), f"resolved_close_records[{index}] must be an object")
            require(common_close_fields <= set(record) <= common_close_fields | {"author_version"}, f"resolved_close_records[{index}] has an invalid schema")
            for field in common_close_fields:
                nonempty_string(record[field], f"resolved_close_records[{index}].{field}")
            require(record["canonical_primary_source"].startswith("https://"), f"resolved_close_records[{index}] lacks an HTTPS canonical source")
            if "author_version" in record:
                require(record["author_version"].startswith("https://"), f"resolved_close_records[{index}].author_version is not HTTPS")
            identifier = record["identifier"]
            require(identifier not in close_identifiers, f"duplicate resolved close identifier {identifier}")
            close_identifiers.add(identifier)
        require(close_identifiers == REQUIRED_CLOSE_IDENTIFIERS, f"resolved close-record identifiers differ: {sorted(close_identifiers)}")

        searches = log["searches"]
        require(isinstance(searches, list) and bool(searches), "searches must be a nonempty list")
        search_fields = {"id", "search_date", "search_type", "query", "authoritative_targets", "authoritative_results", "disposition"}
        search_ids: set[str] = set()
        for index, search in enumerate(searches):
            require(isinstance(search, dict) and set(search) == search_fields, f"searches[{index}] has an invalid schema")
            for field in ("id", "search_date", "search_type", "query", "disposition"):
                nonempty_string(search[field], f"searches[{index}].{field}")
            require(search["search_date"] == audit_date, f"searches[{index}] date differs from audit_date")
            require(re.fullmatch(r"[A-Z]+\d{2}", search["id"]) is not None, f"searches[{index}] has a malformed ID")
            require(search["id"] not in search_ids, f"duplicate search ID {search['id']}")
            search_ids.add(search["id"])
            string_list(search["authoritative_targets"], f"searches[{index}].authoritative_targets")
            string_list(search["authoritative_results"], f"searches[{index}].authoritative_results", allow_empty=True)
        exact_searches = [search for search in searches if search["search_type"].lower() == "exact title"]
        for label in ("A", "B", "C"):
            title = by_label[label]["exact_title"]
            matches = [search for search in exact_searches if title in search["query"]]
            require(matches, f"no exact-title search recorded for candidate {label}")
            require(all(not search["authoritative_results"] for search in matches), f"candidate {label} exact-title search has an unresolved result")

        forwards = log["citing_and_forward_searches"]
        require(isinstance(forwards, list) and len(forwards) >= len(close_records), "citing_and_forward_searches does not cover the close records")
        forward_fields = {"query", "authoritative_record_checked", "additional_authoritative_citing_records_found", "disposition"}
        for index, forward in enumerate(forwards):
            require(isinstance(forward, dict) and set(forward) == forward_fields, f"citing_and_forward_searches[{index}] has an invalid schema")
            nonempty_string(forward["query"], f"citing_and_forward_searches[{index}].query")
            require(nonempty_string(forward["authoritative_record_checked"], f"citing_and_forward_searches[{index}].authoritative_record_checked").startswith("https://"), f"citing_and_forward_searches[{index}] source is not HTTPS")
            string_list(forward["additional_authoritative_citing_records_found"], f"citing_and_forward_searches[{index}].additional_authoritative_citing_records_found", allow_empty=True)
            nonempty_string(forward["disposition"], f"citing_and_forward_searches[{index}].disposition")

        policy_checks = log["aps_policy_checks"]
        require(isinstance(policy_checks, list) and len(policy_checks) == 6, "aps_policy_checks must contain the six audited APS topics")
        policy_fields = {"topic", "canonical_source", "verified"}
        topics: list[str] = []
        for index, check in enumerate(policy_checks):
            require(isinstance(check, dict) and set(check) == policy_fields, f"aps_policy_checks[{index}] has an invalid schema")
            topics.append(nonempty_string(check["topic"], f"aps_policy_checks[{index}].topic").lower())
            source = nonempty_string(check["canonical_source"], f"aps_policy_checks[{index}].canonical_source")
            require(source.startswith("https://journals.aps.org/"), f"aps_policy_checks[{index}] is not an official APS source")
            require(check["verified"] is True, f"aps_policy_checks[{index}] is not verified true")
        for concept in ("protocol article", "acceptance criteria", "scope", "data availability", "ai", "reference"):
            require(any(concept in topic for topic in topics), f"APS policy checks omit {concept!r}")

        unresolved = log["unresolved_records_retained"]
        require(isinstance(unresolved, list) and unresolved == [], "unresolved_records_retained must be an empty list")
        fatal = log["fatal_novelty_test"]
        fatal_fields = {"result", "qualification", "strongest_pair_tested", "missing_from_strongest_pair"}
        require(isinstance(fatal, dict) and set(fatal) == fatal_fields, "fatal_novelty_test has an invalid schema")
        require(fatal["result"] == "PASS", "fatal novelty test is not PASS")
        qualification = nonempty_string(fatal["qualification"], "fatal_novelty_test.qualification").lower()
        require("narrow" in qualification and "conditional" in qualification, "fatal novelty qualification is not narrow and conditional")
        strongest_pair = set(string_list(fatal["strongest_pair_tested"], "fatal_novelty_test.strongest_pair_tested"))
        require(len(strongest_pair) == 2 and strongest_pair <= close_identifiers, "fatal novelty strongest pair is not two resolved close records")
        missing = string_list(fatal["missing_from_strongest_pair"], "fatal_novelty_test.missing_from_strongest_pair")
        require(any("admission" in item.lower() for item in missing), "fatal novelty test does not identify missing claim admission")
        require(any("suppression" in item.lower() for item in missing), "fatal novelty test does not identify missing automatic suppression")

        novelty_audit = (self.final / "NOVELTY_AUDIT.md").read_text(encoding="utf-8")
        require("Fatal novelty test: PASS" in canonical_prose(novelty_audit), "NOVELTY_AUDIT.md does not echo fatal novelty PASS")
        return {
            "audit_date": audit_date,
            "search_count": len(searches),
            "resolved_close_records": len(close_records),
            "fatal_novelty_test": "PASS",
        }

    def verify_title(self) -> dict[str, Any]:
        main = (self.final / "main.tex").read_text(encoding="utf-8")
        title_match = re.search(r"\\title\{(.*?)\}", strip_tex_comments(main), re.S)
        require(title_match is not None, "main.tex has no parseable title")
        manuscript_title = re.sub(r"\s+", " ", title_match.group(1)).strip()
        require(manuscript_title == CHOSEN_TITLE, f"main.tex title differs from frozen title B: {manuscript_title!r}")

        title_audit = canonical_prose((self.final / "TITLE_COLLISION_AUDIT.md").read_text(encoding="utf-8"))
        require("Result: freeze title B." in title_audit, "TITLE_COLLISION_AUDIT.md does not explicitly freeze title B")
        require("Frozen recommendation" in title_audit, "TITLE_COLLISION_AUDIT.md lacks a frozen recommendation")
        require(CHOSEN_TITLE in title_audit, "TITLE_COLLISION_AUDIT.md lacks the exact chosen title B")
        require("No exact authoritative record was found for A, B, or C." in title_audit, "TITLE_COLLISION_AUDIT.md lacks the dated exact-collision result")
        return {"chosen_candidate": "B", "exact_title": CHOSEN_TITLE}

    def verify_aps_fit_and_rights(self) -> dict[str, Any]:
        aps_raw = (self.final / "APS_DESK_FIT.md").read_text(encoding="utf-8")
        aps = canonical_prose(aps_raw)
        require(f"Frozen title for this assessment: {CHOSEN_TITLE}" in aps, "APS_DESK_FIT.md title differs from title B")
        require("Decision: NOT READY - DO NOT SUBMIT." in aps, "APS desk decision is not NOT READY - DO NOT SUBMIT")
        require("rights/public-release authorization is an explicit hard failure" in aps.lower(), "APS decision does not identify the rights hard failure")

        scores: dict[int, tuple[str, int]] = {}
        for match in re.finditer(r"(?m)^\|\s*(\d+)\.\s*([^|]+?)\s*\|\s*\*\*(\d)/5\b", aps_raw):
            index = int(match.group(1))
            require(index not in scores, f"duplicate APS score row {index}")
            scores[index] = (canonical_prose(match.group(2)), int(match.group(3)))
        require(set(scores) == set(range(1, 13)), f"APS scorecard must contain exactly rows 1-12; observed {sorted(scores)}")
        expected_dimensions = {
            1: "Scope",
            2: "Article-type fit",
            3: "Novelty",
            4: "Usefulness",
            5: "Validation",
            6: "Generalizability",
            7: "Reproducibility",
            8: "Open-science readiness",
            9: "Technical correctness",
            10: "Readability",
            11: "Ethical and AI compliance",
            12: "Rights and publication readiness",
        }
        for index, expected in expected_dimensions.items():
            require(scores[index][0] == expected, f"APS score row {index} is {scores[index][0]!r}, expected {expected!r}")
        thresholds = {1: 3, 2: 4, 3: 4, 4: 4, 5: 4, 7: 4, 9: 4, 10: 4}
        for index, threshold in thresholds.items():
            require(scores[index][1] >= threshold, f"APS hard-gate score {expected_dimensions[index]} is below {threshold}/5")
        require(scores[12][1] == 1, "rights/publication-readiness score must remain 1/5 while authorization is unresolved")

        hard_section_match = re.search(r"## Hard gates(.*?)(?:\n###|\Z)", aps_raw, re.S)
        require(hard_section_match is not None, "APS_DESK_FIT.md lacks the hard-gates section")
        hard_rows: dict[str, str] = {}
        for line in hard_section_match.group(1).splitlines():
            if not line.startswith("|") or re.match(r"^\|[-: ]+\|", line):
                continue
            cells = [canonical_prose(cell) for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0] != "Gate":
                hard_rows[cells[0].lower()] = cells[1].upper()
        expected_pass_gates = (
            "scope at least 3",
            "protocol article fit at least 4",
            "novelty at least 4",
            "usefulness at least 4",
            "validation at least 4",
            "technical correctness at least 4",
            "reproducibility at least 4",
            "readability at least 4",
        )
        for gate in expected_pass_gates:
            require(gate in hard_rows and "PASS" in hard_rows[gate], f"APS hard gate {gate!r} is absent or not PASS")
        require("rights resolved" in hard_rows, "APS hard gates omit rights resolution")
        require("FAIL" in hard_rows["rights resolved"] and "FATAL" in hard_rows["rights resolved"], "APS rights gate is not FAIL - FATAL")

        release = load_json_strict(self.final / "release/RELEASE_STATUS.json")
        require(isinstance(release, dict), "release/RELEASE_STATUS.json must be an object")
        require(release.get("title") == CHOSEN_TITLE, "release status title differs from title B")
        require(release.get("release_status") == "BUILT_FOR_REVIEW_NOT_AUTHORIZED_FOR_PUBLICATION", "release status does not preserve review-only authorization")
        require(release.get("license") == "NO_LICENSE_GRANTED_PENDING_HUMAN_CONFIRMATION", "release status no-license marker changed without human confirmation")
        require(release.get("doi") is None, "release status claims a DOI despite unresolved rights")

        human_actions = canonical_prose((self.final / "HUMAN_ACTIONS.md").read_text(encoding="utf-8"))
        require("the manuscript must not be submitted" in human_actions.lower(), "HUMAN_ACTIONS.md does not block submission")
        require("NOT_READY_DO_NOT_SUBMIT" in human_actions, "HUMAN_ACTIONS.md decision differs from APS desk fit")
        rights_audit = canonical_prose((self.final / "supplement/RIGHTS_AND_ACCESS_AUDIT.md").read_text(encoding="utf-8"))
        require("PUBLIC REDISTRIBUTION NOT AUTHORIZED BY THIS AUDIT" in rights_audit, "rights audit no longer records unauthorized public redistribution")

        return {
            "hard_methodological_gates": "PASS",
            "rights_gate": "FAIL_FATAL",
            "decision": "NOT_READY_DO_NOT_SUBMIT",
            "scores": {expected_dimensions[index]: scores[index][1] for index in sorted(scores)},
        }

    def run(self) -> dict[str, Any]:
        self.check("matrix_references_and_manuscript_support", self.verify_matrix_and_references)
        self.check("strict_search_log_and_fatal_novelty_test", self.verify_search_log)
        self.check("frozen_title_collision_audit", self.verify_title)
        self.check("aps_hard_gates_and_rights_consistency", self.verify_aps_fit_and_rights)
        return {
            "schema_version": "research-audit-verification-v1",
            "status": "PASS" if not self.failures else "FAIL",
            "scope": str(self.final),
            "checks": self.checks,
            "failures": self.failures,
        }


def verify(final: Path = FINAL) -> dict[str, Any]:
    return ResearchAuditVerifier(final).run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final-dir", type=Path, default=FINAL, help="final_protocol directory to verify")
    parser.add_argument("--pretty", action="store_true", help="pretty-print the JSON report")
    args = parser.parse_args(argv)
    report = verify(args.final_dir)
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=True, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
