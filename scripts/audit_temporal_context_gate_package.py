#!/usr/bin/env python3
"""Audit packaged context-gate parity on every frozen Aug-6 disagreement."""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np

from ptcg_ai.features import DecisionFeatures, MAX_SELECT_COUNT
from ptcg_ai.model import NumpyPolicyModel
from scripts.package_a2_finalist import sha256_file
from scripts.screen_temporal_context_gate import (
    public_gate_features as offline_features,
    semantic_key,
)


DEFAULT_PACKAGE = ROOT / "artifacts/elite_policy_candidates/temporal_context_gate_screen/package/extracted"
DEFAULT_HOLDOUT = ROOT / "artifacts/emergency_strength_sprint/temporal_elite_schema3/holdout_winners_aug6_rank1_100.jsonl.gz"
DEFAULT_OUTPUT = ROOT / "artifacts/elite_policy_candidates/temporal_context_gate_screen/package/parity_audit_aug6.json"


def desired_count(features: DecisionFeatures, count_logits: np.ndarray) -> int:
    minimum = int(round(float(features.global_features[28]) * MAX_SELECT_COUNT))
    maximum = int(round(float(features.global_features[29]) * MAX_SELECT_COUNT))
    minimum = max(0, min(minimum, len(features.options)))
    maximum = max(minimum, min(maximum, len(features.options), len(count_logits) - 1))
    return minimum + int(np.argmax(count_logits[minimum : maximum + 1]))


