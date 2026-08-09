#!/usr/bin/env python3
"""Train D1: an M0-initialized slot-relational schema-5 direct policy."""

from __future__ import annotations

import argparse
import copy
import json
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

from ptcg_ai.features import ATTACK_LIMIT, CARD_LIMIT, V4_OPTION_NUMERIC_SIZE
from training.schema5 import (
    DECISION_FAMILIES,
    DirectPolicyNet,
    decision_family,
    evaluate_direct,
    greedy_complete_actions,
    load_direct,
    pairwise_preference_loss,
)
from training.train_bc import iter_batches, masked_count_loss, move, policy_loss


MODEL_DIM = 96


class SetAttentionBlock(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.attention = nn.MultiheadAttention(MODEL_DIM, 4, batch_first=True)
        self.norm1 = nn.LayerNorm(MODEL_DIM)
        self.ff1 = nn.Linear(MODEL_DIM, 192)
        self.ff2 = nn.Linear(192, MODEL_DIM)
        self.norm2 = nn.LayerNorm(MODEL_DIM)

    def forward(self, value: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        attended, _ = self.attention(value, value, value, key_padding_mask=~mask, need_weights=False)
        value = self.norm1(value + attended)
        value = self.norm2(value + self.ff2(F.relu(self.ff1(value))))
        return value * mask.unsqueeze(-1)


class RelationalDirectPolicyNet(nn.Module):
    """D1 model: coherent M0 logits plus trainable slot-aware attention residual."""

    def __init__(self) -> None:
        super().__init__()
        self.base = DirectPolicyNet()
        self.entity_attention = nn.ModuleList([SetAttentionBlock(), SetAttentionBlock()])
        self.option_cross_attention = nn.MultiheadAttention(MODEL_DIM, 4, batch_first=True)
        self.cross_norm = nn.LayerNorm(MODEL_DIM)
        self.relational_joint1 = nn.Linear(752, 256)
        self.relational_joint2 = nn.Linear(256, 128)
        self.relational_score_heads = nn.Linear(128, DECISION_FAMILIES)
        self.relational_count1 = nn.Linear(380, 128)
        self.relational_count = nn.Linear(128, 61)
        # Exact behavior preservation at initialization; attention learns only once
        # gradients establish useful relational features.
        nn.init.zeros_(self.relational_score_heads.weight)
        nn.init.zeros_(self.relational_score_heads.bias)
        nn.init.zeros_(self.relational_count.weight)
        nn.init.zeros_(self.relational_count.bias)

    def _options(self, batch: dict) -> torch.Tensor:
        base = self.base
        return F.relu(base.option_input(torch.cat([
            base.option_type(batch["type"].clamp(0, 17)),
            base.option_context(batch["context"].clamp(0, 63)),
            base.option_source(batch["source"].clamp(0, CARD_LIMIT - 1)),
            base.option_target(batch["target"].clamp(0, CARD_LIMIT - 1)),
            base.option_attack(batch["attack"].clamp(0, ATTACK_LIMIT - 1)),
            base.option_area(batch["area"].clamp(0, 15)),
            base.option_area(batch["in_area"].clamp(0, 15)),
            F.relu(base.option_numeric(batch["numeric"])),
        ], dim=-1)))

    def forward(self, batch: dict) -> tuple[torch.Tensor, torch.Tensor]:
        base_logits, base_counts = self.base(batch)
        base = self.base
        entities, _ = base.encode_entities(batch)
        mask = batch["entity_mask"].clone()
        empty = ~mask.any(dim=1)
        if empty.any():
            mask[empty, 0] = True
            entities = entities.clone()
            entities[empty, 0] = 0
        for block in self.entity_attention:
            entities = block(entities, mask)
        entity_mask = mask.unsqueeze(-1)
        mean = entities.sum(dim=1) / entity_mask.sum(dim=1).clamp_min(1)
        maximum = entities.masked_fill(~entity_mask, -1e9).max(dim=1).values
        board = torch.cat([mean, maximum], dim=-1)
        history = base.encode_events(batch)
        global_vector = F.relu(base.global_input(batch["global"]))
        order = (batch["global"][:, 3] >= 0.5).long()
        order_vector = base.order_embedding(order)
        options = self._options(batch)
        records = batch["option_record"]
        source = base.linked(entities, records, batch["source_entity"])
        target = base.linked(entities, records, batch["target_entity"])
        keys = entities[records]
        key_mask = ~mask[records]
        attended, _ = self.option_cross_attention(
            options.unsqueeze(1), keys, keys, key_padding_mask=key_mask, need_weights=False
        )
        attended = self.cross_norm(options + attended.squeeze(1))
        joint = torch.cat([
            options, source, target, attended, board[records], history[records],
            global_vector[records], order_vector[records],
        ], dim=-1)
        hidden = F.relu(self.relational_joint2(F.relu(self.relational_joint1(joint))))
        families = decision_family(batch["context"]).unsqueeze(1)
        residual_logits = self.relational_score_heads(hidden).gather(1, families).squeeze(1)
        starts = torch.tensor([start for start, _ in batch["record_options"]], device=base_logits.device)
        record_context = batch["context"][starts]
        count_input = torch.cat([
            board, history, global_vector, order_vector,
            base.count_context(record_context.clamp(0, 63)),
        ], dim=-1)
        residual_counts = self.relational_count(F.relu(self.relational_count1(count_input)))
        return base_logits + residual_logits, base_counts + residual_counts


def export_relational(model: RelationalDirectPolicyNet, path: Path) -> Path:
    arrays = {
        "model_schema_version": np.asarray(5, np.int16),
        "direct_model_version": np.asarray(2, np.int16),
    }
    for name, value in model.state_dict().items():
        arrays[f"d2__{name.replace('.', '__')}"] = value.detach().cpu().numpy().astype(np.float16)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)
    return path


def load_relational(model: RelationalDirectPolicyNet, path: Path) -> int:
    arrays = np.load(path, allow_pickle=False)
    version = int(np.asarray(arrays["direct_model_version"]).item())
    if int(np.asarray(arrays["model_schema_version"]).item()) != 5:
        raise ValueError("D1 initialization is not schema 5")
    if version == 1:
        load_direct(model.base, path)
        return version
    if version != 2:
        raise ValueError(f"unsupported direct model version {version}")
    state = model.state_dict()
    for name in state:
        key = f"d2__{name.replace('.', '__')}"
        if key not in arrays:
            raise ValueError(f"missing D1 weight {key}")
        state[name].copy_(torch.as_tensor(arrays[key], dtype=state[name].dtype))
    model.load_state_dict(state)
    return version


@torch.no_grad()
def evaluate(model, paths, batch_size, device, max_records=20_000) -> dict:
    model.eval()
    records = exact = singles = single_correct = batches = 0
    loss_total = 0.0
    by_context: dict[str, dict[str, int]] = {}
    for batch in iter_batches(paths, batch_size, max_records=max_records, validation=True, feature_version=5):
        records += len(batch["record_options"])
        batch = move(batch, device)
        logits, counts = model(batch)
        option_loss, correct, total = policy_loss(logits, batch)
        loss = option_loss + .25 * masked_count_loss(counts, batch)
        loss_total += float(loss)
        batches += 1
        single_correct += correct
        singles += total
        for index, (truth, predicted) in enumerate(zip(batch["record_actions"], greedy_complete_actions(logits, counts, batch))):
            match = int(truth == predicted)
            exact += match
            start, _ = batch["record_options"][index]
            context = str(int(batch["context"][start]))
            cell = by_context.setdefault(context, {"records": 0, "exact": 0})
            cell["records"] += 1
            cell["exact"] += match
    return {
        "records": records,
        "loss": loss_total / max(1, batches),
        "complete_agreement": exact / max(1, records),
        "single_top1": single_correct / max(1, singles),
        "by_context": {
            key: {**value, "agreement": value["exact"] / max(1, value["records"])}
            for key, value in by_context.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shards", nargs="+")
    parser.add_argument("--validation", nargs="+", required=True)
    parser.add_argument("--initial-model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--seed", type=int, default=20260809)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=96)
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    args = parser.parse_args()
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = RelationalDirectPolicyNet().to(device)
    initial_version = load_relational(model, Path(args.initial_model))
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-5)
    train_paths, validation_paths = list(map(Path, args.shards)), list(map(Path, args.validation))
    best = None
    best_agreement = float("-inf")
    selected_epoch = 0
    history = []
    for epoch in range(args.epochs):
        model.train(); running = batches = 0
        for batch in iter_batches(train_paths, args.batch_size, max_records=args.max_records, validation=False, feature_version=5):
            batch = move(batch, device)
            logits, counts = model(batch)
            option_loss, _, _ = policy_loss(logits, batch)
            loss = option_loss + .25 * masked_count_loss(counts, batch)
            loss += .50 * pairwise_preference_loss(logits, counts, batch)
            if not torch.isfinite(loss):
                raise FloatingPointError("non-finite D1 loss")
            optimizer.zero_grad(set_to_none=True); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); optimizer.step()
            running += float(loss.detach()); batches += 1
        metrics = evaluate(model, validation_paths, args.batch_size, device)
        metrics.update({"epoch": epoch + 1, "training_loss": running / max(1, batches)})
        history.append(metrics)
        if metrics["complete_agreement"] > best_agreement:
            best_agreement = metrics["complete_agreement"]
            selected_epoch = epoch + 1
            best = copy.deepcopy(model.state_dict())
    if best is None:
        raise RuntimeError("D1 training produced no batches")
    model.load_state_dict(best)
    output = export_relational(model, Path(args.output))
    result = {
        "status": "complete", "schema_version": 5, "direct_model_version": 2,
        "initial_model": str(Path(args.initial_model).resolve()), "initial_model_version": initial_version,
        "seed": args.seed, "selected_epoch": selected_epoch,
        "selected_complete_agreement": best_agreement, "history": history,
        "output": str(output.resolve()),
    }
    manifest = Path(args.manifest) if args.manifest else output.with_suffix(".json")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
