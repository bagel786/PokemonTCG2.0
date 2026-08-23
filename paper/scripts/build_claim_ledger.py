#!/usr/bin/env python3
"""Generate the numerical-claim ledger from verified artifacts and audits."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIELDS = [
    "claim_id", "manuscript_section", "proposed_claim", "status", "raw_source",
    "json_or_line_locator", "branch", "commit", "artifact_sha256",
    "calculation_script", "verified_value", "unit", "sample_size",
    "statistical_method", "limitations", "include_or_omit",
]


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with (ROOT / path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    stats = load("paper/data/statistical_summary.json")
    representation = load("paper/data/representation_audit.json")
    heldout = load("paper/data/heldout_0813_summary.json")
    ablation = load("paper/data/ablation/summary.json")
    training = load("paper/data/ablation/training_report.json")
    negative = load("paper/data/negative_results.json")
    rows = []

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
        "VERIFIED", "artifacts/overnight_20260816/frozen_hashes.json; artifacts/grim_final_escape/decision.json",
        "policy/control entries and decision fields", "final/overnight-20260816", "b7ce5ba7578b125e9fc6fa25b57c33a91c00dddf",
        "0dcd77c2a1f257730996cde774bfbd3cc3a67a69e39e6ac4aa133be2e115a7a8", "direct hashing",
        "A2 model b19871a9...b6bda8; C0 tree 13426288...535c3", "SHA-256", "3 policy files", "byte hashing and source inspection",
        "C0 package is ignored locally; tracked inventory corroborates the bytes.", "INCLUDE")
    add("BASE-002", "Environment and frozen baseline", "EXP23 packages byte-identical trained heads in all three order-policy files.",
        "VERIFIED", "artifacts/overnight_20260816/frozen_hashes.json; artifacts/final_sprint/exp23_identity_trained.tar.gz",
        "candidate entries and archive members", "final/overnight-20260816", "05657c656c04d88b0352bb0db6f9e2a5dce4b234",
        "0734b60c089eea9c2e40550b8e9c6dc3983957210794ba245c4c00bd9d4e7096", "direct hashing",
        "model cefe6118...96984; tree 83489e0c...7f1c0", "SHA-256", "3 policy files", "byte and tree hashing",
        "Package manifest contains stale A2 hashes; actual member bytes are authoritative.", "INCLUDE")
    add("REP-001", "Representation defect", "Historical ordinary PLAY options omitted the actual hand-card identity; the repair binds hand[option.index] to source_card.",
        "VERIFIED", "ptcg_ai/features.py; artifacts/final_sprint/exp23_identity_trained/ptcg_ai/features.py",
        "option_source_card and PLAY binding branch", "paper/aps-open-science-202608", "4c868358041285df7795a756a6aa41a48e67145e",
        "c6ac2f1fac55c48d3896fcddd5d7407ae0fd10f55dd25e1ef96921486b554e02", "source inspection",
        "source_card: 0 -> hand[option.index].id for ordinary PLAY", "code behavior", "one bounded feature path", "line-by-line source audit",
        "Repair is flag-gated and EXP23 main.py enables the flag.", "INCLUDE")
    add("REP-002", "Representation defect", "The flag changes only PLAY source identity in a mechanistic parity audit.",
        "VERIFIED", "artifacts/p0_parity.json", "root fields", "main", "1c5d52a1e151c1a7d630d1f098fa84f6058d1ca3",
        "422a1da8d125078838dc7df928d9e34c83dd8dcbe3575fc3bc79517064f6c59", "historical parity audit",
        "4,659 decisions; 24,065 options; 2,853 values and 658 decisions changed; all MAIN", "counts", "4,659 decisions", "exact feature-array comparison",
        "Mechanistic encoder check, not matched training or gameplay.", "INCLUDE")

    corpus = representation["corpus"]
    rep_hash = sha256_file("paper/data/representation_audit.json")
    add("REP-003", "Representation audit", "All retained ordinary PLAY options are unresolved under the reconstructed blind encoding and bound under the repair.",
        "VERIFIED_WITH_CAVEAT", "paper/data/representation_audit.json", "$.corpus", "paper/aps-open-science-202608", representation["provenance"]["branch_commit"],
        rep_hash, "paper/scripts/audit_representation.py",
        f"{corpus['baseline_unresolved_play_options']:,}/{corpus['ordinary_play_options']:,} blind unresolved; {corpus['identity_bound_play_options']:,} repaired bound",
        "PLAY options", f"{corpus['decisions']:,} decisions", "deterministic retained-row transformation",
        "Retained candidate corpus is not proven to be A2's original training corpus.", "INCLUDE")
    add("REP-004", "Representation audit", "Multi-identity PLAY states and exact blind-signature collisions are common in the retained corpus.",
        "VERIFIED", "paper/data/representation_audit.json", "$.corpus.states_with_two_or_more_play_identities and collision fields",
        "paper/aps-open-science-202608", representation["provenance"]["branch_commit"], rep_hash,
        "paper/scripts/audit_representation.py",
        f"{corpus['states_with_two_or_more_play_identities']:,}/{corpus['states_with_play']:,}; {corpus['blind_signature_collision_groups']} groups; {100*corpus['collision_instance_proportion']:.1f}% instances",
        "states/groups/percent", f"{corpus['decisions']:,} decisions", "exact feature signature grouping",
        "Anonymous source identities; no proprietary card names or IDs released.", "INCLUDE")
    disagreement = representation["head_disagreement"]
    add("REP-005", "Representation audit", "C0 and EXP23 heads disagree disproportionately in multi-identity PLAY states.",
        "VERIFIED_WITH_CAVEAT", "paper/data/representation_audit.json", "$.head_disagreement", "paper/aps-open-science-202608",
        representation["provenance"]["branch_commit"], rep_hash, "paper/scripts/audit_representation.py",
        f"all {100*disagreement['all']['rate']:.1f}%; multi {100*disagreement['multi_play_identity']['rate']:.1f}%; other {100*disagreement['other']['rate']:.1f}%",
        "decision percent", f"{disagreement['all']['decisions']:,} decisions", "head-only index-exact deterministic inference",
        "No runtime shields; association with collision state is not a gameplay causal effect.", "INCLUDE")

    add("DATA-001", "Replay data and training", "The retained identity corpus and split counts are fixed.",
        "VERIFIED", "artifacts/final_sprint/identity_train/train_manifest.json; merged_decisions.jsonl.gz", "manifest counts and direct row scan",
        "final/overnight-20260816", "b7ce5ba7578b125e9fc6fa25b57c33a91c00dddf",
        "a3d28e9c3ab650a1ec3c1cf708fc7684dc5258a86469d622871e7efe25dcdc40", "paper/scripts/audit_representation.py",
        "47,653 total; 38,254 train; 3,361 internal validation; 6,038 six-team holdout; 472 episodes; 69 team labels; 8 empty temporal stubs", "decisions/episodes/teams", "47,653", "manifest audit and direct scan",
        "Nominal temporal holdout contains only empty stubs and is not a valid holdout.", "INCLUDE")
    add("TRAIN-001", "Replay data and training", "EXP23 used a heads-only update with the frozen settings stated in the paper.",
        "VERIFIED", "scripts/train_identity_fix.py; training/replay_refresh.py; artifacts/final_sprint/train_identity.log",
        "training call, optimizer, epoch logs", "main", "4c868358041285df7795a756a6aa41a48e67145e",
        "463bf2331fa8393214ab8a00bf2b4fa052a744c4fe17e62ccf717c0b2f285716", "source/log audit",
        "lr 1e-4; 3 epochs; batch 256; seed 20260816; configured fresh .999; distillation .5; 8/19 arrays changed",
        "hyperparameters/arrays", "38,254 rows per epoch", "source plus log verification",
        "One seed and one candidate; only option/score/count/value heads trainable.", "INCLUDE")
    add("TRAIN-002", "Replay data and training", "Configured 0.1% rehearsal was not realized.",
        "VERIFIED", "training/replay_refresh.py; artifacts/final_sprint/train_identity.log", "mixed_row_batches rounding; epoch logs",
        "main", "4c868358041285df7795a756a6aa41a48e67145e", "463bf2331fa8393214ab8a00bf2b4fa052a744c4fe17e62ccf717c0b2f285716",
        "source/log audit", "fresh_fraction 1.000; rehearsal_records 0 in each of 3 epochs", "fraction/rows", "3 epochs",
        "integer batch rounding", "Conservatism derives from frozen trunk and KL anchoring, not rehearsal mixing.", "INCLUDE")
    add("TRAIN-003", "Four-cell ablation", "The missing blind-trained cell used the frozen transform and completed the matched training schedule.",
        "VERIFIED", "paper/data/ablation/training_report.json", "$", "paper/aps-open-science-202608", training["frozen_protocol_commit"],
        sha256_file("paper/data/ablation/training_report.json"), "paper/scripts/train_blind_ablation.py",
        f"{training['derivation']['rows']:,} rows; {training['derivation']['changed_nonzero_to_zero']:,} options zeroed; model {training['training']['sha256']}; 3 epochs; 0 rehearsal",
        "rows/options/hash", f"{training['derivation']['rows']:,}", "frozen deterministic transform and training",
        "Reproduction begins from retained feature rows, not original replay observations.", "INCLUDE")

    fresh = stats["fresh_confirmation"]
    primary = fresh["primary"]
    fresh_sources = [item for item in stats["source_inventory"] if item["path"].startswith("paper/data/fresh_confirmation")]
    source_paths = "; ".join(item["path"] for item in fresh_sources)
    source_hashes = "; ".join(item["sha256"] for item in fresh_sources)
    add("GAME-001", "Primary results", "EXP23's preregistered equal-weight fresh paired gameplay effect versus C0.",
        "VERIFIED", source_paths, "root rows joined by order and pair_index", "paper/aps-open-science-202608",
        "c17434252deb8fdc3b42b2c12a58f18ca646215e", source_hashes, "paper/scripts/analyze_results.py",
        f"effect {100*primary['effect']:+.2f} pp; 95% CI [{100*primary['paired_bootstrap_95_ci'][0]:+.2f}, {100*primary['paired_bootstrap_95_ci'][1]:+.2f}]; McNemar p={primary['mcnemar_exact_two_sided_p']:.6g}; discordant {primary['candidate_only_wins']}/{primary['control_only_wins']}",
        "percentage points", f"{primary['pairs']:,} pairs", "100,000-draw within-cell paired bootstrap; exact two-sided McNemar",
        "Inference is limited to seven frozen opponents and this engine build.", "INCLUDE")
    for index, cell in enumerate(fresh["cells"], start=1):
        add(f"GAME-C{index:02d}", "Primary results table", f"Fresh paired effect for {cell['opponent']} / {cell['actual_order']}.",
            "VERIFIED", source_paths, "matching source root rows", "paper/aps-open-science-202608", "c17434252deb8fdc3b42b2c12a58f18ca646215e",
            source_hashes, "paper/scripts/analyze_results.py",
            f"{100*cell['effect']:+.1f} pp; CI [{100*cell['paired_bootstrap_95_ci'][0]:+.1f}, {100*cell['paired_bootstrap_95_ci'][1]:+.1f}]; Holm p={cell['holm_adjusted_p_14_cells']:.6g}",
            "percentage points", str(cell["pairs"]), "paired bootstrap; exact McNemar; Holm over 14 cells",
            "Secondary cell estimate; multiplicity-adjusted and not population inference.", "INCLUDE")
    for order, result in fresh["by_actual_order"].items():
        add(f"GAME-O-{order.upper()}", "Generalization", f"Fresh effect by actual order: {order}.", "VERIFIED",
            source_paths, f"$.fresh_confirmation.by_actual_order.{order}", "paper/aps-open-science-202608", "c17434252deb8fdc3b42b2c12a58f18ca646215e",
            source_hashes, "paper/scripts/analyze_results.py",
            f"{100*result['effect']:+.2f} pp; CI [{100*result['paired_bootstrap_95_ci'][0]:+.2f}, {100*result['paired_bootstrap_95_ci'][1]:+.2f}]",
            "percentage points", str(result["pairs"]), "paired bootstrap averaged across opponent cells", "Secondary descriptive split.", "INCLUDE")
    for family, result in fresh["by_opponent_family"].items():
        add(f"GAME-F-{family.upper()}", "Generalization", f"Fresh equal-cell effect for frozen {family} opponent family.", "VERIFIED",
            source_paths, f"$.fresh_confirmation.by_opponent_family.{family}", "paper/aps-open-science-202608", "c17434252deb8fdc3b42b2c12a58f18ca646215e",
            source_hashes, "paper/scripts/analyze_results.py",
            f"{100*result['effect']:+.2f} pp; CI [{100*result['paired_bootstrap_95_ci'][0]:+.2f}, {100*result['paired_bootstrap_95_ci'][1]:+.2f}]",
            "percentage points", str(result["pairs"]), "paired bootstrap averaged across family/order cells",
            "Family is a fixed engineering grouping, not a random sample.", "INCLUDE")
    add("GAME-LAT", "Evaluation protocol", "Per-game latency is unavailable.", "VERIFIED", source_paths,
        "runner rows omit latency", "paper/aps-open-science-202608", "c17434252deb8fdc3b42b2c12a58f18ca646215e", source_hashes,
        "paper/scripts/analyze_results.py", "NA", "milliseconds", f"{primary['pairs']:,} pairs", "field-presence audit",
        "Parallel elapsed_seconds is wall time and is not a latency measure.", "INCLUDE")
    utility = fresh["win_draw_loss_utility_sensitivity"]
    add("GAME-SENS", "Primary results", "Win/draw/loss utility sensitivity preserves the paired direction.", "VERIFIED",
        source_paths, "$.fresh_confirmation.win_draw_loss_utility_sensitivity", "paper/aps-open-science-202608",
        "c17434252deb8fdc3b42b2c12a58f18ca646215e", source_hashes, "paper/scripts/analyze_results.py",
        f"{utility['effect']:+.3f}; CI [{utility['paired_bootstrap_95_ci'][0]:+.3f},{utility['paired_bootstrap_95_ci'][1]:+.3f}]",
        "utility units", str(utility["pairs"]), "100,000-draw paired within-cell bootstrap; win=1 draw=0 loss=-1",
        "Secondary sensitivity; not the preregistered binary primary endpoint.", "INCLUDE")
    add("GAME-ERR", "Evaluation protocol", "The fresh confirmation completed without candidate, control, or opponent policy errors.",
        "VERIFIED", source_paths, "$.fresh_confirmation.primary error fields", "paper/aps-open-science-202608",
        "c17434252deb8fdc3b42b2c12a58f18ca646215e", source_hashes, "paper/scripts/analyze_results.py",
        f"candidate {primary['candidate_errors']}; control {primary['control_errors']}; opponent {primary['opponent_errors']}",
        "errors", str(primary["pairs"]), "exact row aggregation", "Engine truncation is bounded by the frozen runner's terminal checks.", "INCLUDE")

    head = representation["team_holdout_expert_agreement"]["overall"]
    add("OFF-001", "Generalization and held-out disagreement", "Head-only team-holdout expert approval does not exceed one half.",
        "VERIFIED_WITH_CAVEAT", "paper/data/representation_audit.json", "$.team_holdout_expert_agreement.overall",
        "paper/aps-open-science-202608", representation["provenance"]["branch_commit"], rep_hash,
        "paper/scripts/audit_representation.py",
        f"{head['candidate_approved']}/{head['decisive']}={head['approval']:.3f}; CI [{head['episode_bootstrap_95_ci'][0]:.3f},{head['episode_bootstrap_95_ci'][1]:.3f}]; abstain {head['abstain']}",
        "approval proportion", f"{head['decisive']} binary decisions in {head['episodes']} episodes", "episode-clustered bootstrap",
        "Head-only index-exact diagnostic; no runtime shields and conditional on disagreement.", "INCLUDE")
    replay = heldout["overall"]
    heldout_hash = sha256_file("paper/data/heldout_0813_summary.json")
    add("OFF-002", "Generalization and held-out disagreement", "Fresh semantic-action reanalysis of retained 2026-08-13 replay units does not show EXP23 approval above one half.",
        "VERIFIED_WITH_CAVEAT", "paper/data/heldout_0813_summary.json", "$.overall", "paper/aps-open-science-202608",
        "196e696 (sanitizer run after retained-replay evaluation)", heldout_hash, "paper/scripts/summarize_heldout.py",
        f"{replay['candidate_approved']}/{replay['binary_decisive']}={replay['approval']:.3f}; CI [{replay['episode_bootstrap_95_ci'][0]:.3f},{replay['episode_bootstrap_95_ci'][1]:.3f}]; abstain {replay['abstain']}; team-balanced {heldout['team_balanced_approval']:.3f}",
        "approval proportion", f"{replay['disagreements']} disagreements in {replay['episodes']} episodes", "episode-clustered bootstrap",
        "Only retained Aug. 13 exact-team replay units; conditional disagreement estimand.", "INCLUDE")

    ablation_hash = sha256_file("paper/data/ablation/summary.json")
    for index, result in enumerate(ablation["contrasts"], start=1):
        add(f"ABL-{index:02d}", "Four-cell ablation", f"Matched ablation contrast {result['contrast']}.", "VERIFIED",
            "paper/data/ablation/raw/*.json", f"$.contrasts[{index-1}]", "paper/aps-open-science-202608", "63ea313 (frozen gameplay protocol)",
            ablation_hash, "paper/scripts/analyze_ablation.py",
            f"{100*result['effect']:+.2f} pp; CI [{100*result['ci_low']:+.2f},{100*result['ci_high']:+.2f}]; Holm p={result['holm_adjusted_p_5_contrasts']:.6g}",
            "percentage points", str(result["pairs"]), "100,000-draw paired within-cell bootstrap; exact McNemar; Holm over 5",
            "C2 and C3 are mechanistic cells; fixed seven-opponent battery.", "INCLUDE")
    interaction = ablation["interaction"]
    add("ABL-INT", "Four-cell ablation", "Representation-by-training difference-in-differences interaction.", "VERIFIED",
        "paper/data/ablation/raw/*.json", "$.interaction", "paper/aps-open-science-202608", "63ea313 (frozen gameplay protocol)",
        ablation_hash, "paper/scripts/analyze_ablation.py",
        f"{100*interaction['effect']:+.2f} pp; CI [{100*interaction['ci_low']:+.2f},{100*interaction['ci_high']:+.2f}]",
        "percentage points", str(interaction["pairs"]), "100,000-draw paired within-cell bootstrap",
        "Descriptive interaction; no McNemar test.", "INCLUDE")

    negative_hash = sha256_file("paper/data/negative_results.json")
    for index, result in enumerate(negative["results"], start=1):
        add(f"NEG-{index:02d}", "Negative and null experiments", result["label"] + " did not demonstrate benefit in its bounded confirmation.",
            "VERIFIED", "paper/data/negative_results.json", f"$.results[{index-1}]", "archive/grim-5k-variance-floor",
            "816f537548d7733642e32c7ffa59c48151a4e3ce" if "temporal" in result["experiment"] else "def0c62a6cb804d8991df5c91a541037afc50cde",
            negative_hash, "paper/scripts/build_negative_results.py",
            f"{100*result['effect']:+.3f} pp; CI [{100*result['ci_low']:+.3f},{100*result['ci_high']:+.3f}]",
            "percentage points", str(result["n"]), result["method"], result["scope"], "INCLUDE")

    # Explicit conflicts and missing evidence, all omitted from numerical manuscript claims.
    add("HIST-CONFLICT-001", "Evidence audit", "Historical approximately 3,600-pair Grim effect was approximately +4.5 pp.",
        "CONFLICT", "artifacts/final_sprint/exp23_vs_ctl_B0_p1200b.json; exp23_vs_ctl_m1_p800.json; exp23_vs_ctl_m1_p800_fresh.json; exp23_vs_ctl_rr_p800.json",
        "root rows", "final/overnight-20260816", "05657c656c04d88b0352bb0db6f9e2a5dce4b234", "multiple; see statistical_summary source inventory",
        "paper/scripts/analyze_results.py", "3,600 selected rows yield +5.472 pp, not +4.5 pp", "percentage points", "3,600 nominal pairs",
        "retrospective pooling; overlapping/selected historical schedules", "The nine surviving files contain 5,500 nominal pairs; 600 B0 pairs overlap exactly. The sample size and effect do not describe the same estimator.", "OMIT")
    add("HIST-UNSUP-001", "Evidence audit", "Historical seven-policy equal macro was +1.8 pp.", "UNSUPPORTED",
        "docs/sprints/final_overnight/OVERNIGHT_CERT_20260816.md", "summary text only", "final/overnight-20260816", "de532fa52f41d6bb4dece2c3af41175fed15e952",
        "", "artifact search", "+1.8", "percentage points", "reported 7 policies", "not reproducible",
        "All field-wave raw JSON and aggregation code are absent.", "OMIT")
    add("HIST-UNSUP-002", "Evidence audit", "Historical partial meta-weighted effect was +2.0 pp at 54% coverage.", "UNSUPPORTED",
        "docs/sprints/final_overnight/OVERNIGHT_CERT_20260816.md", "summary text only", "final/overnight-20260816", "de532fa52f41d6bb4dece2c3af41175fed15e952",
        "", "artifact search", "+2.0 pp / 54%", "percentage points/coverage", "reported partial field", "not reproducible",
        "Frozen meta_weights.json and raw wave files are absent.", "OMIT")
    add("HIST-CONFLICT-002", "Evidence audit", "CERT-B had 529 decisive disagreements and approval .440 with the reported interval.",
        "CONFLICT", "OVERNIGHT_CERT_20260816.md; missing cert_exp23_vs_c0 rows", "summary counts", "final/overnight-20260816", "de532fa52f41d6bb4dece2c3af41175fed15e952",
        "", "arithmetic reconstruction", "529 total disagreements = 398 binary decisive + 131 abstain; .440 reconstructs as 175/398; interval cannot be rerun",
        "counts/proportion", "529 disagreements", "summary arithmetic only", "Rows absent; protocol says 10k bootstrap while code defaults to 20k.", "OMIT")
    for claim_id, label, value, commit in [
        ("HIST-RERUN-PPO", "Shielded outcome PPO", "+0.15 pp / 2,000 pairs reported", "f4451863ea61e007a184695b01f7b4224dff85a6"),
        ("HIST-RERUN-Q", "Expected-Q planning", "3 stable labels reported", "f4451863ea61e007a184695b01f7b4224dff85a6"),
        ("HIST-RERUN-DIR", "Old Turn Director", "52.95% vs 54.35% reported in unpaired arms", "d78a00d428d6845fd0177fdfda5f7eea14f2377e"),
    ]:
        add(claim_id, "Negative and null experiments", label + " exact numerical result.", "REQUIRES_RERUN",
            "historical audit/postmortem markdown", "summary only", "main", commit, "", "artifact search", value,
            "historical summary", "raw rows absent", "not independently reproducible", "Underlying result/package rows are absent.", "OMIT")

    output = ROOT / "paper/claim_ledger.csv"
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    statuses = {}
    for row in rows:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
    print(json.dumps({"claims": len(rows), "statuses": statuses}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
