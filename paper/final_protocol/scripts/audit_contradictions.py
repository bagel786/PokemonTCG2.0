#!/usr/bin/env python3
"""Fail-closed cross-artifact contradiction audit for the Protocol Article.

The audit separates factual or machine-verification failures from unresolved
human metadata and legal/rights decisions.  The latter block submission but do
not become "contradictions" merely because the author has not supplied them.
No result is inferred from prose: numerical truth is loaded from the checked
processed evidence and its independently regenerated verification record.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
FINAL = SCRIPT.parents[1]
PAPER = SCRIPT.parents[2]
ROOT = SCRIPT.parents[3]
DEFAULT_OUTPUT = FINAL / "CONTRADICTION_AUDIT.json"

EXPECTED_TITLE = (
    "A Protocol for Validating Pairing Assumptions in Seed-Matched Evaluations of "
    "Black-Box Game-Playing Agents"
)
EXPECTED_ARTICLE_TYPE = "APS Open Science Protocol Article"
EXPECTED_PROTOCOL_COMMIT = "803257f102232763fc88d28c14b668f9b62eb277"
EXPECTED_BRANCH = "paper/apsos-submission-closeout-20260825"

REQUIRED_BASE_FILES = (
    "STARTING_STATE.json",
    "main.tex",
    "main.pdf",
    "results_macros.tex",
    "cover_letter.md",
    "data_availability.md",
    "ai_disclosure.md",
    "author_contributions.md",
    "conflict_of_interest.md",
    "claim_ledger.csv",
    "source_data/claim_scope_audit.json",
    "NOVELTY_AUDIT.md",
    "NOVELTY_MATRIX.csv",
    "NOVELTY_SEARCH_LOG.json",
    "APS_DESK_FIT.md",
    "REFERENCE_AUDIT.csv",
    "EQUATION_AUDIT.md",
    "METHOD_ASSUMPTION_AUDIT.md",
    "AUTHOR_DEFENSE_GUIDE.md",
    "HUMAN_ACTIONS.md",
    "RELEASE_COMPONENT_INVENTORY.csv",
    "READABILITY_AUDIT.json",
    "REPRODUCTION_REPORT.json",
    "REPRODUCTION_REPORT.sha256",
    "scripts/verify_reproduction_report.py",
    "SUBMISSION_CHECKLIST.md",
    "supplement/AI_USE_LOG.csv",
)

REQUIRED_JSON = {
    "identity": FINAL / "source_data/artifact_identity.json",
    "build": FINAL / "source_data/build_report.json",
    "verification": FINAL / "source_data/statistics_verification.json",
    "preflight": FINAL / "source_data/processed_preflight.json",
    "stress": FINAL / "source_data/processed_stress.json",
    "factorial": FINAL / "source_data/processed_factorial.json",
    "seed_audit": FINAL / "source_data/processed_seed_namespace_audit.json",
    "stochastic_audit": FINAL / "source_data/processed_stochastic_source_audit.json",
    "synthetic": FINAL / "source_data/processed_synthetic.json",
    "claim_scope": FINAL / "source_data/claim_scope_audit.json",
}

CANONICAL_INPUT_PATHS = {
    "combined": PAPER / "data/pevl/summary.json",
    "factorial": PAPER / "data/pevl/factorial_summary.json",
    "historical": PAPER / "data/ablation/summary.json",
    "preflight": PAPER / "data/pevl/trace_preflight_summary.json",
    "protocol": PAPER / "protocol/PEVL_PROSPECTIVE_PROTOCOL.md",
    "seed_audit": PAPER / "data/seed_namespace_audit.json",
    "stochastic_audit": PAPER / "data/stochastic_source_audit.json",
    "stress": PAPER / "data/pevl/timed_search_stress_summary.json",
    "synthetic": PAPER / "synthetic/results/pevl_results.json",
}

EXPECTED_RESTRICTED_CATEGORIES = {
    "engine": (r"tournament engine", r"game engine", r"engine source", r"engine binaries?"),
    "opponents": (r"third-party opponent packages?", r"opponent packages?"),
    "game_assets": (r"game assets?(?: and metadata)?", r"game metadata"),
    "private_observations": (r"private replay observations?", r"private observations?"),
    "policy_packages": (r"policy packages?", r"model weights?", r"policy weights?"),
    "raw_traces": (r"raw restricted traces?", r"full restricted traces?", r"raw traces?"),
}

PROHIBITED_PRIVATE_LABELS = (
    r"\bstarmie\b",
    r"\bdipplin\b",
    r"\balakazam\b",
    r"\bd842(?:[_-]runtime)?\b",
    r"\bmaster[_-]v1\b",
    r"\breplay[_-]refresh\b",
    r"\bgrim(?:msnarl)?\b",
)

ALLOWED_CLAIM_STATUSES = {
    "VERIFIED",
    "VERIFIED_WITH_CAVEAT",
    "DERIVED_BY_CHECKED_SCRIPT",
}

PROHIBITED_PROVENANCE_PHRASES = {
    "prospectively_frozen_claim_map": r"\bprospectively\s+frozen\s+claim\s+map\b",
    "frozen_rule_admitted_descriptive": (
        r"\bunder\s+the\s+frozen\s+rule\s+this\s+admitted\s+a\s+"
        r"fixed[- ]battery\s+descriptive\b"
    ),
    "stage_8_executes_frozen_map": (
        r"\bstage\s*8\s+executes\s+the\s+frozen\s+admission\s+map\b"
    ),
}


def reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant prohibited: {value}")


def parse_finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite JSON number prohibited: {value}")
    return result


def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key prohibited: {key}")
        result[key] = value
    return result


def load_json_strict(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_json_constant,
        parse_float=parse_finite_float,
        object_pairs_hook=reject_duplicate_pairs,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_title(value: str) -> str:
    value = value.replace("“", "").replace("”", "").replace('"', "")
    value = re.sub(r"[*_`{}]", "", value)
    return normalize_space(value).rstrip(".")


def normalize_visible_prose(value: str, *, strip_latex_comments: bool = False) -> str:
    """Normalize visible Markdown/LaTeX prose for bounded semantic checks.

    LaTeX comments cannot satisfy a manuscript-disclosure requirement.  The
    small amount of markup normalization here is intentionally conservative:
    it preserves visible words while making escaped percent signs, nonbreaking
    spaces, and TeX dashes comparable to ordinary prose.
    """
    visible_lines: list[str] = []
    for line in value.splitlines():
        comment = re.search(r"(?<!\\)%", line) if strip_latex_comments else None
        visible_lines.append(line[: comment.start()] if comment else line)
    text = "\n".join(visible_lines)
    text = text.replace(r"\%", "%").replace("~", " ")
    text = text.replace("---", "-").replace("--", "-")
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(
        r"\\(?:emph|textbf|textit|texttt|paragraph|subsection|section)\*?\{([^{}]*)\}",
        r" \1 ",
        text,
    )
    text = text.replace("{", " ").replace("}", " ").replace("\\", " ")
    return normalize_space(text)


def semantic_terms_within(
    text: str,
    patterns: Iterable[str],
    *,
    max_span: int,
) -> bool:
    """Return true only when every required term occurs in one bounded window."""
    matches = [list(re.finditer(pattern, text, re.I)) for pattern in patterns]
    if any(not group for group in matches):
        return False
    for combination in itertools.product(*matches):
        left = min(match.start() for match in combination)
        right = max(match.end() for match in combination)
        if right - left <= max_span:
            return True
    return False


def provenance_semantics_state(
    protocol_text: str,
    manuscript_text: str,
) -> dict[str, Any]:
    """Evaluate the frozen-plan/completed-reporting provenance boundary.

    These checks deliberately require explicit nearby terms.  Scattered uses
    of words such as ``retrospective`` or ``deviation`` cannot accidentally
    satisfy a disclosure about a different part of the study.
    """
    protocol = normalize_visible_prose(protocol_text)
    manuscript = normalize_visible_prose(manuscript_text, strip_latex_comments=True)

    state: dict[str, Any] = {
        "frozen_95_percent_intervals": bool(
            re.search(
                r"\b95\s*%\s+intervals?\s+(?:use|uses|will use|are computed (?:with|from))\b",
                protocol,
                re.I,
            )
        ),
        "frozen_exact_two_sided_mcnemar": bool(
            re.search(
                r"\bexact\s+two[- ]sided\s+mcnemar\s+(?:inference|test|analysis)\b",
                protocol,
                re.I,
            )
        ),
        "frozen_stress_localization_timing_promise": semantic_terms_within(
            protocol,
            (
                r"\bstress\s+test\b",
                r"\blocali[sz]ation\b",
                r"\btiming\s+summaries\b",
                r"\bpublic\s+package\b",
            ),
            max_span=1200,
        ),
        "completed_case_taxonomy_is_post_acquisition": semantic_terms_within(
            manuscript,
            (
                r"\bcompleted[- ]case\b",
                r"\bdescriptive\b",
                r"\blevel(?:\s+\d+)?\b",
                r"\btaxonomy\b",
                (
                    r"(?:\breporting\s+(?:restriction|limit|taxonomy)s?\b|"
                    r"\b(?:permits?|restricts?)\s+only\b|\bonly\b.{0,80}\bdescriptive\b)"
                ),
                r"\b(?:post[- ]acquisition|after\s+acquisition)\b",
                (
                    r"(?:(?:not|never|did\s+not|was\s+not).{0,100}\bfrozen\s+"
                    r"(?:plan|protocol)\b|\bfrozen\s+(?:plan|protocol)\b.{0,100}"
                    r"(?:not|never|did\s+not|was\s+not)|\bfuture\s+(?:study|users?)\b"
                    r".{0,100}\bmust\s+(?:be\s+)?(?:freeze|frozen)\b.{0,80}"
                    r"\b(?:before\s+acquisition|before\s+collecting\s+outcomes)\b)"
                ),
            ),
            max_span=1200,
        ),
        "historical_audit_is_retrospective_not_blinding": semantic_terms_within(
            manuscript,
            (
                r"\bfrozen\b",
                r"\bhistorical\b",
                r"\baudit(?:\s+rule)?\b",
                r"\bretrospective\b",
                (
                    r"(?:\boutcomes?\b|\boutcome\s+(?:data|records?)\b).{0,90}"
                    r"(?:already\s+existed|were\s+already\s+available|had\s+(?:already\s+)?"
                    r"been\s+(?:generated|recorded|observed|created)|existed|were\s+available)"
                ),
                (
                    r"(?:not|does\s+not|did\s+not|cannot).{0,90}(?:evidence|proof|establish)"
                    r".{0,70}\bprospective\s+blinding\b"
                ),
            ),
            max_span=900,
        ),
        "digest_byte_is_later_extension_without_count_change": semantic_terms_within(
            manuscript,
            (
                r"\bdigests?\b",
                r"\bbyte[- ]counts?\b",
                (
                    r"\b(?:(?:later|post[- ]acquisition)\s+(?:integrity\s+)?(?:extension|addition)|"
                    r"added\s+later\s+as\s+an?\s+integrity\s+(?:extension|check))\b"
                ),
                (
                    r"(?:\bfrozen\b.{0,70}\bendpoint\b.{0,70}\bdigests?\b|"
                    r"\bdigests?\b.{0,70}\b(?:was|remained)\b.{0,50}\bfrozen\b"
                    r".{0,40}\bendpoint\b)"
                ),
                (
                    r"(?:\b(?:did|does)\s+not\b.{0,60}\bchange\b.{0,50}\bcounts?\b|"
                    r"\bchanged\s+no\b.{0,50}\bcounts?\b|\bcounts?\b.{0,50}"
                    r"(?:\bunchanged\b|\bdid\s+not\s+change\b)|\bthe\s+same\s+"
                    r"\d+\s*/\s*\d+\b|\b(?:did|does)\s+not\b.{0,40}\balter\b"
                    r".{0,40}\bdecision\b)"
                ),
            ),
            max_span=950,
        ),
        "stress_partial_recovery_and_position_deviation_disclosed": semantic_terms_within(
            manuscript,
            (
                r"\bstress\b",
                r"\bfrozen\s+(?:plan|(?:stress\s+)?protocol)\b",
                r"\b(?:promised|required|specified|planned)\b",
                r"\bfirst[- ]divergence\s+positions\b",
                r"\bacting[- ]side\s+counts\b",
                r"\btiming\s+summaries\b",
                r"\b(?:found|recovered)\b.{0,350}\bhash[- ]pinned\b",
                r"\bincluded\s+as\s+processed\s+aggregates\b",
                r"\bpending\b.{0,100}\b(?:approval|redistribution)\b",
                r"\bpositions\s+were\s+never\s+recorded\b",
                (
                    r"(?:\bposition[- ]level\s+locali[sz]ation\b.{0,80}"
                    r"\bcannot\s+be\s+verified\b|\bcannot\s+be\s+verified\b.{0,80}"
                    r"\bposition[- ]level\s+locali[sz]ation\b)"
                ),
                (
                    r"(?:\bprotocol\s*(?:/|and|-)\s*reporting\s+deviation\b|"
                    r"\breporting\s+(?:and\s+access\s+)?deviation\b)"
                ),
            ),
            max_span=1500,
        ),
    }
    state["prohibited_phrase_hits"] = sorted(
        name
        for name, pattern in PROHIBITED_PROVENANCE_PHRASES.items()
        if re.search(pattern, manuscript, re.I)
    )
    return state


def count_markdown_headings(path: Path, pattern: str) -> int:
    """Count a declared audit inventory from its stable Markdown headings."""
    if not path.is_file():
        return 0
    return sum(
        bool(re.match(pattern, line))
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def parse_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not an integer count")
    if isinstance(value, int):
        return value
    return int(str(value).replace(",", "").strip())


def parse_float(value: Any) -> float:
    result = float(str(value).replace(",", "").replace("%", "").strip())
    if not math.isfinite(result):
        raise ValueError(f"non-finite number: {value!r}")
    return result


def resampling_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy bootstrap keys and current descriptive-reweighting keys.

    The retained computation is the same deterministic resampling calculation;
    final prose correctly treats its quantiles as descriptive sensitivities,
    not confidence intervals.  Frozen upstream inputs retain legacy field names,
    so the audit compares values without carrying that historical interpretation
    into current outputs.
    """
    interval = record.get("quantiles_2_5_97_5", record.get("bootstrap_95_ci"))
    draws = record.get("reweighting_draws", record.get("bootstrap_draws"))
    seed = record.get("reweighting_seed", record.get("bootstrap_seed"))
    if not isinstance(interval, list) or len(interval) != 2 or draws is None or seed is None:
        raise ValueError("resampling record lacks a two-quantile interval, draw count, or seed")
    return {
        "estimate": parse_float(record["estimate"]),
        "interval": [parse_float(value) for value in interval],
        "draws": parse_int(draws),
        "seed": parse_int(seed),
    }


