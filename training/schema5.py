#!/usr/bin/env python3
"""Train and export the schema-5 direct temporal-relational policy."""

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

from ptcg_ai.features import (
    ATTACK_LIMIT,
    CARD_LIMIT,
    ENTITY_NUMERIC_SIZE,
    ENTITY_ZONE_COUNT,
    EVENT_HISTORY_LENGTH,
    EVENT_NUMERIC_SIZE,
    V4_OPTION_NUMERIC_SIZE,
    V5_GLOBAL_SIZE,
    V2_COUNT_CLASSES,
)
from training.train_bc import iter_batches, masked_count_loss, move, policy_loss

MODEL_DIM = 96
DECISION_FAMILIES = 6


def decision_family(context: torch.Tensor) -> torch.Tensor:
    result = torch.full_like(context, 5)
    result = torch.where(context == 0, 0, result)
    for value in (7, 8, 9, 10, 11, 12, 24, 34, 38):
        result = torch.where(context == value, 1, result)
    for value in (18, 19, 20, 21, 22, 23, 26, 28, 30, 31, 32, 33, 37):
        result = torch.where(context == value, 2, result)
    for value in (3, 4, 5, 6, 25, 35, 36):
        result = torch.where(context == value, 3, result)
    for value in (13, 14, 15, 16, 17, 39, 40):
        result = torch.where(context == value, 4, result)
    return result


