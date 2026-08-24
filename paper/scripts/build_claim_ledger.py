#!/usr/bin/env python3
"""Generate the numerical-claim ledger from verified artifacts and audits."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
FIELDS = [
    "claim_id", "manuscript_section", "proposed_claim", "status", "raw_source",
    "json_or_line_locator", "branch", "commit", "artifact_sha256",
    "calculation_script", "verified_value", "unit", "sample_size",
    "statistical_method", "limitations", "include_or_omit",
]
VALID_STATUSES = {
    "VERIFIED", "VERIFIED_WITH_CAVEAT", "CONFLICT", "UNSUPPORTED", "REQUIRES_RERUN",
}
INCLUDABLE_STATUSES = {"VERIFIED", "VERIFIED_WITH_CAVEAT"}
SHA256_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
GIT_SOURCE_RE = re.compile(r"git:([0-9a-f]{40}):(.+)\Z")
HISTORICAL_SOURCE_COMMITS = {
    "training/evaluate_deterministic_crn.py":
        "c17434252deb8fdc3b42b2c12a58f18ca646215e",
}
HELDOUT_RAW_SUMMARY = "artifacts/paper_heldout/heldout_0813_exp23_vs_c0.json"
HELDOUT_RAW_ROWS = "artifacts/paper_heldout/heldout_0813_exp23_vs_c0.rows.jsonl.gz"
PEVL_PROTOCOL_COMMIT = "803257f102232763fc88d28c14b668f9b62eb277"
PEVL_SYNTHETIC = "paper/synthetic/results/pevl_results.json"
PEVL_SYNTHETIC_MATRIX = "paper/synthetic/results/pevl_matrix.csv"
PEVL_SEED_AUDIT = "paper/data/seed_namespace_audit.json"
PEVL_HISTORICAL = "paper/data/ablation/summary.json"
PEVL_PREFLIGHT = "paper/data/pevl/trace_preflight_summary.json"
PEVL_STRESS = "paper/data/pevl/timed_search_stress_summary.json"
PEVL_FACTORIAL = "paper/data/pevl/factorial_summary.json"
PEVL_FACTORIAL_UNITS = "paper/data/pevl/factorial/units.csv"
PEVL_COMBINED = "paper/data/pevl/summary.json"
PEVL_PROTOCOL = "paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md"
PEVL_ANALYZER = "paper/scripts/analyze_pevl.py"
PEVL_STATIC_COMMIT_BRANCH = "paper/aps-open-science-202608"
PEVL_MODES = {
    "clean_deterministic": ([], "admit"),
    "stateful_draw_shift": ([7], "downgrade"),
    "wall_clock_search": ([4, 5, 6], "suppress"),
    "process_global_state": ([4, 5, 6], "suppress"),
    "uint32_seed_conversion": ([2], "suppress"),
}
PEVL_LEVEL_NAMES = (
    "artifact_identity",
    "seed_namespace_integrity",
    "schedule_parity",
    "identical_arm_record_parity",
    "repeat_and_worker_parity",
    "stochastic_source_audit",
    "cross_arm_event_alignment",
    "statistical_admission",
)


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with (ROOT / path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checked_source_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts or not path:
        raise ValueError(f"source must be a nonempty repository-relative path: {path!r}")
    resolved = (ROOT / candidate).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"source resolves outside the repository: {path!r}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"claim source is not a file: {path}")
    return resolved


def checked_repository_relative_path(path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts or not path:
        raise ValueError(
            f"source must be a nonempty repository-relative path: {path!r}"
        )
    return candidate.as_posix()


def source_sha256(source: str) -> str:
    """Hash a current file or an explicit immutable Git blob source."""

    match = GIT_SOURCE_RE.fullmatch(source)
    if match is None:
        checked_source_path(source)
        return sha256_file(source)
    commit, path = match.groups()
    checked_repository_relative_path(path)
    process = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.returncode != 0:
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"cannot read immutable Git source {source}: {detail}")
    return hashlib.sha256(process.stdout).hexdigest()


def artifact_bundle(paths: list[str] | tuple[str, ...]) -> tuple[str, str]:
    """Return aligned, semicolon-delimited sources and verified byte hashes."""
    if not paths or len(paths) != len(set(paths)):
        raise ValueError(f"artifact path bundle must be nonempty and unique: {paths!r}")
    hashes = []
    for path in paths:
        hashes.append(source_sha256(path))
    return "; ".join(paths), "; ".join(hashes)


def artifact_bundle_from_inventory(
    items: list[dict],
    *,
    git_fallback_by_path: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Validate an inventory against current bytes or named historical blobs."""

    fallback = git_fallback_by_path or {}
    sources: list[str] = []
    hashes: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"source inventory item {index} is not an object")
        path = item.get("path")
        expected = item.get("sha256")
        if not isinstance(path, str) or not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
            raise ValueError(f"invalid source inventory item {index}: {item!r}")
        checked_source_path(path)
        actual = sha256_file(path)
        if actual != expected:
            commit = fallback.get(path)
            if commit is None or not COMMIT_RE.fullmatch(commit):
                raise ValueError(
                    f"source hash mismatch for {path}: {actual} != {expected}"
                )
            source = f"git:{commit}:{path}"
            historical = source_sha256(source)
            if historical != expected:
                raise ValueError(
                    f"historical source hash mismatch for {source}: "
                    f"{historical} != {expected}"
                )
        else:
            source = path
        sources.append(source)
        hashes.append(expected)
    if len(sources) != len(set(sources)):
        raise ValueError("source inventory contains duplicate sources")
    return "; ".join(sources), "; ".join(hashes)


def verified_inventory_paths(
    items: Sequence[Mapping[str, Any]],
    *,
    path_field: str = "path",
    hash_field: str = "sha256",
    git_fallback_by_path: Mapping[str, str] | None = None,
) -> list[str]:
    """Return source references after checking every current or Git byte hash."""

    fallback = git_fallback_by_path or {}
    sources: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise ValueError(f"source inventory item {index} is not an object")
        path = item.get(path_field)
        expected = item.get(hash_field)
        if (
            not isinstance(path, str)
            or not isinstance(expected, str)
            or not SHA256_RE.fullmatch(expected)
        ):
            raise ValueError(f"invalid source inventory item {index}: {item!r}")
        checked_source_path(path)
        actual = sha256_file(path)
        if actual != expected:
            commit = fallback.get(path)
            if commit is None or not COMMIT_RE.fullmatch(commit):
                raise ValueError(
                    f"source hash mismatch for {path}: {actual} != {expected}"
                )
            source = f"git:{commit}:{path}"
            historical = source_sha256(source)
            if historical != expected:
                raise ValueError(
                    f"historical source hash mismatch for {source}: "
                    f"{historical} != {expected}"
                )
        else:
            source = path
        sources.append(source)
    if len(sources) != len(set(sources)):
        raise ValueError("source inventory contains duplicate sources")
    return sources


def claim_row(
    claim_id: str,
    section: str,
    claim: str,
    status: str,
    source: str,
    locator: str,
    branch: str,
    commit: str,
    artifact_hash: str,
    script: str,
    value: str,
    unit: str,
    sample_size: str,
    method: str,
    limitations: str,
    disposition: str,
) -> dict[str, str]:
    return dict(
        zip(
            FIELDS,
            [
                claim_id,
                section,
                claim,
                status,
                source,
                locator,
                branch,
                commit,
                artifact_hash,
                script,
                value,
                unit,
                sample_size,
                method,
                limitations,
                disposition,
            ],
            strict=True,
        )
    )


def require_full_commit(value: Any, label: str) -> str:
    if not isinstance(value, str) or not COMMIT_RE.fullmatch(value):
        raise ValueError(f"{label} must be a full lowercase Git commit")
    return value