def close(observed: Any, expected: Any, tolerance: float = 1e-12) -> bool:
    return math.isclose(parse_float(observed), parse_float(expected), rel_tol=0.0, abs_tol=tolerance)


def macro_map(text: str) -> dict[str, str]:
    return {
        name: value.strip()
        for name, value in re.findall(
            r"\\newcommand\{\\([A-Za-z]+)\}\{([^{}]*)\}", text
        )
    }


def expand_macros(text: str, macros: dict[str, str]) -> str:
    for name in sorted(macros, key=len, reverse=True):
        text = re.sub(rf"\\{re.escape(name)}(?:\{{\}})?", macros[name], text)
    text = text.replace(r"\%", "%").replace("−", "-").replace("–", "-")
    return text


def line_locations(path: Path, pattern: str, flags: int = re.IGNORECASE) -> list[str]:
    if not path.is_file():
        return []
    hits: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if re.search(pattern, line, flags):
            hits.append(f"{relative(path)}:{number}")
    return hits


def text_files_under(root: Path) -> list[Path]:
    allowed = {".md", ".tex", ".txt", ".csv", ".json", ".cff", ".yml", ".yaml"}
    excluded = {DEFAULT_OUTPUT.name, "REPRODUCTION_REPORT.json"}
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in allowed and path.name not in excluded
    )


class Audit:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.contradictions: list[dict[str, Any]] = []
        self.machine_blockers: list[dict[str, Any]] = []
        self.human_or_legal_blockers: list[dict[str, Any]] = []

    def pass_check(
        self,
        check_id: str,
        category: str,
        expected: Any,
        observed: Any,
        evidence: Iterable[str],
        message: str,
    ) -> None:
        self.checks.append(
            {
                "check_id": check_id,
                "category": category,
                "classification": "factual_consistency",
                "status": "PASS",
                "expected": expected,
                "observed": observed,
                "evidence": sorted(set(evidence)),
                "message": message,
            }
        )

    def conflict(
        self,
        check_id: str,
        category: str,
        expected: Any,
        observed: Any,
        evidence: Iterable[str],
        message: str,
    ) -> None:
        item = {
            "check_id": check_id,
            "category": category,
            "classification": "factual_contradiction",
            "status": "FAIL",
            "expected": expected,
            "observed": observed,
            "evidence": sorted(set(evidence)),
            "message": message,
        }
        self.checks.append(item)
        self.contradictions.append(item.copy())

    def machine(
        self,
        check_id: str,
        category: str,
        expected: Any,
        observed: Any,
        evidence: Iterable[str],
        message: str,
    ) -> None:
        item = {
            "check_id": check_id,
            "category": category,
            "classification": "machine_verification_blocker",
            "status": "BLOCKED",
            "expected": expected,
            "observed": observed,
            "evidence": sorted(set(evidence)),
            "message": message,
        }
        self.checks.append(item)
        self.machine_blockers.append(item.copy())

    def human(
        self,
        blocker_id: str,
        category: str,
        evidence: Iterable[str],
        required_resolution: str,
    ) -> None:
        item = {
            "blocker_id": blocker_id,
            "category": category,
            "classification": "human_or_legal_blocker",
            "status": "OPEN",
            "evidence": sorted(set(evidence)),
            "required_resolution": required_resolution,
        }
        self.human_or_legal_blockers.append(item)