class DirectPolicyNet(nn.Module):
    """Fast direct policy with explicit board entities and causal event history."""

    def __init__(self) -> None:
        super().__init__()
        self.entity_card = nn.Embedding(CARD_LIMIT, 32)
        self.entity_zone = nn.Embedding(ENTITY_ZONE_COUNT, 12)
        self.entity_owner = nn.Embedding(3, 4)
        self.entity_slot = nn.Embedding(128, 8)
        self.entity_type = nn.Embedding(8, 8)
        self.entity_numeric = nn.Linear(ENTITY_NUMERIC_SIZE, 32)
        self.entity_input = nn.Linear(96, MODEL_DIM)
        self.entity_hidden = nn.Linear(MODEL_DIM, MODEL_DIM)

        self.event_context = nn.Embedding(64, 12)
        self.event_type = nn.Embedding(18, 8)
        self.event_source = nn.Embedding(CARD_LIMIT, 24)
        self.event_target = nn.Embedding(CARD_LIMIT, 24)
        self.event_attack = nn.Embedding(ATTACK_LIMIT, 12)
        self.event_serial = nn.Embedding(128, 8)
        self.event_position = nn.Embedding(EVENT_HISTORY_LENGTH, 8)
        self.event_numeric = nn.Linear(EVENT_NUMERIC_SIZE, 24)
        self.event_input = nn.Linear(128, MODEL_DIM)
        self.event_gru = nn.GRU(MODEL_DIM, MODEL_DIM, batch_first=True)

        self.option_type = nn.Embedding(18, 8)
        self.option_context = nn.Embedding(64, 12)
        self.option_source = nn.Embedding(CARD_LIMIT, 32)
        self.option_target = nn.Embedding(CARD_LIMIT, 32)
        self.option_attack = nn.Embedding(ATTACK_LIMIT, 16)
        self.option_area = nn.Embedding(16, 8)
        self.option_numeric = nn.Linear(V4_OPTION_NUMERIC_SIZE, 32)
        self.option_input = nn.Linear(148, MODEL_DIM)

        self.global_input = nn.Linear(V5_GLOBAL_SIZE, 64)
        self.order_embedding = nn.Embedding(2, 16)
        self.joint1 = nn.Linear(656, 256)
        self.joint2 = nn.Linear(256, 128)
        self.score_heads = nn.Linear(128, DECISION_FAMILIES)
        self.count_context = nn.Embedding(64, 12)
        self.count1 = nn.Linear(380, 128)
        self.count = nn.Linear(128, V2_COUNT_CLASSES)

    def encode_entities(self, batch: dict) -> tuple[torch.Tensor, torch.Tensor]:
        value = torch.cat([
            self.entity_card(batch["entity_card"].clamp(0, CARD_LIMIT - 1)),
            self.entity_zone(batch["entity_zone"].clamp(0, ENTITY_ZONE_COUNT - 1)),
            self.entity_owner(batch["entity_owner"].clamp(0, 2)),
            self.entity_slot(batch["entity_slot"].clamp(0, 127)),
            self.entity_type(batch["entity_type"].clamp(0, 7)),
            F.relu(self.entity_numeric(batch["entity_numeric"])),
        ], dim=-1)
        value = F.relu(self.entity_input(value))
        value = F.relu(self.entity_hidden(value)) * batch["entity_mask"].unsqueeze(-1)
        mask = batch["entity_mask"].unsqueeze(-1)
        mean = value.sum(dim=1) / mask.sum(dim=1).clamp_min(1)
        maximum = value.masked_fill(~mask, -1e9).max(dim=1).values
        maximum = torch.where(batch["entity_mask"].any(dim=1, keepdim=True), maximum, torch.zeros_like(maximum))
        return value, torch.cat([mean, maximum], dim=-1)

    def encode_events(self, batch: dict) -> torch.Tensor:
        value = torch.cat([
            self.event_context(batch["event_context"].clamp(0, 63)),
            self.event_type(batch["event_type"].clamp(0, 17)),
            self.event_source(batch["event_source"].clamp(0, CARD_LIMIT - 1)),
            self.event_target(batch["event_target"].clamp(0, CARD_LIMIT - 1)),
            self.event_attack(batch["event_attack"].clamp(0, ATTACK_LIMIT - 1)),
            self.event_serial(batch["event_source_serial"].clamp(0, 127)),
            self.event_serial(batch["event_target_serial"].clamp(0, 127)),
            self.event_position(batch["event_position"].clamp(0, EVENT_HISTORY_LENGTH - 1)),
            F.relu(self.event_numeric(batch["event_numeric"])),
        ], dim=-1)
        value = F.relu(self.event_input(value)) * batch["event_mask"].unsqueeze(-1)
        sequence, _ = self.event_gru(value)
        lengths = batch["event_mask"].sum(dim=1)
        rows = torch.arange(len(lengths), device=value.device)
        last = sequence[rows, (lengths - 1).clamp_min(0)]
        return torch.where(lengths.unsqueeze(1) > 0, last, torch.zeros_like(last))

    @staticmethod
    def linked(entities: torch.Tensor, records: torch.Tensor, indices: torch.Tensor) -> torch.Tensor:
        valid = indices >= 0
        selected = entities[records, indices.clamp(0, entities.shape[1] - 1)]
        return selected * valid.unsqueeze(-1)

    def forward(self, batch: dict) -> tuple[torch.Tensor, torch.Tensor]:
        entities, board = self.encode_entities(batch)
        history = self.encode_events(batch)
        global_vector = F.relu(self.global_input(batch["global"]))
        order = (batch["global"][:, 3] >= 0.5).long()
        order_vector = self.order_embedding(order)

        options = F.relu(self.option_input(torch.cat([
            self.option_type(batch["type"].clamp(0, 17)),
            self.option_context(batch["context"].clamp(0, 63)),
            self.option_source(batch["source"].clamp(0, CARD_LIMIT - 1)),
            self.option_target(batch["target"].clamp(0, CARD_LIMIT - 1)),
            self.option_attack(batch["attack"].clamp(0, ATTACK_LIMIT - 1)),
            self.option_area(batch["area"].clamp(0, 15)),
            self.option_area(batch["in_area"].clamp(0, 15)),
            F.relu(self.option_numeric(batch["numeric"])),
        ], dim=-1)))
        records = batch["option_record"]
        source = self.linked(entities, records, batch["source_entity"])
        target = self.linked(entities, records, batch["target_entity"])
        joint = torch.cat([
            options, source, target, board[records], history[records],
            global_vector[records], order_vector[records],
        ], dim=-1)
        hidden = F.relu(self.joint2(F.relu(self.joint1(joint))))
        scores = self.score_heads(hidden)
        families = decision_family(batch["context"]).unsqueeze(1)
        logits = scores.gather(1, families).squeeze(1)

        starts = torch.tensor([start for start, _ in batch["record_options"]], device=logits.device)
        record_context = batch["context"][starts]
        count_input = torch.cat([
            board, history, global_vector, order_vector,
            self.count_context(record_context.clamp(0, 63)),
        ], dim=-1)
        return logits, self.count(F.relu(self.count1(count_input)))


