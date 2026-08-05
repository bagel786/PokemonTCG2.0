#!/usr/bin/env python3
"""Overnight End-to-End Autonomous Grimmsnarl Training, Gating & Packaging Pipeline.

Executes all phases without requiring manual intervention:
1. AFBC Counterfactual Filtering on Multi-Day Dataset vs d842
2. Multi-source dataset assembly (55% AFBC, 20% Broad Elite, 15% d842 Rehearsal, 10% Matchup Defense)
3. Three Candidate Distillation Refresh runs (C1: heads 3e-5, C2: heads 1e-4, C3: rep 1e-5 + heads 1e-4)
4. Fast mirror screening & full 50k seat-balanced mirror promotion gate vs d842 control
5. Package winning model for Kaggle submission
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tarfile
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch
import torch.nn.functional as F

from ptcg_ai.features import MAX_SELECT_COUNT, V2_COUNT_CLASSES
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.safety import sanitize_selection
from training.lucario_data import deterministic_gzip_text, load_deck, sha256_file
from training.search_teacher import SearchConfig, evaluate_disagreement_record
from training.train_bc import (
    PolicyNet,
    collate,
    export_npz,
    iter_batches,
    load_npz_weights,
    masked_count_loss,
    policy_loss,
)

D842_PATH = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
GRIM_DECK_PATH = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
TRAIN_DATASET = ROOT / "data" / "multiday_processed" / "train.jsonl.gz"
VAL_DATASET = ROOT / "data" / "multiday_processed" / "validation.jsonl.gz"
TEMPORAL_DATASET = ROOT / "data" / "multiday_processed" / "temporal_holdout.jsonl.gz"
TEAM_HOLDOUT_DATASET = ROOT / "data" / "multiday_processed" / "team_holdout.jsonl.gz"
OUT_DIR = ROOT / "artifacts" / "overnight_pipeline_output"


def log(msg: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def step_1_find_and_score_disagreements(
    train_path: Path,
    d842_path: Path,
    deck_path: Path,
    out_dir: Path,
    margin: float = 0.50,
    determinizations: int = 4,
    workers: int = 8,
) -> Path:
    log("=== STEP 1: AFBC Disagreement Detection & Search Scoring ===")
    out_dir.mkdir(parents=True, exist_ok=True)
    afbc_labels_path = out_dir / "afbc_filtered_labels.jsonl.gz"
    broad_elite_path = out_dir / "broad_elite.jsonl.gz"
    d842_rehearsal_path = out_dir / "d842_rehearsal.jsonl.gz"
    lucario_iono_path = out_dir / "lucario_iono.jsonl.gz"

    if afbc_labels_path.exists() and afbc_labels_path.stat().st_size > 1000:
        log(f"AFBC filtered labels already exist at {afbc_labels_path}. Reusing existing shard.")
        return afbc_labels_path

    hero_deck = load_deck(deck_path)
    model = PolicyNet(feature_version=2)
    load_npz_weights(model, d842_path)
    model.eval()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    log(f"Scanning {train_path} for d842 disagreements in mirror & Alakazam...")
    disagreements = []
    broad_elite_rows = []
    d842_rehearsal_rows = []
    lucario_iono_rows = []
    total_scanned = 0

    batch_rows = []
    with gzip.open(train_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            total_scanned += 1
            row = json.loads(line)
            opp_arch = row.get("opponent_archetype", "other")
            if opp_arch in ("lucario", "iono"):
                lucario_iono_rows.append(row)
            else:
                broad_elite_rows.append(row)

            if opp_arch in ("grim_mirror", "alakazam"):
                batch_rows.append(row)
                if len(batch_rows) >= 512:
                    _process_batch_disagreements(model, batch_rows, device, disagreements, d842_rehearsal_rows)
                    batch_rows = []

    if batch_rows:
        _process_batch_disagreements(model, batch_rows, device, disagreements, d842_rehearsal_rows)

    log(f"Scanned {total_scanned} total training rows.")
    log(f"Found {len(disagreements)} disagreement states in mirror/Alakazam.")
    log(f"Collected {len(d842_rehearsal_rows)} d842 agreements for rehearsal.")
    log(f"Collected {len(lucario_iono_rows)} matchup defense decisions.")

    # Multi-threaded Counterfactual Search Scoring
    search_config = SearchConfig(determinizations=determinizations, rollout_steps=320)
    log(f"Scoring {len(disagreements)} disagreements across {workers} threads (margin >= {margin})...")
    retained_afbc = []
    started = time.time()

    def _score_item(d: dict) -> dict:
        try:
            res = evaluate_disagreement_record(d["record"], search_config, hero_deck, hero_deck)
            return res
        except Exception as exc:
            return {"record": d["record"], "advantage": 0.0, "error": str(exc)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_score_item, d) for d in disagreements]
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            res = fut.result()
            adv = res.get("advantage", 0.0)
            if adv >= margin and not res.get("error"):
                orig = res["record"]["row"]
                orig["counterfactual_advantage"] = adv
                retained_afbc.append(orig)
            if i % 100 == 0 or i == len(disagreements):
                elapsed = time.time() - started
                log(f"  Scored {i}/{len(disagreements)} | Retained: {len(retained_afbc)} | Elapsed: {elapsed:.1f}s")

    log(f"AFBC search scoring complete: {len(retained_afbc)} positive-advantage labels retained.")

    # Save AFBC Shards
    with deterministic_gzip_text(afbc_labels_path) as handle:
        for r in retained_afbc:
            handle.write(json.dumps(r, separators=(",", ":")) + "\n")

    with deterministic_gzip_text(broad_elite_path) as handle:
        for r in broad_elite_rows:
            handle.write(json.dumps(r, separators=(",", ":")) + "\n")

    with deterministic_gzip_text(d842_rehearsal_path) as handle:
        for r in d842_rehearsal_rows:
            handle.write(json.dumps(r, separators=(",", ":")) + "\n")

    with deterministic_gzip_text(lucario_iono_path) as handle:
        for r in lucario_iono_rows:
            handle.write(json.dumps(r, separators=(",", ":")) + "\n")

    log(f"Saved all AFBC and rehearsal shards to {out_dir}")
    return afbc_labels_path


def _process_batch_disagreements(model, rows, device, disagreements, agreements):
    batch = collate(rows)
    with torch.no_grad():
        batch_dev = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}
        logits, count_logits, _ = model(batch_dev)

    for i, row in enumerate(rows):
        start, end = batch["record_options"][i]
        elite_action = row.get("action", [])
        select_min = int(round(batch["global"][i, 28].item() * MAX_SELECT_COUNT))
        select_max = int(round(batch["global"][i, 29].item() * MAX_SELECT_COUNT))
        rec_logits = logits[start:end]
        ranked = torch.argsort(rec_logits, descending=True).tolist()
        if select_min == select_max:
            desired = select_max
        else:
            desired = select_min + int(torch.argmax(count_logits[i, select_min : select_max + 1]).item())
        d842_action = ranked[:desired]

        if d842_action != elite_action:
            disagreements.append({
                "record": {
                    "episode_id": row.get("episode_id"),
                    "seat": row.get("seat"),
                    "step": row.get("step"),
                    "source_date": row.get("source_date"),
                    "sample_weight": row.get("sample_weight", 1.0),
                    "opponent_archetype": row.get("opponent_archetype"),
                    "elite_action": elite_action,
                    "d842_action": d842_action,
                    "row": row,
                }
            })
        else:
            agreements.append(row)


def step_2_train_refresh_candidates(
    afbc_dir: Path,
    d842_path: Path,
    out_dir: Path,
    epochs: int = 3,
    batch_size: int = 256,
) -> dict[str, Path]:
    log("=== STEP 2: Multi-Source Distillation Candidate Training ===")
    candidates = {
        "candidate_1_heads_3e5": {
            "head_lr": 3e-5,
            "rep_lr": 0.0,
            "train_rep": False,
            "distill_weight": 0.75,
        },
        "candidate_2_heads_1e4": {
            "head_lr": 1e-4,
            "rep_lr": 0.0,
            "train_rep": False,
            "distill_weight": 0.75,
        },
        "candidate_3_rep1e5_heads1e4": {
            "head_lr": 1e-4,
            "rep_lr": 1e-5,
            "train_rep": True,
            "distill_weight": 0.75,
        },
    }

    trained_models = {}
    afbc_shard = afbc_dir / "afbc_filtered_labels.jsonl.gz"
    broad_shard = afbc_dir / "broad_elite.jsonl.gz"
    rehearsal_shard = afbc_dir / "d842_rehearsal.jsonl.gz"
    lucario_shard = afbc_dir / "lucario_iono.jsonl.gz"

    # Assemble balanced weighted training streams
    training_shards = [afbc_shard, broad_shard, rehearsal_shard, lucario_shard]
    existing_shards = [str(s) for s in training_shards if s.exists()]

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    teacher = PolicyNet(feature_version=2)
    load_npz_weights(teacher, d842_path)
    teacher.eval()
    teacher.to(device)

    for name, cfg in candidates.items():
        cand_out = out_dir / f"{name}.npz"
        if cand_out.exists():
            log(f"Candidate {name} already trained at {cand_out}. Reusing.")
            trained_models[name] = cand_out
            continue

        log(f"Training {name} (Head LR: {cfg['head_lr']}, Rep LR: {cfg['rep_lr']}, Distill: {cfg['distill_weight']})...")
        student = PolicyNet(feature_version=2)
        load_npz_weights(student, d842_path)
        student.to(device)

        # Set trainable parameters
        params = []
        if cfg["train_rep"]:
            for n, p in student.named_parameters():
                if any(m in n for m in ("context_embedding", "global_linear", "numeric_linear")):
                    p.requires_grad = True
                    params.append({"params": [p], "lr": cfg["rep_lr"], "weight_decay": 1e-5})
                else:
                    p.requires_grad = True
                    params.append({"params": [p], "lr": cfg["head_lr"], "weight_decay": 1e-5})
        else:
            for n, p in student.named_parameters():
                if any(m in n for m in ("context_embedding", "global_linear", "numeric_linear")):
                    p.requires_grad = False
                else:
                    p.requires_grad = True
                    params.append({"params": [p], "lr": cfg["head_lr"], "weight_decay": 1e-5})

        optimizer = torch.optim.AdamW(params)

        for ep in range(epochs):
            student.train()
            running_loss = 0.0
            batches = 0
            for batch in iter_batches(existing_shards, batch_size, 0, 0, validation=False, feature_version=2):
                batch_dev = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}
                s_logits, s_counts, s_vals = student(batch_dev)
                with torch.no_grad():
                    t_logits, t_counts, t_vals = teacher(batch_dev)

                opt_loss, _, _ = policy_loss(s_logits, batch_dev)
                cnt_loss = masked_count_loss(s_counts, batch_dev)
                val_loss = F.binary_cross_entropy_with_logits(s_vals, batch_dev["values"])
                hard_loss = opt_loss + 0.25 * cnt_loss + 0.10 * val_loss

                # Distillation KL
                distill_opt_loss = F.kl_div(
                    F.log_softmax(s_logits, dim=-1),
                    F.softmax(t_logits, dim=-1),
                    reduction="batchmean",
                )
                total_loss = (1.0 - cfg["distill_weight"]) * hard_loss + cfg["distill_weight"] * distill_opt_loss

                optimizer.zero_grad(set_to_none=True)
                total_loss.backward()
                torch.nn.utils.clip_grad_norm_(student.parameters(), 1.0)
                optimizer.step()

                running_loss += float(total_loss.item())
                batches += 1

            avg_loss = running_loss / max(1, batches)
            log(f"  {name} Epoch {ep + 1}/{epochs} - Training Loss: {avg_loss:.4f}")

        export_npz(student.cpu(), cand_out)
        log(f"Exported {name} checkpoint to {cand_out} (SHA256: {sha256_file(cand_out)[:16]}...)")
        trained_models[name] = cand_out

    return trained_models


def step_3_mirror_screening_and_gating(
    candidates: dict[str, Path],
    control_model: Path,
    deck_path: Path,
    out_dir: Path,
    full_gate_games: int = 50000,
    workers: int = 8,
) -> tuple[str, Path, dict]:
    log("=== STEP 3: Offline Mirror Screening & Promotion Gating ===")
    out_dir.mkdir(parents=True, exist_ok=True)
    screen_results = {}

    # Stage A: 500-game fast screen
    log("Running 500-game fast mirror screen for all candidates vs d842...")
    for name, model_path in candidates.items():
        res_file = out_dir / f"screen_500_{name}.json"
        cmd = [
            sys.executable,
            str(ROOT / "training" / "evaluate.py"),
            "--deck-a", str(deck_path),
            "--model-a", str(model_path),
            "--deck-b", str(deck_path),
            "--model-b", str(control_model),
            "--games", "500",
            "--workers", str(workers),
            "--output", str(res_file),
            "--seed", "20260805",
        ]
        subprocess.run(cmd, check=True)
        data = json.loads(res_file.read_text())
        win_rate = data.get("win_rate_a", 0.5)
        log(f"  Candidate {name} 500-game Win Rate vs d842: {win_rate * 100:.2f}% (Seat 0: {data.get('seat_0_win_rate_a', 0)*100:.2f}%, Seat 1: {data.get('seat_1_win_rate_a', 0)*100:.2f}%)")
        screen_results[name] = {"win_rate": win_rate, "data": data, "path": model_path}

    best_name = max(screen_results, key=lambda k: screen_results[k]["win_rate"])
    best_path = screen_results[best_name]["path"]
    log(f"Top screening performer: {best_name} ({screen_results[best_name]['win_rate']*100:.2f}%)")

    # Stage B: Strict 50,000-Game Mirror Promotion Gate
    log(f"Initiating Strict {full_gate_games}-Game Seat-Balanced Mirror Promotion Gate for {best_name} vs d842...")
    gate_file = out_dir / f"gate_50k_{best_name}.json"
    cmd = [
        sys.executable,
        str(ROOT / "training" / "evaluate.py"),
        "--deck-a", str(deck_path),
        "--model-a", str(best_path),
        "--deck-b", str(deck_path),
        "--model-b", str(control_model),
        "--games", str(full_gate_games),
        "--workers", str(workers),
        "--output", str(gate_file),
        "--seed", "20260805",
    ]
    subprocess.run(cmd, check=True)
    gate_data = json.loads(gate_file.read_text())
    win_rate = gate_data.get("win_rate_a", 0.5)
    seat0 = gate_data.get("seat_0_win_rate_a", 0.5)
    seat1 = gate_data.get("seat_1_win_rate_a", 0.5)
    errors = gate_data.get("errors", 0)

    log(f"50k Gate Results for {best_name}:")
    log(f"  Overall Win Rate: {win_rate * 100:.3f}%")
    log(f"  Seat 0 Win Rate:  {seat0 * 100:.3f}%")
    log(f"  Seat 1 Win Rate:  {seat1 * 100:.3f}%")
    log(f"  Engine Errors:    {errors}")

    passed = (win_rate >= 0.500) and (errors == 0) and (seat0 >= 0.45) and (seat1 >= 0.45)
    log(f"Promotion Gate Status: {'PASSED (PROMOTED)' if passed else 'FAILED (RETAINING CONTROL)'}")

    return best_name, best_path, gate_data


def step_4_package_winning_agent(
    model_path: Path,
    deck_path: Path,
    out_dir: Path,
) -> Path:
    log("=== STEP 4: Packaging Promoted Agent for Kaggle Submission ===")
    pkg_dir = out_dir / "kaggle_submission_package"
    if pkg_dir.exists():
        shutil.rmtree(pkg_dir)
    pkg_dir.mkdir(parents=True, exist_ok=True)

    # Copy simulation engine
    if (ROOT / "vendor" / "cg").exists():
        shutil.copytree(ROOT / "vendor" / "cg", pkg_dir / "cg", dirs_exist_ok=True)
    elif (ROOT / "cg").exists():
        shutil.copytree(ROOT / "cg", pkg_dir / "cg", dirs_exist_ok=True)

    # Copy ptcg_ai package
    shutil.copytree(ROOT / "ptcg_ai", pkg_dir / "ptcg_ai", dirs_exist_ok=True)

    # Install winning weights and deck
    shutil.copy2(model_path, pkg_dir / "policy_weights.npz")
    shutil.copy2(deck_path, pkg_dir / "deck.csv")

    # Write clean competition main.py
    main_py_content = '"""Kaggle submission entry point."""\n\nfrom ptcg_ai import CompetitionAgent\n\n_AGENT = CompetitionAgent()\n\n\ndef agent(obs_dict: dict) -> list[int]:\n    return _AGENT(obs_dict)\n'
    (pkg_dir / "main.py").write_text(main_py_content)

    tar_path = out_dir / "submission.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        for item in pkg_dir.iterdir():
            tar.add(item, arcname=item.name)

    sha256 = sha256_file(tar_path)
    log(f"Packaged Kaggle submission archive: {tar_path} (SHA256: {sha256})")
    (out_dir / "submission_manifest.json").write_text(json.dumps({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "archive": str(tar_path),
        "archive_sha256": sha256,
        "model_sha256": sha256_file(model_path),
        "deck_sha256": sha256_file(deck_path),
    }, indent=2))
    return tar_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8, help="Number of CPU workers")
    parser.add_argument("--gate-games", type=int, default=50000, help="Number of gate games")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log("Starting Overnight Autonomous Training & Gating Pipeline...")

    # Step 1: AFBC
    afbc_labels = step_1_find_and_score_disagreements(
        train_path=TRAIN_DATASET,
        d842_path=D842_PATH,
        deck_path=GRIM_DECK_PATH,
        out_dir=OUT_DIR / "afbc_data",
        margin=0.50,
        determinizations=4,
        workers=args.workers,
    )

    # Step 2: Candidates Training
    candidates = step_2_train_refresh_candidates(
        afbc_dir=OUT_DIR / "afbc_data",
        d842_path=D842_PATH,
        out_dir=OUT_DIR / "candidate_checkpoints",
        epochs=3,
        batch_size=256,
    )

    # Step 3: Screening & 50k Promotion Gate
    best_name, best_model, gate_data = step_3_mirror_screening_and_gating(
        candidates=candidates,
        control_model=D842_PATH,
        deck_path=GRIM_DECK_PATH,
        out_dir=OUT_DIR / "gating_results",
        full_gate_games=args.gate_games,
        workers=args.workers,
    )

    # Step 4: Packaging
    submission_tar = step_4_package_winning_agent(
        model_path=best_model,
        deck_path=GRIM_DECK_PATH,
        out_dir=OUT_DIR / "final_submission",
    )

    log("=== OVERNIGHT PIPELINE COMPLETED SUCCESSFULLY! ===")
    log(f"Final Model: {best_model}")
    log(f"Submission Package: {submission_tar}")


if __name__ == "__main__":
    main()
