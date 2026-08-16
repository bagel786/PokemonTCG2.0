#!/usr/bin/env python3
"""Train the compact option-ranking policy from extracted replay shards."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import random
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from ptcg_ai.features import (
    ATTACK_LIMIT,
    CARD_LIMIT,
    MAX_SELECT_COUNT,
    OPTION_NUMERIC_SIZE,
    ENTITY_NUMERIC_SIZE,
    EVENT_HISTORY_LENGTH,
    EVENT_NUMERIC_SIZE,
    V3_OPTION_NUMERIC_SIZE,
    V4_GLOBAL_SIZE,
    V4_OPTION_NUMERIC_SIZE,
    V5_GLOBAL_SIZE,
    V1_GLOBAL_SIZE,
    V1_ZONE_COUNT,
    V2_GLOBAL_SIZE,
    V2_COUNT_CLASSES,
    V2_ZONE_COUNT,
)


def split_bucket(episode_id) -> int:
    return zlib.crc32(str(episode_id).encode("utf-8")) % 10


def replay_split(row: dict) -> str:
    """Return an explicit audited split when present, else the legacy hash split."""
    explicit = row.get("split")
    if explicit is not None:
        if explicit not in {
            "train", "validation", "holdout", "unseen_team", "temporal",
            "team_holdout", "temporal_holdout", "policy_holdout",
            "policy_identity_holdout",
        }:
            raise ValueError(f"invalid replay split {explicit!r}")
        return explicit
    return "validation" if split_bucket(row.get("episode_id", "")) == 0 else "train"


def iter_rows(paths, shuffle_files=True, required_card=0, validation=False, feature_version=0, team_weights=None, deck_weights=None, deck_default_weight=1.0):
    paths = list(paths)
    if shuffle_files:
        random.shuffle(paths)
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if required_card and required_card not in row.get("deck", []):
                    continue
                row_version = int(row.get("features", {}).get("feature_version", 1))
                if feature_version and row_version != feature_version:
                    continue
                split = replay_split(row)
                selected = split != "train" if validation else split == "train"
                if selected:
                    configured = float((team_weights or {}).get(row.get("team"), 1.0))
                    deck_hash = row.get("deck_hash")
                    if deck_hash is not None and (deck_weights or deck_default_weight != 1.0):
                        configured *= float((deck_weights or {}).get(deck_hash, deck_default_weight))
                    row["sample_weight"] = 1.0 if validation else float(row.get("sample_weight", 1.0)) * configured
                    yield row


def iter_batches(paths, batch_size, max_records=0, required_card=0, validation=False, feature_version=0, team_weights=None, deck_weights=None, deck_default_weight=1.0, shuffle_buffer=20_000):
    batch = []
    seen = 0
    source = iter_rows(
        paths,
        shuffle_files=not validation,
        required_card=required_card,
        validation=validation,
        feature_version=feature_version,
        team_weights=team_weights,
        deck_weights=deck_weights,
        deck_default_weight=deck_default_weight,
    )

    def shuffled_rows():
        if validation:
            yield from source
            return
        buffer = []
        for row in source:
            buffer.append(row)
            if len(buffer) >= shuffle_buffer:
                random.shuffle(buffer)
                yield from buffer
                buffer = []
        random.shuffle(buffer)
        yield from buffer

    for row in shuffled_rows():
        batch.append(row)
        seen += 1
        if len(batch) == batch_size:
            yield collate(batch)
            batch = []
        if max_records and seen >= max_records:
            break
    if batch:
        yield collate(batch)


def collate(rows):
    globals_ = []
    token_values = []
    token_offsets = []
    options = {key: [] for key in ("type", "context", "source", "target", "attack", "area", "in_area", "numeric")}
    option_record = []
    option_selected = []
    counts = []
    values = []
    weights = []
    record_grimmsnarl = []
    record_starmie = []
    record_dipplin = []
    record_alakazam = []
    record_reward = []
    record_options = []
    record_actions = []
    record_rejected_actions = []
    feature_versions = set()
    entity_rows = []
    event_rows = []
    for record_index, row in enumerate(rows):
        features = row["features"]
        feature_versions.add(int(features.get("feature_version", 1)))
        globals_.append(features["global"])
        entity_rows.append(features.get("entities", []))
        event_rows.append(features.get("events", []))
        token_offsets.append(len(token_values))
        feature_tokens = features["tokens"]
        token_values.extend(feature_tokens if len(feature_tokens) else [0])
        selected = set(row["action"])
        start = len(option_record)
        for option_index, option in enumerate(features["options"]):
            options["type"].append(option["option_type"])
            options["context"].append(min(option["context"], 63))
            options["source"].append(option["source_card"])
            options["target"].append(option["target_card"])
            options["attack"].append(option["attack_id"])
            options["area"].append(min(option["area"], 15))
            options["in_area"].append(min(option["in_play_area"], 15))
            options["numeric"].append(option["numeric"])
            option_record.append(record_index)
            option_selected.append(float(option_index in selected))
        record_options.append((start, len(option_record)))
        counts.append(len(row["action"]))
        values.append(float(row["reward"] > 0))
        weights.append(float(row.get("sample_weight", 1.0)))
        record_grimmsnarl.append(bool(row.get("opponent_grimmsnarl", False)))
        record_starmie.append(bool(row.get("opponent_starmie", False)))
        record_dipplin.append(bool(row.get("opponent_dipplin", False)))
        record_alakazam.append(bool(row.get("opponent_alakazam", False)))
        record_reward.append(float(row.get("reward", 0.0)))
        record_actions.append([int(index) for index in row["action"]])
        rejected = row.get("rejected_action")
        record_rejected_actions.append(
            [int(index) for index in rejected] if isinstance(rejected, list) else None
        )
    if len(feature_versions) != 1:
        raise ValueError(f"a batch cannot mix feature schemas: {sorted(feature_versions)}")
    record_action_groups = [
        row.get("action_groups") if isinstance(row.get("action_groups"), list) else None
        for row in rows
    ]
    feature_version = next(iter(feature_versions))
    count_maximum = V2_COUNT_CLASSES - 1 if feature_version >= 2 else MAX_SELECT_COUNT - 1
    counts = [min(count_maximum, value) for value in counts]
    long = lambda value: torch.tensor(value, dtype=torch.long)
    # ``order_ppo`` keeps large audited rollout matrices as compact NumPy
    # arrays.  Normalizing rectangular floating inputs here avoids the very
    # slow list-of-arrays conversion path while preserving ordinary list input.
    floating = lambda value: torch.as_tensor(np.asarray(value), dtype=torch.float32)
    maximum_entities = max(1, max((len(row) for row in entity_rows), default=0))
    entity_card = []
    entity_serial = []
    entity_owner = []
    entity_zone = []
    entity_slot = []
    entity_type = []
    entity_numeric = []
    entity_mask = []
    for row in entity_rows:
        padded = list(row) + [None] * (maximum_entities - len(row))
        entity_card.append([int(item["card_id"]) if item else 0 for item in padded])
        entity_serial.append([int(item["serial"]) if item else 0 for item in padded])
        entity_owner.append([int(item["owner"]) if item else 0 for item in padded])
        entity_zone.append([int(item["zone"]) if item else 0 for item in padded])
        entity_slot.append([int(item["slot"]) if item else 0 for item in padded])
        entity_type.append([int(item["entity_type"]) if item else 0 for item in padded])
        entity_numeric.append([
            list(item["numeric"]) if item else [0.0] * ENTITY_NUMERIC_SIZE for item in padded
        ])
        entity_mask.append([bool(item) for item in padded])
    source_entity = []
    target_entity = []
    for row in rows:
        for option in row["features"]["options"]:
            source_entity.append(int(option.get("source_entity", -1)))
            target_entity.append(int(option.get("target_entity", -1)))
    event_context = []
    event_type = []
    event_source = []
    event_source_serial = []
    event_target = []
    event_target_serial = []
    event_attack = []
    event_position = []
    event_numeric = []
    event_mask = []
    for row in event_rows:
        clipped = list(row)[-EVENT_HISTORY_LENGTH:]
        padded = clipped + [None] * (EVENT_HISTORY_LENGTH - len(clipped))
        event_context.append([int(item.get("context", 0)) if item else 0 for item in padded])
        event_type.append([int(item.get("option_type", 0)) if item else 0 for item in padded])
        event_source.append([int(item.get("source_card", 0)) if item else 0 for item in padded])
        event_source_serial.append([int(item.get("source_serial", 0)) if item else 0 for item in padded])
        event_target.append([int(item.get("target_card", 0)) if item else 0 for item in padded])
        event_target_serial.append([int(item.get("target_serial", 0)) if item else 0 for item in padded])
        event_attack.append([int(item.get("attack_id", 0)) if item else 0 for item in padded])
        event_position.append([int(item.get("position", index)) if item else index for index, item in enumerate(padded)])
        event_numeric.append([
            (list(item.get("numeric", [])) + [0.0] * EVENT_NUMERIC_SIZE)[:EVENT_NUMERIC_SIZE]
            if item else [0.0] * EVENT_NUMERIC_SIZE
            for item in padded
        ])
        event_mask.append([bool(item) for item in padded])
    return {
        "global": floating(globals_),
        "tokens": long(token_values),
        "offsets": long(token_offsets),
        "type": long(options["type"]),
        "context": long(options["context"]),
        "source": long(options["source"]),
        "target": long(options["target"]),
        "attack": long(options["attack"]),
        "area": long(options["area"]),
        "in_area": long(options["in_area"]),
        "numeric": floating(options["numeric"]),
        "source_entity": long(source_entity),
        "target_entity": long(target_entity),
        "entity_card": long(entity_card),
        "entity_serial": long(entity_serial),
        "entity_owner": long(entity_owner),
        "entity_zone": long(entity_zone),
        "entity_slot": long(entity_slot),
        "entity_type": long(entity_type),
        "entity_numeric": floating(entity_numeric),
        "entity_mask": torch.tensor(entity_mask, dtype=torch.bool),
        "event_context": long(event_context),
        "event_type": long(event_type),
        "event_source": long(event_source),
        "event_source_serial": long(event_source_serial),
        "event_target": long(event_target),
        "event_target_serial": long(event_target_serial),
        "event_attack": long(event_attack),
        "event_position": long(event_position),
        "event_numeric": floating(event_numeric),
        "event_mask": torch.tensor(event_mask, dtype=torch.bool),
        "option_record": long(option_record),
        "selected": floating(option_selected),
        "counts": long(counts),
        "values": floating(values),
        "weights": floating(weights),
        "record_grimmsnarl": record_grimmsnarl,
        "record_starmie": record_starmie,
        "record_dipplin": record_dipplin,
        "record_alakazam": record_alakazam,
        "record_reward": record_reward,
        "record_options": record_options,
        "record_actions": record_actions,
        "record_rejected_actions": record_rejected_actions,
        "record_action_groups": record_action_groups,
        "feature_version": feature_version,
    }


class PolicyNet(nn.Module):
    def __init__(self, feature_version: int = 2):
        super().__init__()
        self.feature_version = int(feature_version)
        zone_count = V2_ZONE_COUNT if self.feature_version >= 2 else V1_ZONE_COUNT
        global_size = V5_GLOBAL_SIZE if self.feature_version >= 5 else V4_GLOBAL_SIZE if self.feature_version >= 4 else V2_GLOBAL_SIZE if self.feature_version >= 2 else V1_GLOBAL_SIZE
        self.state_embedding = nn.EmbeddingBag(CARD_LIMIT * zone_count, 64, mode="sum" if self.feature_version >= 2 else "mean")
        self.card_embedding = nn.Embedding(CARD_LIMIT, 32)
        self.attack_embedding = nn.Embedding(ATTACK_LIMIT, 16)
        self.type_embedding = nn.Embedding(18, 8)
        self.context_embedding = nn.Embedding(64, 16)
        self.area_embedding = nn.Embedding(16, 8)
        self.global_linear = nn.Linear(global_size, 64)
        numeric_size = (
            V4_OPTION_NUMERIC_SIZE if self.feature_version >= 4
            else V3_OPTION_NUMERIC_SIZE if self.feature_version >= 3
            else OPTION_NUMERIC_SIZE
        )
        self.numeric_linear = nn.Linear(numeric_size, 32)
        self.option_linear = nn.Linear(280, 128)
        self.score = nn.Linear(128, 1)
        self.count = nn.Linear(144, V2_COUNT_CLASSES if self.feature_version >= 2 else MAX_SELECT_COUNT)
        self.value = nn.Linear(128, 1)

    def forward(self, batch):
        state = self.state_embedding(batch["tokens"], batch["offsets"])
        if self.feature_version >= 2:
            ends = torch.cat([
                batch["offsets"][1:],
                torch.tensor([len(batch["tokens"])], device=batch["offsets"].device),
            ])
            lengths = (ends - batch["offsets"]).clamp_min(1).sqrt().unsqueeze(1)
            state = state / lengths
        global_vector = torch.tanh(self.global_linear(batch["global"]))
        shared = torch.cat([state, global_vector], dim=-1)
        option_shared = shared[batch["option_record"]]
        numeric = torch.tanh(self.numeric_linear(batch["numeric"]))
        option_vector = torch.cat([
            option_shared,
            self.card_embedding(batch["source"]),
            self.card_embedding(batch["target"]),
            self.attack_embedding(batch["attack"]),
            self.type_embedding(batch["type"]),
            self.context_embedding(batch["context"]),
            self.area_embedding(batch["area"]),
            self.area_embedding(batch["in_area"]),
            numeric,
        ], dim=-1)
        logits = self.score(torch.tanh(self.option_linear(option_vector))).squeeze(-1)
        record_context = batch["context"][torch.tensor([start for start, _ in batch["record_options"]], device=logits.device)]
        count_logits = self.count(torch.cat([shared, self.context_embedding(record_context)], dim=-1))
        values = self.value(shared).squeeze(-1)
        return logits, count_logits, values


def move(batch, device):
    return {key: value.to(device) if torch.is_tensor(value) else value for key, value in batch.items()}


def policy_loss(logits, batch):
    losses = []
    correct = total = 0
    for record_index, (start, end) in enumerate(batch["record_options"]):
        local = logits[start:end]
        actions = batch["record_actions"][record_index]
        if actions:
            available = torch.ones(len(local), dtype=torch.bool, device=local.device)
            terms = []
            for action in actions:
                step_available = available.clone()
                masked = local.masked_fill(~step_available, -torch.inf)
                terms.append(-F.log_softmax(masked, dim=0)[action])
                available = step_available.clone()
                available[action] = False
            losses.append(torch.stack(terms).mean() * batch["weights"][record_index])
        if len(actions) == 1:
            label = actions[0]
            correct += int(torch.argmax(local).item() == label)
            total += 1
    if not losses:
        return logits.sum() * 0.0, correct, total
    return torch.stack(losses).sum() / batch["weights"].sum().clamp_min(1e-6), correct, total


def masked_count_loss(count_logits, batch):
    last_class = count_logits.shape[1] - 1
    minimum = torch.round(batch["global"][:, 28] * MAX_SELECT_COUNT).long().clamp(0, last_class)
    maximum = torch.round(batch["global"][:, 29] * MAX_SELECT_COUNT).long().clamp(0, last_class)
    maximum = torch.maximum(maximum, minimum)
    classes = torch.arange(count_logits.shape[1], device=count_logits.device).unsqueeze(0)
    valid = (classes >= minimum.unsqueeze(1)) & (classes <= maximum.unsqueeze(1))
    valid.scatter_(1, batch["counts"].unsqueeze(1), True)
    masked = count_logits.masked_fill(~valid, -torch.inf)
    losses = F.cross_entropy(masked, batch["counts"], reduction="none")
    return (losses * batch["weights"]).sum() / batch["weights"].sum().clamp_min(1e-6)


def export_npz(model: PolicyNet, path: Path):
    state = model.state_dict()
    arrays = {
        "model_schema_version": np.asarray(model.feature_version, dtype=np.int16),
        "state_embedding": state["state_embedding.weight"].cpu().numpy(),
        "card_embedding": state["card_embedding.weight"].cpu().numpy(),
        "attack_embedding": state["attack_embedding.weight"].cpu().numpy(),
        "type_embedding": state["type_embedding.weight"].cpu().numpy(),
        "context_embedding": state["context_embedding.weight"].cpu().numpy(),
        "area_embedding": state["area_embedding.weight"].cpu().numpy(),
        "global_w": state["global_linear.weight"].cpu().numpy().T,
        "global_b": state["global_linear.bias"].cpu().numpy(),
        "numeric_w": state["numeric_linear.weight"].cpu().numpy().T,
        "numeric_b": state["numeric_linear.bias"].cpu().numpy(),
        "option_w": state["option_linear.weight"].cpu().numpy().T,
        "option_b": state["option_linear.bias"].cpu().numpy(),
        "score_w": state["score.weight"].cpu().numpy().T,
        "score_b": state["score.bias"].cpu().numpy(),
        "count_w": state["count.weight"].cpu().numpy().T,
        "count_b": state["count.bias"].cpu().numpy(),
        "value_w": state["value.weight"].cpu().numpy().T,
        "value_b": state["value.bias"].cpu().numpy(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **{name: value.astype(np.float16) for name, value in arrays.items()})


def load_npz_weights(model: PolicyNet, path: str | Path):
    weights = np.load(path, allow_pickle=False)
    state = model.state_dict()
    mapping = {
        "state_embedding.weight": weights["state_embedding"],
        "card_embedding.weight": weights["card_embedding"],
        "attack_embedding.weight": weights["attack_embedding"],
        "type_embedding.weight": weights["type_embedding"],
        "context_embedding.weight": weights["context_embedding"],
        "area_embedding.weight": weights["area_embedding"],
        "global_linear.weight": weights["global_w"].T,
        "global_linear.bias": weights["global_b"],
        "numeric_linear.weight": weights["numeric_w"].T,
        "numeric_linear.bias": weights["numeric_b"],
        "option_linear.weight": weights["option_w"].T,
        "option_linear.bias": weights["option_b"],
        "score.weight": weights["score_w"].T,
        "score.bias": weights["score_b"],
        "count.weight": weights["count_w"].T,
        "count.bias": weights["count_b"],
        "value.weight": weights["value_w"].T,
        "value.bias": weights["value_b"],
    }
    for name, value in mapping.items():
        state[name].copy_(torch.as_tensor(value, dtype=state[name].dtype))
    model.load_state_dict(state)


@torch.no_grad()
def evaluate(model, paths, batch_size, required_card, device, max_records=5000):
    model.eval()
    running = agreements = agreement_total = batches = records = 0
    for batch in iter_batches(paths, batch_size, max_records, required_card, validation=True, feature_version=model.feature_version):
        records += len(batch["record_options"])
        batch = move(batch, device)
        logits, count_logits, values = model(batch)
        option_loss, correct, total = policy_loss(logits, batch)
        loss = option_loss + 0.25 * masked_count_loss(count_logits, batch) + 0.10 * F.binary_cross_entropy_with_logits(values, batch["values"])
        running += float(loss.item())
        agreements += correct
        agreement_total += total
        batches += 1
    return {
        "validation_records": records,
        "validation_loss": running / max(1, batches),
        "validation_single_top1": agreements / max(1, agreement_total),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("shards", nargs="+")
    parser.add_argument("--output", default="artifacts/policy_weights.npz")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--require-card", type=int, default=0, help="train only decks containing this card ID")
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--feature-version", type=int, choices=(1, 2, 3, 4, 5), default=2)
    parser.add_argument("--team-ranks", help="ordered newline-delimited team names used for rank weighting")
    parser.add_argument("--early-stop-patience", type=int, default=2)
    parser.add_argument("--initial-model", help="optional compatible checkpoint for supervised fine-tuning")
    args = parser.parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = PolicyNet(args.feature_version).to(device)
    if args.initial_model:
        load_npz_weights(model, args.initial_model)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-5)
    paths = [Path(path) for path in args.shards]
    team_weights = {}
    if args.team_ranks:
        names = [line.strip() for line in Path(args.team_ranks).read_text().splitlines() if line.strip()]
        for rank, name in enumerate(names, 1):
            team_weights[name] = 1.5 if rank <= 20 else 1.2 if rank <= 50 else 1.0
    best_state = None
    best_validation = float("inf")
    stale_epochs = 0
    for epoch in range(args.epochs):
        model.train()
        running = agreements = agreement_total = batches = 0
        for batch in iter_batches(
            paths,
            args.batch_size,
            args.max_records,
            args.require_card,
            validation=False,
            feature_version=args.feature_version,
            team_weights=team_weights,
        ):
            batch = move(batch, device)
            logits, count_logits, values = model(batch)
            option_loss, correct, total = policy_loss(logits, batch)
            count_loss = masked_count_loss(count_logits, batch)
            value_losses = F.binary_cross_entropy_with_logits(values, batch["values"], reduction="none")
            value_loss = (value_losses * batch["weights"]).sum() / batch["weights"].sum().clamp_min(1e-6)
            loss = option_loss + 0.25 * count_loss + 0.10 * value_loss
            if not torch.isfinite(loss):
                minimum = torch.round(batch["global"][:, 28] * MAX_SELECT_COUNT).long()
                maximum = torch.round(batch["global"][:, 29] * MAX_SELECT_COUNT).long()
                raise FloatingPointError(json.dumps({
                    "error": "non_finite_training_loss",
                    "option_loss": float(option_loss.detach()),
                    "count_loss": float(count_loss.detach()),
                    "value_loss": float(value_loss.detach()),
                    "feature_version": batch["feature_version"],
                    "minimums": torch.bincount(minimum.cpu(), minlength=10).tolist(),
                    "maximums": torch.bincount(maximum.cpu(), minlength=10).tolist(),
                    "targets": torch.bincount(batch["counts"].cpu(), minlength=10).tolist(),
                }))
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            running += float(loss.item())
            agreements += correct
            agreement_total += total
            batches += 1
        metrics = {"epoch": epoch + 1, "loss": running / max(1, batches), "single_top1": agreements / max(1, agreement_total), "device": str(device)}
        metrics.update(evaluate(model, paths, args.batch_size, args.require_card, device))
        print(metrics)
        if metrics["validation_loss"] < best_validation - 1e-6:
            best_validation = metrics["validation_loss"]
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= args.early_stop_patience:
                print({"early_stop": epoch + 1, "best_validation_loss": best_validation})
                break
    if best_state is None:
        raise RuntimeError("no training batches matched the requested feature schema and deck")
    model.load_state_dict(best_state)
    export_npz(model.cpu(), Path(args.output))
    print({"output": args.output})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