def export_direct(model: DirectPolicyNet, path: str | Path) -> Path:
    arrays: dict[str, np.ndarray] = {
        "model_schema_version": np.asarray(5, dtype=np.int16),
        "direct_model_version": np.asarray(1, dtype=np.int16),
    }
    for name, value in model.state_dict().items():
        arrays[f"d__{name.replace('.', '__')}"] = value.detach().cpu().numpy().astype(np.float16)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(destination, **arrays)
    return destination


def load_direct(model: DirectPolicyNet, path: str | Path) -> None:
    arrays = np.load(path, allow_pickle=False)
    if int(np.asarray(arrays["model_schema_version"]).item()) != 5:
        raise ValueError("direct model is not schema 5")
    state = model.state_dict()
    for name in state:
        key = f"d__{name.replace('.', '__')}"
        if key not in arrays:
            raise ValueError(f"missing direct weight: {key}")
        state[name].copy_(torch.as_tensor(arrays[key], dtype=state[name].dtype))
    model.load_state_dict(state)


def greedy_complete_actions(logits: torch.Tensor, counts: torch.Tensor, batch: dict) -> list[list[int]]:
    result = []
    for record_index, (start, end) in enumerate(batch["record_options"]):
        minimum = int(round(float(batch["global"][record_index, 28]) * 9))
        maximum = int(round(float(batch["global"][record_index, 29]) * 9))
        maximum = max(minimum, min(maximum, counts.shape[1] - 1, end - start))
        desired = minimum + int(torch.argmax(counts[record_index, minimum:maximum + 1]).item())
        ranked = torch.argsort(logits[start:end], descending=True, stable=True).tolist()
        result.append([int(index) for index in ranked[:desired]])
    return result


def _complete_log_probability(logits, count_logits, action, minimum, maximum):
    available = list(range(len(logits)))
    terms = []
    for selected in action:
        if selected not in available:
            return logits.new_tensor(-1e6)
        terms.append(logits[selected] - torch.logsumexp(logits[available], dim=0))
        available.remove(selected)
    valid_counts = count_logits[minimum:maximum + 1]
    count_index = len(action) - minimum
    if not 0 <= count_index < len(valid_counts):
        return logits.new_tensor(-1e6)
    terms.append(valid_counts[count_index] - torch.logsumexp(valid_counts, dim=0))
    return torch.stack(terms).sum()


def pairwise_preference_loss(logits, counts, batch, margin=0.10):
    """Rank certified complete actions without introducing a scalar value policy."""
    losses, weights = [], []
    for record_index, rejected in enumerate(batch.get("record_rejected_actions", [])):
        if rejected is None:
            continue
        start, end = batch["record_options"][record_index]
        minimum = int(round(float(batch["global"][record_index, 28]) * 9))
        maximum = int(round(float(batch["global"][record_index, 29]) * 9))
        maximum = max(minimum, min(maximum, counts.shape[1] - 1, end - start))
        preferred_score = _complete_log_probability(
            logits[start:end], counts[record_index], batch["record_actions"][record_index], minimum, maximum
        )
        rejected_score = _complete_log_probability(
            logits[start:end], counts[record_index], rejected, minimum, maximum
        )
        losses.append(F.softplus(-(preferred_score - rejected_score - margin)))
        weights.append(batch["weights"][record_index])
    if not losses:
        return logits.sum() * 0.0
    stacked, weight = torch.stack(losses), torch.stack(weights)
    return (stacked * weight).sum() / weight.sum().clamp_min(1e-6)


