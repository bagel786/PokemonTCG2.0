#!/usr/bin/env python3
"""Train the P1 PLAY-only residual from causally labeled states.

Features per (state, PLAY card):
- frozen R0 card embedding (32 dims)
- R0 logit / margin for that card at the prompt
- card metadata (cardType, basic, stage1, stage2)
- public context (turn, ordinal, order, hand sizes, prizes, flags, bench)

Correction: c = scale * tanh(w.x + b), applied additively to PLAY logits.
Loss per clear preference pair (preferred p, base b):
    max(0, M - (c_p - c_b)) + lam * (c_p^2 + c_b^2)
plus L2 rehearsal toward zero sampled from every mining-state card so
ordinary prompts do not drift.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from ptcg_ai.view import card_table  # noqa: E402

R0_MODEL = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/winner/extracted/policy_weights.npz")
MARGIN = 0.5


def _ordinal(turn: int, seat: int, first_player: int) -> int:
    if first_player not in (0, 1) or turn <= 0:
        return 0
    return (turn + 1) // 2 if seat == first_player else turn // 2


def build_features(states: list[dict]) -> dict:
    arrays = np.load(R0_MODEL, allow_pickle=False)
    embedding = arrays["card_embedding"].astype(np.float32)
    table = card_table()
    rows = []
    for state in states:
        card_logits = {int(card): float(value) for card, value in state["card_logits"].items()}
        top_logit = max(card_logits.values())
        order_flag = 1.0 if state["order"] == "first" else 0.0
        ordinal = _ordinal(state["turn"], state["your_index"], state["first_player"])
        current = state["obs"]["current"]
        for card in state["playable"]:
            meta = table.get(int(card))
            scalars = np.array(
                [
                    card_logits.get(int(card), -9e9) / 10.0,
                    (top_logit - card_logits.get(int(card), -9e9)) / 10.0,
                    state["turn"] / 100.0,
                    ordinal / 20.0,
                    order_flag,
                    state["hand_size"] / 30.0,
                    state["opponent_hand_size"] / 30.0,
                    state["my_prizes"] / 6.0,
                    state["opponent_prizes"] / 6.0,
                    current["supporterPlayed"],
                    current["energyAttached"],
                    (int(meta.cardType) / 6.0) if meta is not None else 0.0,
                    float(bool(meta and meta.basic)),
                    float(bool(meta and meta.stage1)),
                    float(bool(meta and meta.stage2)),
                    len(current["players"][state["your_index"]]["bench"] or []) / 5.0,
                    len(current["players"][1 - state["your_index"]]["bench"] or []) / 5.0,
                ],
                dtype=np.float32,
            )
            vector = np.concatenate([embedding[int(card)], scalars]).astype(np.float32)
            rows.append({"state": state, "card": int(card), "vector": vector})
    return {"rows": rows, "dim": 32 + 17}


def extract_preferences(states: list[dict]) -> list[dict]:
    preferences = []
    for state in states:
        chosen = state["chosen_card"]
        per_card = {int(card): value for card, value in state["per_card"].items()}
        if not all(value["runs"] >= 3 for value in per_card.values()):
            continue
        cards = list(per_card)
        if chosen is None:
            ranked = sorted(cards, key=lambda c: per_card[c]["wins"], reverse=True)
            if len(ranked) >= 2 and per_card[ranked[0]]["wins"] - per_card[ranked[1]]["wins"] >= 2:
                preferences.append({"state": state, "preferred": ranked[0], "base": ranked[1]})
            continue
        for card in cards:
            if card == chosen:
                continue
            if per_card[card]["wins"] - per_card[chosen]["wins"] >= 2:
                preferences.append({"state": state, "preferred": card, "base": chosen})
    return preferences


def train(
    pairs: list[tuple[np.ndarray, np.ndarray]],
    rehearsal: np.ndarray,
    dim: int,
    lam: float,
    scale: float,
    steps: int = 6000,
    lr: float = 1e-2,
) -> tuple[np.ndarray, float]:
    rng = np.random.default_rng(12345)
    mean = rehearsal.mean(axis=0).astype(np.float32)
    std = np.maximum(rehearsal.std(axis=0), 1e-4).astype(np.float32)

    def standardize(x: np.ndarray) -> np.ndarray:
        return (x - mean) / std

    pairs = [(standardize(xp), standardize(xb)) for xp, xb in pairs]
    rehearsal = standardize(rehearsal)
    w = np.zeros(dim, dtype=np.float32)
    b = 0.0
    beta1, beta2 = 0.9, 0.999
    mw, vw = np.zeros(dim, dtype=np.float32), np.zeros(dim, dtype=np.float32)
    mb, vb = 0.0, 0.0
    eps = 1e-8
    weight_decay = 0.02
    for step in range(steps):
        xp, xb = pairs[int(rng.integers(0, len(pairs)))]
        lp, lb = float(xp @ w + b), float(xb @ w + b)
        cp, cb = scale * math.tanh(lp), scale * math.tanh(lb)
        dp, db = (1.0 - math.tanh(lp) ** 2) * scale, (1.0 - math.tanh(lb) ** 2) * scale
        gw = np.zeros(dim, dtype=np.float32)
        gb = 0.0
        if cp - cb < MARGIN:
            gw += -dp * xp + db * xb
            gb += -dp + db
        xr = rehearsal[int(rng.integers(0, len(rehearsal)))]
        lr_ = float(xr @ w + b)
        cr = scale * math.tanh(lr_)
        dr = (1.0 - math.tanh(lr_) ** 2) * scale
        gw += lam * 2.0 * cr * dr * xr
        gb += lam * 2.0 * cr * dr
        gw += weight_decay * w
        mw = beta1 * mw + (1 - beta1) * gw
        vw = beta2 * vw + (1 - beta2) * (gw ** 2)
        mb = beta1 * mb + (1 - beta1) * gb
        vb = beta2 * vb + (1 - beta2) * (gb ** 2)
        w -= lr * (mw / (1 - beta1 ** (step + 1))) / (np.sqrt(vw / (1 - beta2 ** (step + 1))) + eps)
        b -= lr * (mb / (1 - beta1 ** (step + 1))) / (np.sqrt(vb / (1 - beta2 ** (step + 1))) + eps)
    return w, b, mean, std


def corrections(w: np.ndarray, b: float, X: np.ndarray, scale: float, mean=None, std=None) -> np.ndarray:
    if mean is not None and std is not None:
        X = (X - mean) / std
    return scale * np.tanh(X @ w + b)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, default=ROOT / "artifacts/p1_causal_labels.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/p1_residual.npz")
    parser.add_argument("--report", type=Path, default=ROOT / "artifacts/p1_training_report.json")
    args = parser.parse_args()

    states = [json.loads(line) for line in args.labels.read_text().splitlines()]
    preferences = extract_preferences(states)
    print("clear preferences:", len(preferences))

    built = build_features(states)
    dim = built["dim"]
    by_key = {(row["state"]["game_seed"], row["card"]): row["vector"] for row in built["rows"]}

    def vector(state: dict, card: int):
        return by_key.get((state["game_seed"], card))

    seed_rank = sorted({p["state"]["game_seed"] for p in preferences})
    val_seeds = set(seed_rank[::5])
    train_prefs = [p for p in preferences if p["state"]["game_seed"] not in val_seeds]
    val_prefs = [p for p in preferences if p["state"]["game_seed"] in val_seeds]
    print("train prefs:", len(train_prefs), "val prefs:", len(val_prefs))

    def pairs_from(prefs):
        result = []
        for p in prefs:
            xp = vector(p["state"], p["preferred"])
            xb = vector(p["state"], p["base"])
            if xp is None or xb is None:
                continue
            result.append((xp, xb))
        return result

    train_pairs = pairs_from(train_prefs)
    val_pairs = pairs_from(val_prefs)
    rehearsal = np.stack([row["vector"] for row in built["rows"]]).astype(np.float32)
    print("train pairs:", len(train_pairs), "val pairs:", len(val_pairs))

    grid = {}
    best = None
    for lam in (0.1, 0.5):
        for scale in (1.0, 2.0):
            w, b, mean, std = train(train_pairs, rehearsal, dim, lam=lam, scale=scale)
            val_correct = 0
            for xp, xb in val_pairs:
                val_correct += int(corrections(w, b, xp[None, :], scale, mean, std)[0] > corrections(w, b, xb[None, :], scale, mean, std)[0])
            val_acc = val_correct / len(val_pairs) if val_pairs else float("nan")
            rehe_mean_abs = float(np.mean(np.abs(corrections(w, b, rehearsal, scale, mean, std))))
            train_correct = sum(
                int(corrections(w, b, xp[None, :], scale, mean, std)[0] > corrections(w, b, xb[None, :], scale, mean, std)[0])
                for xp, xb in train_pairs
            )
            train_acc = train_correct / len(train_pairs) if train_pairs else float("nan")
            grid[f"lam{lam}_scale{scale}"] = {"val_acc": val_acc, "train_acc": train_acc, "rehearsal_mean_abs": rehe_mean_abs}
            print(f"lam={lam} scale={scale} val_acc={val_acc:.3f} train_acc={train_acc:.3f} rehe_mean_abs={rehe_mean_abs:.4f}")
            if best is None or (not math.isnan(val_acc) and val_acc > best["val_acc"]):
                best = {"lam": lam, "scale": scale, "w": w, "b": b, "mean": mean, "std": std, "val_acc": val_acc}

    np.savez(
        args.output,
        w=best["w"].astype(np.float32),
        b=np.float32(best["b"]),
        scale=np.float32(best["scale"]),
        dim=np.int64(dim),
        mean=best["mean"].astype(np.float32),
        std=best["std"].astype(np.float32),
    )
    print("saved:", args.output, "scale", best["scale"], "val_acc", best["val_acc"])

    report = {
        "preferences": len(preferences),
        "train_prefs": len(train_prefs),
        "val_prefs": len(val_prefs),
        "val_seeds": sorted(val_seeds),
        "dim": dim,
        "hyperparameter_grid": grid,
        "chosen": {"lam": best["lam"], "scale": best["scale"], "val_acc": best["val_acc"]},
        "preference_by_opponent": {op: sum(1 for p in preferences if p["state"]["opponent"] == op) for op in ("d842", "master_v1", "replay_refresh")},
        "states_total": len(states),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
