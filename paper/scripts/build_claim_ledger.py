#!/usr/bin/env python3
"""Generate the numerical-claim ledger from verified artifacts and audits."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
from pathlib import Path


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
HELDOUT_RAW_SUMMARY = "artifacts/paper_heldout/heldout_0813_exp23_vs_c0.json"
HELDOUT_RAW_ROWS = "artifacts/paper_heldout/heldout_0813_exp23_vs_c0.rows.jsonl.gz"


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


def artifact_bundle(paths: list[str] | tuple[str, ...]) -> tuple[str, str]:
    """Return aligned, semicolon-delimited source paths and current byte hashes."""
    if not paths or len(paths) != len(set(paths)):
        raise ValueError(f"artifact path bundle must be nonempty and unique: {paths!r}")
    hashes = []
    for path in paths:
        checked_source_path(path)
        hashes.append(sha256_file(path))
    return "; ".join(paths), "; ".join(hashes)


def artifact_bundle_from_inventory(items: list[dict]) -> tuple[str, str]:
    """Validate an analysis-produced source inventory against the surviving bytes."""
    paths = []
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
            raise ValueError(f"source hash mismatch for {path}: {actual} != {expected}")
        paths.append(path)
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
            checked_source_path(source)
            if not SHA256_RE.fullmatch(expected_hash):
                raise ValueError(f"{claim_id}: invalid SHA-256 {expected_hash!r}")
            actual_hash = sha256_file(source)
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
    source_paths, source_hashes = artifact_bundle_from_inventory(fresh_sources)
    execution_caveat = fresh["execution_provenance_caveat"]
    mcnemar_scope = primary["mcnemar_scope"]
    add("GAME-001", "Primary results", "EXP23's prospectively specified, locally committed equal-weight fresh paired gameplay effect versus C0.",
        "VERIFIED", source_paths, "root rows joined by order and pair_index", "paper/aps-open-science-202608",
        "c17434252deb8fdc3b42b2c12a58f18ca646215e", source_hashes, "paper/scripts/analyze_results.py",
        f"effect {100*primary['effect']:+.2f} pp; 95% CI [{100*primary['paired_bootstrap_95_ci'][0]:+.2f}, {100*primary['paired_bootstrap_95_ci'][1]:+.2f}]; McNemar p={primary['mcnemar_exact_two_sided_p']:.6g}; discordant {primary['candidate_only_wins']}/{primary['control_only_wins']}",
        "percentage points", f"{primary['pairs']:,} pairs", "100,000-draw paired bootstrap stratified over 14 frozen cells; exact two-sided pooled McNemar",
        f"Inference is limited to seven frozen opponents and this engine build. {mcnemar_scope} {execution_caveat}", "INCLUDE")
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

    expected_ablation_contrasts = ["C2-C1", "C3-C1", "C4-C1", "C4-C2", "C4-C3"]
    if ablation.get("schema_version") != 1:
        raise ValueError("ablation summary must use schema version 1")
    if [item.get("contrast") for item in ablation.get("contrasts", [])] != expected_ablation_contrasts:
        raise ValueError("ablation summary has an unexpected contrast set or order")
    if ablation.get("interaction", {}).get("contrast") != "C4-C3-C2+C1":
        raise ValueError("ablation summary has an unexpected interaction label")
    if len(ablation.get("sources", [])) != 22:
        raise ValueError("ablation summary must inventory one training report and 21 gameplay files")
    ablation_source, ablation_hash = artifact_bundle_from_inventory(ablation["sources"])
    raw_ablation_sources = [
        item for item in ablation["sources"]
        if item["path"].startswith("paper/data/ablation/raw/")
    ]
    if len(raw_ablation_sources) != 14:
        raise ValueError("ablation source inventory must contain 14 C2/C3 raw gameplay files")
    for index, result in enumerate(ablation["contrasts"], start=1):
        add(f"ABL-{index:02d}", "Four-cell ablation", f"Matched ablation contrast {result['contrast']}.", "VERIFIED",
            ablation_source, f"$.contrasts[{index-1}]", "paper/aps-open-science-202608", "63ea3135709646c41feb892e863a8bc00e758ed3",
            ablation_hash, "paper/scripts/analyze_ablation.py",
            f"{100*result['effect']:+.2f} pp; CI [{100*result['ci_low']:+.2f},{100*result['ci_high']:+.2f}]; Holm p={result['holm_adjusted_p_5_contrasts']:.6g}",
            "percentage points", str(result["pairs"]), "100,000-draw paired within-cell bootstrap; exact McNemar; Holm over 5",
            "C2 and C3 are mechanistic cells on a fixed seven-opponent battery. The first pre-gameplay C3 package/report/log was overwritten; only the final manifest-corrected package was evaluated.", "INCLUDE")
    interaction = ablation["interaction"]
    add("ABL-INT", "Four-cell ablation", "Representation-by-training difference-in-differences interaction.", "VERIFIED",
        ablation_source, "$.interaction", "paper/aps-open-science-202608", "63ea3135709646c41feb892e863a8bc00e758ed3",
        ablation_hash, "paper/scripts/analyze_ablation.py",
        f"{100*interaction['effect']:+.2f} pp; CI [{100*interaction['ci_low']:+.2f},{100*interaction['ci_high']:+.2f}]",
        "percentage points", str(interaction["pairs"]), "100,000-draw paired within-cell bootstrap",
        "Descriptive interaction; no McNemar test. The first pre-gameplay C3 package/report/log was overwritten; only the final manifest-corrected package was evaluated.", "INCLUDE")

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