@torch.no_grad()
def evaluate_direct(model, paths, batch_size, device, max_records=20_000) -> dict:
    model.eval()
    records = exact = singles = single_correct = batches = 0
    running = 0.0
    by_context: dict[str, dict[str, int]] = {}
    for batch in iter_batches(paths, batch_size, max_records=max_records, validation=True, feature_version=5):
        records += len(batch["record_options"])
        batch = move(batch, device)
        logits, counts = model(batch)
        option_loss, correct, total = policy_loss(logits, batch)
        loss = option_loss + 0.25 * masked_count_loss(counts, batch)
        running += float(loss)
        batches += 1
        single_correct += correct
        singles += total
        predicted = greedy_complete_actions(logits, counts, batch)
        for index, (actual, candidate) in enumerate(zip(batch["record_actions"], predicted)):
            is_exact = int(actual == candidate)
            exact += is_exact
            start, _ = batch["record_options"][index]
            context = str(int(batch["context"][start]))
            values = by_context.setdefault(context, {"records": 0, "exact": 0})
            values["records"] += 1
            values["exact"] += is_exact
    return {
        "records": records,
        "loss": running / max(1, batches),
        "complete_agreement": exact / max(1, records),
        "single_top1": single_correct / max(1, singles),
        "by_context": {
            context: {**values, "agreement": values["exact"] / max(1, values["records"])}
            for context, values in sorted(by_context.items(), key=lambda item: int(item[0]))
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shards", nargs="+")
    parser.add_argument("--validation", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--seed", type=int, default=20260808)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--initial-model")
    parser.add_argument("--checkpoint-metric", choices=("loss", "agreement"), default="agreement")
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = DirectPolicyNet().to(device)
    if args.initial_model:
        load_direct(model, args.initial_model)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-5)
    paths = [Path(path) for path in args.shards]
    validation_paths = [Path(path) for path in args.validation]
    best = None
    best_loss = float("inf")
    best_agreement = float("-inf")
    selected_epoch = 0
    history = []
    for epoch in range(args.epochs):
        model.train()
        running = batches = 0
        for batch in iter_batches(
            paths, args.batch_size, max_records=args.max_records,
            validation=False, feature_version=5,
        ):
            batch = move(batch, device)
            logits, counts = model(batch)
            option_loss, _, _ = policy_loss(logits, batch)
            loss = option_loss + 0.25 * masked_count_loss(counts, batch)
            loss += 0.50 * pairwise_preference_loss(logits, counts, batch)
            if not torch.isfinite(loss):
                raise FloatingPointError("non-finite schema-5 direct-policy loss")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            running += float(loss.detach())
            batches += 1
        metrics = evaluate_direct(model, validation_paths, args.batch_size, device)
        if metrics["records"] <= 0:
            raise RuntimeError("schema-5 validation stream produced zero records")
        metrics.update({"epoch": epoch + 1, "training_loss": running / max(1, batches)})
        history.append(metrics)
        improved = (
            metrics["loss"] < best_loss
            if args.checkpoint_metric == "loss"
            else metrics["complete_agreement"] > best_agreement
        )
        if improved:
            best_loss = metrics["loss"]
            best_agreement = metrics["complete_agreement"]
            selected_epoch = epoch + 1
            best = copy.deepcopy(model.state_dict())
    if best is None:
        raise RuntimeError("schema-5 training produced no matching batches")
    model.load_state_dict(best)
    output = export_direct(model, args.output)
    manifest = {
        "status": "complete",
        "schema_version": 5,
        "direct_model_version": 1,
        "seed": args.seed,
        "output": str(output.resolve()),
        "training_streams": [str(path.resolve()) for path in paths],
        "validation_streams": [str(path.resolve()) for path in validation_paths],
        "checkpoint_metric": args.checkpoint_metric,
        "selected_epoch": selected_epoch,
        "selected_validation_loss": best_loss,
        "selected_complete_agreement": best_agreement,
        "history": history,
    }
    manifest_path = Path(args.manifest) if args.manifest else output.with_suffix(".json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