def load_pevl_json(path: str) -> dict[str, Any]:
    checked_source_path(path)
    try:
        payload = json.loads((ROOT / path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid PEVL JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"PEVL input must be a JSON object: {path}")
    return payload


def bundle_pevl_sources(
    fixed_paths: Sequence[str], inventory_paths: Sequence[str] = ()
) -> tuple[str, str]:
    paths = [*fixed_paths, *inventory_paths]
    return artifact_bundle(paths)


def retained_corpus_facts(path: str) -> dict[str, int]:
    """Verify the selection/storage facts claimed for the retained feature corpus."""
    checked_source_path(path)
    facts = {"rows": 0, "reward_one": 0, "daily_top_episode": 0, "null_observation": 0}
    with gzip.open(ROOT / path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid corpus JSON at line {line_number}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"corpus row {line_number} is not an object")
            facts["rows"] += 1
            facts["reward_one"] += int(row.get("reward") == 1.0)
            facts["daily_top_episode"] += int(row.get("source") == "daily_top_episode")
            facts["null_observation"] += int(row.get("observation") is None)
    if any(facts[key] != facts["rows"] for key in facts if key != "rows"):
        raise ValueError(f"retained-corpus selection/storage facts failed: {facts}")
    return facts


def validate_synthetic_pevl(payload: Mapping[str, Any]) -> dict[str, Any]:
    if (
        payload.get("schema_version") != "1.1.0"
        or payload.get("framework") != "Paired Evaluation Validity Ladder"
        or payload.get("testbed") != "pevl_synthetic_coupling_validation"
    ):
        raise ValueError("synthetic PEVL header is not the published schema")
    levels = payload.get("levels")
    if not isinstance(levels, list) or len(levels) != 8:
        raise ValueError("synthetic PEVL must contain exactly eight levels")
    for expected_level, (row, expected_name) in enumerate(
        zip(levels, PEVL_LEVEL_NAMES, strict=True), start=1
    ):
        if not isinstance(row, dict):
            raise ValueError("synthetic PEVL level is not an object")
        expected_kind = "admission_decision" if expected_level == 8 else "evidence_gate"
        if (
            row.get("level") != expected_level
            or row.get("level_name") != expected_name
            or row.get("kind") != expected_kind
        ):
            raise ValueError(f"synthetic PEVL Level {expected_level} definition drift")
    modes = payload.get("modes")
    if not isinstance(modes, list) or len(modes) != len(PEVL_MODES):
        raise ValueError("synthetic PEVL mode inventory is incomplete")
    by_mode: dict[str, Mapping[str, Any]] = {}
    expected_matrix: dict[tuple[str, int], tuple[str, str, str]] = {}
    for mode in modes:
        if not isinstance(mode, dict) or not isinstance(mode.get("mode"), str):
            raise ValueError("synthetic PEVL mode is malformed")
        name = mode["mode"]
        if name in by_mode or name not in PEVL_MODES:
            raise ValueError(f"unexpected or duplicate synthetic mode: {name!r}")
        expected_catches, expected_admission = PEVL_MODES[name]
        if mode.get("caught_by_levels") != expected_catches:
            raise ValueError(f"synthetic catch set drift for {name}")
        expected_first = expected_catches[0] if expected_catches else None
        if mode.get("first_catching_level") != expected_first:
            raise ValueError(f"synthetic first-catch level drift for {name}")
        audit = mode.get("audit")
        if not isinstance(audit, list) or len(audit) != 8:
            raise ValueError(f"synthetic audit inventory is incomplete for {name}")
        observed_catches = []
        for expected_level, row in enumerate(audit, start=1):
            if not isinstance(row, dict):
                raise ValueError(f"synthetic audit row is malformed for {name}")
            digest = row.get("evidence_sha256")
            if (
                row.get("level") != expected_level
                or row.get("level_name") != PEVL_LEVEL_NAMES[expected_level - 1]
                or not isinstance(digest, str)
                or not SHA256_RE.fullmatch(digest)
            ):
                raise ValueError(f"synthetic audit Level {expected_level} drift for {name}")
            expected_matrix[(name, expected_level)] = (
                str(row.get("status")),
                str(row.get("catches_failure")).lower(),
                digest,
            )
            if row.get("catches_failure") is True:
                observed_catches.append(expected_level)
            elif row.get("catches_failure") is not False:
                raise ValueError(
                    f"synthetic catch flag is not boolean for {name}/L{expected_level}"
                )
        if observed_catches != expected_catches:
            raise ValueError(f"synthetic audit rows do not reproduce catches for {name}")
        if audit[7].get("status") != expected_admission:
            raise ValueError(f"synthetic admission drift for {name}")
        by_mode[name] = mode
    if set(by_mode) != set(PEVL_MODES):
        raise ValueError("synthetic PEVL mode set is incomplete")

    with checked_source_path(PEVL_SYNTHETIC_MATRIX).open(
        encoding="utf-8", newline=""
    ) as handle:
        reader = csv.DictReader(handle)
        matrix_rows = list(reader)
    if len(matrix_rows) != 40:
        raise ValueError("synthetic PEVL matrix must contain 40 rows")
    observed_matrix: dict[tuple[str, int], tuple[str, str, str]] = {}
    for row in matrix_rows:
        try:
            key = (row["mode"], int(row["level"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("synthetic PEVL matrix row is malformed") from exc
        if key in observed_matrix:
            raise ValueError(f"duplicate synthetic PEVL matrix row: {key}")
        observed_matrix[key] = (
            row.get("status", ""),
            row.get("catches_failure", ""),
            row.get("evidence_sha256", ""),
        )
    if observed_matrix != expected_matrix:
        raise ValueError("synthetic PEVL JSON and CSV matrix disagree")

    draw_shift = by_mode["stateful_draw_shift"]
    level_7 = draw_shift["audit"][6].get("evidence")
    remedy = draw_shift.get("evidence", {}).get("event_keyed_remediation")
    if not isinstance(level_7, dict) or not isinstance(remedy, dict):
        raise ValueError("synthetic draw-shift evidence or remedy is missing")
    if (
        level_7.get("shared_event_count") != 5
        or level_7.get("mismatched_count") != 4
        or remedy.get("aligned_common_events") is not True
        or remedy.get("level_7_status_after_remediation") != "pass"
        or remedy.get("method") != "sha256(seed_uint32, semantic_event_key)"
        or remedy.get("mismatched_common_event_keys") != []
        or len(remedy.get("covered_event_keys", [])) != 5
        or remedy.get("remediated_control_event_values_sha256")
        != remedy.get("remediated_treatment_event_values_sha256")
    ):
        raise ValueError("synthetic event-keyed remediation evidence drift")
    return {"by_mode": by_mode, "shared_events": 5, "raw_mismatches": 4}


def validate_seed_namespace_pevl(payload: Mapping[str, Any]) -> list[str]:
    if (
        payload.get("conversion_rule") != "scheduled_seed & 0xffffffff"
        or payload.get("uint32_max") != (1 << 32) - 1
        or payload.get("prospective_passed") is not True
        or payload.get("historical_prospective_engine_seed_overlap") != []
    ):
        raise ValueError("seed-namespace audit header or separation check drift")
    historical = payload.get("historical_fresh_confirmation")
    prospective = payload.get("prospective_all")
    if not isinstance(historical, dict) or not isinstance(prospective, dict):
        raise ValueError("seed-namespace audit summaries are missing")
    if (
        historical.get("scheduled_count") != 2_800
        or historical.get("scheduled_unique") != 2_800
        or historical.get("scheduled_outside_uint32") != 2_800
        or historical.get("conversion_changed") != 2_800
        or historical.get("engine_seed_unique") != 2_800
        or historical.get("collision_groups") != {}
        or historical.get("passed_no_collision") is not True
    ):
        raise ValueError("historical seed-namespace result drift")
    if (
        prospective.get("scheduled_count") != 2_450
        or prospective.get("scheduled_unique") != 2_450
        or prospective.get("scheduled_outside_uint32") != 0
        or prospective.get("conversion_changed") != 0
        or prospective.get("engine_seed_unique") != 2_450
        or prospective.get("collision_groups") != {}
        or prospective.get("passed_no_collision") is not True
    ):
        raise ValueError("prospective seed-namespace result drift")
    expected_schedules = {
        "trace_preflight": (5, 50),
        "timed_search_stress": (2, 100),
        "factorial": (5, 400),
    }
    by_schedule = payload.get("prospective_by_schedule")
    if not isinstance(by_schedule, dict) or set(by_schedule) != set(expected_schedules):
        raise ValueError("prospective seed schedule inventory drift")
    schedule_total = 0
    for schedule, (expected_groups, expected_count) in expected_schedules.items():
        rows = by_schedule[schedule]
        if not isinstance(rows, dict) or len(rows) != expected_groups:
            raise ValueError(f"seed schedule group inventory drift for {schedule}")
        for label, row in rows.items():
            if (
                not isinstance(row, dict)
                or row.get("scheduled_count") != expected_count
                or row.get("scheduled_unique") != expected_count
                or row.get("engine_seed_unique") != expected_count
                or row.get("conversion_changed") != 0
                or row.get("collision_groups") != {}
                or row.get("passed_no_collision") is not True
            ):
                raise ValueError(f"seed schedule result drift for {schedule}/{label}")
            schedule_total += expected_count
    if schedule_total != prospective["scheduled_count"]:
        raise ValueError("prospective seed schedules do not reproduce the total")
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("seed-namespace provenance is missing")
    if (
        require_full_commit(provenance.get("git_commit"), "seed audit commit")
        != PEVL_PROTOCOL_COMMIT
        or provenance.get("script") != "paper/scripts/audit_seed_namespace.py"
        or provenance.get("script_sha256")
        != sha256_file("paper/scripts/audit_seed_namespace.py")
    ):
        raise ValueError("seed-namespace provenance drift")
    sources = payload.get("sources")
    if not isinstance(sources, list) or len(sources) != 7:
        raise ValueError("seed-namespace raw source inventory is incomplete")
    return verified_inventory_paths(sources)


def validate_historical_pevl(payload: Mapping[str, Any]) -> tuple[list[str], str]:
    if payload.get("schema_version") != 2 or payload.get("status") != "INVALIDATED":
        raise ValueError("historical parity analysis must remain invalidated schema 2")
    planned = payload.get("planned_analysis")
    audit = payload.get("control_parity_audit")
    if not isinstance(planned, dict) or not isinstance(audit, dict):
        raise ValueError("historical parity analysis fields are missing")
    if (
        planned.get("status") != "NOT_ESTIMABLE_UNDER_FROZEN_VALIDATION"
        or planned.get("pairs") != 2_800
        or audit.get("pairs") != 2_800
        or audit.get("outcome_record_mismatch_units") != 210
        or audit.get("serialized_record_mismatch_units") != 458
        or audit.get("trace_capture") is not False
    ):
        raise ValueError("historical parity failure totals drift")
    by_opponent = audit.get("by_opponent")
    if not isinstance(by_opponent, dict) or len(by_opponent) != 7:
        raise ValueError("historical parity opponent inventory is incomplete")
    if (
        sum(row.get("pairs", 0) for row in by_opponent.values()) != 2_800
        or sum(
            row.get("any_outcome_record_mismatch_units", 0)
            for row in by_opponent.values()
        )
        != 210
        or sum(
            row.get("any_serialized_record_mismatch_units", 0)
            for row in by_opponent.values()
        )
        != 458
        or by_opponent.get("starmie", {}).get(
            "any_outcome_record_mismatch_units"
        )
        != 191
        or by_opponent.get("starmie", {}).get(
            "any_serialized_record_mismatch_units"
        )
        != 377
        or by_opponent.get("dipplin", {}).get(
            "any_outcome_record_mismatch_units"
        )
        != 19
        or by_opponent.get("dipplin", {}).get(
            "any_serialized_record_mismatch_units"
        )
        != 81
    ):
        raise ValueError("historical opponent rows do not reproduce parity totals")
    cause = payload.get("cause_audit")
    if (
        not isinstance(cause, dict)
        or "time.monotonic" not in str(cause.get("starmie"))
        or "time.monotonic" not in str(cause.get("dipplin"))
    ):
        raise ValueError("historical stochastic-source audit is incomplete")
    if (
        payload.get("script") != "paper/scripts/analyze_ablation.py"
        or payload.get("script_sha256") != sha256_file("paper/scripts/analyze_ablation.py")
    ):
        raise ValueError("historical analyzer provenance drift")
    require_full_commit(payload.get("generated_at_commit"), "historical analysis commit")
    protocol_commits = payload.get("protocol_commits")
    if not isinstance(protocol_commits, dict):
        raise ValueError("historical protocol commits are missing")
    protocol_commit = require_full_commit(
        protocol_commits.get("contrast_clarification"),
        "historical contrast protocol commit",
    )
    sources = payload.get("sources")
    if not isinstance(sources, list) or len(sources) != 29:
        raise ValueError("historical source inventory is incomplete")
    return verified_inventory_paths(
        sources, git_fallback_by_path=HISTORICAL_SOURCE_COMMITS
    ), protocol_commit


def build_static_pevl_claim_rows() -> list[dict[str, str]]:
    synthetic = load_pevl_json(PEVL_SYNTHETIC)
    validate_synthetic_pevl(synthetic)
    synthetic_source, synthetic_hash = bundle_pevl_sources(
        [
            PEVL_SYNTHETIC,
            PEVL_SYNTHETIC_MATRIX,
            "paper/synthetic/results/pevl_results.schema.json",
            "paper/synthetic/pevl_synthetic.py",
            "paper/supplement/PEVL_FRAMEWORK.md",
        ]
    )
    seed = load_pevl_json(PEVL_SEED_AUDIT)
    seed_inventory = validate_seed_namespace_pevl(seed)
    seed_source, seed_hash = bundle_pevl_sources(
        [PEVL_SEED_AUDIT, "paper/scripts/audit_seed_namespace.py"],
        seed_inventory,
    )
    historical = load_pevl_json(PEVL_HISTORICAL)
    historical_inventory, historical_commit = validate_historical_pevl(historical)
    historical_source, historical_hash = bundle_pevl_sources(
        [PEVL_HISTORICAL, "paper/scripts/analyze_ablation.py"],
        historical_inventory,
    )
    return [
        claim_row(
            "PEVL-SYNTH",
            "PEVL open validation",
            "Five deterministic synthetic modes exercise distinct PEVL failure gates, and event-keyed hashing repairs the shared-event draw shift.",
            "VERIFIED",
            synthetic_source,
            "$.modes[*].caught_by_levels, $.modes[stateful_draw_shift].evidence.event_keyed_remediation, and CSV matrix",
            PEVL_STATIC_COMMIT_BRANCH,
            PEVL_PROTOCOL_COMMIT,
            synthetic_hash,
            "paper/synthetic/pevl_synthetic.py",
            "clean: no catch/admit; draw shift: L7/downgrade; wall-clock: L4-L6/suppress; process-global: L4-L6/suppress; uint32 conversion: L2/suppress; event-keyed remedy: 0/5 mismatched shared event keys after 4/5 mismatched under a stateful stream",
            "modes and shared semantic events",
            "5 modes; 5 shared event keys",
            "dependency-free deterministic fixtures with byte-stable JSON/CSV evidence",
            "These fixtures are constructive counterexamples, not an exhaustive failure taxonomy or empirical evidence about the restricted game engine. The event-keyed remedy requires white-box semantic event identifiers that the restricted engine does not expose.",
            "INCLUDE",
        ),
        claim_row(
            "PEVL-SEED",
            "PEVL seed-namespace audit",
            "Historical requested seeds were narrowed to uint32 without collision, and all frozen prospective schedules are collision-free in the engine namespace.",
            "VERIFIED",
            seed_source,
            "$.historical_fresh_confirmation, $.prospective_all, $.prospective_by_schedule, and $.provenance",
            PEVL_STATIC_COMMIT_BRANCH,
            PEVL_PROTOCOL_COMMIT,
            seed_hash,
            "paper/scripts/audit_seed_namespace.py",
            "historical: 2,800/2,800 requested seeds changed under uint32 narrowing, 2,800 unique consumed seeds, 0 collisions; prospective: 2,450/2,450 distinct scheduled and consumed seeds, 0 collisions; historical/prospective overlap 0",
            "scheduled and engine-consumed seeds",
            "2,800 historical plus 2,450 prospective schedule values",
            "exact schedule enumeration and unsigned-32-bit conversion audit",
            "Seed-namespace integrity establishes neither identical random draws nor repeat/worker reproducibility nor Level 7 cross-arm event alignment.",
            "INCLUDE",
        ),
        claim_row(
            "PEVL-HIST",
            "PEVL retrospective audit",
            "The historical seven-opponent four-cell study failed its identical-control available-record parity gate and its planned contrasts remain suppressed.",
            "VERIFIED",
            historical_source,
            "$.status, $.planned_analysis, $.control_parity_audit, and $.cause_audit",
            PEVL_STATIC_COMMIT_BRANCH,
            historical_commit,
            historical_hash,
            "paper/scripts/analyze_ablation.py",
            "210/2,800 outcome-record mismatch units and 458/2,800 serialized-record mismatch units; Starmie 191/377 and Dipplin 19/81",
            "scheduled seed-condition units",
            "2,800 units across 7 opponents and 14 strata",
            "exact repeated-control join on opponent, order, engine seed, and physical seat",
            "Trace capture was disabled. The result proves failure of available-record parity, not a unique causal contribution from wall time or process-local state; it cannot establish Level 7 and does not admit the planned mechanistic contrasts.",
            "INCLUDE",
        ),
    ]


def pevl_result_validators():
    """Import the shared terminal-result validators in package or script mode."""

    try:
        from paper.scripts import build_pevl_result_macros as validators
    except ModuleNotFoundError:
        import build_pevl_result_macros as validators  # type: ignore[no-redef]
    return validators


def validate_terminal_pevl(
    preflight: dict[str, Any],
    stress: dict[str, Any],
    factorial: dict[str, Any],
    combined: dict[str, Any],
) -> dict[str, Any]:
    validators = pevl_result_validators()
    validated_preflight = validators.validate_preflight(preflight)
    validated_stress = validators.validate_stress(stress)
    validated_factorial = validators.validate_factorial(
        factorial, validated_preflight["status"]
    )
    validators.validate_combined(combined, preflight, stress, factorial)
    historical = load_pevl_json(PEVL_HISTORICAL)
    validate_historical_pevl(historical)
    historical_audit = historical["control_parity_audit"]
    expected_historical = {
        "status": historical["status"],
        "units": historical_audit["pairs"],
        "outcome_record_mismatch_units": historical_audit[
            "outcome_record_mismatch_units"
        ],
        "outcome_record_mismatch_rate": historical_audit[
            "outcome_record_mismatch_units"
        ]
        / historical_audit["pairs"],
        "serialized_record_mismatch_units": historical_audit[
            "serialized_record_mismatch_units"
        ],
        "serialized_record_mismatch_rate": historical_audit[
            "serialized_record_mismatch_units"
        ]
        / historical_audit["pairs"],
        "by_opponent": historical_audit["by_opponent"],
        "cause_audit": historical["cause_audit"],
        "source": PEVL_HISTORICAL,
        "source_sha256": sha256_file(PEVL_HISTORICAL),
    }
    if combined.get("historical_control_parity") != expected_historical:
        raise ValueError(
            "combined PEVL historical control-parity record conflicts with "
            "the validated retrospective source"
        )
    commits = {
        validated_preflight["protocol_commit"],
        validated_stress["protocol_commit"],
    }
    if "protocol_commit" in validated_factorial:
        commits.add(validated_factorial["protocol_commit"])
    if commits != {PEVL_PROTOCOL_COMMIT}:
        raise ValueError(
            f"terminal PEVL analyses mix or misidentify protocol commits: {sorted(commits)}"
        )
    claim_boundary = combined.get("claim_boundary")
    if not isinstance(claim_boundary, str) or "Level 7" not in claim_boundary:
        raise ValueError("combined PEVL summary omits the Level 7 claim boundary")
    preflight_boundary = preflight.get("claim_boundary")
    if (
        not isinstance(preflight_boundary, str)
        or "cross-arm event alignment" not in preflight_boundary
    ):
        raise ValueError("trace preflight omits its cross-arm alignment boundary")
    if factorial.get("status") == "ADMITTED_SEED_MATCHED":
        levels = factorial.get("pevl_levels")
        if (
            not isinstance(levels, dict)
            or "not established" not in str(levels.get("level_7", "")).lower()
        ):
            raise ValueError("admitted factorial omits its Level 7 limitation")
    return {
        "preflight": validated_preflight,
        "stress": validated_stress,
        "factorial": validated_factorial,
    }


def terminal_pevl_source_paths(
    preflight: Mapping[str, Any],
    stress: Mapping[str, Any],
    factorial: Mapping[str, Any],
) -> dict[str, list[str]]:
    preflight_rows = preflight.get("rows")
    if not isinstance(preflight_rows, list):
        raise ValueError("terminal preflight rows are missing")
    preflight_inventory = [
        {
            "path": row.get("source") if isinstance(row, dict) else None,
            "sha256": row.get("source_sha256") if isinstance(row, dict) else None,
        }
        for row in preflight_rows
    ]
    stress_inventory = stress.get("sources")
    if not isinstance(stress_inventory, list):
        raise ValueError("terminal stress source inventory is missing")
    factorial_inventory = factorial.get("sources", [])
    if not isinstance(factorial_inventory, list):
        raise ValueError("terminal factorial source inventory is malformed")
    return {
        "preflight": verified_inventory_paths(preflight_inventory),
        "stress": verified_inventory_paths(stress_inventory),
        "factorial": verified_inventory_paths(factorial_inventory),
    }


def format_pevl_effect(name: str, row: Mapping[str, Any]) -> str:
    estimate = float(row["estimate"])
    low, high = (float(value) for value in row["bootstrap_95_ci"])
    return f"{name} {100 * estimate:+.2f} pp [{100 * low:+.2f}, {100 * high:+.2f}]"


def validate_factorial_units_csv(
    factorial: Mapping[str, Any], path: str = PEVL_FACTORIAL_UNITS
) -> None:
    expected_fields = [
        "opponent",
        "actual_order",
        "pair_index",
        "scheduled_seed",
        "engine_seed_uint32",
        "physical_seat",
        "c1_win",
        "c2_win",
        "c3_win",
        "c4_win",
        "c1_draw",
        "c2_draw",
        "c3_draw",
        "c4_draw",
        "c1_decisions",
        "c2_decisions",
        "c3_decisions",
        "c4_decisions",
    ]
    bases = {
        "b0": 2026082700,
        "d842": 2026083700,
        "master": 2026084700,
        "replay": 2026085700,
        "alakazam_no_search": 2026086700,
    }
    win_totals = {cell: 0 for cell in ("C1", "C2", "C3", "C4")}
    c4_only = c1_only = 0
    with checked_source_path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != expected_fields:
            raise ValueError("factorial unit table has an unexpected schema")
        identities = set()
        for row_number, row in enumerate(reader, start=2):
            try:
                opponent = row["opponent"]
                order = row["actual_order"]
                pair_index = int(row["pair_index"])
                scheduled_seed = int(row["scheduled_seed"])
                engine_seed = int(row["engine_seed_uint32"])
                seat = int(row["physical_seat"])
                outcomes = {
                    cell: (int(row[f"{cell}_win"]), int(row[f"{cell}_draw"]))
                    for cell in ("c1", "c2", "c3", "c4")
                }
                decisions = [
                    int(row[f"{cell}_decisions"])
                    for cell in ("c1", "c2", "c3", "c4")
                ]
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"malformed factorial unit CSV row {row_number}") from exc
            if (
                opponent
                not in {"b0", "d842", "master", "replay", "alakazam_no_search"}
                or order not in {"first", "second"}
                or not 0 <= pair_index < 200
                or scheduled_seed
                != bases[opponent]
                + (1_000_000 if order == "second" else 0)
                + pair_index
                or scheduled_seed != engine_seed
                or seat != pair_index % 2
                or any(
                    win not in {0, 1}
                    or draw not in {0, 1}
                    or win + draw > 1
                    for win, draw in outcomes.values()
                )
                or any(not 0 <= value <= 2_000 for value in decisions)
            ):
                raise ValueError(f"factorial unit CSV row {row_number} violates the protocol")
            identity = (opponent, order, pair_index)
            if identity in identities:
                raise ValueError(f"duplicate factorial unit CSV identity: {identity}")
            identities.add(identity)
            for cell, (win, _draw) in outcomes.items():
                win_totals[cell.upper()] += win
            c1_win = outcomes["c1"][0]
            c4_win = outcomes["c4"][0]
            c4_only += int(c4_win == 1 and c1_win == 0)
            c1_only += int(c1_win == 1 and c4_win == 0)
    expected_identities = {
        (opponent, order, pair_index)
        for opponent in ("b0", "d842", "master", "replay", "alakazam_no_search")
        for order in ("first", "second")
        for pair_index in range(200)
    }
    if identities != expected_identities:
        raise ValueError("factorial unit CSV does not contain the frozen 2,000 units")
    rates = factorial.get("cell_win_rates")
    mcnemar = factorial.get("primary_mcnemar")
    if not isinstance(rates, dict) or not isinstance(mcnemar, dict):
        raise ValueError("admitted factorial summary omits rates or McNemar counts")
    for cell, wins in win_totals.items():
        reported = rates.get(cell)
        if (
            isinstance(reported, bool)
            or not isinstance(reported, (int, float))
            or not math.isclose(
                float(reported), wins / 2_000, rel_tol=0.0, abs_tol=1e-12
            )
        ):
            raise ValueError(f"factorial unit CSV does not reproduce {cell} win rate")
    if (
        mcnemar.get("c4_only_wins") != c4_only
        or mcnemar.get("c1_only_wins") != c1_only
    ):
        raise ValueError("factorial unit CSV does not reproduce McNemar discordances")
    discordant = c4_only + c1_only
    if discordant:
        lower = min(c4_only, c1_only)
        exact_p = min(
            1.0,
            2.0
            * sum(math.comb(discordant, index) for index in range(lower + 1))
            / (2**discordant),
        )
    else:
        exact_p = 1.0
    reported_p = mcnemar.get("exact_two_sided_p")
    if (
        isinstance(reported_p, bool)
        or not isinstance(reported_p, (int, float))
        or not math.isclose(
            float(reported_p), exact_p, rel_tol=0.0, abs_tol=1e-15
        )
    ):
        raise ValueError("factorial unit CSV does not reproduce exact McNemar p-value")


def build_terminal_pevl_claim_rows() -> list[dict[str, str]]:
    preflight = load_pevl_json(PEVL_PREFLIGHT)
    stress = load_pevl_json(PEVL_STRESS)
    factorial = load_pevl_json(PEVL_FACTORIAL)
    combined = load_pevl_json(PEVL_COMBINED)
    validated = validate_terminal_pevl(preflight, stress, factorial, combined)
    inventory = terminal_pevl_source_paths(preflight, stress, factorial)
    fixed_common = [PEVL_COMBINED, PEVL_PROTOCOL, PEVL_ANALYZER]
    preflight_source, preflight_hash = bundle_pevl_sources(
        [PEVL_PREFLIGHT, *fixed_common], inventory["preflight"]
    )
    stress_source, stress_hash = bundle_pevl_sources(
        [PEVL_STRESS, *fixed_common], inventory["stress"]
    )
    factorial_status = validated["factorial"]["status"]
    units_path = ROOT / PEVL_FACTORIAL_UNITS
    if factorial_status == "ADMITTED_SEED_MATCHED":
        validate_factorial_units_csv(factorial)
        factorial_fixed = [PEVL_FACTORIAL, PEVL_FACTORIAL_UNITS, *fixed_common]
    else:
        if units_path.is_symlink() or units_path.exists():
            raise ValueError(
                "suppressed factorial has a stale unit table; refusing to risk "
                "publishing inadmissible effects"
            )
        factorial_fixed = [PEVL_FACTORIAL, *fixed_common]
    factorial_source, factorial_hash = bundle_pevl_sources(
        factorial_fixed, inventory["factorial"]
    )

    preflight_result = validated["preflight"]
    preflight_status = preflight_result["status"]
    preflight_decision = (
        "factorial acquisition admitted"
        if preflight_status == "PASS"
        else "factorial acquisition suppressed"
    )
    preflight_value = (
        f"{preflight_status}; {preflight['mismatch_units']:,}/"
        f"{preflight['trajectory_units']:,} mismatch units across "
        f"{preflight['executions']:,} executions; {preflight_decision}"
    )
    preflight_row = claim_row(
        "PEVL-PREFLIGHT",
        "PEVL prospective audit",
        "The frozen four-arm trace preflight reached a terminal admission decision for factorial acquisition.",
        "VERIFIED",
        preflight_source,
        "$.status, $.admission_decision, $.mismatch_units, $.rows, and $.claim_boundary",
        PEVL_STATIC_COMMIT_BRANCH,
        PEVL_PROTOCOL_COMMIT,
        preflight_hash,
        PEVL_ANALYZER,
        preflight_value,
        "seed-condition trajectories and executions",
        "1,000 trajectories; 3,000 executions; 4 arms by 5 frozen opponents",
        "exact within-arm public-state/action trace equality across two serial and one eight-worker execution",
        "This establishes or rejects reproducibility only for the frozen artifacts, five determinism-eligible opponents, schedules, and exercised contexts. It does not establish Level 7 cross-arm event alignment.",
        "INCLUDE",
    )

    stress_result = validated["stress"]
    stress_rate = stress_result["rate"]
    stress_counts = stress_result["aggregates"]
    stress_value = (
        f"{stress_result['status']}; {stress_counts['trace']}/200 trace-disagreement "
        f"clusters ({100 * stress_rate['estimate']:.2f}%; 95% cluster-bootstrap CI "
        f"[{100 * stress_rate['interval'][0]:.2f}%, "
        f"{100 * stress_rate['interval'][1]:.2f}%]); outcome "
        f"{stress_counts['outcome']}, decision-count {stress_counts['decision']}, "
        f"error {stress_counts['error']}, policy-error {stress_counts['policy']}"
    )
    stress_row = claim_row(
        "PEVL-STRESS",
        "PEVL timed-search stress test",
        "The terminal timed-search stress test quantifies complete-trace disagreement across serial/parallel and enqueue-order execution contexts.",
        "VERIFIED_WITH_CAVEAT",
        stress_source,
        "$.status, $.trace_disagreement, $.strata, $.cluster_rows, and $.pevl_level_6_boundary",
        PEVL_STATIC_COMMIT_BRANCH,
        PEVL_PROTOCOL_COMMIT,
        stress_hash,
        PEVL_ANALYZER,
        stress_value,
        "seed-condition clusters and disagreement proportion",
        "200 clusters; 800 executions; 2 timed-search opponents by 2 actual orders",
        "100,000-draw seed-condition cluster bootstrap with four executions retained per cluster",
        "The two opponent packages and four execution profiles are a bounded diagnostic population, not randomized hardware effects. Trace localization identifies plausible mechanisms but not a unique causal source. This stress test does not establish Level 7 cross-arm event alignment.",
        "INCLUDE",
    )

    factorial_result = validated["factorial"]
    factorial_status = factorial_result["status"]
    if factorial_status == "ADMITTED_SEED_MATCHED":
        contrast_order = (
            "primary_c4_minus_c1",
            "representation_main",
            "training_main",
            "interaction",
        )
        factorial_value = "; ".join(
            format_pevl_effect(name, factorial["contrasts"][name])
            for name in contrast_order
        )
        factorial_claim = (
            "The terminal five-opponent factorial admits bounded seed-matched "
            "finite-population contrasts."
        )
        factorial_status_label = "VERIFIED_WITH_CAVEAT"
        factorial_unit = "win-rate percentage points"
        factorial_sample = "2,000 units; 12,000 games; 10 opponent-by-order strata"
        factorial_method = (
            "100,000-draw paired bootstrap within each frozen opponent-by-order stratum"
        )
        factorial_limits = (
            "Inference is limited to the five prospectively frozen determinism-eligible "
            "opponents and exact schedules. Level 7 is not established; counterfactual, "
            "fully coupled common-random-number, and general causal wording are prohibited."
        )
        factorial_locator = (
            "$.status, $.cell_win_rates, $.contrasts, $.primary_mcnemar, and $.pevl_levels"
        )
    elif factorial_status == "SUPPRESSED_BY_PREFLIGHT":
        factorial_value = (
            "SUPPRESSED_BY_PREFLIGHT; no factorial effects admitted; reason: "
            f"{factorial_result['reason']}"
        )
        factorial_claim = (
            "The terminal factorial branch was transparently suppressed because the "
            "four-arm trace preflight failed."
        )
        factorial_status_label = "VERIFIED"
        factorial_unit = "admission disposition"
        factorial_sample = "no factorial acquisition"
        factorial_method = "prespecified fail-closed PEVL admission rule"
        factorial_limits = (
            "No factorial effect estimate, confidence interval, or mechanistic contrast "
            "is admissible. Level 7 is not established."
        )
        factorial_locator = "$.status, $.admission_decision, and $.reason"
    elif factorial_status == "SUPPRESSED_CONTROL_PARITY_FAILURE":
        mismatch_units = factorial_result["control_mismatch_units"]
        factorial_value = (
            "SUPPRESSED_CONTROL_PARITY_FAILURE; "
            f"{mismatch_units:,} repeated-control mismatch units; no effects admitted"
        )
        factorial_claim = (
            "The terminal factorial branch was transparently suppressed by its "
            "repeated-control parity gate."
        )
        factorial_status_label = "VERIFIED"
        factorial_unit = "mismatch units and admission disposition"
        factorial_sample = "2,000 scheduled factorial units; effects suppressed"
        factorial_method = "prespecified fail-closed control-parity admission rule"
        factorial_limits = (
            "Control-parity failure suppresses every factorial contrast; no effect estimate "
            "or causal interpretation is admissible, and Level 7 is not established."
        )
        factorial_locator = (
            "$.status, $.admission_decision, $.control_mismatch_units, and "
            "$.first_control_mismatches"
        )
    else:
        raise AssertionError(f"unhandled terminal factorial status: {factorial_status}")
    factorial_row = claim_row(
        "PEVL-FACTORIAL",
        "PEVL gated factorial",
        factorial_claim,
        factorial_status_label,
        factorial_source,
        factorial_locator,
        PEVL_STATIC_COMMIT_BRANCH,
        PEVL_PROTOCOL_COMMIT,
        factorial_hash,
        PEVL_ANALYZER,
        factorial_value,
        factorial_unit,
        factorial_sample,
        factorial_method,
        factorial_limits,
        "INCLUDE",
    )
    return [preflight_row, stress_row, factorial_row]


def build_pevl_claim_rows() -> list[dict[str, str]]:
    rows = [*build_static_pevl_claim_rows(), *build_terminal_pevl_claim_rows()]
    expected_ids = [
        "PEVL-SYNTH",
        "PEVL-SEED",
        "PEVL-HIST",
        "PEVL-PREFLIGHT",
        "PEVL-STRESS",
        "PEVL-FACTORIAL",
    ]
    if [row["claim_id"] for row in rows] != expected_ids:
        raise AssertionError("PEVL claim inventory or ordering drift")
    return rows


def validate_ledger(rows: list[dict[str, str]]) -> None:
    """Fail closed on schema, dispositions, locators, hashes, and local source bytes."""
    if len(FIELDS) != 16 or len(set(FIELDS)) != 16:
        raise ValueError("claim ledger schema must contain exactly 16 unique columns")
    claim_ids = set()
    for index, row in enumerate(rows, start=1):
        if list(row) != FIELDS or len(row) != 16:
            raise ValueError(f"claim row {index} does not match the exact 16-column schema")
        if any(not isinstance(value, str) for value in row.values()):
            raise ValueError(f"claim row {index} contains a non-string value")
        claim_id = row["claim_id"]
        if not claim_id or claim_id in claim_ids:
            raise ValueError(f"claim row {index} has a missing or duplicate claim_id: {claim_id!r}")
        claim_ids.add(claim_id)
        status = row["status"]
        disposition = row["include_or_omit"]
        if status not in VALID_STATUSES:
            raise ValueError(f"{claim_id}: invalid status {status!r}")
        if disposition not in {"INCLUDE", "OMIT"}:
            raise ValueError(f"{claim_id}: invalid disposition {disposition!r}")
        if disposition == "INCLUDE" and status not in INCLUDABLE_STATUSES:
            raise ValueError(f"{claim_id}: status {status} cannot be included")
        if status not in INCLUDABLE_STATUSES and disposition != "OMIT":
            raise ValueError(f"{claim_id}: status {status} must be omitted")
        for field in FIELDS:
            if not row[field].strip():
                raise ValueError(f"{claim_id}: required field {field!r} is blank")
        if not COMMIT_RE.fullmatch(row["commit"]):
            raise ValueError(f"{claim_id}: commit is not a full lowercase Git object ID")
        sources = row["raw_source"].split("; ")
        hashes = row["artifact_sha256"].split("; ")
        if len(sources) != len(hashes):
            raise ValueError(f"{claim_id}: source/hash counts differ")
        for source, expected_hash in zip(sources, hashes, strict=True):
            if not SHA256_RE.fullmatch(expected_hash):
                raise ValueError(f"{claim_id}: invalid SHA-256 {expected_hash!r}")
            actual_hash = source_sha256(source)
            if actual_hash != expected_hash:
                raise ValueError(
                    f"{claim_id}: source hash mismatch for {source}: {actual_hash} != {expected_hash}"
                )


def main() -> int:
    stats = load("paper/data/statistical_summary.json")
    representation = load("paper/data/representation_audit.json")
    heldout = load("paper/data/heldout_0813_summary.json")
    ablation = load("paper/data/ablation/summary.json")
    training = load("paper/data/ablation/training_report.json")
    negative = load("paper/data/negative_results.json")
    rows = []

    base_c0_source, base_c0_hash = artifact_bundle([
        "artifacts/overnight_20260816/frozen_hashes.json",
        "artifacts/grim_final_escape/decision.json",
    ])
    base_exp23_source, base_exp23_hash = artifact_bundle([
        "artifacts/overnight_20260816/frozen_hashes.json",
        "artifacts/final_sprint/exp23_identity_trained.tar.gz",
    ])
    representation_source, representation_hash = artifact_bundle([
        "paper/data/representation_audit.json",
    ])
    representation_code_source, representation_code_hash = artifact_bundle([
        "ptcg_ai/features.py",
        "artifacts/final_sprint/exp23_identity_trained/ptcg_ai/features.py",
    ])
    parity_source, parity_hash = artifact_bundle(["artifacts/p0_parity.json"])
    conflict_source, conflict_hash = artifact_bundle([
        "paper/data/representation_audit.json",
        "paper/scripts/audit_representation.py",
    ])
    data_source, data_hash = artifact_bundle([
        "artifacts/final_sprint/identity_train/train_manifest.json",
        "artifacts/final_sprint/identity_train/merged_decisions.jsonl.gz",
    ])
    exp23_training_source, exp23_training_hash = artifact_bundle([
        "scripts/train_identity_fix.py",
        "training/replay_refresh.py",
        "artifacts/final_sprint/train_identity.log",
    ])
    blind_training_source, blind_training_hash = artifact_bundle([
        "paper/data/ablation/training_report.json",
        "paper/data/ablation/summary.json",
    ])

    def add(claim_id: str, section: str, claim: str, status: str, source: str,
            locator: str, branch: str, commit: str, artifact_hash: str, script: str,
            value: str, unit: str, n: str, method: str, limits: str,
            disposition: str) -> None:
        rows.append(dict(zip(FIELDS, [
            claim_id, section, claim, status, source, locator, branch, commit,
            artifact_hash, script, value, unit, n, method, limits, disposition,
        ], strict=True)))

    # Frozen policy and representation identity.
    add("BASE-001", "Environment and frozen baseline", "C0 is A2 plus deterministic Damage V0 runtime logic; all order-policy files use the same A2 weights.",
        "VERIFIED", base_c0_source,
        "policy/control entries and decision fields", "final/overnight-20260816", "b7ce5ba7578b125e9fc6fa25b57c33a91c00dddf",
        base_c0_hash, "direct hashing",
        "A2 model b19871a9...b6bda8; C0 tree 13426288...535c3", "SHA-256", "3 policy files", "byte hashing and source inspection",
        "C0 package is ignored locally; tracked inventory corroborates the bytes.", "INCLUDE")
    add("BASE-002", "Environment and frozen baseline", "EXP23 packages byte-identical trained output-module weights in all three order-policy files.",
        "VERIFIED", base_exp23_source,
        "candidate entries and archive members", "final/overnight-20260816", "05657c656c04d88b0352bb0db6f9e2a5dce4b234",
        base_exp23_hash, "direct hashing",
        "model cefe6118...96984; tree 83489e0c...7f1c0", "SHA-256", "3 policy files", "byte and tree hashing",
        "Package manifest contains stale A2 hashes; actual member bytes are authoritative.", "INCLUDE")
    add("REP-001", "Representation defect", "Historical ordinary PLAY options omitted the actual hand-card identity; the repair binds hand[option.index] to source_card.",
        "VERIFIED", representation_code_source,
        "option_source_card and PLAY binding branch", "paper/aps-open-science-202608", "4c868358041285df7795a756a6aa41a48e67145e",
        representation_code_hash, "source inspection",
        "source_card: 0 -> hand[option.index].id for ordinary PLAY", "code behavior", "one bounded feature path", "line-by-line source audit",
        "Repair is flag-gated and EXP23 main.py enables the flag.", "INCLUDE")
    add("REP-002", "Representation defect", "The flag changes only PLAY source identity in a mechanistic parity audit.",
        "VERIFIED", parity_source, "root fields", "main", "1c5d52a1e151c1a7d630d1f098fa84f6058d1ca3",
        parity_hash, "historical parity audit",
        "4,659 decisions; 24,065 options; 2,853 values and 658 decisions changed; all MAIN", "counts", "4,659 decisions", "exact feature-array comparison",
        "Mechanistic encoder check, not matched training or gameplay.", "INCLUDE")

    corpus = representation["corpus"]
    if representation.get("schema_version") != 2:
        raise ValueError("representation audit schema_version must be 2")
    ordinary_play_options = corpus["ordinary_play_options"]
    if not (
        corpus["baseline_unresolved_play_options"]
        == corpus["identity_bound_play_options"]
        == corpus["play_options_with_numeric_index_matching_raw"]
        == ordinary_play_options
    ):
        raise ValueError("representation PLAY source/index accounting does not reconcile")
    if corpus["multi_play_option_states_with_unique_hand_indices"] != corpus["states_with_two_or_more_play_options"]:
        raise ValueError("not every retained multi-PLAY state has unique raw hand indices")
    collision_fields = (
        "within_state_duplicate_blind_signature_groups",
        "within_state_cross_identity_collision_groups",
        "states_with_within_state_cross_identity_collision",
        "play_option_instances_in_within_state_cross_identity_collisions",
    )
    if any(corpus[field] != 0 for field in collision_fields):
        raise ValueError("representation audit found an exact within-state collision")
    add("REP-003", "Representation audit", "Every retained ordinary PLAY option has source_card=0 under the reconstructed blind encoding and a positive source identity under the repaired encoding.",
        "VERIFIED_WITH_CAVEAT", representation_source, "$.corpus", "paper/aps-open-science-202608", representation["provenance"]["branch_commit"],
        representation_hash, "paper/scripts/audit_representation.py",
        f"{corpus['baseline_unresolved_play_options']:,}/{ordinary_play_options:,} blind source coordinates zero; {corpus['identity_bound_play_options']:,}/{ordinary_play_options:,} repaired source coordinates positive",
        "PLAY options", f"{corpus['decisions']:,} decisions", "deterministic retained-row transformation",
        "These retained feature rows have observation=null, so they cannot establish raw-observation binding correctness; that mechanistic claim rests on the separate parity/source audit. The corpus is outcome-selected and is not A2's original training corpus.", "INCLUDE")
    add("REP-004", "Representation audit", "The blind input retains normalized hand index but omits the relation from that index to card identity; no exact within-state input collision was observed in the retained rows.",
        "VERIFIED", representation_source, "$.corpus states_with_two_or_more_play_options, multi_play_option_states_with_unique_hand_indices, play_options_with_numeric_index_matching_raw, states_with_two_or_more_play_identities, and within_state_* fields",
        "paper/aps-open-science-202608", representation["provenance"]["branch_commit"], representation_hash,
        "paper/scripts/audit_representation.py",
        f"index matched raw in {corpus['play_options_with_numeric_index_matching_raw']:,}/{ordinary_play_options:,} PLAY options; unique indices in {corpus['multi_play_option_states_with_unique_hand_indices']:,}/{corpus['states_with_two_or_more_play_options']:,} multi-PLAY states; {corpus['states_with_two_or_more_play_identities']:,}/{corpus['states_with_play']:,} PLAY states had >=2 identities; exact duplicate groups/cross-identity groups/states/instances = 0/0/0/0",
        "states/groups/percent", f"{corpus['decisions']:,} decisions", "exact feature signature grouping",
        "Zero exact collisions do not make the representation relationally sufficient: the option index is present, but the card identity occupying that index is absent.", "INCLUDE")
    disagreement = representation["head_disagreement"]
    add("REP-005", "Representation audit", "C0 and EXP23 output modules disagree disproportionately in multi-identity PLAY states.",
        "VERIFIED_WITH_CAVEAT", representation_source, "$.head_disagreement", "paper/aps-open-science-202608",
        representation["provenance"]["branch_commit"], representation_hash, "paper/scripts/audit_representation.py",
        f"all {100*disagreement['all']['rate']:.1f}%; multi {100*disagreement['multi_play_identity']['rate']:.1f}%; other {100*disagreement['other']['rate']:.1f}%",
        "decision percent", f"{disagreement['all']['decisions']:,} decisions", "output-module-only index-exact deterministic inference",
        "No runtime shields; association with a multi-identity state is not a gameplay causal effect.", "INCLUDE")
    add("REP-CONFLICT-001", "Representation audit", "A corpus-wide repeated-signature count represented exact within-state action collisions.",
        "CONFLICT", conflict_source, "former global blind_groups aggregation and corrected $.corpus within-state fields",
        "paper/aps-open-science-202608", "dc392e7986c9c620d8a604ee582ed4b8bfd9ae10", conflict_hash,
        "independent within-row recomputation and corrected paper/scripts/audit_representation.py",
        "former 17 groups / 99.7% instances were cross-observation pattern reuse; corrected within-state result is 0 groups / 0 instances",
        "groups/percent", f"{corpus['decisions']:,} decisions", "within-row exact option-head signature audit",
        "Shared state vectors differ across observations, so cross-row option-pattern reuse is not an action collision.", "OMIT")

    corpus_facts = retained_corpus_facts("artifacts/final_sprint/identity_train/merged_decisions.jsonl.gz")
    if corpus_facts["rows"] != corpus["decisions"]:
        raise ValueError("representation report and direct corpus row count disagree")
    split_counts = corpus["split_decisions"]
    if sum(split_counts.values()) != corpus_facts["rows"]:
        raise ValueError("representation split counts do not sum to retained corpus rows")
    add("DATA-001", "Replay data and training", "The retained refresh corpus is an outcome-selected winner/top-episode feature-row sample with fixed split counts and no stored raw observations.",
        "VERIFIED_WITH_CAVEAT", data_source, "manifest counts and direct merged_decisions row scan",
        "final/overnight-20260816", "b7ce5ba7578b125e9fc6fa25b57c33a91c00dddf",
        data_hash, "paper/scripts/audit_representation.py and direct claim-ledger corpus scan",
        f"{corpus_facts['rows']:,}/{corpus_facts['rows']:,} rows reward=1, source=daily_top_episode, observation=null; {split_counts['train']:,} train; {split_counts['internal_validation']:,} internal validation; {split_counts['team_holdout']:,} six-team refresh holdout; 472 episodes; 69 team labels; 8 empty temporal stubs", "decisions/episodes/teams", f"{corpus_facts['rows']:,}", "manifest audit and exact direct row scan",
        "Winner/top-episode outcome selection is not a random expert sample; demonstrator expertise was not independently established. Null observations prevent reconstructing option-card bindings from these rows, and the nominal temporal holdout contains only empty stubs.", "INCLUDE")
    add("TRAIN-001", "Replay data and training", "EXP23 updated only four output modules while freezing the remaining network; the A2 teacher consumed the same identity-aware cell encoding as the student.",
        "VERIFIED", exp23_training_source,
        "training call, optimizer, epoch logs", "main", "4c868358041285df7795a756a6aa41a48e67145e",
        exp23_training_hash, "source/log audit",
        "lr 1e-4; 3 epochs; batch 256; seed 20260816; configured fresh .999; distillation .5; 8/19 arrays changed",
        "hyperparameters/arrays", "38,254 rows per epoch", "source plus log verification",
        "One seed and one candidate; only option_linear/score/count/value output modules were trainable. The distillation teacher is not a blind-encoder counterfactual because it receives the cell's identity-aware features.", "INCLUDE")
    add("TRAIN-002", "Replay data and training", "Configured 0.1% rehearsal was not realized.",
        "VERIFIED", exp23_training_source, "mixed_row_batches rounding; epoch logs",
        "main", "4c868358041285df7795a756a6aa41a48e67145e", exp23_training_hash,
        "source/log audit", "fresh_fraction 1.000; rehearsal_records 0 in each of 3 epochs", "fraction/rows", "3 epochs",
        "integer batch rounding", "Conservatism derives from frozen trunk and KL anchoring, not rehearsal mixing.", "INCLUDE")
    expected_trainable = {
        "option_linear.weight", "option_linear.bias", "score.weight", "score.bias",
        "count.weight", "count.bias", "value.weight", "value.bias",
    }
    if set(training["training"]["trainable_parameters"]) != expected_trainable:
        raise ValueError("blind-trained cell has an unexpected trainable-parameter set")
    if not (
        training["training"]["epochs_completed"] == 3
        and training["realized_rehearsal_records"] == 0
        and training["training"]["frozen_parameters_verified"] is True
    ):
        raise ValueError("blind-trained cell does not match the frozen training schedule")
    if not ablation.get("overwritten_pre_gameplay_c3_caveat"):
        raise ValueError("ablation report omits the overwritten pre-gameplay C3 caveat")
    add("TRAIN-003", "Four-cell ablation", "The blind-trained cell used the frozen transform and matched output-module training schedule; its A2 teacher and student both consumed the blind cell encoding, and only the final manifest-corrected package entered gameplay.",
        "VERIFIED_WITH_CAVEAT", blind_training_source, "training report root and $.overwritten_pre_gameplay_c3_caveat", "paper/aps-open-science-202608", training["frozen_protocol_commit"],
        blind_training_hash, "paper/scripts/train_blind_ablation.py and paper/scripts/analyze_ablation.py",
        f"{training['derivation']['rows']:,} rows; {training['derivation']['changed_nonzero_to_zero']:,} options zeroed; final model {training['training']['sha256']}; final tree {training['package_tree_sha256']}; 3 epochs; 0 rehearsal",
        "rows/options/hash", f"{training['derivation']['rows']:,}", "frozen deterministic transform and training",
        "The teacher is conditioned on the cell's blind-transformed inputs, not the identity-aware counterfactual. Reproduction begins from retained feature rows, not original replay observations. The first pre-gameplay C3 package/report/log was overwritten by the deterministic manifest-correction rerun; its first complete bytes no longer survive, and the report's frozen_protocol_commit field is the final training execution commit rather than the protocol-freeze commit.", "INCLUDE")

    fresh = stats["fresh_confirmation"]
    primary = fresh["primary"]
    fresh_sources = [item for item in stats["source_inventory"] if item["path"].startswith("paper/data/fresh_confirmation")]
    coupling_audit_sources = [
        item for item in ablation["sources"]
        if item.get("role") not in {"gameplay result", "C3 training report"}
    ]
    source_paths, source_hashes = artifact_bundle_from_inventory(
        fresh_sources + coupling_audit_sources,
        git_fallback_by_path=HISTORICAL_SOURCE_COMMITS,
    )
    execution_caveat = fresh["execution_provenance_caveat"]
    mcnemar_scope = primary["mcnemar_scope"]
    add("GAME-001", "Primary results", "EXP23's prospectively specified, locally committed equal-weight fresh paired gameplay effect versus C0.",
        "VERIFIED_WITH_CAVEAT", source_paths, "root rows joined by order and pair_index", "paper/aps-open-science-202608",
        "c17434252deb8fdc3b42b2c12a58f18ca646215e", source_hashes, "paper/scripts/analyze_results.py",
        f"effect {100*primary['effect']:+.2f} pp; 95% CI [{100*primary['paired_bootstrap_95_ci'][0]:+.2f}, {100*primary['paired_bootstrap_95_ci'][1]:+.2f}]; McNemar p={primary['mcnemar_exact_two_sided_p']:.6g}; discordant {primary['candidate_only_wins']}/{primary['control_only_wins']}",
        "percentage points", f"{primary['pairs']:,} pairs", "100,000-draw paired bootstrap stratified over 14 frozen cells; exact two-sided pooled McNemar",
        f"Observed schedule-paired comparison limited to seven frozen opponents, this engine build, and one realized execution. This is not full common-random-number coupling. {mcnemar_scope} {execution_caveat}", "INCLUDE")
    for index, cell in enumerate(fresh["cells"], start=1):
        add(f"GAME-C{index:02d}", "Primary results table", f"Fresh paired effect for {cell['opponent']} / {cell['actual_order']}.",
            "VERIFIED", source_paths, "matching source root rows", "paper/aps-open-science-202608", "c17434252deb8fdc3b42b2c12a58f18ca646215e",
            source_hashes, "paper/scripts/analyze_results.py",
            f"{100*cell['effect']:+.1f} pp; CI [{100*cell['paired_bootstrap_95_ci'][0]:+.1f}, {100*cell['paired_bootstrap_95_ci'][1]:+.1f}]; Holm p={cell['holm_adjusted_p_14_cells']:.6g}",
            "percentage points", str(cell["pairs"]), "paired bootstrap; exact McNemar; Holm over 14 cells",
            f"Secondary cell estimate; multiplicity-adjusted and not population inference. {execution_caveat}", "INCLUDE")
    for order, result in fresh["by_actual_order"].items():
        add(f"GAME-O-{order.upper()}", "Generalization", f"Fresh effect by actual order: {order}.", "VERIFIED",
            source_paths, f"$.fresh_confirmation.by_actual_order.{order}", "paper/aps-open-science-202608", "c17434252deb8fdc3b42b2c12a58f18ca646215e",
            source_hashes, "paper/scripts/analyze_results.py",
            f"{100*result['effect']:+.2f} pp; CI [{100*result['paired_bootstrap_95_ci'][0]:+.2f}, {100*result['paired_bootstrap_95_ci'][1]:+.2f}]",
            "percentage points", str(result["pairs"]), "paired bootstrap averaged across opponent cells", f"Secondary descriptive split. {execution_caveat}", "INCLUDE")
    for family, result in fresh["by_opponent_family"].items():
        add(f"GAME-F-{family.upper()}", "Generalization", f"Fresh equal-cell effect for frozen {family} opponent family.", "VERIFIED",
            source_paths, f"$.fresh_confirmation.by_opponent_family.{family}", "paper/aps-open-science-202608", "c17434252deb8fdc3b42b2c12a58f18ca646215e",
            source_hashes, "paper/scripts/analyze_results.py",
            f"{100*result['effect']:+.2f} pp; CI [{100*result['paired_bootstrap_95_ci'][0]:+.2f}, {100*result['paired_bootstrap_95_ci'][1]:+.2f}]",
            "percentage points", str(result["pairs"]), "paired bootstrap averaged across family/order cells",
            f"Family is a fixed engineering grouping, not a random sample. {execution_caveat}", "INCLUDE")
    add("GAME-LAT", "Evaluation protocol", "Per-game latency is unavailable.", "VERIFIED", source_paths,
        "runner rows omit latency", "paper/aps-open-science-202608", "c17434252deb8fdc3b42b2c12a58f18ca646215e", source_hashes,
        "paper/scripts/analyze_results.py", "NA", "milliseconds", f"{primary['pairs']:,} pairs", "field-presence audit",
        f"Parallel elapsed_seconds is wall time and is not a latency measure. {execution_caveat}", "INCLUDE")
    utility = fresh["win_draw_loss_utility_sensitivity"]
    add("GAME-SENS", "Primary results", "Win/draw/loss utility sensitivity preserves the paired direction.", "VERIFIED",
        source_paths, "$.fresh_confirmation.win_draw_loss_utility_sensitivity", "paper/aps-open-science-202608",
        "c17434252deb8fdc3b42b2c12a58f18ca646215e", source_hashes, "paper/scripts/analyze_results.py",
        f"{utility['effect']:+.3f}; CI [{utility['paired_bootstrap_95_ci'][0]:+.3f},{utility['paired_bootstrap_95_ci'][1]:+.3f}]",
        "utility units", str(utility["pairs"]), "100,000-draw paired within-cell bootstrap; win=1 draw=0 loss=-1",
        f"Secondary sensitivity; not the prospectively specified binary primary endpoint. {execution_caveat}", "INCLUDE")
    add("GAME-ERR", "Evaluation protocol", "The fresh confirmation completed without candidate, control, or opponent policy errors.",
        "VERIFIED", source_paths, "$.fresh_confirmation.primary error fields", "paper/aps-open-science-202608",
        "c17434252deb8fdc3b42b2c12a58f18ca646215e", source_hashes, "paper/scripts/analyze_results.py",
        f"candidate {primary['candidate_errors']}; control {primary['control_errors']}; opponent {primary['opponent_errors']}",
        "errors", str(primary["pairs"]), "exact row aggregation", f"Zero serialized policy errors do not independently verify the unserialized max-decisions or NO_SEARCH settings. {execution_caveat}", "INCLUDE")

    head = representation["refresh_holdout_recorded_action_agreement"]["overall"]
    add("OFF-001", "Generalization and held-out disagreement", "The refresh team-holdout recorded-action approval interval spans one half.",
        "VERIFIED_WITH_CAVEAT", representation_source, "$.refresh_holdout_recorded_action_agreement.overall",
        "paper/aps-open-science-202608", representation["provenance"]["branch_commit"], representation_hash,
        "paper/scripts/audit_representation.py",
        f"{head['candidate_approved']}/{head['decisive']}={head['approval']:.3f}; CI [{head['episode_bootstrap_95_ci'][0]:.3f},{head['episode_bootstrap_95_ci'][1]:.3f}]; abstain {head['abstain']}",
        "approval proportion", f"{head['decisive']} binary decisions in {head['episodes']} episodes", "episode-clustered bootstrap interval; no directional null test",
        "Output-module-only, index-exact diagnostic with no runtime shields, conditional on disagreement. The six fixed team labels were held out only from refresh gradients/internal validation; historical certification materials had already been inspected. The episode bootstrap does not model between-team sampling uncertainty.", "INCLUDE")
    replay = heldout["overall"]
    heldout_metadata = heldout["source"]
    heldout_commit = heldout_metadata["historical_evaluator_last_change_commit"]
    if heldout.get("schema_version") != 2 or not COMMIT_RE.fullmatch(heldout_commit):
        raise ValueError("heldout summary must use schema 2 and a full evaluator commit")
    if heldout_metadata["historical_evaluator"] != "scripts/overnight_20260816/replay_disagreement.py":
        raise ValueError("heldout summary names an unexpected historical evaluator")
    heldout_source, heldout_hash = artifact_bundle_from_inventory([
        {"path": HELDOUT_RAW_SUMMARY, "sha256": heldout_metadata["raw_summary_sha256"]},
        {"path": HELDOUT_RAW_ROWS, "sha256": heldout_metadata["raw_rows_sha256"]},
        {
            "path": heldout_metadata["historical_evaluator"],
            "sha256": heldout_metadata["historical_evaluator_sha256"],
        },
        {"path": heldout_metadata["sanitizer"], "sha256": heldout_metadata["sanitizer_sha256"]},
    ])
    add("OFF-002", "Generalization and held-out disagreement", "The fresh semantic-action interval on retained 2026-08-13 replay disagreements spans one half.",
        "VERIFIED_WITH_CAVEAT", heldout_source, "$.overall, $.eligibility, and $.source", "main (historical evaluator)",
        heldout_commit, heldout_hash, "paper/scripts/summarize_heldout.py",
        f"{replay['candidate_approved']}/{replay['binary_decisive']}={replay['approval']:.3f}; CI [{replay['episode_bootstrap_95_ci'][0]:.3f},{replay['episode_bootstrap_95_ci'][1]:.3f}]; abstain {replay['abstain']}; team-balanced {heldout['team_balanced_approval']:.3f} over {heldout['team_balanced_nonnull_team_count']}/{heldout['eligibility']['prespecified_team_count']} teams with nonnull estimates",
        "approval proportion", f"{replay['disagreements']} disagreements in {replay['episodes']} episodes", "episode-clustered bootstrap interval; no directional null test",
        f"Conditional disagreement estimand from winner-only, exact-deck units for five fixed, prespecified teams; only {heldout['eligibility']['teams_with_eligible_units']} supplied eligible units, and demonstrator expertise was not established. Teams and certification materials were previously inspected, so this is refresh-heldout rather than untouched external evidence. The episode bootstrap does not model between-team uncertainty, and the descriptive team-balanced estimate has no interval.", "INCLUDE")

    if ablation.get("schema_version") != 2 or ablation.get("status") != "INVALIDATED":
        raise ValueError("ablation summary must preserve the invalidated schema-2 analysis")
    planned = ablation.get("planned_analysis", {})
    parity_audit = ablation.get("control_parity_audit", {})
    if planned.get("status") != "NOT_ESTIMABLE_UNDER_FROZEN_VALIDATION":
        raise ValueError("planned ablation must remain not estimable")
    if (
        parity_audit.get("outcome_record_mismatch_units") != 210
        or parity_audit.get("serialized_record_mismatch_units") != 458
        or parity_audit.get("pairs") != 2_800
        or parity_audit.get("trace_capture") is not False
    ):
        raise ValueError("ablation parity audit differs from the verified fail-closed result")
    if len(ablation.get("sources", [])) != 29:
        raise ValueError(
            "ablation summary must inventory training, 21 gameplay, and 7 cause-audit files"
        )
    ablation_source, ablation_hash = artifact_bundle_from_inventory(
        ablation["sources"],
        git_fallback_by_path=HISTORICAL_SOURCE_COMMITS,
    )
    gameplay_sources = [
        item for item in ablation["sources"] if item.get("role") == "gameplay result"
    ]
    if len(gameplay_sources) != 21:
        raise ValueError("ablation source inventory must contain 21 gameplay result files")
    raw_ablation_sources = [
        item for item in gameplay_sources
        if item["path"].startswith("paper/data/ablation/raw/")
    ]
    if len(raw_ablation_sources) != 14:
        raise ValueError("ablation source inventory must contain 14 C2/C3 raw gameplay files")
    add(
        "ABL-FAIL", "Four-cell ablation",
        "The planned seven-opponent four-cell analysis failed the prospectively frozen C1 control-parity gate.",
        "VERIFIED", ablation_source, "$.status, $.planned_analysis, $.control_parity_audit",
        "paper/aps-open-science-202608", "63ea3135709646c41feb892e863a8bc00e758ed3",
        ablation_hash, "paper/scripts/analyze_ablation.py",
        "not estimable; 210/2,800 C1 outcome records and 458/2,800 available serialized records differed across runs (Starmie 191/377; Dipplin 19/81)",
        "units", "2,800 scheduled seed-condition units",
        "exact join on opponent, order, engine seed, and physical seat",
        "Trace capture was disabled. The discrepancies establish failure of available-record parity, not the exact causal contribution of wall time versus process-local native state.",
        "INCLUDE",
    )
    add(
        "ABL-PLAN", "Four-cell ablation",
        "The planned seven-opponent C2-C1, C3-C1, C4-C1, C4-C2, C4-C3, and interaction estimands.",
        "REQUIRES_RERUN", ablation_source, "$.planned_analysis.contrasts",
        "paper/aps-open-science-202608", "63ea3135709646c41feb892e863a8bc00e758ed3",
        ablation_hash, "paper/scripts/analyze_ablation.py",
        "not estimable under frozen validation",
        "percentage points", "2,800 planned units / 14 strata",
        "planned paired within-cell bootstrap and secondary McNemar/Holm calculations not performed",
        "A valid rerun requires deterministic opponent-search seeding or a fixed computational budget and a newly frozen protocol; the current raw runs must remain preserved.",
        "OMIT",
    )
    within = ablation["within_run_descriptive"]["contrasts"]
    add(
        "ABL-WITHIN", "Four-cell ablation",
        "Post-failure candidate-versus-own-control realized-run descriptions for C2, C3, and C4.",
        "VERIFIED_WITH_CAVEAT", ablation_source, "$.within_run_descriptive",
        "paper/aps-open-science-202608", "63ea3135709646c41feb892e863a8bc00e758ed3",
        ablation_hash, "paper/scripts/analyze_ablation.py",
        "; ".join(f"{item['contrast']} {100*item['effect']:+.3f} pp" for item in within),
        "percentage points", "2,800 units per realized run",
        "exact descriptive aggregation; no interval or hypothesis test",
        "Process-pool scheduling, wall-clock search, and process-local native search state were not serialized or coupled. These values are not validated common-random-number ablation estimates.",
        "INCLUDE",
    )
    exploratory = ablation["exploratory_reproducible_control_subset"]
    exploratory_values = exploratory["contrasts"] + [exploratory["interaction"]]
    add(
        "ABL-EXP-5", "Four-cell ablation",
        "Post hoc five-opponent whole-package control-parity sensitivity.",
        "VERIFIED_WITH_CAVEAT", ablation_source,
        "$.exploratory_reproducible_control_subset",
        "paper/aps-open-science-202608", "63ea3135709646c41feb892e863a8bc00e758ed3",
        ablation_hash, "paper/scripts/analyze_ablation.py",
        "; ".join(f"{item['contrast']} {100*item['effect']:+.2f} pp" for item in exploratory_values),
        "percentage points", "2,000 units / 10 strata / 5 fixed opponent packages",
        "exact descriptive aggregation; no interval, p-value, or multiplicity claim",
        "The subset was defined after the parity failure using identical available serialized C1 win/draw/error/decision summaries; traces were unavailable. It changes the target population and is not confirmatory.",
        "INCLUDE",
    )

    for index, result in enumerate(negative["results"], start=1):
        if result["experiment"] == "temporal_two_turn_takeover":
            relevant_sources = [
                item for item in negative["sources"]
                if item["path"].startswith("artifacts/grim_b_final_confirmation_")
            ]
        elif result["experiment"] == "bounded_sequence_oracle":
            relevant_sources = [
                item for item in negative["sources"]
                if item["path"].startswith("artifacts/grim_sequence_oracle_v0/")
            ]
        else:
            raise ValueError(f"unrecognized negative experiment: {result['experiment']!r}")
        if len(relevant_sources) != 3:
            raise ValueError(
                f"{result['experiment']} must have exactly three relevant raw source artifacts"
            )
        negative_source, negative_hash = artifact_bundle_from_inventory(relevant_sources)
        add(f"NEG-{index:02d}", "Negative and null experiments", result["label"] + " did not demonstrate benefit in its bounded confirmation.",
            "VERIFIED", negative_source, f"paper/data/negative_results.json $.results[{index-1}]", "archive/grim-5k-variance-floor",
            "816f537548d7733642e32c7ffa59c48151a4e3ce" if "temporal" in result["experiment"] else "def0c62a6cb804d8991df5c91a541037afc50cde",
            negative_hash, "paper/scripts/build_negative_results.py",
            f"{100*result['effect']:+.3f} pp; CI [{100*result['ci_low']:+.3f},{100*result['ci_high']:+.3f}]",
            "percentage points", str(result["n"]), result["method"], result["scope"], "INCLUDE")

    oracle = next(
        item for item in negative["results"]
        if item["experiment"] == "bounded_sequence_oracle"
    )
    expected_gate_provenance = {
        "historically_reported_gate": 0.03,
        "gate_provenance_commit": "def0c62a6cb804d8991df5c91a541037afc50cde",
        "gate_provenance_path": "docs/GRIM_SEQUENCE_ORACLE_V0.md",
        "gate_provenance_git_blob": "6a9e8e145e9e99dabde5bfa1bcd1a1794b926b40",
        "gate_provenance_sha256": "780c754f351e966037cfb7fa2384b6568c1bf91e27ee37ddf8d598d0ca6303c2",
    }
    if any(oracle.get(key) != value for key, value in expected_gate_provenance.items()):
        raise ValueError("sequence-oracle historical gate provenance differs from the verified Git object")
    gate_source, gate_hash = artifact_bundle(["paper/data/negative_results.json"])
    add(
        "NEG-GATE", "Negative and null experiments",
        "The sequence-oracle report names a +3 percentage-point decision gate.",
        "VERIFIED_WITH_CAVEAT", gate_source,
        "$.results[bounded_sequence_oracle].historically_reported_gate and gate_provenance_*",
        "archive/grim-5k-variance-floor", expected_gate_provenance["gate_provenance_commit"],
        gate_hash, "paper/scripts/build_negative_results.py",
        "+3.000 pp, historically reported; advance specification not independently verified",
        "percentage points", "not applicable", "Git object/blob/SHA-256 verification",
        oracle["gate_provenance_status"], "INCLUDE",
    )

    # Explicit conflicts, secondary live evidence, and missing raw evidence.
    historical_grim_source, historical_grim_hash = artifact_bundle([
        "artifacts/final_sprint/exp23_vs_ctl_B0_p1200b.json",
        "artifacts/final_sprint/exp23_vs_ctl_m1_p800.json",
        "artifacts/final_sprint/exp23_vs_ctl_m1_p800_fresh.json",
        "artifacts/final_sprint/exp23_vs_ctl_rr_p800.json",
    ])
    cert_source, cert_hash = artifact_bundle([
        "docs/sprints/final_overnight/OVERNIGHT_CERT_20260816.md",
    ])
    live_source, live_hash = artifact_bundle([
        "docs/sprints/final_overnight/DIPB_NEW_LOSS_BUCKETS_20260816.md",
    ])
    add("LIVE-001", "Secondary live evidence", "The latest surviving live snapshot records EXP23 at 19 wins and 14 losses over 33 games.",
        "VERIFIED_WITH_CAVEAT", live_source, "section 1, EXP23 snapshot", "final/overnight-20260816",
        "1333272cbe442a78359db3d645f9c1e9b58220e9", live_hash, "report extraction",
        "19-14 (57.6%)", "live games/win proportion", "33 games", "exact arithmetic from the surviving report snapshot",
        "Small, adaptively observed public-competition sample with heterogeneous opponents, no paired control, no frozen sampling frame, and no population estimand. It is secondary evidence only and is omitted from the numerical manuscript claims.", "OMIT")
    add("HIST-CONFLICT-001", "Evidence audit", "Historical approximately 3,600-pair Grim effect was approximately +4.5 pp.",
        "CONFLICT", historical_grim_source,
        "root rows", "final/overnight-20260816", "05657c656c04d88b0352bb0db6f9e2a5dce4b234", historical_grim_hash,
        "paper/scripts/analyze_results.py", "3,600 selected rows yield +5.472 pp, not +4.5 pp", "percentage points", "3,600 nominal pairs",
        "retrospective pooling; overlapping/selected historical schedules", "The nine surviving files contain 5,500 nominal pairs; 600 B0 pairs overlap exactly. The sample size and effect do not describe the same estimator.", "OMIT")
    add("HIST-UNSUP-001", "Evidence audit", "Historical seven-policy equal macro was +1.8 pp.", "UNSUPPORTED",
        cert_source, "summary text only", "final/overnight-20260816", "de532fa52f41d6bb4dece2c3af41175fed15e952",
        cert_hash, "artifact search", "+1.8", "percentage points", "reported 7 policies", "not reproducible",
        "All field-wave raw JSON and aggregation code are absent.", "OMIT")
    add("HIST-UNSUP-002", "Evidence audit", "Historical partial meta-weighted effect was +2.0 pp at 54% coverage.", "UNSUPPORTED",
        cert_source, "summary text only", "final/overnight-20260816", "de532fa52f41d6bb4dece2c3af41175fed15e952",
        cert_hash, "artifact search", "+2.0 pp / 54%", "percentage points/coverage", "reported partial field", "not reproducible",
        "Frozen meta_weights.json and raw wave files are absent.", "OMIT")
    add("HIST-CONFLICT-002", "Evidence audit", "CERT-B had 529 decisive disagreements and approval .440 with the reported interval.",
        "CONFLICT", cert_source, "CERT-B summary counts; referenced cert_exp23_vs_c0 rows are absent", "final/overnight-20260816", "de532fa52f41d6bb4dece2c3af41175fed15e952",
        cert_hash, "arithmetic reconstruction", "529 total disagreements = 398 binary decisive + 131 abstain; .440 reconstructs as 175/398; interval cannot be rerun",
        "counts/proportion", "529 disagreements", "summary arithmetic only", "Rows absent; protocol says 10k bootstrap while code defaults to 20k.", "OMIT")
    for claim_id, label, value, commit, report_path in [
        ("HIST-RERUN-PPO", "Shielded outcome PPO", "+0.15 pp / 2,000 pairs reported", "f4451863ea61e007a184695b01f7b4224dff85a6", "docs/sprints/strength_and_a2/A2_SHIELDED_OUTCOME_PPO_AUDIT.md"),
        ("HIST-RERUN-Q", "Expected-Q planning", "3 stable labels reported", "f4451863ea61e007a184695b01f7b4224dff85a6", "docs/archive_and_logs/SEEDED_Q_EXPECTED_ADVANTAGE_AUDIT.md"),
        ("HIST-RERUN-DIR", "Old Turn Director", "52.95% vs 54.35% reported in unpaired arms", "d78a00d428d6845fd0177fdfda5f7eea14f2377e", "docs/strategy/POSTMORTEM_SEARCH_V1.md"),
    ]:
        rerun_source, rerun_hash = artifact_bundle([report_path])
        add(claim_id, "Negative and null experiments", label + " exact numerical result.", "REQUIRES_RERUN",
            rerun_source, "summary only; referenced raw rows are absent", "main", commit, rerun_hash, "artifact search", value,
            "historical summary", "raw rows absent", "not independently reproducible", "Underlying result/package rows are absent.", "OMIT")

    # Append the PEVL paper claims without altering the legacy/appendix inventory.
    rows.extend(build_pevl_claim_rows())

    output = ROOT / "paper/claim_ledger.csv"
    validate_ledger(rows)
    temporary = output.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(output)
    statuses = {}
    for row in rows:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
    print(json.dumps({"claims": len(rows), "statuses": statuses}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