def load_packaged_runtime(path: Path):
    name = "ptcg_ai._packaged_temporal_context_gate_audit"
    spec = importlib.util.spec_from_file_location(name, path / "ptcg_ai/temporal_context_gate.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load packaged context-gate runtime")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def summarize(counter: Counter) -> dict:
    single = int(counter["single"])
    a2 = int(counter["a2_correct"])
    continuation = int(counter["continuation_correct"])
    runtime = a2 + int(counter["runtime_fix_selected"] - counter["runtime_harm_selected"])
    offline = a2 + int(counter["offline_fix_selected"] - counter["offline_harm_selected"])
    return {
        **dict(sorted(counter.items())),
        "rates": {
            "a2_semantic_top1": a2 / single,
            "continuation_semantic_top1": continuation / single,
            "offline_unrestricted_gate_semantic_top1": offline / single,
            "runtime_eligible_gate_semantic_top1": runtime / single,
            "runtime_gate_uplift_pp_vs_a2": 100.0 * (runtime - a2) / single,
            "runtime_gate_uplift_pp_vs_continuation": 100.0 * (runtime - continuation) / single,
            "runtime_route_coverage_all_single": counter["runtime_continuation_routes"] / single,
            "runtime_route_coverage_disagreements": (
                counter["runtime_continuation_routes"] / max(1, counter["semantic_disagreement"])
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--holdout", type=Path, default=DEFAULT_HOLDOUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    runtime = load_packaged_runtime(args.package)
    a2_path = args.package / "policy_a2_schema3.npz"
    continuation_path = args.package / "policy_continuation.npz"
    gate_path = args.package / "context_gate_weights.npz"
    a2 = NumpyPolicyModel(a2_path)
    continuation = NumpyPolicyModel(continuation_path)
    gate = runtime.LinearContextGate(gate_path)
    broad = Counter()
    hard = Counter()
    max_vector_delta = 0.0
    max_probability_delta = 0.0
    with np.load(gate_path, allow_pickle=False) as arrays:
        coef = np.asarray(arrays["coef"], dtype=np.float32)
        bias = float(arrays["bias"].item())
        mean = np.asarray(arrays["mean"], dtype=np.float32)
        std = np.asarray(arrays["std"], dtype=np.float32)
        threshold = float(arrays["threshold"].item())

    with gzip.open(args.holdout, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            scopes = [broad]
            if int(row.get("team_rank_aug4", 9999)) <= 20:
                scopes.append(hard)
            action = [int(index) for index in row.get("action", [])]
            for counter in scopes:
                counter["records"] += 1
            if len(action) != 1:
                for counter in scopes:
                    counter["multi_excluded"] += 1
                continue
            features = DecisionFeatures.from_json(row["features"])
            a2_logits, a2_counts, a2_value = a2.predict(features)
            continuation_logits, continuation_counts, continuation_value = continuation.predict(features)
            a2_index = int(np.argmax(a2_logits))
            continuation_index = int(np.argmax(continuation_logits))
            truth = semantic_key(features.options[action[0]])
            a2_correct = semantic_key(features.options[a2_index]) == truth
            continuation_correct = semantic_key(features.options[continuation_index]) == truth
            for counter in scopes:
                counter["single"] += 1
                counter["a2_correct"] += int(a2_correct)
                counter["continuation_correct"] += int(continuation_correct)
            if semantic_key(features.options[a2_index]) == semantic_key(features.options[continuation_index]):
                continue
            offline, slices = offline_features(
                features, a2, continuation, a2_logits, continuation_logits,
                a2_value, continuation_value, a2_index, continuation_index,
            )
            packaged = runtime.public_gate_features(
                features, a2, continuation, a2_logits, continuation_logits,
                a2_value, continuation_value, a2_index, continuation_index,
            )
            vector_delta = float(np.max(np.abs(offline - packaged)))
            max_vector_delta = max(max_vector_delta, vector_delta)
            if slices["full_public_model"] != 858 or vector_delta != 0.0:
                raise RuntimeError("offline/package feature-transform mismatch")
            normalized = np.clip((offline - mean) / std, -8.0, 8.0)
            logit = float(normalized @ coef + bias)
            offline_probability = 1.0 / (1.0 + np.exp(-np.clip(logit, -30.0, 30.0)))
            packaged_probability = gate.probability(packaged)
            max_probability_delta = max(max_probability_delta, abs(offline_probability - packaged_probability))
            choose_offline = offline_probability >= threshold
            eligible = desired_count(features, a2_counts) == desired_count(features, continuation_counts) == 1
            choose_runtime = bool(eligible and packaged_probability >= threshold)
            for counter in scopes:
                counter["semantic_disagreement"] += 1
                counter["runtime_eligible_disagreement"] += int(eligible)
                counter["offline_continuation_routes"] += int(choose_offline)
                counter["runtime_continuation_routes"] += int(choose_runtime)
                if choose_offline:
                    counter["offline_fix_selected"] += int(continuation_correct and not a2_correct)
                    counter["offline_harm_selected"] += int(a2_correct and not continuation_correct)
                if choose_runtime:
                    counter["runtime_fix_selected"] += int(continuation_correct and not a2_correct)
                    counter["runtime_harm_selected"] += int(a2_correct and not continuation_correct)

    report = {
        "schema_version": 1,
        "kind": "packaged_context_gate_full_aug6_parity_audit",
        "checks": {
            "all_disagreement_feature_vectors_byte_equal": max_vector_delta == 0.0,
            "all_gate_probabilities_equal_within_1e-7": max_probability_delta <= 1e-7,
            "package_models_match_frozen_inputs": (
                sha256_file(a2_path) == "80A0EF14D00256F2718D23E8323544B2901A7DF1A9CAAFD5070ED0B4B9779ACC"
                and sha256_file(continuation_path) == "D4EFD8A8EEF1F617109DB80E74BB7EF667C74184BD3D579A3EFFFAD00B9BAB31"
            ),
            "gate_matches_frozen_fit": (
                sha256_file(gate_path) == "660DD386FBEDBC46A2218CBFBC8E6FD773DFA435DE43B43589D922F2AFA4D42C"
            ),
        },
        "maximum_absolute_feature_delta": max_vector_delta,
        "maximum_absolute_probability_delta": max_probability_delta,
        "package": str(args.package.resolve()),
        "holdout": {"path": str(args.holdout.resolve()), "sha256": sha256_file(args.holdout)},
        "broad_rank1_100": summarize(broad),
        "hard_rank1_20": summarize(hard),
        "note": (
            "runtime eligibility additionally requires both policy count heads to select one; "
            "this is the deployed pre-shield route, not a simulation of shield interventions"
        ),
    }
    report["passed"] = all(report["checks"].values())
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
