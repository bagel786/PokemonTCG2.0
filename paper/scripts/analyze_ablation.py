#!/usr/bin/env python3
"""Analyze the frozen four-cell representation-by-training ablation."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRESH = ROOT / "paper/data/fresh_confirmation/raw"
ABLATION = ROOT / "paper/data/ablation/raw"
TRAINING_REPORT = ROOT / "paper/data/ablation/training_report.json"
C3_PACKAGE = ROOT / "artifacts/paper_ablation/blind_trained_package"
C1_PACKAGE = ROOT / "artifacts/grim_damage_conversion/winner/extracted"
OPPONENT_FILES = {
    "B0": ("grim_b0", "grim_b0.json", "0c15b56adf3b09c654505a152309fdc9f8401579a495da714347d98ae735003c", 202608230000, 8),
    "d842_runtime": ("grim_d842_runtime", "grim_d842_runtime.json", "7db753d6610930d8bd9694b4b9bece5ac48733b825422a3e399c18077b55e64e", 202608231000, 8),
    "master_v1": ("grim_master_v1", "grim_master_v1.json", "8a06ebab47cc60ed981dfada85972eb8a62e732e349f01c2a3085262079f06e8", 202608232000, 8),
    "replay_refresh": ("grim_replay_refresh", "grim_replay_refresh.json", "30e45955b67893514c8ee077cac15d46fc207efe781cbce1b94242defda4cbdc", 202608233000, 8),
    "starmie": ("starmie", "starmie_v2_boss_atk.json", "1b73779da7dcc93c8f121090bb0f1ae2d9b10b798ca4c70447b0ce1d6d01c0db", 202608234000, 4),
    "dipplin": ("dipplin", "dipplin_d1.json", "076ae8de12d2d6c4a170b47b2d2f9cf538c1d318a05bb2e81f13da9be2cd2026", 202608235000, 4),
    "alakazam_no_search": ("alakazam_no_search", "alakazam_2_4a_no_search.json", "5d44338891094988ca15f0c26d5187316549facd64a7bfbac04aa0048424e8c7", 202608236000, 8),
}
EXPECTED = {
    "C1": "13426288358d597ead809e45c364c7f7b9274a6eebf55ddd942142e3326535c3",
    "C2": "36e804ae6c593db57b595bfca9fd48592da10957f0e5f840a7e390edbeb39b63",
    "C4": "83489e0c80c631763c65375d2a7a34d28d6aa9fbb1d11e89d130c83b1e27f1c0",
    "C3": "236afa20b4ced63169736fea616849fa564281c05e9435e4dd77ecfb4ae5fd54",
}
EXPECTED_ENGINE = "867e3f9bb87e0b48889a44b5d4b04f5d2d434b2a0788d1b2bcfe0caebcb5ab78"
EXPECTED_PRODUCTION_ENGINE = "7a157f045d333f99d1996d49c12bdbdd148072a619af246385c7295518776e30"
EXPECTED_C3_MODEL = "d22d0b52dd4fac875e93fa1b510733ac14be20acd1152974e147c6742480ab70"
EXPECTED_SOURCE = "a3d28e9c3ab650a1ec3c1cf708fc7684dc5258a86469d622871e7efe25dcdc40"
EXPECTED_BLIND = "b0167f91ec2a8cfb8fe53b04a8e22b95f65bb1db30d0d2569f981382f34b111e"
EXPECTED_MANIFEST = "8c13a5de5b34c3deec5909948fb8c03117048f0295140c48a0325550a9a1a774"
EXPECTED_A2_MODEL = "b19871a9f1499c2460ae266e58194acab1d8c90b390fa5cf24ed94b9a2b6bda8"
EXPECTED_TRAINING_SCRIPT = "43284492e59cbe591a20a4213962cc0f155888fe48aea7f46bc9b698195d2709"
EXPECTED_C3_ORDER_MANIFEST = "42235534c7e2b73be92472d7123bd1cb937bfa262513860270d771607a1aefb7"
CAUSE_FILES = {
    "paired_evaluator": (
        ROOT / "training/evaluate_deterministic_crn.py",
        "fa60021b0906401aeb2c7c33e0f65f586eff256d83d689d688a86a40480e1341",
    ),
    "starmie_search": (
        ROOT / "artifacts/sprint_870/opponents/starmie_v2_boss_atk/agent/search.py",
        "658ed0280ed70bad423d39b35a19a79491518fbbf2a82996ac9ac00d90204b6a",
    ),
    "starmie_entrypoint": (
        ROOT / "artifacts/sprint_870/opponents/starmie_v2_boss_atk/main.py",
        "7ce106340de055db14e283bf692d10d4ebbaff136d2825caa84c377175376537",
    ),
    "dipplin_search": (
        ROOT / "artifacts/sprint_870/opponents/dipplin_d1/ptcg_ai/dipplin/search.py",
        "14fdb20b672aa16a6f7d02a1b923f4194d44c26f082ddddb288e729f64c2c291",
    ),
    "dipplin_entrypoint": (
        ROOT / "artifacts/sprint_870/opponents/dipplin_d1/main.py",
        "4f7dd46f778e75bc9d865619f2577129ab4ad4ae643a41e4b4876297760bbb5c",
    ),
    "native_search_api": (
        ROOT / "vendor/cg/api.py",
        "593f1298e52a635f90f8f505a52113e9af114f444c293404e37906f18ee06ced",
    ),
    "external_policy_loader": (
        ROOT / "ptcg_ai/external.py",
        "f18294f2e1ee60630fdcc8a63422aa1115365a0b31edeb4ffa6079a270944283",
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    children = sorted(
        child for child in path.rglob("*")
        if child.is_file() and "__pycache__" not in child.parts and child.suffix != ".pyc"
    )
    for child in children:
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(child)))
    return digest.hexdigest()


def nonpolicy_parity(left: Path, right: Path) -> bool:
    excluded = {
        "order_policy_manifest.json", "policy_first.npz", "policy_second.npz",
        "policy_weights.npz",
    }
    def inventory(root: Path) -> dict[str, str]:
        return {
            child.relative_to(root).as_posix(): sha256_file(child)
            for child in root.rglob("*")
            if child.is_file() and "__pycache__" not in child.parts
            and child.suffix != ".pyc" and child.relative_to(root).as_posix() not in excluded
        }
    return inventory(left) == inventory(right)


def candidate_and_control(path: Path) -> tuple[dict, dict, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    grouped = defaultdict(dict)
    for row in payload["rows"]:
        key = (str(row["actual_order"]), int(row["seed"]), int(row["physical_seat"]))
        arm = str(row["arm"])
        if arm not in {"candidate", "control"}:
            raise ValueError(f"{path}: invalid arm {arm!r}")
        if arm in grouped[key]:
            raise ValueError(f"{path}: duplicate {arm} arm for {key}")
        grouped[key][arm] = row
    candidate, control = {}, {}
    for key, pair in grouped.items():
        if set(pair) != {"candidate", "control"}:
            raise ValueError(f"{path}: incomplete pair {key}")
        candidate[key] = pair["candidate"]
        control[key] = pair["control"]
    if len(grouped) != 400:
        raise ValueError(f"{path}: expected 400 pairs, got {len(grouped)}")
    if len(payload["rows"]) != 800:
        raise ValueError(f"{path}: expected 800 rows, got {len(payload['rows'])}")
    return payload, candidate, control


def validate_payload(payload: dict, path: Path, opponent_hash: str,
                     base_seed: int, workers: int) -> None:
    checks = {
        "engine": payload.get("engine_sha256") == EXPECTED_ENGINE,
        "opponent": payload.get("opponent_sha256") == opponent_hash,
        "production_before": payload.get("production_engine_sha256_before") == EXPECTED_PRODUCTION_ENGINE,
        "production_after": payload.get("production_engine_sha256_after") == EXPECTED_PRODUCTION_ENGINE,
        "production_preserved": payload.get("production_engine_preserved") is True,
        "orders": payload.get("actual_orders") == ["first", "second"],
        "base_seed": payload.get("base_seed") == base_seed,
        "workers": payload.get("workers") == workers,
        "pairs": payload.get("pairs_per_order") == 200 and payload.get("overall", {}).get("pairs") == 400,
        "rng_pairing": payload.get("rng_provenance", {}).get("same_seed_within_candidate_control_pair") is True,
        "rng_order_seat": payload.get("rng_provenance", {}).get("same_actual_order_and_physical_seat_within_pair") is True,
    }
    if not all(checks.values()):
        raise ValueError(f"{path}: frozen-protocol check failed: {checks}")
    seen = set()
    for row in payload["rows"]:
        order = str(row["actual_order"])
        pair_index = int(row["pair_index"])
        arm = str(row["arm"])
        key = (order, pair_index, arm)
        if key in seen:
            raise ValueError(f"{path}: duplicate schedule row {key}")
        seen.add(key)
        if order not in {"first", "second"} or not 0 <= pair_index < 200:
            raise ValueError(f"{path}: out-of-schedule row {key}")
        expected_seed = base_seed + (1_000_000 if order == "second" else 0) + pair_index
        if int(row["seed"]) != expected_seed or int(row["physical_seat"]) != pair_index % 2:
            raise ValueError(f"{path}: seed/seat mismatch at {key}")
        win, draw = int(row.get("win", 0)), int(row.get("draw", 0))
        if win not in {0, 1} or draw not in {0, 1} or win + draw > 1:
            raise ValueError(f"{path}: invalid outcome at {key}")
        if int(row.get("hero_policy_errors", 0)) or int(row.get("opponent_policy_errors", 0)):
            raise ValueError(f"{path}: policy error at {key}")


def row_signature(row: dict, *, include_decisions: bool) -> tuple[int, ...]:
    signature = (
        int(row["win"]),
        int(row.get("draw", 0)),
        int(row.get("hero_policy_errors", 0)),
        int(row.get("opponent_policy_errors", 0)),
    )
    if include_decisions:
        return signature + (int(row["decisions"]),)
    return signature


def main() -> int:
    training = json.loads(TRAINING_REPORT.read_text(encoding="utf-8"))
    history = training.get("training", {}).get("history", [])
    training_checks = {
        "package_tree": training.get("package_tree_sha256") == EXPECTED["C3"],
        "package_tree_bytes": C3_PACKAGE.is_dir() and sha256_tree(C3_PACKAGE) == EXPECTED["C3"],
        "nonpolicy_package_parity": nonpolicy_parity(C1_PACKAGE, C3_PACKAGE),
        "source": training.get("derivation", {}).get("source_sha256") == EXPECTED_SOURCE,
        "blind": training.get("derivation", {}).get("blind_sha256") == EXPECTED_BLIND,
        "manifest": training.get("source_manifest_sha256") == EXPECTED_MANIFEST,
        "control_model": training.get("control_model_sha256") == EXPECTED_A2_MODEL,
        "rows": training.get("derivation", {}).get("rows") == 47_653,
        "zeroed": training.get("derivation", {}).get("changed_nonzero_to_zero") == 37_199,
        "ordinary_play": training.get("derivation", {}).get("ordinary_play_options") == 37_199,
        "already_zero": training.get("derivation", {}).get("already_zero") == 0,
        "model": training.get("training", {}).get("sha256") == EXPECTED_C3_MODEL,
        "package_models": set(training.get("package_policy_hashes", {}).values()) == {EXPECTED_C3_MODEL},
        "package_model_bytes": all(
            sha256_file(C3_PACKAGE / name) == EXPECTED_C3_MODEL
            for name in ("policy_first.npz", "policy_second.npz", "policy_weights.npz")
        ),
        "order_manifest": training.get("package_order_manifest_sha256") == EXPECTED_C3_ORDER_MANIFEST
        and sha256_file(C3_PACKAGE / "order_policy_manifest.json") == EXPECTED_C3_ORDER_MANIFEST,
        "training_script": training.get("script_sha256") == EXPECTED_TRAINING_SCRIPT,
        "epochs": [row.get("epoch") for row in history] == [1, 2, 3],
        "rehearsal": training.get("realized_rehearsal_records") == 0
        and all(row.get("rehearsal_records") == 0 for row in history),
        "frozen": training.get("training", {}).get("frozen_parameters_verified") is True,
    }
    if not all(training_checks.values()):
        raise ValueError(f"C3 training/package validation failed: {training_checks}")
    expected = dict(EXPECTED)
    rows: list[dict] = []
    sources = [{
        "role": "C3 training report",
        "path": str(TRAINING_REPORT.relative_to(ROOT)),
        "sha256": sha256_file(TRAINING_REPORT),
    }]
    for role, (path, expected_hash) in CAUSE_FILES.items():
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise ValueError(f"{path}: causal-audit source hash drift")
        sources.append({
            "role": role,
            "path": str(path.relative_to(ROOT)),
            "sha256": actual_hash,
        })
    for opponent, (ablation_label, fresh_filename, opponent_hash, base_seed, workers) in OPPONENT_FILES.items():
        paths = {
            "C2": ABLATION / f"c2_identity_a2_{ablation_label}.json",
            "C3": ABLATION / f"c3_blind_trained_{ablation_label}.json",
            "C4": FRESH / fresh_filename,
        }
        loaded = {cell: candidate_and_control(path) for cell, path in paths.items()}
        for cell, (payload, _, _) in loaded.items():
            validate_payload(payload, paths[cell], opponent_hash, base_seed, workers)
            if payload["candidate_sha256"] != expected[cell]:
                raise ValueError(f"{paths[cell]}: unexpected {cell} package hash")
            if payload["control_sha256"] != expected["C1"]:
                raise ValueError(f"{paths[cell]}: unexpected C1 package hash")
            sources.append({
                "role": "gameplay result", "cell": cell, "opponent": opponent,
                "path": str(paths[cell].relative_to(ROOT)), "sha256": sha256_file(paths[cell]),
            })
        keys = set(loaded["C4"][1])
        if any(set(loaded[cell][1]) != keys for cell in ("C2", "C3")):
            raise ValueError(f"{opponent}: candidate seed/order/seat schedules do not match")
        for key in sorted(keys):
            controls = {cell: loaded[cell][2][key] for cell in ("C2", "C3", "C4")}
            if any(
                int(row.get("hero_policy_errors", 0))
                or int(row.get("opponent_policy_errors", 0))
                for row in controls.values()
            ):
                raise ValueError(f"{opponent} {key}: C1 policy error")
            candidates = {cell: loaded[cell][1][key] for cell in ("C2", "C3", "C4")}
            if any(int(row.get("hero_policy_errors", 0)) for row in candidates.values()):
                raise ValueError(f"{opponent} {key}: candidate policy error")
            if any(int(row.get("opponent_policy_errors", 0)) for row in candidates.values()):
                raise ValueError(f"{opponent} {key}: opponent policy error")
            order, seed, seat = key
            canonical_row = {
                "opponent": opponent,
                "actual_order": order,
                "seed": seed,
                "physical_seat": seat,
            }
            for cell in ("C2", "C3", "C4"):
                canonical_row.update({
                    f"c1_{cell.lower()}_run_win": int(controls[cell]["win"]),
                    f"c1_{cell.lower()}_run_draw": int(controls[cell].get("draw", 0)),
                    f"c1_{cell.lower()}_run_decisions": int(controls[cell]["decisions"]),
                    f"{cell.lower()}_candidate_win": int(candidates[cell]["win"]),
                    f"{cell.lower()}_candidate_draw": int(candidates[cell].get("draw", 0)),
                    f"{cell.lower()}_candidate_decisions": int(candidates[cell]["decisions"]),
                })
            canonical_row["c1_outcome_records_identical"] = int(
                len({row_signature(row, include_decisions=False) for row in controls.values()}) == 1
            )
            canonical_row["c1_serialized_records_identical"] = int(
                len({row_signature(row, include_decisions=True) for row in controls.values()}) == 1
            )
            rows.append(canonical_row)
    if len(rows) != 2_800:
        raise ValueError(f"expected 2800 matched seed-condition units, got {len(rows)}")

    fields = list(rows[0])
    canonical = ROOT / "paper/data/ablation/canonical_ablation.csv"
    with canonical.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    by_opponent: dict[str, dict] = {}
    run_pairs = (("C2", "C3"), ("C2", "C4"), ("C3", "C4"))
    for opponent in OPPONENT_FILES:
        opponent_rows = [row for row in rows if row["opponent"] == opponent]
        pairwise_outcome = {}
        pairwise_decisions = {}
        for left, right in run_pairs:
            pairwise_outcome[f"{left}-{right}"] = sum(
                (
                    row[f"c1_{left.lower()}_run_win"],
                    row[f"c1_{left.lower()}_run_draw"],
                ) != (
                    row[f"c1_{right.lower()}_run_win"],
                    row[f"c1_{right.lower()}_run_draw"],
                )
                for row in opponent_rows
            )
            pairwise_decisions[f"{left}-{right}"] = sum(
                row[f"c1_{left.lower()}_run_decisions"]
                != row[f"c1_{right.lower()}_run_decisions"]
                for row in opponent_rows
            )
        by_opponent[opponent] = {
            "pairs": len(opponent_rows),
            "c1_wins_by_run": {
                cell: sum(row[f"c1_{cell.lower()}_run_win"] for row in opponent_rows)
                for cell in ("C2", "C3", "C4")
            },
            "c1_decisions_by_run": {
                cell: sum(row[f"c1_{cell.lower()}_run_decisions"] for row in opponent_rows)
                for cell in ("C2", "C3", "C4")
            },
            "any_outcome_record_mismatch_units": sum(
                not row["c1_outcome_records_identical"] for row in opponent_rows
            ),
            "any_serialized_record_mismatch_units": sum(
                not row["c1_serialized_records_identical"] for row in opponent_rows
            ),
            "pairwise_outcome_mismatch_units": pairwise_outcome,
            "pairwise_decision_count_mismatch_units": pairwise_decisions,
        }
    outcome_mismatches = sum(not row["c1_outcome_records_identical"] for row in rows)
    serialized_mismatches = sum(not row["c1_serialized_records_identical"] for row in rows)
    if outcome_mismatches != 210 or serialized_mismatches != 458:
        raise ValueError(
            "unexpected C1 parity audit result: "
            f"outcome={outcome_mismatches}, serialized={serialized_mismatches}"
        )
    reproducible_opponents = [
        opponent for opponent, audit in by_opponent.items()
        if audit["any_serialized_record_mismatch_units"] == 0
    ]
    expected_reproducible = [
        "B0", "d842_runtime", "master_v1", "replay_refresh", "alakazam_no_search"
    ]
    if reproducible_opponents != expected_reproducible:
        raise ValueError(f"unexpected reproducible-control subset: {reproducible_opponents}")

    def descriptive_contrast(
        selected: list[dict], label: str, left: str, right: str,
    ) -> dict:
        differences = [int(row[left]) - int(row[right]) for row in selected]
        return {
            "contrast": label,
            "effect": sum(differences) / len(differences),
            "left_only_wins": sum(value == 1 for value in differences),
            "right_only_wins": sum(value == -1 for value in differences),
            "pairs": len(selected),
            "status": "DESCRIPTIVE_ONLY",
        }

    within_run_descriptive = [
        descriptive_contrast(rows, "C2-C1 (C2 run)", "c2_candidate_win", "c1_c2_run_win"),
        descriptive_contrast(rows, "C3-C1 (C3 run)", "c3_candidate_win", "c1_c3_run_win"),
        descriptive_contrast(rows, "C4-C1 (C4 run)", "c4_candidate_win", "c1_c4_run_win"),
    ]
    exploratory_rows = [row for row in rows if row["opponent"] in reproducible_opponents]
    exploratory_contrasts = [
        descriptive_contrast(exploratory_rows, "C2-C1", "c2_candidate_win", "c1_c2_run_win"),
        descriptive_contrast(exploratory_rows, "C3-C1", "c3_candidate_win", "c1_c2_run_win"),
        descriptive_contrast(exploratory_rows, "C4-C1", "c4_candidate_win", "c1_c2_run_win"),
        descriptive_contrast(exploratory_rows, "C4-C2", "c4_candidate_win", "c2_candidate_win"),
        descriptive_contrast(exploratory_rows, "C4-C3", "c4_candidate_win", "c3_candidate_win"),
    ]
    interaction_values = [
        row["c4_candidate_win"] - row["c3_candidate_win"]
        - row["c2_candidate_win"] + row["c1_c2_run_win"]
        for row in exploratory_rows
    ]
    exploratory_interaction = {
        "contrast": "C4-C3-C2+C1",
        "effect": sum(interaction_values) / len(interaction_values),
        "pairs": len(exploratory_rows),
        "status": "DESCRIPTIVE_ONLY",
    }
    planned_contrasts = [
        {"contrast": label, "status": "NOT_ESTIMABLE"}
        for label in ("C2-C1", "C3-C1", "C4-C1", "C4-C2", "C4-C3", "C4-C3-C2+C1")
    ]
    report = {
        "schema_version": 2,
        "status": "INVALIDATED",
        "invalidating_error": "C1_NOT_REPRODUCIBLE_ACROSS_SEPARATELY_EXECUTED_CELLS",
        "generated_at_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "script": str(Path(__file__).resolve().relative_to(ROOT)),
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "canonical_sha256": sha256_file(canonical),
        "package_hashes": expected,
        "training_validation": training_checks,
        "protocol_commits": {
            "initial_freeze": "a976a2b",
            "contrast_clarification": "63ea3135709646c41feb892e863a8bc00e758ed3",
            "manifest_correction_before_c3_gameplay": "1780417cde50d161f076a8b5fb88a11347586edc",
            "final_training_execution_commit": training.get("frozen_protocol_commit"),
        },
        "overwritten_pre_gameplay_c3_caveat": (
            "The first C3 package/report/log were overwritten by the deterministic manifest-correction "
            "rerun before C3 gameplay. Session evidence recorded model d22d0b52...8b70 and tree "
            "e8122eea...415a6, but those first bytes no longer survive; the final package is the only "
            "C3 package evaluated."
        ),
        "planned_analysis": {
            "estimand": "equal-weight seven-opponent, fourteen-stratum four-cell contrasts",
            "pairs": 2_800,
            "strata": 14,
            "status": "NOT_ESTIMABLE_UNDER_FROZEN_VALIDATION",
            "contrasts": planned_contrasts,
            "reason": (
                "The protocol treated C1 as the within-pair control and the analyzer required its "
                "realized record to agree across the separately executed C2, C3, and C4 runs. "
                "That gate failed for search-enabled Starmie and Dipplin."
            ),
        },
        "control_parity_audit": {
            "outcome_record_mismatch_units": outcome_mismatches,
            "serialized_record_mismatch_units": serialized_mismatches,
            "pairs": len(rows),
            "trace_capture": False,
            "c1_wins_by_run": {
                cell: sum(row[f"c1_{cell.lower()}_run_win"] for row in rows)
                for cell in ("C2", "C3", "C4")
            },
            "by_opponent": by_opponent,
        },
        "within_run_descriptive": {
            "status": "POST_FAILURE_PROCESS_SENSITIVE_DESCRIPTION",
            "contrasts": within_run_descriptive,
            "limitations": (
                "These are realized candidate-versus-own-control differences, not validated "
                "common-random-number ablation estimates. No interval or p-value is reported."
            ),
        },
        "exploratory_reproducible_control_subset": {
            "status": "POST_HOC_EXPLORATORY_OMIT_FROM_CONFIRMATORY_CLAIMS",
            "selection_rule": (
                "Whole opponent packages with identical available C1 win, draw, error, and "
                "decision-count records across all three runs"
            ),
            "opponents": reproducible_opponents,
            "pairs": len(exploratory_rows),
            "contrasts": exploratory_contrasts,
            "interaction": exploratory_interaction,
            "limitations": (
                "The five-opponent subset was defined after the parity failure, changes the target "
                "population, has no trace capture, and is reported only as a descriptive sensitivity. "
                "No interval, p-value, or generalization claim is warranted."
            ),
        },
        "cause_audit": {
            "runner": (
                "Candidate and control are separate imap_unordered process-pool tasks. The scheduled "
                "gameplay-engine seed, opponent, order, and seat are shared; opponent-search "
                "randomness and wall-clock execution are not coupled."
            ),
            "starmie": "Search branches and terminates against a 3.0-second time.monotonic deadline.",
            "dipplin": "Search uses time.monotonic soft and hard deadlines.",
            "native_search_state": (
                "The production search API lazily initializes a module-global native agent pointer; "
                "the external policy loader preserves already loaded cg modules across tasks."
            ),
            "inference": (
                "This is a design incompatibility, not permission to select the 2,590 agreeing-"
                "outcome units or weaken the validation gate."
            ),
        },
        "execution_provenance_caveat": (
            "Raw rows do not serialize max-decisions or opponent environment, and trace capture is "
            "disabled. Those settings are fixed by the committed protocol/runner commands rather "
            "than independently recoverable from result rows."
        ),
        "sources": sources,
    }
    output = ROOT / "paper/data/ablation/summary.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (ROOT / "paper/data/ablation/contrasts.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        fields = [
            "analysis_set", "status", "contrast", "effect", "pairs",
            "left_only_wins", "right_only_wins", "limitations",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in within_run_descriptive:
            writer.writerow({
                "analysis_set": "within_run_descriptive",
                **result,
                "limitations": report["within_run_descriptive"]["limitations"],
            })
        for result in exploratory_contrasts + [exploratory_interaction]:
            writer.writerow({
                "analysis_set": "post_hoc_five_opponent_subset",
                **result,
                "limitations": report["exploratory_reproducible_control_subset"]["limitations"],
            })
    print(json.dumps({
        "status": report["status"],
        "outcome_mismatch_units": outcome_mismatches,
        "serialized_record_mismatch_units": serialized_mismatches,
        "within_run_descriptive": within_run_descriptive,
        "exploratory_reproducible_control_subset": exploratory_contrasts,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