def require_json_inputs(audit: Audit) -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    for label, path in REQUIRED_JSON.items():
        if not path.is_file():
            audit.machine(
                f"JSON-{label.upper()}-MISSING",
                "authoritative evidence",
                "strict JSON file present",
                "missing",
                [relative(path)],
                "An authoritative processed input is unavailable.",
            )
            continue
        try:
            payloads[label] = load_json_strict(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            audit.machine(
                f"JSON-{label.upper()}-INVALID",
                "authoritative evidence",
                "finite duplicate-free JSON",
                str(exc),
                [relative(path)],
                "The authoritative processed input could not be parsed fail closed.",
            )
    return payloads


def expected_truth(payloads: dict[str, Any]) -> dict[str, Any] | None:
    required = {"identity", "verification", "preflight", "stress", "factorial", "seed_audit"}
    if not required.issubset(payloads):
        return None
    verification = payloads["verification"]
    stress = payloads["stress"]
    factorial = payloads["factorial"]
    preflight = payloads["preflight"]
    stress_resampling = resampling_record(stress["trace_disagreement"])
    factorial_resampling = resampling_record(factorial["contrasts"]["primary_c4_minus_c1"])
    return {
        "protocol_commit": EXPECTED_PROTOCOL_COMMIT,
        "historical_units": parse_int(verification["historical"]["units"]),
        "historical_outcome_mismatch": parse_int(verification["historical"]["outcome_error_mismatch"]),
        "historical_available_mismatch": parse_int(verification["historical"]["available_record_mismatch"]),
        "preflight_units": parse_int(preflight["trajectory_units"]),
        "preflight_executions": parse_int(preflight["executions"]),
        "preflight_mismatches": parse_int(preflight["mismatch_units"]),
        "stress_clusters": parse_int(stress["clusters"]),
        "stress_executions": parse_int(stress["executions"]),
        "stress_trace_mismatch": parse_int(stress["trace_disagreement_clusters"]),
        "stress_trace_pct": 100.0 * stress_resampling["estimate"],
        "stress_low_pct": 100.0 * stress_resampling["interval"][0],
        "stress_high_pct": 100.0 * stress_resampling["interval"][1],
        "stress_outcome_mismatch": parse_int(stress["outcome_disagreement_clusters"]),
        "stress_decision_mismatch": parse_int(stress["decision_count_disagreement_clusters"]),
        "stress_error_mismatch": parse_int(stress["error_disagreement_clusters"]),
        "stress_reweighting_draws": stress_resampling["draws"],
        "stress_reweighting_seed": stress_resampling["seed"],
        "factorial_units": parse_int(factorial["units"]),
        "factorial_games": parse_int(factorial["games"]),
        "factorial_control_mismatch": parse_int(factorial["control_mismatch_units"]),
        "factorial_reweighting_draws": factorial_resampling["draws"],
        "factorial_reweighting_seed": factorial_resampling["seed"],
        "factorial_rates": factorial["cell_win_rates"],
        "factorial_contrasts": factorial["contrasts"],
        "factorial_mcnemar_numerical_audit": verification["factorial"][
            "mcnemar_numerical_audit_not_admitted"
        ],
        "identity_hashes": {key: value["sha256"] for key, value in payloads["identity"]["inputs"].items()},
        "seed_audit": payloads["seed_audit"],
    }


def compare_exact(
    audit: Audit,
    check_id: str,
    category: str,
    expected: Any,
    observations: dict[str, Any],
    message: str,
) -> None:
    bad = {source: value for source, value in observations.items() if value != expected}
    if bad:
        audit.conflict(check_id, category, expected, bad, observations, message)
    else:
        audit.pass_check(check_id, category, expected, observations, observations, message)


def check_required_files(audit: Audit) -> None:
    missing = [relative(FINAL / name) for name in REQUIRED_BASE_FILES if not (FINAL / name).is_file()]
    if missing:
        audit.machine(
            "FILES-REQUIRED",
            "artifact inventory",
            list(REQUIRED_BASE_FILES),
            {"missing": missing},
            missing,
            "Required final Protocol Article artifacts are missing.",
        )
    else:
        audit.pass_check(
            "FILES-REQUIRED",
            "artifact inventory",
            len(REQUIRED_BASE_FILES),
            len(REQUIRED_BASE_FILES),
            [relative(FINAL / name) for name in REQUIRED_BASE_FILES],
            "All base artifacts required for this cross-file audit are present.",
        )

    release = FINAL / "release"
    required_release = ("README.md", "RELEASE_STATUS.json", "LICENSE", "CITATION.cff", "MANIFEST.sha256")
    missing_release = [relative(release / name) for name in required_release if not (release / name).is_file()]
    if missing_release:
        audit.machine(
            "FILES-RELEASE",
            "release inventory",
            list(required_release),
            {"missing": missing_release},
            missing_release,
            "The release README/status/license/citation/manifest set is incomplete.",
        )
    else:
        audit.pass_check(
            "FILES-RELEASE",
            "release inventory",
            list(required_release),
            list(required_release),
            [relative(release / name) for name in required_release],
            "Release identity and status documents are present.",
        )


def check_identity(audit: Audit, payloads: dict[str, Any], macros: dict[str, str]) -> None:
    main_path = FINAL / "main.tex"
    cover_path = FINAL / "cover_letter.md"
    main = main_path.read_text(encoding="utf-8") if main_path.is_file() else ""
    cover = cover_path.read_text(encoding="utf-8") if cover_path.is_file() else ""
    release_status_path = FINAL / "release/RELEASE_STATUS.json"
    release_readme_path = FINAL / "release/README.md"
    citation_path = FINAL / "release/CITATION.cff"

    titles: dict[str, str] = {}
    title_match = re.search(r"\\title\{([^{}]+)\}", main)
    titles[relative(main_path)] = normalize_title(title_match.group(1)) if title_match else "MISSING"
    cover_match = re.search(r"consideration of\s+[“\"](.+?)[”\"]\s+as an?", cover, re.I | re.S)
    titles[relative(cover_path)] = normalize_title(cover_match.group(1)) if cover_match else "MISSING"
    if release_status_path.is_file():
        try:
            titles[relative(release_status_path)] = normalize_title(str(load_json_strict(release_status_path).get("title", "MISSING")))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            titles[relative(release_status_path)] = "INVALID_JSON"
    if release_readme_path.is_file():
        readme = release_readme_path.read_text(encoding="utf-8")
        match = re.search(r"Protocol Article\s+\*\*[“\"]?(.+?)[.][”\"]?\*\*", readme, re.I | re.S)
        if match:
            titles[relative(release_readme_path)] = normalize_title(match.group(1))
    if citation_path.is_file():
        citation = citation_path.read_text(encoding="utf-8")
        match = re.search(r"(?ms)^title:\s*>-\s*\n\s*(.+)$", citation)
        if match:
            titles[relative(citation_path)] = normalize_title(match.group(1).splitlines()[0])
    compare_exact(
        audit,
        "IDENTITY-TITLE",
        "title",
        EXPECTED_TITLE,
        titles,
        "Every file that declares the article title must use the frozen exact title.",
    )

    article_types: dict[str, str] = {}
    preprint = re.search(r"\\preprint\{([^{}]+)\}", main)
    article_types[relative(main_path)] = normalize_space(preprint.group(1)) if preprint else "MISSING"
    cover_type = re.search(r"as an?\s+\*\*([^*]+)\*\*", cover, re.I)
    article_types[relative(cover_path)] = normalize_space(cover_type.group(1)) if cover_type else "MISSING"
    if release_status_path.is_file():
        try:
            article_types[relative(release_status_path)] = str(load_json_strict(release_status_path).get("article_type", "MISSING"))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            article_types[relative(release_status_path)] = "INVALID_JSON"
    compare_exact(
        audit,
        "IDENTITY-ARTICLE-TYPE",
        "article type",
        EXPECTED_ARTICLE_TYPE,
        article_types,
        "The Protocol Article identity is fixed and may not drift across submission or release files.",
    )

    declared_main_authors = [
        normalize_space(value)
        for value in re.findall(r"\\author\{([^{}]+)\}", main)
        if not re.search(r"(?i)requires human|human confirmation|\[author", value)
    ]
    cover_signature = ""
    signature_match = re.search(r"(?is)Sincerely,\s*\n\s*\*\*([^*\n]+)\*\*", cover)
    if signature_match and not re.search(r"(?i)requires human|\[corresponding", signature_match.group(1)):
        cover_signature = normalize_space(signature_match.group(1))
    cff_authors: list[str] = []
    if citation_path.is_file():
        citation = citation_path.read_text(encoding="utf-8")
        given = re.findall(r"(?m)^\s*given-names:\s*[\"']?([^\n\"']+)", citation)
        family = re.findall(r"(?m)^\s*family-names:\s*[\"']?([^\n\"']+)", citation)
        if len(given) == len(family):
            cff_authors = [normalize_space(f"{first} {last}") for first, last in zip(given, family, strict=True)]
    if not declared_main_authors:
        audit.pass_check(
            "IDENTITY-AUTHORS",
            "author names",
            "no inferred author identity while human metadata is unresolved",
            {"manuscript": "PLACEHOLDER", "cover_signature": cover_signature or "PLACEHOLDER", "citation_authors": cff_authors or "OMITTED"},
            [relative(main_path), relative(cover_path), relative(citation_path)],
            "Author names are deferred to the human-metadata blocker and no concrete conflicting identity is asserted.",
        )
    else:
        concrete_declarations: dict[str, list[str]] = {relative(main_path): declared_main_authors}
        if cover_signature:
            concrete_declarations[relative(cover_path)] = [cover_signature]
        if cff_authors:
            concrete_declarations[relative(citation_path)] = cff_authors
        normalized_expected = {normalize_space(name).casefold() for name in declared_main_authors}
        conflicts = {
            source: names
            for source, names in concrete_declarations.items()
            if {normalize_space(name).casefold() for name in names} != normalized_expected
        }
        if conflicts:
            audit.conflict(
                "IDENTITY-AUTHORS", "author names", declared_main_authors, conflicts,
                concrete_declarations, "Concrete author-name declarations disagree across manuscript, cover letter, or citation metadata."
            )
        else:
            audit.pass_check(
                "IDENTITY-AUTHORS", "author names", declared_main_authors, concrete_declarations,
                concrete_declarations, "All concrete author-name declarations agree."
            )

    branch_observed = "UNAVAILABLE"
    try:
        branch_observed = subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=ROOT, text=True, stderr=subprocess.PIPE
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    if branch_observed == EXPECTED_BRANCH:
        audit.pass_check(
            "IDENTITY-BRANCH", "article identity", EXPECTED_BRANCH, branch_observed,
            ["git:branch --show-current"], "The working branch is the frozen finalization branch."
        )
    else:
        audit.machine(
            "IDENTITY-BRANCH", "article identity", EXPECTED_BRANCH, branch_observed,
            ["git:branch --show-current"], "The audit was not run from the designated finalization branch."
        )

    protocol_values: dict[str, Any] = {}
    for label in ("identity", "build", "verification", "preflight", "stress", "factorial", "seed_audit", "stochastic_audit"):
        if label in payloads and isinstance(payloads[label], dict) and "protocol_commit" in payloads[label]:
            protocol_values[relative(REQUIRED_JSON[label])] = payloads[label]["protocol_commit"]
    if release_status_path.is_file():
        try:
            release_status_payload = load_json_strict(release_status_path)
            if isinstance(release_status_payload, dict) and "protocol_commit" in release_status_payload:
                protocol_values[relative(release_status_path)] = release_status_payload["protocol_commit"]
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            pass
    if "ProtocolCommitShort" in macros:
        protocol_values[relative(FINAL / "results_macros.tex") + "#short"] = macros["ProtocolCommitShort"]
    wrong = {
        source: value
        for source, value in protocol_values.items()
        if value not in {EXPECTED_PROTOCOL_COMMIT, EXPECTED_PROTOCOL_COMMIT[:8]}
    }
    if not protocol_values:
        audit.machine(
            "IDENTITY-PROTOCOL-COMMIT", "protocol identity", EXPECTED_PROTOCOL_COMMIT,
            "no declarations", [relative(FINAL / "source_data")], "No protocol-commit declarations were available."
        )
    elif wrong:
        audit.conflict(
            "IDENTITY-PROTOCOL-COMMIT", "protocol identity", EXPECTED_PROTOCOL_COMMIT,
            wrong, protocol_values, "Protocol-linked artifacts disagree on the frozen commit."
        )
    else:
        audit.pass_check(
            "IDENTITY-PROTOCOL-COMMIT", "protocol identity", EXPECTED_PROTOCOL_COMMIT,
            protocol_values, protocol_values, "All protocol-linked artifacts use the full commit or its declared eight-character display prefix."
        )

    protocol_path = PAPER / "protocol/PEVL_PROSPECTIVE_PROTOCOL.md"
    try:
        first_commit = subprocess.check_output(
            ["git", "log", "--reverse", "--format=%H", "--", relative(protocol_path)],
            cwd=ROOT,
            text=True,
            stderr=subprocess.PIPE,
        ).splitlines()[0]
    except (OSError, subprocess.CalledProcessError, IndexError):
        first_commit = "UNAVAILABLE"
    if first_commit == EXPECTED_PROTOCOL_COMMIT:
        audit.pass_check(
            "IDENTITY-PROTOCOL-GIT-ORDER", "protocol identity", EXPECTED_PROTOCOL_COMMIT,
            first_commit, [relative(protocol_path), "git:log --reverse"],
            "Git history confirms the first commit containing the frozen protocol."
        )
    else:
        audit.machine(
            "IDENTITY-PROTOCOL-GIT-ORDER", "protocol identity", EXPECTED_PROTOCOL_COMMIT,
            first_commit, [relative(protocol_path), "git:log --reverse"],
            "The frozen protocol's first Git commit could not be confirmed."
        )


def check_authoritative_numbers(audit: Audit, payloads: dict[str, Any], truth: dict[str, Any], macros: dict[str, str]) -> None:
    preflight = payloads["preflight"]
    stress = payloads["stress"]
    factorial = payloads["factorial"]
    verification = payloads["verification"]
    release_payloads: dict[str, Any] = {}
    release_json_paths = {
        "historical": FINAL / "release/data/processed/historical_summary.json",
        "preflight": FINAL / "release/data/processed/preflight_summary.json",
        "stress": FINAL / "release/data/processed/timed_search_stress.json",
        "factorial": FINAL / "release/data/processed/factorial_summary.json",
    }
    for label, path in release_json_paths.items():
        if not path.is_file():
            continue
        try:
            release_payloads[label] = load_json_strict(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            audit.machine(
                f"NUM-RELEASE-{label.upper()}-PARSE", "release numerical evidence",
                "finite duplicate-free JSON", str(exc), [relative(path)],
                "A release processed-data record could not be parsed."
            )

    observations = {
        "processed_preflight": (
            parse_int(preflight["trajectory_units"]), parse_int(preflight["executions"]), parse_int(preflight["mismatch_units"])
        ),
        "statistics_verification": (
            parse_int(verification["preflight"]["trajectory_units"]),
            parse_int(verification["preflight"]["executions"]),
            parse_int(verification["preflight"]["mismatch_units"]),
        ),
    }
    if "preflight" in release_payloads:
        item = release_payloads["preflight"]
        observations["release_preflight"] = (
            parse_int(item["trajectory_units"]), parse_int(item["executions"]), parse_int(item["mismatch_units"])
        )
    compare_exact(
        audit, "NUM-PREFLIGHT", "sample and execution counts",
        (truth["preflight_units"], truth["preflight_executions"], truth["preflight_mismatches"]),
        observations, "Preflight units, executions, and mismatch count must agree."
    )

    stress_tuple = (
        truth["stress_clusters"], truth["stress_executions"], truth["stress_trace_mismatch"],
        truth["stress_outcome_mismatch"], truth["stress_decision_mismatch"], truth["stress_error_mismatch"],
    )
    observations = {
        "processed_stress": (
            parse_int(stress["clusters"]), parse_int(stress["executions"]),
            parse_int(stress["trace_disagreement_clusters"]), parse_int(stress["outcome_disagreement_clusters"]),
            parse_int(stress["decision_count_disagreement_clusters"]), parse_int(stress["error_disagreement_clusters"]),
        ),
        "statistics_verification": (
            parse_int(verification["stress"]["empirical_reweighting"]["clusters"]),
            truth["stress_executions"],
            parse_int(verification["stress"]["trace_disagreement_clusters"]),
            parse_int(verification["stress"]["outcome_disagreement_clusters"]),
            parse_int(verification["stress"]["decision_count_disagreement_clusters"]),
            parse_int(verification["stress"]["error_disagreement_clusters"]),
        ),
    }
    if "stress" in release_payloads:
        item = release_payloads["stress"]
        observations["release_stress"] = (
            parse_int(item["clusters"]), parse_int(item["executions"]),
            parse_int(item["trace_disagreement_clusters"]), parse_int(item["outcome_disagreement_clusters"]),
            parse_int(item["decision_count_disagreement_clusters"]), parse_int(item["error_disagreement_clusters"]),
        )
    compare_exact(
        audit, "NUM-STRESS-COUNTS", "mismatch counts", stress_tuple, observations,
        "Timed-search cluster, execution, trace, outcome, decision, and error counts must agree."
    )

    expected_stress_reweighting = (
        truth["stress_trace_pct"], truth["stress_low_pct"], truth["stress_high_pct"],
        truth["stress_reweighting_draws"], truth["stress_reweighting_seed"],
    )
    processed_stress_resampling = resampling_record(stress["trace_disagreement"])
    verified_stress_resampling = resampling_record(
        verification["stress"]["empirical_reweighting"]
    )
    stress_reweighting_observed = {
        "processed_stress": (
            100.0 * processed_stress_resampling["estimate"],
            100.0 * processed_stress_resampling["interval"][0],
            100.0 * processed_stress_resampling["interval"][1],
            processed_stress_resampling["draws"],
            processed_stress_resampling["seed"],
        ),
        "statistics_verification": (
            100.0 * verified_stress_resampling["estimate"],
            100.0 * verified_stress_resampling["interval"][0],
            100.0 * verified_stress_resampling["interval"][1],
            verified_stress_resampling["draws"],
            verified_stress_resampling["seed"],
        ),
    }
    if "stress" in release_payloads:
        item = release_payloads["stress"]["trace_disagreement"]
        released_stress_resampling = resampling_record(item)
        stress_reweighting_observed["release_stress"] = (
            100.0 * released_stress_resampling["estimate"],
            100.0 * released_stress_resampling["interval"][0],
            100.0 * released_stress_resampling["interval"][1],
            released_stress_resampling["draws"], released_stress_resampling["seed"],
        )
    bad_stress = {
        source: observed
        for source, observed in stress_reweighting_observed.items()
        if not all(close(a, b, 1e-9) for a, b in zip(observed, expected_stress_reweighting, strict=True))
    }
    if bad_stress:
        audit.conflict(
            "NUM-STRESS-RESAMPLING", "descriptive reweighting specification", expected_stress_reweighting,
            bad_stress, stress_reweighting_observed, "Stress estimate, quantiles, draw count, or analysis seed drifted."
        )
    else:
        audit.pass_check(
            "NUM-STRESS-RESAMPLING", "descriptive reweighting specification", expected_stress_reweighting,
            stress_reweighting_observed, stress_reweighting_observed, "Stress estimate, quantiles, draw count, and analysis seed agree."
        )

    historical_expected = (
        truth["historical_units"], truth["historical_outcome_mismatch"], truth["historical_available_mismatch"]
    )
    historical_observed = {
        "statistics_verification": (
            parse_int(verification["historical"]["units"]),
            parse_int(verification["historical"]["outcome_error_mismatch"]),
            parse_int(verification["historical"]["available_record_mismatch"]),
        )
    }
    if "historical" in release_payloads:
        item = release_payloads["historical"]
        historical_observed["release_historical"] = (
            parse_int(item["units"]), parse_int(item["outcome_record_mismatches"]),
            parse_int(item["available_record_mismatches"]),
        )
    compare_exact(
        audit, "NUM-HISTORICAL", "historical mismatch counts", historical_expected,
        historical_observed, "Historical analysis-unit and available-record mismatch counts must agree."
    )

    factorial_expected = (
        truth["factorial_units"], truth["factorial_games"], truth["factorial_control_mismatch"]
    )
    factorial_observed = {
        "processed_factorial": (
            parse_int(factorial["units"]), parse_int(factorial["games"]), parse_int(factorial["control_mismatch_units"])
        ),
        "statistics_verification": (
            parse_int(verification["factorial"]["units"]),
            parse_int(verification["factorial"]["games"]),
            truth["factorial_control_mismatch"],
        ),
    }
    if "factorial" in release_payloads:
        item = release_payloads["factorial"]
        factorial_observed["release_factorial"] = (
            parse_int(item["units"]), parse_int(item["games"]), parse_int(item["control_mismatch_units"])
        )
    compare_exact(
        audit, "NUM-FACTORIAL-SIZE", "sample and execution counts", factorial_expected,
        factorial_observed, "Factorial units, engine games, and repeated-control mismatch count must agree."
    )

    rates_expected = {key: parse_float(value) for key, value in truth["factorial_rates"].items()}
    rates_observed = {
        "processed_factorial": {key: parse_float(value) for key, value in factorial["cell_win_rates"].items()},
        "statistics_verification": {key: parse_float(value) for key, value in verification["factorial"]["cell_win_rates"].items()},
    }
    if "factorial" in release_payloads:
        rates_observed["release_factorial"] = {
            key: parse_float(value) for key, value in release_payloads["factorial"]["cell_win_rates"].items()
        }
    compare_exact(
        audit, "NUM-FACTORIAL-RATES", "factorial values", rates_expected, rates_observed,
        "All four factorial cell rates must agree across independent outputs."
    )

    contrast_observed: dict[str, Any] = {}
    release_contrast_observed: dict[str, Any] = {}
    contrast_expected: dict[str, Any] = {}
    for name, record in truth["factorial_contrasts"].items():
        contrast_expected[name] = resampling_record(record)
        contrast_observed[name] = resampling_record(factorial["contrasts"][name])
        if "factorial" in release_payloads:
            release_record = release_payloads["factorial"]["contrasts"][name]
            release_contrast_observed[name] = resampling_record(release_record)
    verified_contrast_observed = {
        name: resampling_record(verification["factorial"]["contrasts"][name])
        for name in truth["factorial_contrasts"]
    }
    contrast_sources = {
        "processed_factorial": contrast_observed,
        "statistics_verification": verified_contrast_observed,
    }
    if release_contrast_observed:
        contrast_sources["release_factorial"] = release_contrast_observed
    compare_exact(
        audit, "NUM-FACTORIAL-CONTRASTS", "factorial values", contrast_expected,
        contrast_sources,
        "Factorial estimates, descriptive quantiles, reweighting draws, and seeds must match the checked evidence."
    )

    mcnemar_expected = {
        "c1_only_wins": parse_int(
            truth["factorial_mcnemar_numerical_audit"]["c1_only_wins"]
        ),
        "c4_only_wins": parse_int(
            truth["factorial_mcnemar_numerical_audit"]["c4_only_wins"]
        ),
        "exact_two_sided_p": parse_float(
            truth["factorial_mcnemar_numerical_audit"]["exact_two_sided_p"]
        ),
    }
    mcnemar_observed = {
        "statistics_verification": {
            "c1_only_wins": parse_int(
                verification["factorial"]["mcnemar_numerical_audit_not_admitted"][
                    "c1_only_wins"
                ]
            ),
            "c4_only_wins": parse_int(
                verification["factorial"]["mcnemar_numerical_audit_not_admitted"][
                    "c4_only_wins"
                ]
            ),
            "exact_two_sided_p": parse_float(
                verification["factorial"]["mcnemar_numerical_audit_not_admitted"][
                    "exact_two_sided_p"
                ]
            ),
        },
    }
    if "primary_mcnemar" in factorial:
        item = factorial["primary_mcnemar"]
        mcnemar_observed["processed_factorial"] = {
            "c1_only_wins": parse_int(item["c1_only_wins"]),
            "c4_only_wins": parse_int(item["c4_only_wins"]),
            "exact_two_sided_p": parse_float(item["exact_two_sided_p"]),
        }
    if "factorial" in release_payloads and "primary_mcnemar" in release_payloads["factorial"]:
        item = release_payloads["factorial"]["primary_mcnemar"]
        mcnemar_observed["release_factorial"] = {
            "c1_only_wins": parse_int(item["c1_only_wins"]),
            "c4_only_wins": parse_int(item["c4_only_wins"]),
            "exact_two_sided_p": parse_float(item["exact_two_sided_p"]),
        }
    bad_mcnemar = {
        source: value
        for source, value in mcnemar_observed.items()
        if value["c1_only_wins"] != mcnemar_expected["c1_only_wins"]
        or value["c4_only_wins"] != mcnemar_expected["c4_only_wins"]
        or not close(value["exact_two_sided_p"], mcnemar_expected["exact_two_sided_p"], 1e-12)
    }
    if bad_mcnemar:
        audit.conflict(
            "NUM-MCNEMAR", "numerical audit only; not admitted", mcnemar_expected,
            bad_mcnemar, mcnemar_observed,
            "The nonadmitted McNemar arithmetic check disagrees."
        )
    else:
        audit.pass_check(
            "NUM-MCNEMAR", "numerical audit only; not admitted", mcnemar_expected,
            mcnemar_observed, mcnemar_observed,
            "The nonadmitted McNemar arithmetic check agrees; no inferential claim is authorized."
        )

    expected_macros: dict[str, Any] = {
        "HistoricalUnits": truth["historical_units"],
        "HistoricalOutcomeMismatch": truth["historical_outcome_mismatch"],
        "HistoricalAvailableRecordMismatch": truth["historical_available_mismatch"],
        "PreflightUnits": truth["preflight_units"],
        "PreflightExecutions": truth["preflight_executions"],
        "PreflightMismatches": truth["preflight_mismatches"],
        "StressClusters": truth["stress_clusters"],
        "StressExecutions": truth["stress_executions"],
        "StressTraceMismatch": truth["stress_trace_mismatch"],
        "StressTracePct": truth["stress_trace_pct"],
        "StressTraceLowPct": truth["stress_low_pct"],
        "StressTraceHighPct": truth["stress_high_pct"],
        "StressOutcomeMismatch": truth["stress_outcome_mismatch"],
        "StressDecisionMismatch": truth["stress_decision_mismatch"],
        "StressErrorMismatch": truth["stress_error_mismatch"],
        "ReweightingDraws": truth["factorial_reweighting_draws"],
        "FactorialUnits": truth["factorial_units"],
        "FactorialGames": truth["factorial_games"],
        "FactorialControlMismatch": truth["factorial_control_mismatch"],
    }
    macro_bad: dict[str, Any] = {}
    for name, expected in expected_macros.items():
        if name not in macros:
            macro_bad[name] = "MISSING"
        else:
            try:
                if isinstance(expected, float):
                    if not close(macros[name], expected, 1e-9):
                        macro_bad[name] = macros[name]
                elif parse_int(macros[name]) != expected:
                    macro_bad[name] = macros[name]
            except ValueError:
                macro_bad[name] = macros[name]
    if macro_bad:
        audit.conflict(
            "NUM-GENERATED-MACROS", "generated numerical prose", expected_macros,
            macro_bad, [relative(FINAL / "results_macros.tex")],
            "Generated central-result macros are missing or inconsistent."
        )
    else:
        audit.pass_check(
            "NUM-GENERATED-MACROS", "generated numerical prose", expected_macros,
            expected_macros, [relative(FINAL / "results_macros.tex")],
            "Generated count and disagreement macros agree with the checked evidence."
        )

    contrast_macro_names = {
        "primary_c4_minus_c1": ("PrimaryEstimatePP", "PrimaryLowPP", "PrimaryHighPP"),
        "representation_main": ("RepresentationEstimatePP", "RepresentationLowPP", "RepresentationHighPP"),
        "training_main": ("TrainingEstimatePP", "TrainingLowPP", "TrainingHighPP"),
        "interaction": ("InteractionEstimatePP", "InteractionLowPP", "InteractionHighPP"),
    }
    contrast_macro_bad: dict[str, Any] = {}
    for name, macro_names in contrast_macro_names.items():
        record = truth["factorial_contrasts"][name]
        normalized_record = resampling_record(record)
        expected_pp = (
            100.0 * normalized_record["estimate"],
            100.0 * normalized_record["interval"][0],
            100.0 * normalized_record["interval"][1],
        )
        observed = tuple(macros.get(macro, "MISSING") for macro in macro_names)
        try:
            if not all(close(a, b, 0.006) for a, b in zip(observed, expected_pp, strict=True)):
                contrast_macro_bad[name] = {"expected": expected_pp, "observed": observed}
        except ValueError:
            contrast_macro_bad[name] = {"expected": expected_pp, "observed": observed}
    if contrast_macro_bad:
        audit.conflict(
            "NUM-FACTORIAL-MACROS", "generated numerical prose", "rounded checked contrasts",
            contrast_macro_bad, [relative(FINAL / "results_macros.tex")],
            "Generated factorial contrast/quantile macros disagree after declared two-decimal rounding."
        )
    else:
        audit.pass_check(
            "NUM-FACTORIAL-MACROS", "generated numerical prose", "rounded checked contrasts",
            "all four agree", [relative(FINAL / "results_macros.tex")],
            "All factorial estimate and interval macros agree after two-decimal rounding."
        )


def tuple_claims(text: str, patterns: Iterable[str]) -> list[tuple[int, ...]]:
    claims: list[tuple[int, ...]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I | re.S):
            try:
                claims.append(tuple(parse_int(value) for value in match.groups()))
            except ValueError:
                continue
    return claims


def check_textual_numbers(audit: Audit, truth: dict[str, Any], macros: dict[str, str]) -> None:
    paths = [
        FINAL / "main.tex",
        FINAL / "cover_letter.md",
        FINAL / "METHOD_ASSUMPTION_AUDIT.md",
        FINAL / "AUTHOR_DEFENSE_GUIDE.md",
        FINAL / "SUBMISSION_CHECKLIST.md",
        FINAL / "tables/table_3_prospective_results.tex",
        FINAL / "tables/table_4_factorial.tex",
        PAPER / "protocol/PEVL_PROSPECTIVE_PROTOCOL.md",
        FINAL / "release/README.md",
    ]
    observed_by_fact: dict[str, dict[str, list[tuple[int, ...]]]] = {
        key: {} for key in ("historical", "preflight", "stress_direct", "stress_of", "factorial")
    }
    for path in paths:
        if not path.is_file():
            continue
        expanded = normalize_space(expand_macros(path.read_text(encoding="utf-8"), macros))
        source = relative(path)
        observed_by_fact["historical"][source] = tuple_claims(
            expanded,
            (
                r"(\d[\d,]*)\s*(?:of|/)\s*(\d[\d,]*).{0,90}?(?:outcome|win/draw).{0,180}?(\d[\d,]*)\s*(?:of|/)\s*(\d[\d,]*).{0,100}?decision count",
                r"(\d[\d,]*)\s*(?:of|/)\s*(\d[\d,]*).{0,100}?(?:outcome|win/draw).{0,220}?(\d[\d,]*)\s*(?:of|/)\s*(\d[\d,]*).{0,100}?available",
            ),
        )
        observed_by_fact["preflight"][source] = tuple_claims(
            expanded,
            (
                r"(\d[\d,]*)\s+(?:arm[- ]+)?seed[- ]condition\s+(?:units|trajectories).{0,90}?(\d[\d,]*)\s+(?:execution trajectories|executions|games)",
                r"(\d[\d,]*)\s+deterministic preflight units\s*\((\d[\d,]*)\s+executions\)",
            ),
        )
        observed_by_fact["stress_direct"][source] = tuple_claims(
            expanded,
            (
                r"(\d[\d,]*)\s*(?:of|/)\s*(\d[\d,]*).{0,80}?trace[- ](?:projection )?disagreement",
                r"found\s+(\d[\d,]*).{0,70}?trace[- ]projection disagreement.{0,40}?(?:among|of)\s+(\d[\d,]*)",
            ),
        )
        observed_by_fact["stress_of"][source] = tuple_claims(
            expanded,
            (r"of\s+(\d[\d,]*)\s+clusters\s+and\s+(\d[\d,]*)\s+executions,\s+(\d[\d,]*)\s+clusters had.{0,40}?trace",),
        )
        observed_by_fact["factorial"][source] = tuple_claims(
            expanded,
            (
                r"(\d[\d,]*)\s+(?:common |fixed[- ]schedule )?units per cell.{0,140}?(\d[\d,]*)\s+(?:engine )?games",
                r"(\d[\d,]*)\s+factorial units.{0,70}?(\d[\d,]*)\s+(?:engine )?games",
            ),
        )

    expected = {
        "historical": (
            truth["historical_outcome_mismatch"], truth["historical_units"],
            truth["historical_available_mismatch"], truth["historical_units"],
        ),
        "preflight": (truth["preflight_units"], truth["preflight_executions"]),
        "stress_direct": (truth["stress_trace_mismatch"], truth["stress_clusters"]),
        "stress_of": (truth["stress_clusters"], truth["stress_executions"], truth["stress_trace_mismatch"]),
        "factorial": (truth["factorial_units"], truth["factorial_games"]),
    }
    for fact, by_source in observed_by_fact.items():
        claims = [(source, value) for source, values in by_source.items() for value in values]
        wrong = [{"source": source, "observed": value} for source, value in claims if value != expected[fact]]
        if wrong:
            audit.conflict(
                f"PROSE-{fact.upper().replace('_', '-')}", "numerical prose",
                expected[fact], wrong, [item["source"] for item in wrong],
                f"A prose declaration of {fact.replace('_', ' ')} disagrees with authoritative evidence."
            )
        else:
            audit.pass_check(
                f"PROSE-{fact.upper().replace('_', '-')}", "numerical prose",
                expected[fact], {source: values for source, values in by_source.items() if values},
                [source for source, values in by_source.items() if values],
                f"Every detected prose declaration of {fact.replace('_', ' ')} agrees."
            )

    # The headline percentages and intervals are deliberately checked as exact
    # strings after macro expansion; unlike a generic number scan this does not
    # confuse equation examples with empirical results.
    central = "\n".join(
        expand_macros(path.read_text(encoding="utf-8"), macros)
        for path in paths
        if path.is_file()
    ).replace("−", "-").replace("–", "-")
    primary_resampling = resampling_record(truth["factorial_contrasts"]["primary_c4_minus_c1"])
    expected_fragments = {
        "stress_percent": [truth["stress_trace_pct"], truth["stress_low_pct"], truth["stress_high_pct"]],
        "primary_factorial_pp": [
            100 * primary_resampling["estimate"],
            100 * primary_resampling["interval"][0],
            100 * primary_resampling["interval"][1],
        ],
    }
    stress_patterns = re.findall(
        r"(\d+(?:\.\d+)?)\s*%[^.;\n]{0,100}?(\d+(?:\.\d+)?)\s*%\s*[-,]\s*(\d+(?:\.\d+)?)\s*%",
        normalize_space(central), re.I,
    )
    wrong_stress = [row for row in stress_patterns if not all(close(a, b, 0.051) for a, b in zip(row, expected_fragments["stress_percent"], strict=True))]
    if wrong_stress:
        audit.conflict(
            "PROSE-STRESS-INTERVAL", "numerical prose", expected_fragments["stress_percent"],
            wrong_stress, [relative(path) for path in paths if path.is_file()],
            "A detected stress percentage/interval tuple is inconsistent."
        )
    else:
        audit.pass_check(
            "PROSE-STRESS-INTERVAL", "numerical prose", expected_fragments["stress_percent"],
            stress_patterns, [relative(path) for path in paths if path.is_file()],
            "Detected stress percentage/interval tuples use the checked values."
        )


def check_seeds(audit: Audit, payloads: dict[str, Any], truth: dict[str, Any]) -> None:
    seed_audit = truth["seed_audit"]
    protocol_path = PAPER / "protocol/PEVL_PROSPECTIVE_PROTOCOL.md"
    protocol = protocol_path.read_text(encoding="utf-8") if protocol_path.is_file() else ""
    seed_checks = {
        "factorial_draws": (truth["factorial_reweighting_draws"], r"95% intervals use\s+([\d,]+)\s+paired resamples"),
        "factorial_seed": (truth["factorial_reweighting_seed"], r"paired resamples.{0,120}?seed\s+`?(\d+)`?"),
        "stress_draws": (truth["stress_reweighting_draws"], r"timed-search disagreement proportions use\s+([\d,]+)\s+cluster bootstrap"),
        "stress_seed": (truth["stress_reweighting_seed"], r"cluster bootstrap draws.{0,80}?seed\s+`?(\d+)`?"),
    }
    for name, (expected, pattern) in seed_checks.items():
        match = re.search(pattern, normalize_space(protocol), re.I | re.S)
        observed = parse_int(match.group(1)) if match else "MISSING"
        if observed == expected:
            audit.pass_check(
                f"SEED-{name.upper().replace('_', '-')}", "frozen resampling specification (legacy source wording)", expected,
                observed, [relative(protocol_path)], "The frozen protocol agrees with the result artifact."
            )
        else:
            audit.conflict(
                f"SEED-{name.upper().replace('_', '-')}", "frozen resampling specification (legacy source wording)", expected,
                observed, [relative(protocol_path)], "The frozen protocol and result artifact disagree."
            )

    prospective = seed_audit["prospective_all"]
    study = seed_audit["prospective_study_summary"]
    expected_counts = {
        "trace_preflight": 250,
        "timed_search_stress": truth["stress_clusters"],
        "factorial": truth["factorial_units"],
    }
    observed_counts = {key: parse_int(study[key]["scheduled_count"]) for key in expected_counts}
    if observed_counts == expected_counts and parse_int(prospective["scheduled_count"]) == sum(expected_counts.values()):
        audit.pass_check(
            "SEED-SCHEDULE-COUNTS", "seed ranges", {**expected_counts, "total": sum(expected_counts.values())},
            {**observed_counts, "total": parse_int(prospective["scheduled_count"])},
            [relative(REQUIRED_JSON["seed_audit"])], "Prospective seed-namespace counts agree with the three schedules."
        )
    else:
        audit.conflict(
            "SEED-SCHEDULE-COUNTS", "seed ranges", {**expected_counts, "total": sum(expected_counts.values())},
            {**observed_counts, "total": prospective.get("scheduled_count")},
            [relative(REQUIRED_JSON["seed_audit"])], "Prospective seed-namespace counts are inconsistent."
        )

    expected_range = (2026072700, 2027093749)
    observed_range = (parse_int(prospective["scheduled_min"]), parse_int(prospective["scheduled_max"]))
    collision_state = (
        bool(prospective["passed_no_collision"]),
        parse_int(prospective["scheduled_unique"]),
        parse_int(prospective["engine_seed_unique"]),
    )
    expected_collision_state = (True, sum(expected_counts.values()), sum(expected_counts.values()))
    if observed_range == expected_range and collision_state == expected_collision_state:
        audit.pass_check(
            "SEED-PROSPECTIVE-RANGE", "seed ranges",
            {"range": expected_range, "collision_state": expected_collision_state},
            {"range": observed_range, "collision_state": collision_state},
            [relative(REQUIRED_JSON["seed_audit"]), relative(protocol_path)],
            "The prospective scheduled and converted seed namespace is collision free over the frozen range."
        )
    else:
        audit.conflict(
            "SEED-PROSPECTIVE-RANGE", "seed ranges",
            {"range": expected_range, "collision_state": expected_collision_state},
            {"range": observed_range, "collision_state": collision_state},
            [relative(REQUIRED_JSON["seed_audit"]), relative(protocol_path)],
            "The prospective seed range or uniqueness declaration drifted."
        )


def check_protocol_reporting_provenance(audit: Audit) -> None:
    """Fail closed on frozen-plan claims added only after outcome acquisition."""
    protocol_path = PAPER / "protocol/PEVL_PROSPECTIVE_PROTOCOL.md"
    manuscript_path = FINAL / "main.tex"
    protocol_text = (
        protocol_path.read_text(encoding="utf-8") if protocol_path.is_file() else ""
    )
    manuscript_text = (
        manuscript_path.read_text(encoding="utf-8") if manuscript_path.is_file() else ""
    )
    state = provenance_semantics_state(protocol_text, manuscript_text)

    requirements = (
        (
            "PROVENANCE-FROZEN-95-INTERVALS",
            "frozen_95_percent_intervals",
            "the frozen protocol visibly prescribes 95% intervals",
            [relative(protocol_path)],
            "The completed report must not conceal or rewrite the frozen 95% interval prescription.",
        ),
        (
            "PROVENANCE-FROZEN-EXACT-MCNEMAR",
            "frozen_exact_two_sided_mcnemar",
            "the frozen protocol visibly prescribes exact two-sided McNemar inference",
            [relative(protocol_path)],
            "The completed report must preserve the frozen exact two-sided McNemar prescription as protocol history.",
        ),
        (
            "PROVENANCE-FROZEN-STRESS-OUTPUTS",
            "frozen_stress_localization_timing_promise",
            "the frozen stress section promises localization and timing summaries in the public package",
            [relative(protocol_path)],
            "The frozen stress-output promise must remain machine visible when omissions are assessed.",
        ),
        (
            "PROVENANCE-POST-ACQUISITION-TAXONOMY",
            "completed_case_taxonomy_is_post_acquisition",
            (
                "the manuscript explicitly identifies the completed-case descriptive-only Level "
                "taxonomy/reporting restriction as post-acquisition and outside the frozen plan"
            ),
            [relative(manuscript_path), relative(protocol_path)],
            "A later conservative reporting restriction cannot be described as prospectively frozen.",
        ),
        (
            "PROVENANCE-HISTORICAL-RETROSPECTIVE",
            "historical_audit_is_retrospective_not_blinding",
            (
                "the manuscript says the frozen historical audit was retrospective after outcomes "
                "existed and is not evidence of prospective blinding"
            ),
            [relative(manuscript_path), relative(protocol_path)],
            "Git ordering or an outcome-invariant audit cannot be promoted to prospective blinding.",
        ),
        (
            "PROVENANCE-DIGEST-BYTE-EXTENSION",
            "digest_byte_is_later_extension_without_count_change",
            (
                "the manuscript says digest-plus-byte-count is a later integrity extension, the "
                "frozen endpoint was the digest, and no reported mismatch count changed"
            ),
            [relative(manuscript_path), relative(protocol_path)],
            "A later integrity extension must not be attributed to the frozen endpoint.",
        ),
        (
            "PROVENANCE-STRESS-REPORTING-DEVIATION",
            "stress_partial_recovery_and_position_deviation_disclosed",
            (
                "the manuscript says acting-side counts and timing summaries were recovered from "
                "hash-pinned evidence but remain redistribution-rights-pending, while promised "
                "positions were never recorded, position-level localization remains unverifiable, "
                "and the omission remains a protocol/reporting deviation"
            ),
            [relative(manuscript_path), relative(protocol_path)],
            "Partial recovery must not conceal the unrecovered position-level deviation or its rights gate.",
        ),
    )
    for check_id, key, expected, evidence, message in requirements:
        observed = bool(state[key])
        if observed:
            audit.pass_check(
                check_id,
                "protocol/reporting provenance",
                expected,
                "explicit bounded disclosure found",
                evidence,
                message,
            )
        else:
            audit.conflict(
                check_id,
                "protocol/reporting provenance",
                expected,
                "required explicit disclosure not found",
                evidence,
                message,
            )

    prohibited_hits = state["prohibited_phrase_hits"]
    if prohibited_hits:
        audit.conflict(
            "PROVENANCE-NO-FALSE-FROZEN-PHRASES",
            "protocol/reporting provenance",
            "none of the known false frozen-admission formulations",
            prohibited_hits,
            [relative(manuscript_path), relative(protocol_path)],
            "The manuscript retains language that falsely attributes a post-acquisition admission taxonomy to the frozen plan.",
        )
    else:
        audit.pass_check(
            "PROVENANCE-NO-FALSE-FROZEN-PHRASES",
            "protocol/reporting provenance",
            "none of the known false frozen-admission formulations",
            "none detected",
            [relative(manuscript_path), relative(protocol_path)],
            "Known false frozen-admission formulations are absent.",
        )


def check_hashes(audit: Audit, payloads: dict[str, Any], truth: dict[str, Any]) -> None:
    identities = truth["identity_hashes"]
    observed: dict[str, Any] = {}
    for role, path in CANONICAL_INPUT_PATHS.items():
        if not path.is_file():
            observed[role] = "MISSING"
        else:
            observed[role] = sha256(path)
    bad = {
        role: {"expected": identities.get(role), "observed": value}
        for role, value in observed.items()
        if identities.get(role) != value
    }
    if bad:
        audit.conflict(
            "HASH-CANONICAL-INPUTS", "result hashes", identities, bad,
            [relative(path) for path in CANONICAL_INPUT_PATHS.values()],
            "A canonical input no longer matches the hash bound into artifact identity."
        )
    else:
        audit.pass_check(
            "HASH-CANONICAL-INPUTS", "result hashes", identities, observed,
            [relative(path) for path in CANONICAL_INPUT_PATHS.values()],
            "Canonical protocol/result/source-audit bytes match their declared hashes."
        )

    macro_text = (FINAL / "results_macros.tex").read_text(encoding="utf-8")
    header_hashes = dict(re.findall(r"^%\s+([a-z_]+)_sha256=([0-9a-f]{64})$", macro_text, re.M))
    expected_header = {key: identities[key] for key in ("combined", "preflight", "stress", "factorial")}
    if header_hashes == expected_header:
        audit.pass_check(
            "HASH-MACRO-HEADER", "result hashes", expected_header, header_hashes,
            [relative(FINAL / "results_macros.tex")], "Generated macros identify the same central inputs."
        )
    else:
        audit.conflict(
            "HASH-MACRO-HEADER", "result hashes", expected_header, header_hashes,
            [relative(FINAL / "results_macros.tex")], "Generated macro provenance differs from artifact identity."
        )

    build = payloads.get("build")
    if isinstance(build, dict):
        declared = build.get("generated_sha256", {})
        mismatches: dict[str, Any] = {}
        for name, expected_hash in declared.items():
            path = FINAL / name
            if not path.is_file():
                mismatches[name] = {"expected": expected_hash, "observed": "MISSING"}
            else:
                actual = sha256(path)
                if actual != expected_hash:
                    mismatches[name] = {"expected": expected_hash, "observed": actual}
        if mismatches:
            audit.conflict(
                "HASH-GENERATED-ARTIFACTS", "figure/table/result hashes", declared,
                mismatches, [relative(FINAL / name) for name in mismatches],
                "A generated source-data, macro, figure, or table artifact is stale."
            )
        else:
            audit.pass_check(
                "HASH-GENERATED-ARTIFACTS", "figure/table/result hashes", len(declared), len(declared),
                [relative(FINAL / name) for name in declared], "Generated artifacts match the build report."
            )

    manifest_path = FINAL / "release/MANIFEST.sha256"
    if manifest_path.is_file():
        release = manifest_path.parent
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
        manifest: dict[str, str] = {}
        malformed: list[str] = []
        for line in lines:
            match = re.fullmatch(r"([0-9a-f]{64})  ([^\r\n]+)", line)
            if not match:
                malformed.append(line)
                continue
            name = match.group(2)
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or name != pure.as_posix() or name in manifest:
                malformed.append(line)
                continue
            manifest[name] = match.group(1)
        actual_files = {
            path.relative_to(release).as_posix()
            for path in release.rglob("*")
            if path.is_file() and path != manifest_path and "__pycache__" not in path.parts and path.suffix != ".pyc"
        }
        mismatches = {
            name: {"expected": expected_hash, "observed": sha256(release / name) if (release / name).is_file() else "MISSING"}
            for name, expected_hash in manifest.items()
            if not (release / name).is_file() or sha256(release / name) != expected_hash
        }
        if malformed or set(manifest) != actual_files or mismatches:
            audit.machine(
                "HASH-RELEASE-MANIFEST", "release manifest",
                "well-formed complete manifest with matching hashes",
                {"malformed": malformed, "missing": sorted(actual_files - set(manifest)), "extra": sorted(set(manifest) - actual_files), "mismatches": mismatches},
                [relative(manifest_path)], "The release manifest is malformed, incomplete, or stale."
            )
        else:
            audit.pass_check(
                "HASH-RELEASE-MANIFEST", "release manifest", len(actual_files), len(manifest),
                [relative(manifest_path)], "The release manifest covers every payload except itself and all hashes match."
            )


def detect_actual_doi(text: str) -> list[str]:
    return sorted(set(re.findall(r"(?i)\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", text)))


def check_release_and_disclosures(audit: Audit) -> None:
    paths = {
        "manuscript": FINAL / "main.tex",
        "data_availability": FINAL / "data_availability.md",
        "cover_letter": FINAL / "cover_letter.md",
        "ai_disclosure": FINAL / "ai_disclosure.md",
        "release_readme": FINAL / "release/README.md",
        "release_status": FINAL / "release/RELEASE_STATUS.json",
        "release_license": FINAL / "release/LICENSE",
    }
    texts = {name: path.read_text(encoding="utf-8") for name, path in paths.items() if path.is_file()}

    negative_public_patterns = (
        r"public archival availability.{0,60}?not (?:yet )?established",
        r"not an authorized archive",
        r"built_for_review_not_authorized_for_publication",
        r"does not describe the package as public",
    )
    unqualified_public = re.compile(
        r"(?i)\b(?:is|are|now|currently|has been)\s+(?:publicly available|openly available|archived)\b|"
        r"\bpublic release (?:is|has been) available\b"
    )
    public_conflicts: dict[str, list[str]] = {}
    for name, text in texts.items():
        hits = []
        for match in unqualified_public.finditer(text):
            window = text[max(0, match.start() - 80):match.end() + 20]
            if re.search(
                r"(?i)block(?:s|ed)? any claim|does not describe|cannot (?:claim|describe)|"
                r"not (?:claim|describe)|no claim",
                window,
            ):
                continue
            hits.append(match.group(0))
        if hits:
            public_conflicts[relative(paths[name])] = hits
    status_doc_count = sum(
        1 for name in ("manuscript", "data_availability", "cover_letter", "release_readme", "release_status")
        if name in texts and any(re.search(pattern, normalize_space(texts[name]), re.I) for pattern in negative_public_patterns)
    )
    if public_conflicts:
        audit.conflict(
            "STATUS-PUBLIC-AVAILABILITY", "open/release status",
            "review package is not an authorized public archive", public_conflicts,
            public_conflicts, "An unqualified public/archive claim conflicts with the unresolved rights status."
        )
    elif status_doc_count >= 4:
        audit.pass_check(
            "STATUS-PUBLIC-AVAILABILITY", "open/release status",
            "not publicly archived or distribution-authorized", status_doc_count,
            [relative(path) for name, path in paths.items() if name in texts],
            "Submission and release documents consistently distinguish a review package from an authorized public archive."
        )
    else:
        audit.machine(
            "STATUS-PUBLIC-AVAILABILITY", "open/release status",
            "explicit bounded status in manuscript, availability statement, cover letter, and release metadata",
            status_doc_count, [relative(path) for name, path in paths.items() if name in texts],
            "Too few final documents establish the same bounded release status."
        )

    doi_hits = {relative(paths[name]): detect_actual_doi(text) for name, text in texts.items() if detect_actual_doi(text)}
    if doi_hits:
        audit.conflict(
            "STATUS-DOI", "DOI status", "no software/data DOI until a verified archive exists",
            doi_hits, doi_hits, "A DOI appears in a release/submission status document despite the declared no-DOI state."
        )
    else:
        audit.pass_check(
            "STATUS-DOI", "DOI status", "no DOI assigned", "no DOI syntax detected",
            [relative(path) for name, path in paths.items() if name in texts],
            "No software/data DOI is invented in the audited status documents."
        )

    license_text = texts.get("release_license", "")
    permissive = re.search(r"(?i)permission is hereby granted|apache license|gnu general public license|bsd license", license_text)
    no_license = bool(re.search(r"(?i)no license granted|no .* permission is granted", license_text))
    if permissive or ("release_license" in texts and not no_license):
        audit.conflict(
            "STATUS-LICENSE", "license status", "NO LICENSE GRANTED pending human rights approval",
            normalize_space(license_text[:400]), [relative(paths["release_license"])],
            "The release license does not agree with the unresolved-rights status."
        )
    elif "release_license" in texts:
        audit.pass_check(
            "STATUS-LICENSE", "license status", "NO LICENSE GRANTED", "NO LICENSE GRANTED",
            [relative(paths["release_license"]), relative(paths["data_availability"]), relative(paths["manuscript"])],
            "The license notice and availability statements agree that no redistribution permission is established."
        )

    future_promises: dict[str, list[str]] = {}
    promise_re = re.compile(r"(?i)\b(?:will be|shall be)\s+(?:released|made public|archived|deposited)\b|\bupon publication\b")
    for name, text in texts.items():
        hits = [match.group(0) for match in promise_re.finditer(text)]
        if hits:
            future_promises[relative(paths[name])] = hits
    if future_promises:
        audit.conflict(
            "STATUS-NO-FUTURE-PROMISE", "release status", "no future-release promise",
            future_promises, future_promises, "A future release/archive promise is unsupported."
        )
    else:
        audit.pass_check(
            "STATUS-NO-FUTURE-PROMISE", "release status", "no future-release promise",
            "none detected", [relative(path) for name, path in paths.items() if name in texts],
            "No audited file promises a future public release."
        )

    restricted_docs = {
        name: text for name, text in texts.items()
        if name in {"manuscript", "data_availability", "cover_letter", "release_readme"}
    }
    restricted_presence: dict[str, dict[str, bool]] = {}
    for name, text in restricted_docs.items():
        text = normalize_space(text)
        restricted_presence[relative(paths[name])] = {
            category: any(re.search(pattern, text, re.I) for pattern in patterns)
            for category, patterns in EXPECTED_RESTRICTED_CATEGORIES.items()
        }
    incomplete = {
        source: [category for category, present in categories.items() if not present]
        for source, categories in restricted_presence.items()
        if not all(categories.values())
    }
    if incomplete:
        audit.conflict(
            "STATUS-RESTRICTED-LIST", "restricted-material status",
            sorted(EXPECTED_RESTRICTED_CATEGORIES), incomplete,
            incomplete, "A final availability/release document omits a canonical restricted-material category."
        )
    elif restricted_presence:
        audit.pass_check(
            "STATUS-RESTRICTED-LIST", "restricted-material status",
            sorted(EXPECTED_RESTRICTED_CATEGORIES), restricted_presence,
            restricted_presence, "The canonical restricted-material categories agree across final documents."
        )

    on_request_conflicts: dict[str, list[str]] = {}
    for name, text in restricted_docs.items():
        for match in re.finditer(r"(?i).{0,45}available on request.{0,45}", text):
            window = match.group(0)
            if not re.search(r"(?i)not|neither|cannot|do not", window):
                on_request_conflicts.setdefault(relative(paths[name]), []).append(normalize_space(window))
    if on_request_conflicts:
        audit.conflict(
            "STATUS-ON-REQUEST", "restricted-material status",
            "no available-on-request claim without authority", on_request_conflicts,
            on_request_conflicts, "A restricted-material access promise lacks an established mechanism."
        )
    else:
        audit.pass_check(
            "STATUS-ON-REQUEST", "restricted-material status",
            "no unsupported available-on-request claim", "none detected",
            [relative(paths[name]) for name in restricted_docs],
            "Restricted materials are not offered on request."
        )

    ai_docs = {
        "manuscript": texts.get("manuscript", ""),
        "ai_disclosure": texts.get("ai_disclosure", ""),
        "cover_letter": texts.get("cover_letter", ""),
        "ai_log": (FINAL / "supplement/AI_USE_LOG.csv").read_text(encoding="utf-8") if (FINAL / "supplement/AI_USE_LOG.csv").is_file() else "",
    }
    ai_requirements = {
        "tool": r"OpenAI Codex",
        "model_precision": r"GPT-5-family",
        "snapshot_unexposed": r"exact deployed snapshot.{0,30}(?:not exposed|was not exposed|not expose)",
        "not_author": r"no AI system is an author|OpenAI Codex is not an author|list no AI system as an author",
        "no_generated_image": r"no generative-image system was used|no AI-generated figure was used",
    }
    ai_missing: dict[str, list[str]] = {}
    for name, text in ai_docs.items():
        required_here = set(ai_requirements)
        if name == "ai_log":
            required_here = {"tool", "model_precision", "snapshot_unexposed", "not_author", "no_generated_image"}
        for requirement in required_here:
            if not re.search(ai_requirements[requirement], normalize_space(text), re.I):
                ai_missing.setdefault(name, []).append(requirement)
    if ai_missing:
        audit.conflict(
            "DISCLOSURE-AI-CONSISTENCY", "AI-use description", sorted(ai_requirements),
            ai_missing, [relative(FINAL / ("supplement/AI_USE_LOG.csv" if name == "ai_log" else ("main.tex" if name == "manuscript" else f"{name}.md"))) for name in ai_missing],
            "A final AI disclosure omits or contradicts the common tool/model/authorship/image boundary."
        )
    else:
        audit.pass_check(
            "DISCLOSURE-AI-CONSISTENCY", "AI-use description", sorted(ai_requirements),
            "consistent", [relative(FINAL / "main.tex"), relative(FINAL / "ai_disclosure.md"), relative(FINAL / "cover_letter.md"), relative(FINAL / "supplement/AI_USE_LOG.csv")],
            "AI tool, exposed model precision, human authority, authorship, and figure statements agree."
        )

    private_scan_paths = [FINAL / "main.tex", FINAL / "cover_letter.md"] + text_files_under(FINAL / "release")
    private_hits: dict[str, list[str]] = {}
    for path in private_scan_paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for pattern in PROHIBITED_PRIVATE_LABELS:
            matches = sorted(set(match.group(0) for match in re.finditer(pattern, text, re.I)))
            if matches:
                private_hits.setdefault(relative(path), []).extend(matches)
    if private_hits:
        audit.conflict(
            "LABELS-NEUTRAL", "agent/opponent labels", "neutral context labels in manuscript and release",
            private_hits, private_hits, "Private or game-specific package labels escaped into final reader-facing/release files."
        )
    else:
        audit.pass_check(
            "LABELS-NEUTRAL", "agent/opponent labels", "neutral labels", "no private labels detected",
            [relative(path) for path in private_scan_paths if path.is_file()],
            "Manuscript, cover letter, and release use neutral context labels."
        )


def check_figures_tables(audit: Audit, payloads: dict[str, Any]) -> None:
    main_path = FINAL / "main.tex"
    main = main_path.read_text(encoding="utf-8") if main_path.is_file() else ""
    figure_refs = re.findall(r"\\includegraphics(?:\[[^]]*\])?\{([^{}]+)\}", main)
    table_refs = re.findall(r"\\input\{(tables/[^{}]+\.tex)\}", main)
    figure_captions = re.findall(r"\\caption\{", main)
    expected_figures = [f"figures/figure_{index}_{stem}.pdf" for index, stem in (
        (1, "distinctions"), (2, "admission_flow"), (3, "synthetic_matrix"),
        (4, "timed_search"), (5, "factorial"),
    )]
    expected_tables = [f"tables/table_{index}_{stem}.tex" for index, stem in (
        (1, "prior_work"), (2, "protocol_stages"), (3, "prospective_results"), (4, "factorial"),
    )]
    actual_figure_files = sorted(path.relative_to(FINAL).as_posix() for path in (FINAL / "figures").glob("figure_*.pdf"))
    actual_table_files = sorted(path.relative_to(FINAL).as_posix() for path in (FINAL / "tables").glob("table_*.tex"))
    table_caption_count = 0
    for name in expected_tables:
        path = FINAL / name
        if path.is_file():
            table_caption_count += len(re.findall(r"\\caption\{", path.read_text(encoding="utf-8")))
    observed = {
        "manuscript_figure_refs": figure_refs,
        "figure_files": actual_figure_files,
        "manuscript_table_refs": table_refs,
        "table_files": actual_table_files,
        "manuscript_caption_count": len(figure_captions) + table_caption_count,
    }
    expected = {
        "manuscript_figure_refs": expected_figures,
        "figure_files": expected_figures,
        "manuscript_table_refs": expected_tables,
        "table_files": expected_tables,
        "manuscript_caption_count": 9,
    }
    if observed != expected:
        audit.conflict(
            "INVENTORY-FIGURES-TABLES", "figures and tables", expected, observed,
            [relative(main_path), relative(FINAL / "figures"), relative(FINAL / "tables")],
            "Manuscript references, generated files, or caption count do not match the frozen five-figure/four-table inventory."
        )
    else:
        audit.pass_check(
            "INVENTORY-FIGURES-TABLES", "figures and tables", expected, observed,
            [relative(main_path)] + expected_figures + expected_tables,
            "The manuscript contains five generated figures and four generated tables."
        )

    source_refs = re.findall(r"source\\_data/([A-Za-z0-9\\_]+\.(?:csv|json))", main)
    normalized_refs = [name.replace(r"\_", "_") for name in source_refs]
    missing_sources = [name for name in normalized_refs if not (FINAL / "source_data" / name).is_file()]
    if len(normalized_refs) != 5 or missing_sources:
        audit.conflict(
            "INVENTORY-FIGURE-SOURCE-DATA", "figures and tables",
            "five existing figure source-data files", {"references": normalized_refs, "missing": missing_sources},
            [relative(main_path)], "Figure captions and source-data inventory disagree."
        )
    else:
        audit.pass_check(
            "INVENTORY-FIGURE-SOURCE-DATA", "figures and tables", 5, len(normalized_refs),
            [relative(FINAL / "source_data" / name) for name in normalized_refs],
            "Every figure caption points to an existing source-data file."
        )

    build = payloads.get("build", {})
    generated = set(build.get("generated", [])) if isinstance(build, dict) else set()
    expected_generated = set(expected_figures + expected_tables)
    missing_from_build = sorted(expected_generated - generated)
    if missing_from_build:
        audit.conflict(
            "INVENTORY-BUILD-REPORT", "figures and tables", sorted(expected_generated),
            {"missing": missing_from_build}, [relative(REQUIRED_JSON["build"])],
            "The build report does not account for every main figure/table."
        )
    else:
        audit.pass_check(
            "INVENTORY-BUILD-REPORT", "figures and tables", len(expected_generated), len(expected_generated),
            [relative(REQUIRED_JSON["build"])], "The build report accounts for every main figure and table."
        )

    release = FINAL / "release"
    if release.is_dir():
        release_figures = sorted(path.name for path in (release / "figures").glob("figure_*.pdf"))
        release_tables = sorted(path.name for path in (release / "tables").glob("table_*.tex"))
        expected_release_figures = sorted(Path(name).name for name in expected_figures)
        expected_release_tables = sorted(Path(name).name for name in expected_tables)
        if release_figures != expected_release_figures or release_tables != expected_release_tables:
            audit.conflict(
                "INVENTORY-RELEASE-FIGURES-TABLES", "figures and tables",
                {"figures": expected_release_figures, "tables": expected_release_tables},
                {"figures": release_figures, "tables": release_tables},
                [relative(release / "figures"), relative(release / "tables")],
                "Release figure/table inventory differs from the manuscript."
            )
        else:
            audit.pass_check(
                "INVENTORY-RELEASE-FIGURES-TABLES", "figures and tables",
                {"figures": 5, "tables": 4}, {"figures": len(release_figures), "tables": len(release_tables)},
                [relative(release / "README.md")], "Release and manuscript figure/table inventories agree."
            )


def check_claim_ledger(audit: Audit) -> None:
    path = FINAL / "claim_ledger.csv"
    if not path.is_file():
        return
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as exc:
        audit.machine(
            "LEDGER-PARSE", "claim status", "parseable claim ledger", str(exc),
            [relative(path)], "The claim ledger could not be parsed."
        )
        return
    disallowed = [
        {"claim_id": row.get("claim_id", ""), "status": row.get("status", "")}
        for row in rows
        if row.get("status", "") not in ALLOWED_CLAIM_STATUSES
    ]
    duplicate_ids = sorted({
        row.get("claim_id", "")
        for row in rows
        if sum(other.get("claim_id", "") == row.get("claim_id", "") for other in rows) > 1
    })
    main_text = normalized_main = ""
    if (FINAL / "main.tex").is_file():
        main_text = (FINAL / "main.tex").read_text(encoding="utf-8")
        normalized_main = normalize_space(main_text)
    missing_sentences = [
        row.get("claim_id", "")
        for row in rows
        if row.get("exact_sentence", "") and normalize_space(row["exact_sentence"]) not in normalized_main
    ]
    wrong_commits = [
        {"claim_id": row.get("claim_id", ""), "protocol_commit": row.get("protocol_commit", "")}
        for row in rows
        if row.get("protocol_commit", "") not in {EXPECTED_PROTOCOL_COMMIT, "not applicable"}
    ]
    if disallowed or duplicate_ids or missing_sentences or wrong_commits:
        audit.conflict(
            "LEDGER-STATUS", "article claims",
            {"statuses": sorted(ALLOWED_CLAIM_STATUSES), "unique_ids": True, "sentences_in_manuscript": True, "protocol_commit": EXPECTED_PROTOCOL_COMMIT},
            {"disallowed_statuses": disallowed, "duplicate_ids": duplicate_ids, "missing_sentences": missing_sentences, "wrong_commits": wrong_commits},
            [relative(path), relative(FINAL / "main.tex")],
            "A ledger status, identifier, exact manuscript sentence, or protocol commit is inconsistent."
        )
    elif not rows:
        audit.machine(
            "LEDGER-STATUS", "article claims", "nonempty ledger", "zero rows",
            [relative(path)], "The final claim ledger is empty."
        )
    else:
        audit.pass_check(
            "LEDGER-STATUS", "article claims", sorted(ALLOWED_CLAIM_STATUSES),
            {"rows": len(rows), "statuses": sorted({row["status"] for row in rows})},
            [relative(path)], "Every final claim-ledger row has an allowed evidentiary status."
        )

    scope_path = FINAL / "source_data/claim_scope_audit.json"
    scope_failures: list[str] = []
    try:
        scope = load_json_strict(scope_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        scope = None
        scope_failures.append(f"claim-scope audit is not strict JSON: {exc}")
    if not isinstance(scope, dict):
        scope_failures.append("claim-scope audit root is not an object")
    else:
        ledger_ids = {row.get("claim_id", "") for row in rows}
        ledger_by_id = {row.get("claim_id", ""): row for row in rows}
        records = scope.get("records")
        counts = scope.get("counts")
        if scope.get("status") != "PASS":
            scope_failures.append("claim-scope status is not PASS")
        if scope.get("manuscript_sha256") != sha256(FINAL / "main.tex"):
            scope_failures.append("claim-scope manuscript hash is stale")
        if scope.get("builder_sha256") != sha256(FINAL / "scripts/build_claim_ledger.py"):
            scope_failures.append("claim-scope builder hash is stale")
        if scope.get("ledger_sha256") != sha256(path):
            scope_failures.append("claim-scope ledger hash is stale")
        if scope.get("all_in_scope_bound") is not True:
            scope_failures.append("all_in_scope_bound is not true")
        if scope.get("all_outside_scope_explained") is not True:
            scope_failures.append("all_outside_scope_explained is not true")
        if not isinstance(records, list) or not records:
            scope_failures.append("claim-scope records are missing or empty")
            records = []
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                scope_failures.append(f"scope record {index} is not an object")
                continue
            if record.get("scope") == "IN_SCOPE":
                claim_id = record.get("claim_id")
                if claim_id not in ledger_ids:
                    scope_failures.append(f"scope record {index} has no bound ledger claim")
                elif normalize_space(str(record.get("exact_sentence", ""))) != normalize_space(
                    ledger_by_id[str(claim_id)].get("exact_sentence", "")
                ):
                    scope_failures.append(f"scope record {index} sentence differs from its ledger row")
                claim_types = record.get("matched_claim_types")
                if not isinstance(claim_types, list) or not claim_types:
                    scope_failures.append(f"scope record {index} has no claim classification")
            elif record.get("scope") == "OUTSIDE_SCOPE":
                if not record.get("outside_scope_reason"):
                    scope_failures.append(f"scope record {index} has no outside-scope reason")
            else:
                scope_failures.append(f"scope record {index} has invalid scope")
        if not isinstance(counts, dict):
            scope_failures.append("claim-scope counts are missing")
        else:
            if counts.get("unique_ledger_rows") != len(rows):
                scope_failures.append("dynamic claim count differs from the ledger")
            if counts.get("prose_sentence_occurrences") != len(records):
                scope_failures.append("prose-sentence occurrence count differs from records")
            if counts.get("human_verified_yes") != 0:
                scope_failures.append("claim-scope audit prematurely reports human verification")
    prematurely_signed = [
        row.get("claim_id", "")
        for row in rows
        if not row.get("human_verified", "").strip().upper().startswith("NO")
    ]
    if prematurely_signed:
        scope_failures.append("ledger contains non-NO human verification: " + ", ".join(prematurely_signed))
    if scope_failures:
        audit.conflict(
            "LEDGER-SCOPE-COVERAGE", "article claims",
            {
                "every_in_scope_prose_sentence_bound": True,
                "every_exclusion_explained": True,
                "claim_count_dynamic": True,
                "human_verified_yes": 0,
            },
            {"failures": scope_failures},
            [relative(path), relative(scope_path), relative(FINAL / "main.tex")],
            "The generated ledger does not exhaustively and currently bind the manuscript prose scope.",
        )
    else:
        audit.pass_check(
            "LEDGER-SCOPE-COVERAGE", "article claims",
            "all narrative and caption sentences classified and bound",
            {
                "rows": len(rows),
                "prose_sentence_occurrences": len(scope["records"]),
                "human_verified_yes": 0,
            },
            [relative(path), relative(scope_path), relative(FINAL / "main.tex")],
            "The fail-closed scope pass binds every narrative and caption sentence; structured exclusions are enumerated.",
        )
    unsigned = [
        row.get("claim_id", "")
        for row in rows
        if not re.match(r"(?i)^(?:yes|verified|approved)\b", row.get("human_verified", "").strip())
    ]
    if unsigned:
        audit.human(
            "HUMAN-CLAIM-LEDGER-SIGNOFF", "human claim verification",
            [relative(path)],
            f"The corresponding author must verify all {len(unsigned)} claim-ledger rows; no machine status substitutes for that sign-off.",
        )


def check_reproduction_binding(audit: Audit) -> None:
    report_path = FINAL / "REPRODUCTION_REPORT.json"
    sidecar_path = FINAL / "REPRODUCTION_REPORT.sha256"
    verifier_path = FINAL / "scripts/verify_reproduction_report.py"
    if not report_path.is_file() or not sidecar_path.is_file() or not verifier_path.is_file():
        return
    failures: list[str] = []
    try:
        report = load_json_strict(report_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report = None
        failures.append(f"report is not strict JSON: {exc}")
    try:
        sidecar = sidecar_path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        sidecar = ""
        failures.append(f"sidecar is unreadable: {exc}")
    match = re.fullmatch(r"([0-9a-f]{64})  REPRODUCTION_REPORT\.json\n", sidecar)
    if not match:
        failures.append("sidecar format or filename is invalid")
    elif match.group(1) != sha256(report_path):
        failures.append("sidecar hash does not match the report bytes")
    if not isinstance(report, dict):
        failures.append("report root is not an object")
    else:
        if report.get("schema_version") != 2 or report.get("status") != "PASS":
            failures.append("report is not a schema-v2 PASS")
        if report.get("readiness_decision") != "NOT_READY_DO_NOT_SUBMIT":
            failures.append("report does not preserve NOT_READY_DO_NOT_SUBMIT")
        if report.get("submission_ready") is not False:
            failures.append("report does not explicitly preserve submission_ready=false")
        gate = report.get("rights_and_human_gate")
        if not isinstance(gate, dict) or gate.get("rights_and_license_resolved") is not False:
            failures.append("report does not preserve the unresolved-rights gate")
        if not isinstance(gate, dict) or gate.get("human_signoffs_complete") is not False:
            failures.append("report does not preserve the incomplete-human-signoff gate")
    if failures:
        audit.machine(
            "REPRODUCTION-REPORT-BINDING", "reproduction provenance",
            "strict schema-v2 PASS report, exact lowercase SHA-256 sidecar, and fail-closed readiness gate",
            failures,
            [relative(report_path), relative(sidecar_path), relative(verifier_path)],
            "The reproduction report cannot be accepted until its report/sidecar binding and fail-closed gate are current.",
        )
    else:
        audit.pass_check(
            "REPRODUCTION-REPORT-BINDING", "reproduction provenance",
            "exact sidecar and NOT_READY gate",
            {"sidecar_matches_report": True, "readiness_decision": "NOT_READY_DO_NOT_SUBMIT"},
            [relative(report_path), relative(sidecar_path), relative(verifier_path)],
            "The provisional or final schema-v2 technical PASS is byte-bound and remains non-submittable.",
        )


def check_human_and_legal_blockers(audit: Audit) -> None:
    main = FINAL / "main.tex"
    cover = FINAL / "cover_letter.md"
    contributions = FINAL / "author_contributions.md"
    conflicts = FINAL / "conflict_of_interest.md"
    checklist = FINAL / "SUBMISSION_CHECKLIST.md"
    equation = FINAL / "EQUATION_AUDIT.md"
    methods = FINAL / "METHOD_ASSUMPTION_AUDIT.md"
    defense = FINAL / "AUTHOR_DEFENSE_GUIDE.md"
    availability = FINAL / "data_availability.md"
    ai = FINAL / "ai_disclosure.md"
    release_status = FINAL / "release/RELEASE_STATUS.json"

    signoff_expected = {
        "defense_questions": 29,
        "method_entries": 17,
        "equation_entries": 4,
    }
    signoff_observed = {
        "defense_questions": count_markdown_headings(defense, r"^##\s+\d+\.\s+"),
        "method_entries": count_markdown_headings(methods, r"^##\s+M\d+\s+—\s+"),
        "equation_entries": count_markdown_headings(equation, r"^##\s+EQ\d+\s+—\s+"),
    }
    signoff_evidence = [relative(defense), relative(methods), relative(equation)]
    if signoff_observed != signoff_expected:
        audit.conflict(
            "HUMAN-SIGNOFF-INVENTORY",
            "human comprehension",
            signoff_expected,
            signoff_observed,
            signoff_evidence,
            "The method, equation, or author-defense signoff inventory has drifted.",
        )
    else:
        audit.pass_check(
            "HUMAN-SIGNOFF-INVENTORY",
            "human comprehension",
            signoff_expected,
            signoff_observed,
            signoff_evidence,
            "All signoff inventories have the mandated current counts.",
        )

    author_hits = line_locations(main, r"\\author\{\[|author name requires human") + line_locations(cover, r"Corresponding author name|names.*require human")
    if author_hits:
        audit.human("HUMAN-AUTHORS", "human metadata", author_hits, "Supply and approve every author name, order, and eligibility.")
    affiliation_hits = line_locations(main, r"\\affiliation\{\[|affiliation.*requires human") + line_locations(cover, r"Affiliation and complete postal address")
    if affiliation_hits:
        audit.human("HUMAN-AFFILIATIONS", "human metadata", affiliation_hits, "Supply and approve affiliations and complete postal addresses.")
    email_hits = line_locations(main, r"\\email\{\[|email requires human") + line_locations(cover, r"\*\*\[Email\]\*\*")
    if email_hits:
        audit.human("HUMAN-CORRESPONDENCE", "human metadata", email_hits, "Supply and verify the corresponding-author name and email.")
    orcid_hits = line_locations(cover, r"ORCID") + line_locations(checklist, r"ORCID")
    if orcid_hits:
        audit.human("HUMAN-ORCID", "human metadata", orcid_hits, "Supply ORCIDs or an explicit permitted none/decline decision.")
    credit_hits = line_locations(contributions, r"human-supplied|human confirmation|required") + line_locations(main, r"CRediT roles.*require human")
    if credit_hits:
        audit.human("HUMAN-CREDIT", "human metadata", credit_hits, "Confirm CRediT roles for every eligible author.")
    funding_hits = line_locations(contributions, r"Funding acquisition.*required|confirmed .none") + line_locations(checklist, r"Funding sources")
    if funding_hits:
        audit.human("HUMAN-FUNDING", "human metadata", funding_hits, "Confirm funding and grant identifiers or approve a no-funding statement.")
    conflict_hits = line_locations(conflicts, r"Submission blocker|Neither form is currently established") + line_locations(main, r"No reliable competing-interest statement")
    if conflict_hits:
        audit.human("HUMAN-CONFLICTS", "human metadata", conflict_hits, "Collect and approve every author's financial and nonfinancial disclosure.")
    acknowledgement_hits = line_locations(checklist, r"Acknowledgments") + line_locations(main, r"acknowledgments.*require human")
    if acknowledgement_hits:
        audit.human("HUMAN-ACKNOWLEDGMENTS", "human metadata", acknowledgement_hits, "Approve acknowledgments and naming permissions or confirm none.")

    audit.human(
        "HUMAN-AUTHOR-APPROVAL", "human approval",
        line_locations(checklist, r"Author approval|responsibility for the final content|originality"),
        "Every author must approve the final manuscript, disclosures, package, authorship, and overlap statements."
    )
    audit.human(
        "HUMAN-METHOD-EQUATION-SIGNOFF", "human comprehension",
        line_locations(equation, r"human_verified.*PENDING") + line_locations(methods, r"human verification.*PENDING|human_verified.*PENDING"),
        f"A human author must verify all {signoff_observed['method_entries']} method entries and all {signoff_observed['equation_entries']} equation entries, including assumptions, signs, units, and interpretations."
    )
    audit.human(
        "HUMAN-DEFENSE-COMPREHENSION", "human comprehension",
        line_locations(defense, r"human_verified.*PENDING|sign-off"),
        f"The corresponding author must demonstrate comprehension of and sign off all {signoff_observed['defense_questions']} defense-guide questions."
    )
    audit.human(
        "HUMAN-AI-COMPLETENESS", "AI disclosure",
        line_locations(ai, r"must still confirm|submission blocker") + line_locations(checklist, r"complete history of substantive AI"),
        "The human author must confirm the complete AI-use history and applicable privacy, access, IP, and tool-term compliance."
    )

    rights_evidence = line_locations(availability, r"ownership|redistribution authority|license|rights are not established") + line_locations(checklist, r"Ownership:|Redistribution authority:|License:")
    audit.human(
        "LEGAL-OWNERSHIP-REDISTRIBUTION", "rights and license", rights_evidence,
        "Identify rights holders and document redistribution authority for every proposed release component."
    )
    audit.human(
        "LEGAL-LICENSE", "rights and license",
        line_locations(availability, r"no-license|license") + line_locations(release_status, r"NO_LICENSE"),
        "Rights holders must approve a specific license and its scope before public distribution."
    )
    audit.human(
        "LEGAL-ARCHIVE-DOI", "archive and DOI",
        line_locations(availability, r"archive|DOI") + line_locations(checklist, r"Archive:|DOI:"),
        "Approve archive creators/version/maintainer/location and add a DOI only after a persistent record actually exists."
    )
    audit.human(
        "LEGAL-RESTRICTED-LIST-NAMING", "restricted materials",
        line_locations(checklist, r"Restricted-list approval|Naming permissions"),
        "Confirm the exclusion list and permissions to identify organizations, packages, opponents, or people."
    )


def build_report() -> dict[str, Any]:
    audit = Audit()
    check_required_files(audit)
    payloads = require_json_inputs(audit)
    macro_path = FINAL / "results_macros.tex"
    macros = macro_map(macro_path.read_text(encoding="utf-8")) if macro_path.is_file() else {}

    check_identity(audit, payloads, macros)
    check_protocol_reporting_provenance(audit)
    truth = expected_truth(payloads)
    if truth is None:
        audit.machine(
            "TRUTH-CONSTRUCTION", "authoritative evidence", "complete authoritative truth record",
            sorted(payloads), [relative(path) for path in REQUIRED_JSON.values()],
            "Central numerical truth could not be constructed; numerical checks were not guessed."
        )
    else:
        check_authoritative_numbers(audit, payloads, truth, macros)
        check_textual_numbers(audit, truth, macros)
        check_seeds(audit, payloads, truth)
        check_hashes(audit, payloads, truth)
    check_release_and_disclosures(audit)
    check_figures_tables(audit, payloads)
    check_claim_ledger(audit)
    check_reproduction_binding(audit)
    check_human_and_legal_blockers(audit)

    corpus = [
        FINAL / name for name in REQUIRED_BASE_FILES if (FINAL / name).is_file()
    ]
    corpus.extend(sorted((PAPER / "protocol").glob("*.md")))
    corpus.extend(text_files_under(FINAL / "supplement"))
    corpus.extend(text_files_under(FINAL / "release"))
    files_scanned = sorted({relative(path) for path in corpus if path.is_file()})

    factual_status = "FAIL" if audit.contradictions else "PASS"
    machine_status = "FAIL" if audit.machine_blockers else "PASS"
    if audit.contradictions or audit.machine_blockers:
        overall = "FAIL"
    elif audit.human_or_legal_blockers:
        overall = "PASS_WITH_HUMAN_OR_LEGAL_BLOCKERS"
    else:
        overall = "PASS"
    return {
        "schema_version": "final-protocol-contradiction-audit-v1",
        "scope": {
            "title": EXPECTED_TITLE,
            "article_type": EXPECTED_ARTICLE_TYPE,
            "branch": EXPECTED_BRANCH,
            "protocol_commit": EXPECTED_PROTOCOL_COMMIT,
            "source_of_truth": "checked processed evidence and independent statistics verification; prose is never authoritative",
            "files_scanned": files_scanned,
        },
        "checks": audit.checks,
        "contradictions": audit.contradictions,
        "machine_verification_blockers": audit.machine_blockers,
        "human_or_legal_blockers": audit.human_or_legal_blockers,
        "summary": {
            "checks_total": len(audit.checks),
            "checks_passed": sum(item["status"] == "PASS" for item in audit.checks),
            "contradictions": len(audit.contradictions),
            "machine_verification_blockers": len(audit.machine_blockers),
            "human_or_legal_blockers": len(audit.human_or_legal_blockers),
            "factual_consistency_status": factual_status,
            "machine_verification_status": machine_status,
            "submission_ready": not (
                audit.contradictions or audit.machine_blockers or audit.human_or_legal_blockers
            ),
        },
        "overall_status": overall,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-write", action="store_true", help="Evaluate without writing the JSON report.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = build_report()
    if not args.no_write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    if not args.quiet:
        print(
            "contradiction audit: "
            f"{report['overall_status']} "
            f"({report['summary']['contradictions']} contradictions, "
            f"{report['summary']['machine_verification_blockers']} machine blockers, "
            f"{report['summary']['human_or_legal_blockers']} human/legal blockers)"
        )
    return 1 if report["contradictions"] or report["machine_verification_blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
