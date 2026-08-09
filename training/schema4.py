#!/usr/bin/env python3
"""Schema-4 slot-aware residual policy training and export.

The historical A2 network is frozen and evaluated on its exact schema-2 view.
The relational branch sees schema 4 and is initialized to emit zero residuals,
so an untrained artifact is behaviorally identical to A2.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from ptcg_ai.features import (
    ATTACK_LIMIT,
    CARD_LIMIT,
    ENTITY_NUMERIC_SIZE,
    ENTITY_ZONE_COUNT,
    V2_COUNT_CLASSES,
    V4_GLOBAL_SIZE,
    V4_OPTION_NUMERIC_SIZE,
)
from training.train_bc import (
    PolicyNet,
    iter_batches,
    load_npz_weights,
    masked_count_loss,
    move,
    policy_loss,
)

MODEL_DIM = 128
HEADS = 4
HEAD_DIM = MODEL_DIM // HEADS


class SetAttentionBlock(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.qkv = nn.Linear(MODEL_DIM, MODEL_DIM * 3)
        self.out = nn.Linear(MODEL_DIM, MODEL_DIM)
        self.norm1 = nn.LayerNorm(MODEL_DIM)
        self.ff1 = nn.Linear(MODEL_DIM, 256)
        self.ff2 = nn.Linear(256, MODEL_DIM)
        self.norm2 = nn.LayerNorm(MODEL_DIM)

    def forward(self, value: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        batch, count, _ = value.shape
        qkv = self.qkv(value).reshape(batch, count, 3, HEADS, HEAD_DIM)
        q, k, v = qkv.permute(2, 0, 3, 1, 4).unbind(0)
        scores = torch.matmul(q, k.transpose(-1, -2)) / math.sqrt(HEAD_DIM)
        scores = scores.masked_fill(~mask[:, None, None, :], -1e9)
        attention = torch.softmax(scores, dim=-1)
        context = torch.matmul(attention, v).transpose(1, 2).reshape(batch, count, MODEL_DIM)
        value = self.norm1(value + self.out(context))
        value = self.norm2(value + self.ff2(F.relu(self.ff1(value))))
        return value * mask.unsqueeze(-1)


class RelationalResidualNet(nn.Module):
    def __init__(self, mode: str = "r1") -> None:
        super().__init__()
        if mode not in {"r0", "r1"}:
            raise ValueError(f"unsupported residual mode: {mode}")
        self.mode = mode
        self.entity_card = nn.Embedding(CARD_LIMIT, 32)
        self.entity_zone = nn.Embedding(ENTITY_ZONE_COUNT, 16)
        self.entity_owner = nn.Embedding(3, 8)
        self.entity_slot = nn.Embedding(128, 16)
        self.entity_type = nn.Embedding(8, 8)
        self.entity_numeric = nn.Linear(ENTITY_NUMERIC_SIZE, 48)
        self.entity_input = nn.Linear(128, MODEL_DIM)
        self.set_blocks = nn.ModuleList([SetAttentionBlock(), SetAttentionBlock()])

        self.option_type = nn.Embedding(18, 16)
        self.option_card = nn.Embedding(CARD_LIMIT, 32)
        self.option_target = nn.Embedding(CARD_LIMIT, 32)
        self.option_attack = nn.Embedding(ATTACK_LIMIT, 16)
        self.option_context = nn.Embedding(64, 16)
        self.option_area = nn.Embedding(16, 8)
        self.option_numeric = nn.Linear(V4_OPTION_NUMERIC_SIZE, 48)
        self.option_input = nn.Linear(176, MODEL_DIM)

        self.cross_q = nn.Linear(MODEL_DIM, MODEL_DIM)
        self.cross_k = nn.Linear(MODEL_DIM, MODEL_DIM)
        self.cross_v = nn.Linear(MODEL_DIM, MODEL_DIM)
        self.cross_out = nn.Linear(MODEL_DIM, MODEL_DIM)
        self.joint1 = nn.Linear(MODEL_DIM * 4, 256)
        self.score = nn.Linear(256, 1)

        self.pool1 = nn.Linear(MODEL_DIM * 2 + V4_GLOBAL_SIZE, 256)
        self.count = nn.Linear(256, V2_COUNT_CLASSES)
        self.value = nn.Linear(256, 1)
        self.reset_residual_outputs()

    def reset_residual_outputs(self) -> None:
        nn.init.zeros_(self.score.weight)
        nn.init.zeros_(self.score.bias)
        nn.init.zeros_(self.count.weight)
        nn.init.zeros_(self.count.bias)

    def encode_entities(self, batch: dict) -> torch.Tensor:
        pieces = [
            self.entity_card(batch["entity_card"]),
            self.entity_zone(batch["entity_zone"].clamp(0, ENTITY_ZONE_COUNT - 1)),
            self.entity_owner(batch["entity_owner"].clamp(0, 2)),
            self.entity_slot(batch["entity_slot"].clamp(0, 127)),
            self.entity_type(batch["entity_type"].clamp(0, 7)),
            F.relu(self.entity_numeric(batch["entity_numeric"])),
        ]
        value = F.relu(self.entity_input(torch.cat(pieces, dim=-1)))
        value = value * batch["entity_mask"].unsqueeze(-1)
        for block in self.set_blocks:
            value = block(value, batch["entity_mask"])
        return value

    def encode_options(self, batch: dict) -> torch.Tensor:
        pieces = [
            self.option_type(batch["type"].clamp(0, 17)),
            self.option_card(batch["source"].clamp(0, CARD_LIMIT - 1)),
            self.option_target(batch["target"].clamp(0, CARD_LIMIT - 1)),
            self.option_attack(batch["attack"].clamp(0, ATTACK_LIMIT - 1)),
            self.option_context(batch["context"].clamp(0, 63)),
            self.option_area(batch["area"].clamp(0, 15)),
            self.option_area(batch["in_area"].clamp(0, 15)),
            F.relu(self.option_numeric(batch["numeric"])),
        ]
        return F.relu(self.option_input(torch.cat(pieces, dim=-1)))

    @staticmethod
    def _linked(entities: torch.Tensor, records: torch.Tensor, indices: torch.Tensor) -> torch.Tensor:
        valid = indices >= 0
        selected = entities[records, indices.clamp(0, entities.shape[1] - 1)]
        return selected * valid.unsqueeze(-1)

    def forward(self, batch: dict) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        entities = self.encode_entities(batch)
        options = self.encode_options(batch)
        records = batch["option_record"]
        option_entities = entities[records]
        option_mask = batch["entity_mask"][records]

        q = self.cross_q(options).reshape(-1, HEADS, HEAD_DIM)
        k = self.cross_k(option_entities).reshape(
            option_entities.shape[0], option_entities.shape[1], HEADS, HEAD_DIM
        ).permute(0, 2, 1, 3)
        v = self.cross_v(option_entities).reshape(
            option_entities.shape[0], option_entities.shape[1], HEADS, HEAD_DIM
        ).permute(0, 2, 1, 3)
        scores = torch.einsum("ohd,ohed->ohe", q, k) / math.sqrt(HEAD_DIM)
        scores = scores.masked_fill(~option_mask[:, None, :], -1e9)
        attention = torch.softmax(scores, dim=-1)
        cross = torch.einsum("ohe,ohed->ohd", attention, v).reshape(-1, MODEL_DIM)
        cross = self.cross_out(cross)

        source = self._linked(entities, records, batch["source_entity"])
        target = self._linked(entities, records, batch["target_entity"])
        joint = F.relu(self.joint1(torch.cat([options, source, target, cross], dim=-1)))
        residual_logits = self.score(joint).squeeze(-1)

        mask = batch["entity_mask"].unsqueeze(-1)
        total = (entities * mask).sum(dim=1)
        denominator = mask.sum(dim=1).clamp_min(1)
        mean = total / denominator
        maximum = entities.masked_fill(~mask, -1e9).max(dim=1).values
        maximum = torch.where(batch["entity_mask"].any(dim=1, keepdim=True), maximum, torch.zeros_like(maximum))
        pooled = F.relu(self.pool1(torch.cat([mean, maximum, batch["global"]], dim=-1)))
        return residual_logits, self.count(pooled), self.value(pooled).squeeze(-1)


def legacy_a2_batch(batch: dict) -> dict:
    legacy = dict(batch)
    legacy["global"] = batch["global"][:, :118]
    legacy["numeric"] = batch["numeric"][:, :12]
    source = torch.where(batch["type"] == 3, batch["target"], batch["source"])
    legacy["source"] = torch.where(batch["type"] == 7, torch.zeros_like(source), source)
    legacy["feature_version"] = 2
    return legacy


def export_residual(model: RelationalResidualNet, path: str | Path, *, support_margin: float = 0.25) -> Path:
    arrays: dict[str, np.ndarray] = {
        "residual_schema_version": np.asarray(4, dtype=np.int16),
        "residual_mode": np.asarray(0 if model.mode == "r0" else 1, dtype=np.int16),
        "support_margin": np.asarray(support_margin, dtype=np.float32),
    }
    for name, value in model.state_dict().items():
        arrays[f"r__{name.replace('.', '__')}"] = value.detach().cpu().numpy().astype(np.float16)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(destination, **arrays)
    return destination


def load_residual(model: RelationalResidualNet, path: str | Path) -> None:
    arrays = np.load(path, allow_pickle=False)
    state = model.state_dict()
    for name in state:
        key = f"r__{name.replace('.', '__')}"
        if key not in arrays:
            raise ValueError(f"missing residual weight: {key}")
        state[name].copy_(torch.as_tensor(arrays[key], dtype=state[name].dtype))
    model.load_state_dict(state)


@torch.no_grad()
def evaluate_residual(model, base, paths, batch_size, device, max_records=10_000) -> dict:
    model.eval()
    records = correct = total = 0
    losses = []
    for batch in iter_batches(paths, batch_size, max_records=max_records, validation=True, feature_version=4):
        records += len(batch["record_options"])
        batch = move(batch, device)
        base_logits, base_count, _ = base(legacy_a2_batch(batch))
        residual_logits, residual_count, values = model(batch)
        logits, counts = base_logits + residual_logits, base_count + residual_count
        option_loss, batch_correct, batch_total = policy_loss(logits, batch)
        loss = option_loss + 0.25 * masked_count_loss(counts, batch)
        loss += 0.10 * F.binary_cross_entropy_with_logits(values, batch["values"])
        losses.append(float(loss))
        correct += batch_correct
        total += batch_total
    return {
        "records": records,
        "loss": sum(losses) / max(1, len(losses)),
        "single_top1": correct / max(1, total),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shards", nargs="+")
    parser.add_argument("--base", default="artifacts/recovery_probes/extracted/a2_base/policy_weights.npz")
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", choices=("r0", "r1"), default="r0")
    parser.add_argument("--seed", type=int, default=20260808)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--support-margin", type=float, default=0.25)
    parser.add_argument(
        "--checkpoint-metric", choices=("loss", "top1"), default="loss",
        help="Select the exported checkpoint by validation loss or action fidelity.",
    )
    parser.add_argument("--manifest")
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    base = PolicyNet(2).to(device).eval()
    load_npz_weights(base, args.base)
    for parameter in base.parameters():
        parameter.requires_grad_(False)
    model = RelationalResidualNet(args.mode).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-5)
    paths = [Path(path) for path in args.shards]
    best = None
    best_loss = float("inf")
    best_top1 = float("-inf")
    best_epoch = None
    history = []
    for epoch in range(args.epochs):
        model.train()
        running = batches = 0
        for batch in iter_batches(
            paths, args.batch_size, max_records=args.max_records,
            validation=False, feature_version=4,
        ):
            batch = move(batch, device)
            with torch.no_grad():
                base_logits, base_count, _ = base(legacy_a2_batch(batch))
            residual_logits, residual_count, values = model(batch)
            logits, counts = base_logits + residual_logits, base_count + residual_count
            option_loss, _, _ = policy_loss(logits, batch)
            count_loss = masked_count_loss(counts, batch)
            value_losses = F.binary_cross_entropy_with_logits(values, batch["values"], reduction="none")
            value_loss = (value_losses * batch["weights"]).sum() / batch["weights"].sum().clamp_min(1e-6)
            loss = option_loss + 0.25 * count_loss + 0.10 * value_loss
            if not torch.isfinite(loss):
                raise FloatingPointError("non-finite schema-4 training loss")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            running += float(loss.detach())
            batches += 1
        metrics = evaluate_residual(model, base, paths, args.batch_size, device)
        metrics.update({"epoch": epoch + 1, "training_loss": running / max(1, batches)})
        history.append(metrics)
        improved = (
            metrics["loss"] < best_loss
            if args.checkpoint_metric == "loss"
            else metrics["single_top1"] > best_top1
        )
        if improved:
            best_loss = metrics["loss"]
            best_top1 = metrics["single_top1"]
            best_epoch = epoch + 1
            best = copy.deepcopy(model.state_dict())
    if best is None:
        raise RuntimeError("schema-4 training produced no batches")
    model.load_state_dict(best)
    output = export_residual(model, args.output, support_margin=args.support_margin)
    manifest = {
        "status": "complete",
        "schema_version": 4,
        "mode": args.mode,
        "seed": args.seed,
        "base": str(Path(args.base).resolve()),
        "output": str(output.resolve()),
        "checkpoint_metric": args.checkpoint_metric,
        "selected_epoch": best_epoch,
        "selected_validation_loss": best_loss,
        "selected_validation_top1": best_top1,
        "history": history,
    }
    manifest_path = Path(args.manifest) if args.manifest else output.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
