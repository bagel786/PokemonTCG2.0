#!/usr/bin/env python3
"""Analyze the frozen four-cell representation-by-training ablation."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np


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


def exact_mcnemar(left: np.ndarray, right: np.ndarray) -> float:
    differences = left.astype(int) - right.astype(int)
    positive = int(sum(differences == 1))
    negative = int(sum(differences == -1))
    total = positive + negative
    if not total:
        return 1.0
    lower = min(positive, negative)
    return min(1.0, 2 * sum(math.comb(total, k) for k in range(lower + 1)) / 2 ** total)


def holm(values: list[float]) -> list[float]:
    adjusted = [0.0] * len(values)
    running = 0.0
    for rank, index in enumerate(sorted(range(len(values)), key=values.__getitem__)):
        running = max(running, (len(values) - rank) * values[index])
        adjusted[index] = min(1.0, running)
    return adjusted


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
    rows = []
    sources = [{"path": str(TRAINING_REPORT.relative_to(ROOT)), "sha256": sha256_file(TRAINING_REPORT)}]
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
                "cell": cell, "opponent": opponent,
                "path": str(paths[cell].relative_to(ROOT)), "sha256": sha256_file(paths[cell]),
            })
        keys = set(loaded["C4"][1])
        if any(set(loaded[cell][1]) != keys for cell in ("C2", "C3")):
            raise ValueError(f"{opponent}: candidate seed/order/seat schedules do not match")
        for key in sorted(keys):
            controls = [loaded[cell][2][key] for cell in ("C2", "C3", "C4")]
            control_tuple = [
                (int(row["win"]), int(row.get("draw", 0)), int(row.get("hero_policy_errors", 0)))
                for row in controls
            ]
            if len(set(control_tuple)) != 1:
                raise ValueError(f"{opponent} {key}: deterministic C1 arm differs across runs")
            if any(
                int(row.get("hero_policy_errors", 0))
                or int(row.get("opponent_policy_errors", 0))
                for row in controls
            ):
                raise ValueError(f"{opponent} {key}: C1 policy error")
            candidates = {cell: loaded[cell][1][key] for cell in ("C2", "C3", "C4")}
            if any(int(row.get("hero_policy_errors", 0)) for row in candidates.values()):
                raise ValueError(f"{opponent} {key}: candidate policy error")
            if any(int(row.get("opponent_policy_errors", 0)) for row in candidates.values()):
                raise ValueError(f"{opponent} {key}: opponent policy error")
            order, seed, seat = key
            rows.append({
                "opponent": opponent,
                "actual_order": order,
                "seed": seed,
                "physical_seat": seat,
                "c1_blind_a2_win": int(controls[0]["win"]),
                "c2_identity_a2_win": int(candidates["C2"]["win"]),
                "c3_blind_trained_win": int(candidates["C3"]["win"]),
                "c4_identity_trained_win": int(candidates["C4"]["win"]),
            })
    if len(rows) != 2_800:
        raise ValueError(f"expected 2800 matched seed-condition units, got {len(rows)}")

    fields = list(rows[0])
    canonical = ROOT / "paper/data/ablation/canonical_ablation.csv"
    with canonical.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    cell_keys = [
        "c1_blind_a2_win", "c2_identity_a2_win",
        "c3_blind_trained_win", "c4_identity_trained_win",
    ]
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["opponent"], row["actual_order"])].append(row)
    strata = sorted(grouped)
    if len(strata) != 14 or any(len(grouped[key]) != 200 for key in strata):
        raise ValueError("ablation is not balanced over 14 200-pair strata")
    iterations = 100_000
    rng = np.random.default_rng(20260824)
    bootstrap = np.empty((len(strata), len(cell_keys), iterations), dtype=np.float32)
    batch = 1_000
    for stratum_index, key in enumerate(strata):
        values = np.asarray([[row[field] for field in cell_keys] for row in grouped[key]], dtype=np.float32)
        for start in range(0, iterations, batch):
            stop = min(iterations, start + batch)
            indices = rng.integers(0, len(values), size=(stop - start, len(values)))
            bootstrap[stratum_index, :, start:stop] = values[indices].mean(axis=1).T
    cell_bootstrap = bootstrap.mean(axis=0)
    observed = np.asarray([[row[field] for field in cell_keys] for row in rows], dtype=np.int8)
    cell_rates = {f"C{index + 1}": float(observed[:, index].mean()) for index in range(4)}
    contrasts = [
        ("C2-C1", 1, 0),
        ("C3-C1", 2, 0),
        ("C4-C1", 3, 0),
        ("C4-C2", 3, 1),
        ("C4-C3", 3, 2),
    ]
    results = []
    raw_p = []
    for label, left, right in contrasts:
        samples = cell_bootstrap[left] - cell_bootstrap[right]
        differences = observed[:, left].astype(int) - observed[:, right].astype(int)
        result = {
            "contrast": label,
            "effect": float(differences.mean()),
            "ci_low": float(np.percentile(samples, 2.5)),
            "ci_high": float(np.percentile(samples, 97.5)),
            "left_only_wins": int(sum(differences == 1)),
            "right_only_wins": int(sum(differences == -1)),
            "mcnemar_exact_two_sided_p": exact_mcnemar(observed[:, left], observed[:, right]),
            "pairs": len(rows),
        }
        raw_p.append(result["mcnemar_exact_two_sided_p"])
        results.append(result)
    for result, adjusted in zip(results, holm(raw_p), strict=True):
        result["holm_adjusted_p_5_contrasts"] = adjusted
    interaction_samples = cell_bootstrap[3] - cell_bootstrap[2] - cell_bootstrap[1] + cell_bootstrap[0]
    interaction_values = observed[:, 3] - observed[:, 2] - observed[:, 1] + observed[:, 0]
    interaction = {
        "contrast": "C4-C3-C2+C1",
        "effect": float(interaction_values.mean()),
        "ci_low": float(np.percentile(interaction_samples, 2.5)),
        "ci_high": float(np.percentile(interaction_samples, 97.5)),
        "pairs": len(rows),
        "method": "paired within-cell bootstrap; no McNemar test for interaction",
    }
    report = {
        "schema_version": 1,
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
        "cell_win_rates": cell_rates,
        "contrasts": results,
        "interaction": interaction,
        "bootstrap": {"iterations": iterations, "seed": 20260824, "strata": 14},
        "mcnemar_scope": (
            "Each pooled exact McNemar test targets conditional discordant-direction symmetry; "
            "the paired bootstrap interval is primary for the equal-weight mean contrast."
        ),
        "execution_provenance_caveat": (
            "Raw rows do not serialize max-decisions or opponent environment; those settings are "
            "fixed by the committed protocol/runner commands rather than independently recoverable "
            "from result rows."
        ),
        "sources": sources,
    }
    output = ROOT / "paper/data/ablation/summary.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (ROOT / "paper/data/ablation/contrasts.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        fields = list(results[0])
        for key in interaction:
            if key not in fields:
                fields.append(key)
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results + [interaction])
    (ROOT / "paper/ablation_macros.tex").write_text(
        "% Auto-generated by paper/scripts/analyze_ablation.py; do not edit.\n"
        + "".join(
            f"\\newcommand{{\\Ablation{result['contrast'].replace('-', 'to').replace('+', 'plus')}}}"
            f"{{{100 * result['effect']:.2f}}}\n"
            for result in results
        ),
        encoding="utf-8",
    )
    print(json.dumps({
        "cell_win_rates": cell_rates,
        "contrasts": results,
        "interaction": interaction,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
