"""Command-line entry points for schedule, engine, and bounded acquisition tasks."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from .acquire import (
    ARTIFACT_HASH_KEYS,
    RUN_CONFIG_ARTIFACT_KEYS,
    SCIENTIFIC_PHASES,
    SHA256_PATTERN,
    acquire_schedule,
    compute_artifact_hashes,
    validate_schedule_for_acquisition,
)
from .adapters.pokemon import PokemonAdapterConfig, default_agent_configs
from .canonical import canonical_json_bytes, hash_file, write_canonical_json
from .scheduler import ScheduleConfig, build_schedule


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DECK = ROOT / "artifacts" / "grim_final_escape" / "candidate" / "deck.csv"
DEFAULT_MODEL = ROOT / "artifacts" / "grim_final_escape" / "candidate" / "policy_weights.npz"
DEFAULT_ENGINE_SOURCE = ROOT / "freshstart" / "engine" / "ptcgProgram" / "Export.cpp"


def _parse_agents(value: str) -> tuple[str, ...]:
    agents = tuple(item.strip() for item in value.split(",") if item.strip())
    if not agents:
        raise argparse.ArgumentTypeError("at least one agent is required")
    return agents


def _parse_fixed_work(value: str | None, agents: tuple[str, ...]) -> dict[str, int] | None:
    if value is None:
        return None
    if value.startswith("{"):
        result = {str(key): int(count) for key, count in json.loads(value).items()}
    else:
        counts = [int(item) for item in value.split(",")]
        if len(counts) != len(agents):
            raise ValueError("fixed-work list length must match agents")
        result = dict(zip(agents, counts))
    return result


def _parse_artifact_hashes(values: list[str] | None) -> dict[str, str] | None:
    if not values:
        return None
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("artifact hashes must use NAME=SHA256")
        key, digest = value.split("=", 1)
        if key in result:
            raise ValueError(f"duplicate artifact hash: {key}")
        if key not in ARTIFACT_HASH_KEYS or not SHA256_PATTERN.fullmatch(digest):
            raise ValueError(f"invalid artifact hash: {value}")
        result[key] = digest
    if set(result) != ARTIFACT_HASH_KEYS:
        raise ValueError(
            f"artifact hashes must name exactly {sorted(ARTIFACT_HASH_KEYS)}"
        )
    return result


def _resolve_run_artifact(path: str, config_dir: Path) -> Path:
    value = Path(path)
    return (value if value.is_absolute() else config_dir / value).resolve()


def _load_scientific_run_config(
    path: str | Path,
    scheduled_agents: set[str],
) -> tuple[
    dict[str, object],
    dict[str, Path],
    dict[str, str],
    dict[str, PokemonAdapterConfig],
]:
    """Load one canonical, self-consistent source of scientific runtime settings."""

    config_path = Path(path).resolve()
    raw = config_path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schema_version") != "acquisition-run-config-1.0.0":
        raise ValueError("invalid scientific acquisition run-config schema")
    if raw != canonical_json_bytes(value):
        raise ValueError("scientific acquisition run-config is not canonical JSON")
    required = {
        "schema_version",
        "artifacts",
        "target_cpus",
        "load_workers",
        "max_decisions",
        "worker_timeout_s",
        "thread_env",
        "platform_expectations",
        "adapter_configs",
    }
    if set(value) != required:
        raise ValueError(
            f"run-config keys must be exactly {sorted(required)}, observed {sorted(value)}"
        )
    artifacts = value["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != RUN_CONFIG_ARTIFACT_KEYS:
        raise ValueError(
            "run-config artifacts must name exactly "
            f"{sorted(RUN_CONFIG_ARTIFACT_KEYS)}"
        )
    paths: dict[str, Path] = {}
    embedded_hashes: dict[str, str] = {}
    for key in sorted(RUN_CONFIG_ARTIFACT_KEYS):
        record = artifacts[key]
        if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
            raise ValueError(f"run-config artifact {key} must contain only path and sha256")
        if not isinstance(record["path"], str) or not SHA256_PATTERN.fullmatch(
            str(record["sha256"])
        ):
            raise ValueError(f"run-config artifact {key} is malformed")
        paths[key] = _resolve_run_artifact(record["path"], config_path.parent)
        embedded_hashes[key] = str(record["sha256"])
    actual_hashes = compute_artifact_hashes(
        engine_binary=paths["engine_binary"],
        engine_source=paths["engine_source"],
        hero_deck=paths["hero_deck"],
        hero_model=paths["hero_model"],
        opponent_deck=paths["opponent_deck"],
        opponent_model=paths["opponent_model"],
        run_config=config_path,
    )
    for key in sorted(RUN_CONFIG_ARTIFACT_KEYS):
        if embedded_hashes[key] != actual_hashes[key]:
            raise ValueError(
                f"run-config artifact hash mismatch for {key}: "
                f"frozen={embedded_hashes[key]}, observed={actual_hashes[key]}"
            )

    target_cpus = value["target_cpus"]
    if (
        not isinstance(target_cpus, list)
        or not target_cpus
        or any(not isinstance(cpu, int) or isinstance(cpu, bool) or cpu < 0 for cpu in target_cpus)
        or len(set(target_cpus)) != len(target_cpus)
    ):
        raise ValueError("run-config target_cpus must be unique non-negative integers")
    if not isinstance(value["load_workers"], int) or value["load_workers"] <= 0:
        raise ValueError("run-config load_workers must be positive")
    if not isinstance(value["max_decisions"], int) or value["max_decisions"] <= 0:
        raise ValueError("run-config max_decisions must be positive")
    if (
        not isinstance(value["worker_timeout_s"], (int, float))
        or isinstance(value["worker_timeout_s"], bool)
        or value["worker_timeout_s"] <= 0
    ):
        raise ValueError("run-config worker_timeout_s must be positive")
    thread_env = value["thread_env"]
    required_thread_env = {
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "PYTHONHASHSEED",
        "VECLIB_MAXIMUM_THREADS",
    }
    if not isinstance(thread_env, dict) or not required_thread_env <= set(thread_env):
        raise ValueError(
            f"run-config thread_env must include {sorted(required_thread_env)}"
        )
    if any(not isinstance(key, str) or not isinstance(item, str) for key, item in thread_env.items()):
        raise ValueError("run-config thread_env keys and values must be strings")
    for key in required_thread_env - {"PYTHONHASHSEED"}:
        if thread_env[key] != "1":
            raise ValueError(f"run-config {key} must be frozen to 1")
    if not thread_env["PYTHONHASHSEED"].isdigit():
        raise ValueError("run-config PYTHONHASHSEED must be a decimal integer")
    expectations = value["platform_expectations"]
    if not isinstance(expectations, dict) or set(expectations) != {"system", "machine"}:
        raise ValueError("platform_expectations must contain exactly system and machine")
    if not all(isinstance(expectations[key], str) and expectations[key] for key in expectations):
        raise ValueError("platform expectations must be non-empty strings")

    raw_configs = value["adapter_configs"]
    if not isinstance(raw_configs, dict) or set(raw_configs) != scheduled_agents:
        raise ValueError("run-config adapter IDs do not exactly match the schedule")
    configured: dict[str, PokemonAdapterConfig] = {}
    path_fields = {
        "hero_deck_path": "hero_deck",
        "hero_model_path": "hero_model",
        "opponent_deck_path": "opponent_deck",
        "opponent_model_path": "opponent_model",
        "seeded_engine_path": "engine_binary",
    }
    for agent_id, raw_config in raw_configs.items():
        if not isinstance(raw_config, dict):
            raise ValueError(f"adapter config {agent_id} is not an object")
        normalized = dict(raw_config)
        for field, artifact_key in path_fields.items():
            if field not in normalized or not isinstance(normalized[field], str):
                raise ValueError(f"adapter config {agent_id} lacks {field}")
            normalized[field] = str(
                _resolve_run_artifact(normalized[field], config_path.parent)
            )
            if Path(normalized[field]) != paths[artifact_key]:
                raise ValueError(
                    f"adapter config {agent_id} {field} differs from frozen artifact path"
                )
        config = PokemonAdapterConfig(**normalized)
        if config.agent_id != agent_id:
            raise ValueError(f"adapter mapping key does not match agent_id for {agent_id}")
        config.validate()
        expected_algorithms = {
            "one_ply_value_v1": "one_ply_value",
            "flat_rollout_v1": "flat_rollout",
            "puct_tree_v1": "puct_tree",
        }
        if expected_algorithms.get(agent_id) != config.algorithm:
            raise ValueError(f"adapter {agent_id} has unexpected algorithm {config.algorithm}")
        if config.initialize_engine:
            raise ValueError(f"adapter {agent_id} must not reinitialize the evaluation engine")
        configured[agent_id] = config
    return value, paths, actual_hashes, configured


def command_schedule(args: argparse.Namespace) -> int:
    agents = _parse_agents(args.agents)
    artifact_hashes = _parse_artifact_hashes(args.artifact_hash)
    if args.phase in SCIENTIFIC_PHASES and artifact_hashes is None:
        raise ValueError(f"{args.phase} schedule requires all seven artifact hashes")
    config = ScheduleConfig(
        phase=args.phase,
        master_seed=args.master_seed,
        agents=agents,
        block_count=args.blocks,
        paired_load_batches=args.load_batches,
        minimum_persistent_sessions=args.persistent_sessions,
        persistent_sequence_length=args.persistent_length,
        wall_clock_budget_ns=(None if args.deadline_ms is None else int(args.deadline_ms * 1_000_000)),
        fixed_work_by_agent=_parse_fixed_work(args.fixed_work, agents),
        artifact_hashes=artifact_hashes,
    )
    manifest = build_schedule(config)
    digest = write_canonical_json(args.output, manifest)
    print(json.dumps({"output": str(Path(args.output).resolve()), "sha256": digest, "rows": len(manifest["rows"])}, sort_keys=True))
    return 0


def command_build_engine(args: argparse.Namespace) -> int:
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Linux":
        command = [
            args.compiler or "g++",
            "-std=c++20",
            "-O3",
            "-DNDEBUG",
            "-fPIC",
            "-shared",
            str(source),
            "-o",
            str(output),
        ]
    elif platform.system() == "Darwin":
        command = [
            args.compiler or "clang++",
            "-std=c++20",
            "-O3",
            "-DNDEBUG",
            "-dynamiclib",
            str(source),
            "-o",
            str(output),
        ]
    else:
        raise RuntimeError("study engine build currently supports Linux and macOS")
    subprocess.run(command, check=True)
    symbols = subprocess.run(
        ["nm", "-g", str(output)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    required = ("BattleStartSeeded", "SearchSetSeed", "SearchBegin", "SearchEnd")
    missing = [symbol for symbol in required if symbol not in symbols]
    if missing:
        raise RuntimeError(f"evaluation engine lacks required symbols: {missing}")
    metadata = {
        "schema_version": "engine-build-1.0.0",
        "source": str(source),
        "source_sha256": hash_file(source),
        "output": str(output),
        "output_sha256": hash_file(output),
        "compiler_command": command,
        "platform": platform.platform(),
        "required_symbols": list(required),
        "production_replacement": False,
        "redistributable": False,
    }
    metadata_path = output.with_suffix(output.suffix + ".build.json")
    write_canonical_json(metadata_path, metadata)
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0


def command_acquire(args: argparse.Namespace) -> int:
    from training.azure_guard import enforce_azure_workload

    schedule_path = Path(args.schedule).resolve()
    manifest = validate_schedule_for_acquisition(
        json.loads(schedule_path.read_text(encoding="utf-8"))
    )
    phase = str(manifest["config"]["phase"])
    scientific = phase in SCIENTIFIC_PHASES
    if args.allow_local_smoke and phase != "smoke":
        raise ValueError("--allow-local-smoke is forbidden for scientific phases")
    enforce_azure_workload(
        allow_local_smoke=(bool(args.allow_local_smoke) if phase == "smoke" else False),
        workload_size=len(manifest["rows"]),
    )
    scheduled_agents = set(manifest["config"]["agents"])
    actual_hashes: dict[str, str] | None = None
    thread_env: dict[str, str] = {}
    platform_expectations: dict[str, object] = {}
    if scientific:
        scientific_overrides = {
            "engine": args.engine,
            "deck": args.deck,
            "model": args.model,
            "anchor_deck": args.anchor_deck,
            "anchor_model": args.anchor_model,
            "target_cpu": args.target_cpu,
            "load_workers": args.load_workers,
            "max_decisions": args.max_decisions,
            "worker_timeout_s": args.worker_timeout_s,
        }
        supplied = sorted(key for key, value in scientific_overrides.items() if value is not None)
        if supplied:
            raise ValueError(
                "scientific runtime settings may come only from --run-config; "
                f"remove overrides {supplied}"
            )
        if args.run_config is None:
            raise ValueError(f"{phase} acquisition requires --run-config")
        run_config, paths, actual_hashes, configured = _load_scientific_run_config(
            args.run_config, scheduled_agents
        )
        thread_env = {str(key): str(value) for key, value in run_config["thread_env"].items()}
        for key, value in thread_env.items():
            os.environ[key] = value
        platform_expectations = dict(run_config["platform_expectations"])
        engine = paths["engine_binary"]
        hero_deck = paths["hero_deck"]
        hero_model = paths["hero_model"]
        anchor_deck = paths["opponent_deck"]
        anchor_model = paths["opponent_model"]
        target_cpus = tuple(int(cpu) for cpu in run_config["target_cpus"])
        load_workers = int(run_config["load_workers"])
        max_decisions = int(run_config["max_decisions"])
        worker_timeout_s = float(run_config["worker_timeout_s"])
    else:
        if args.run_config is not None or args.freeze_manifest is not None:
            raise ValueError("smoke acquisition does not accept scientific freeze inputs")
        if args.engine is None:
            raise ValueError("smoke acquisition requires --engine")
        engine = Path(args.engine).resolve()
        hero_deck = Path(args.deck or DEFAULT_DECK).resolve()
        hero_model = Path(args.model or DEFAULT_MODEL).resolve()
        anchor_deck = Path(args.anchor_deck or DEFAULT_DECK).resolve()
        anchor_model = Path(args.anchor_model or DEFAULT_MODEL).resolve()
        configs = default_agent_configs(
            hero_deck_path=str(hero_deck),
            hero_model_path=str(hero_model),
            opponent_deck_path=str(anchor_deck),
            opponent_model_path=str(anchor_model),
            seeded_engine_path=str(engine),
            initialize_engine=False,
        )
        configured = {config.agent_id: config for config in configs}
        target_cpus = tuple(args.target_cpu or [0])
        load_workers = int(args.load_workers or 1)
        max_decisions = int(args.max_decisions or 2_000)
        worker_timeout_s = float(args.worker_timeout_s or 3_600.0)
    if set(configured) != scheduled_agents:
        raise ValueError(
            f"schedule agents {sorted(scheduled_agents)} do not match frozen adapters {sorted(configured)}"
        )
    summary = acquire_schedule(
        manifest,
        engine_path=engine,
        adapter_configs=configured,
        anchor_deck_path=anchor_deck,
        anchor_model_path=anchor_model,
        output_dir=args.output_dir,
        target_cpus=target_cpus,
        load_workers=load_workers,
        max_decisions=max_decisions,
        worker_timeout_s=worker_timeout_s,
        schedule_path=schedule_path,
        freeze_manifest_path=args.freeze_manifest,
        actual_artifact_hashes=actual_hashes,
        artifact_paths=(
            None
            if not scientific
            else {**paths, "run_config": Path(args.run_config).resolve()}
        ),
        thread_env=thread_env,
        platform_expectations=platform_expectations,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    schedule = subparsers.add_parser("schedule", help="generate a canonical factorial schedule")
    schedule.add_argument("--phase", choices=("smoke", "pilot", "final"), required=True)
    schedule.add_argument("--master-seed", type=int, required=True)
    schedule.add_argument("--agents", default="one_ply_value_v1,flat_rollout_v1,puct_tree_v1")
    schedule.add_argument("--blocks", type=int, required=True)
    schedule.add_argument("--load-batches", type=int, required=True)
    schedule.add_argument("--persistent-sessions", type=int, required=True)
    schedule.add_argument("--persistent-length", type=int, default=8)
    schedule.add_argument("--deadline-ms", type=float)
    schedule.add_argument("--fixed-work", help="comma counts in agent order or a JSON object")
    schedule.add_argument(
        "--artifact-hash",
        action="append",
        help="repeat NAME=SHA256 for the seven frozen artifact hashes",
    )
    schedule.add_argument("--output", required=True)
    schedule.set_defaults(func=command_schedule)

    engine = subparsers.add_parser("build-engine", help="build the evaluation-only seeded engine")
    engine.add_argument("--source", default=str(DEFAULT_ENGINE_SOURCE))
    engine.add_argument("--output", required=True)
    engine.add_argument("--compiler")
    engine.set_defaults(func=command_build_engine)

    acquire = subparsers.add_parser("acquire", help="execute a frozen schedule")
    acquire.add_argument("--schedule", required=True)
    acquire.add_argument("--run-config")
    acquire.add_argument("--freeze-manifest")
    acquire.add_argument("--engine", help="smoke only")
    acquire.add_argument("--deck", help="smoke only")
    acquire.add_argument("--model", help="smoke only")
    acquire.add_argument("--anchor-deck", help="smoke only")
    acquire.add_argument("--anchor-model", help="smoke only")
    acquire.add_argument("--output-dir", required=True)
    acquire.add_argument("--target-cpu", type=int, action="append")
    acquire.add_argument("--load-workers", type=int, help="smoke only")
    acquire.add_argument("--max-decisions", type=int, help="smoke only")
    acquire.add_argument("--worker-timeout-s", type=float, help="smoke only")
    acquire.add_argument("--allow-local-smoke", action="store_true")
    acquire.set_defaults(func=command_acquire)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
