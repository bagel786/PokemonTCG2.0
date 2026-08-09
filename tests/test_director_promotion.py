from training.director_promotion import owned_gate, replay_gate


def owned_payload(errors=0):
    cells = []
    for shard in range(8):
        for lineage in ("master", "refresh", "v22"):
            for order in ("first", "second"):
                cells.append({
                    "shard": shard, "lineage": lineage, "actual_order": order,
                    "candidate_wins": 145, "candidate_games": 250,
                    "control_wins": 125, "control_games": 250,
                    "policy_errors": errors, "source_type": "authentic_owned",
                    "candidate_sha256": "A", "control_sha256": "B", "opponent_sha256": "C",
                })
    return {"cells": cells, "direct_vs_r0": {"games": 4000, "wins": 2320}}


def test_owned_gate_accepts_large_robust_uplift():
    result = owned_gate(owned_payload())
    assert result["passed"]
    assert all(value["one_sided_95_lower"] > 0 for value in result["leave_one_out"].values())


def test_owned_gate_fails_errors():
    assert not owned_gate(owned_payload(errors=1))["passed"]


def test_replay_gate_requires_causal_public_prefix_protocol():
    payload = {
        "episodes": 120, "teams": 8, "orders": {"first": 60, "second": 60},
        "all_signature_compatible_variants": True, "agreement_gain": .08,
        "clustered_lower": .02, "worst_team_or_order_regression": -.01,
        "banks": {name: {"movement": .01} for name in ("munkidori_attachment", "adrena_brain", "shadow_bullet", "search_composition")},
        "public_prefix_only": True, "first_pre_divergence_only": True,
        "uses_behavior_clone": False,
    }
    assert replay_gate(payload)["passed"]
    payload["public_prefix_only"] = False
    assert not replay_gate(payload)["passed"]
