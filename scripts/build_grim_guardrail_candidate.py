#!/usr/bin/env python3
"""Build the deterministic, search-disabled Original-5k guardrail candidate.

This builder is intentionally packaging-only.  It never reads evaluation data,
runs games, invokes Linux, uploads, or uses cloud resources.  Both candidate
trees start from fresh extractions of the hash-pinned original archive.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = ROOT / "grimmsnarl_5k_reference.tar.gz"
DEFAULT_OUTPUT = ROOT / "artifacts" / "grim_guardrail_candidate"
ARCHIVE_NAME = "grim_5k_guardrail_search_disabled_v1.tar.gz"
EXTRACTED_NAME = "extracted_search_disabled_v1"
MANIFEST_NAME = "build_manifest.json"
INTERNAL_MANIFEST_NAME = "grim_guardrail_build.json"

FROZEN_ARCHIVE_SHA256 = "3ECB0BBF119E23C31905E39E19ECA8F6145104AAEFFC0A5675D2FE03855BB458"
FROZEN_MODEL_SHA256 = "D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3"
FROZEN_RAW_DECK_SHA256 = "92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D"
FROZEN_CANONICAL_DECK_SHA256 = "C20A8A46F5C635773754F03103652F5C534B13DC622448ED2255A97234C103AF"
FROZEN_SOURCE_HASHES = {
    "main.py": "2C4AFF05CE379E96C90FDBBAE30E883E3A535011644774419696A14A725742EE",
    "ptcg_ai/__init__.py": "36BE9FEE3CC86FC94D00589ED21772D206A9DE876A50926F80925B9CE5DADAA7",
    "ptcg_ai/agent.py": "3F864338975F5B872902A5916D5F12773BB0A57679E2B967131684CFF1DAF867",
    "ptcg_ai/model.py": "31203FD3C25CA89958E6C8780B19545E4F4A352722640F538195BD964BB037A5",
}
FROZEN_ENGINE_HASHES = {
    "cg/__init__.py": "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855",
    "cg/api.py": "593F1298E52A635F90F8F505A52113E9AF114F444C293404E37906F18EE06CED",
    "cg/cg.dll": "EAE88634E26DC31D94150A4D8202FC9D32596B8C688EF67E14CB4088CD4D5771",
    "cg/game.py": "3BD3D4F4A369A11E6D2F5DA9094CF15EBC410A2221835E6417B7CFF4883F1FC2",
    "cg/libcg-arm64.so": "1670740B73FAB46586FD25C0A1F96608EA75B1F39381D66A0B8D9486BEA6D4A2",
    "cg/libcg.dylib": "7A157F045D333F99D1996D49C12BDBDD148072A619AF246385C7295518776E30",
    "cg/libcg.so": "D16244A3157FC55C3314F08DCC7C5179168697D78C105B95C7DEBD556B764BB7",
    "cg/sim.py": "1555F57F5D22BF4C09D70E0E667A916E575E68C9DD1DE9EAD34BA5E7E4968655",
    "cg/utils.py": "60F29665CEE0A88525D6F0383BC45959A6262D16FE35EF380AECE1E0EA13C49B",
}

RUNTIME_DEPENDENCIES = (
    "card_ids.py",
    "view.py",
    "safety.py",
    "prevention.py",
    "prevention.json",
    "tactical_shield.py",
    "grim_guardrails.py",
    "grim_variance_floor.py",
    "grim_runtime_policy.py",
)
FORBIDDEN_RUNTIME_FILES = frozenset(
    {
        "ptcg_ai/grim_floor_controller.py",
        "ptcg_ai/proof_search.py",
        "ptcg_ai/runtime_proof_director.py",
        "ptcg_ai/search.py",
    }
)
SEARCH_DISABLED_RATIONALE = (
    "development native audit observed 0 terminal branches in 100 sampled "
    "decisions and nondeterministic classifications; runtime native search "
    "is therefore disabled in this candidate"
)


class BuildError(RuntimeError):
    pass


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def canonical_deck_sha256(cards: Iterable[int]) -> str:
    normalized = tuple(sorted(map(int, cards)))
    if len(normalized) != 60:
        raise BuildError(f"expected exactly 60 deck cards, got {len(normalized)}")
    return hashlib.sha256(",".join(map(str, normalized)).encode("ascii")).hexdigest().upper()


def _is_cache_path(path: Path) -> bool:
    return (
        any(part in {"__pycache__", ".pytest_cache"} for part in path.parts)
        or path.suffix.lower() in {".pyc", ".pyo"}
    )


def safe_extract(archive: str | Path, destination: str | Path) -> None:
    archive = Path(archive)
    destination = Path(destination)
    root = destination.resolve()
    with tarfile.open(archive, "r:gz") as handle:
        for member in handle.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise BuildError(f"unsafe archive member: {member.name}")
            if member.issym() or member.islnk() or member.isdev():
                raise BuildError(f"unsupported archive member type: {member.name}")
        handle.extractall(destination)


def _tree_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not _is_cache_path(path.relative_to(root))
    )


def package_file_hashes(root: str | Path) -> dict[str, str]:
    root = Path(root)
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in _tree_files(root)
    }


def tree_digest(hashes: Mapping[str, str]) -> str:
    payload = json.dumps(dict(sorted(hashes.items())), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()


def deterministic_tar(stage: str | Path, output: str | Path) -> None:
    stage = Path(stage)
    output = Path(output)
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in _tree_files(stage):
                    relative = path.relative_to(stage).as_posix()
                    info = archive.gettarinfo(str(path), arcname=relative)
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mode = 0o644
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)


def _require_hash(stage: Path, relative: str, expected: str) -> str:
    path = stage / relative
    if not path.is_file():
        raise BuildError(f"pinned file is missing: {relative}")
    actual = sha256_file(path)
    if actual != expected:
        raise BuildError(f"pinned hash mismatch for {relative}: expected {expected}, got {actual}")
    return actual


def verify_frozen_tree(stage: str | Path) -> dict[str, Any]:
    stage = Path(stage)
    _require_hash(stage, "policy_weights.npz", FROZEN_MODEL_SHA256)
    _require_hash(stage, "deck.csv", FROZEN_RAW_DECK_SHA256)
    for name, expected in FROZEN_SOURCE_HASHES.items():
        _require_hash(stage, name, expected)
    for name, expected in FROZEN_ENGINE_HASHES.items():
        _require_hash(stage, name, expected)
    try:
        cards = [
            int(line)
            for line in (stage / "deck.csv").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except ValueError as exc:
        raise BuildError("pinned deck contains a non-integer card ID") from exc
    canonical = canonical_deck_sha256(cards)
    if canonical != FROZEN_CANONICAL_DECK_SHA256:
        raise BuildError(
            "pinned canonical deck hash mismatch: "
            f"expected {FROZEN_CANONICAL_DECK_SHA256}, got {canonical}"
        )
    return {
        "model_sha256": FROZEN_MODEL_SHA256,
        "raw_deck_sha256": FROZEN_RAW_DECK_SHA256,
        "canonical_deck_sha256": canonical,
        "deck_multiset": {str(key): value for key, value in sorted(Counter(cards).items())},
        "engine_sha256": dict(FROZEN_ENGINE_HASHES),
        "original_source_sha256": dict(FROZEN_SOURCE_HASHES),
    }


def copy_runtime_dependencies(stage: str | Path) -> dict[str, str]:
    stage = Path(stage)
    destination = stage / "ptcg_ai"
    hashes: dict[str, str] = {}
    for name in RUNTIME_DEPENDENCIES:
        source = ROOT / "ptcg_ai" / name
        if not source.is_file():
            raise BuildError(f"runtime dependency is missing: {source}")
        target = destination / name
        shutil.copyfile(source, target)
        source_hash = sha256_file(source)
        packaged_hash = sha256_file(target)
        if packaged_hash != source_hash:
            raise BuildError(f"runtime dependency copy mismatch: {name}")
        hashes[f"ptcg_ai/{name}"] = source_hash
    return hashes


def patch_model_and_agent(stage: str | Path) -> dict[str, dict[str, str]]:
    """Patch only freshly extracted model.py and agent.py via strict anchors."""

    stage = Path(stage)
    model = stage / "ptcg_ai" / "model.py"
    original_model_hash = sha256_file(model)
    source = model.read_text(encoding="utf-8")
    import_anchor = "from .safety import sanitize_selection\n"
    init_anchor = "        self.fallback = fallback\n"
    return_anchor = "        return sanitize_selection(obs.select, ranked, desired)\n"
    choose_anchor = "    def choose(self, obs) -> list[int]:\n"
    for label, anchor in (
        ("model import", import_anchor),
        ("model init", init_anchor),
        ("model return", return_anchor),
        ("model choose", choose_anchor),
    ):
        if source.count(anchor) != 1:
            raise BuildError(f"ambiguous pinned {label} anchor")
    source = source.replace(
        import_anchor,
        import_anchor
        + "from .grim_runtime_policy import GrimRuntimePolicy, SearchDisabledProof\n",
    )
    source = source.replace(
        "from .grim_runtime_policy import GrimRuntimePolicy, SearchDisabledProof\n",
        "from .grim_runtime_policy import GrimRuntimePolicy, SearchDisabledProof\n"
        "from .grim_variance_floor import GrimVarianceConfig, GrimVarianceFloorDirector\n",
    )
    source = source.replace(
        init_anchor,
        init_anchor
        + "        self.runtime_policy = GrimRuntimePolicy(proof=SearchDisabledProof())\n",
    )
    source = source.replace(
        "        self.runtime_policy = GrimRuntimePolicy(proof=SearchDisabledProof())\n",
        "        self.runtime_policy = GrimRuntimePolicy(proof=SearchDisabledProof())\n"
        "        self.runtime_policy.guardrail = GrimVarianceFloorDirector(\n"
        "            GrimVarianceConfig(punk_up_floor=True, dead_active_escape=True)\n"
        "        )\n",
    )
    source = source.replace(
        choose_anchor,
        "    def reset(self) -> None:\n"
        "        self.runtime_policy.reset()\n\n"
        + choose_anchor,
    )
    source = source.replace(
        return_anchor,
        "        baseline = sanitize_selection(obs.select, ranked, desired)\n"
        "        try:\n"
        "            return self.runtime_policy.choose(obs, ranked, desired)\n"
        "        except Exception:\n"
        "            return baseline\n",
    )
    model.write_text(source, encoding="utf-8", newline="\n")

    agent = stage / "ptcg_ai" / "agent.py"
    original_agent_hash = sha256_file(agent)
    source = agent.read_text(encoding="utf-8")
    handshake = (
        "        if obs.select is None:\n"
        "            self.errors = 0\n"
        "            return list(self.deck)\n"
    )
    replacement = (
        "        if obs.select is None:\n"
        "            self.errors = 0\n"
        "            if hasattr(self.policy, \"reset\"):\n"
        "                try:\n"
        "                    self.policy.reset()\n"
        "                except Exception:\n"
        "                    pass\n"
        "            return list(self.deck)\n"
    )
    if source.count(handshake) != 1:
        raise BuildError("ambiguous pinned agent handshake anchor")
    agent.write_text(source.replace(handshake, replacement), encoding="utf-8", newline="\n")

    return {
        "ptcg_ai/model.py": {
            "original_sha256": original_model_hash,
            "patched_sha256": sha256_file(model),
        },
        "ptcg_ai/agent.py": {
            "original_sha256": original_agent_hash,
            "patched_sha256": sha256_file(agent),
        },
    }


def _assert_search_disabled_tree(stage: Path) -> None:
    present_forbidden = sorted(name for name in FORBIDDEN_RUNTIME_FILES if (stage / name).exists())
    if present_forbidden:
        raise BuildError(f"forbidden runtime implementation packaged: {present_forbidden}")
    model_source = (stage / "ptcg_ai" / "model.py").read_text(encoding="utf-8")
    if "GrimRuntimePolicy(proof=SearchDisabledProof())" not in model_source:
        raise BuildError("patched model is not explicitly bound to SearchDisabledProof")
    if "runtime_policy.choose(obs, ranked, desired)" not in model_source:
        raise BuildError("patched model does not forward exact d842 ranking/count")
    if "GrimFloorController" in model_source:
        raise BuildError("broad GrimFloorController is forbidden")


def stage_candidate(base_archive: str | Path, destination: str | Path) -> dict[str, Any]:
    base_archive = Path(base_archive)
    destination = Path(destination)
    if any(destination.iterdir()):
        raise BuildError(f"candidate stage must be empty: {destination}")
    safe_extract(base_archive, destination)
    frozen = verify_frozen_tree(destination)
    runtime_hashes = copy_runtime_dependencies(destination)
    patches = patch_model_and_agent(destination)
    # Model, deck, and every engine payload must remain byte-identical after patching.
    _require_hash(destination, "policy_weights.npz", FROZEN_MODEL_SHA256)
    _require_hash(destination, "deck.csv", FROZEN_RAW_DECK_SHA256)
    for name, expected in FROZEN_ENGINE_HASHES.items():
        _require_hash(destination, name, expected)
    _assert_search_disabled_tree(destination)
    if any(_is_cache_path(path.relative_to(destination)) for path in destination.rglob("*")):
        raise BuildError("cache artifact appeared in fresh candidate stage")

    internal = {
        "schema_version": 1,
        "label": "ORIGINAL_5K_GRIM_GUARDRAIL_SEARCH_DISABLED_V1",
        "policy_status": "development_candidate_not_evaluated",
        "frozen": {
            "base_archive_sha256": FROZEN_ARCHIVE_SHA256,
            **frozen,
        },
        "runtime": {
            "guardrail": "GrimVarianceFloorDirector(B3)",
            "coordinator": "GrimRuntimePolicy",
            "tactical_allowlist": ["end_with_productive_attack", "nullified_attack"],
            "broad_floor_controller": False,
            "native_search_enabled": False,
            "proof_component": "SearchDisabledProof",
            "search_disabled_rationale": SEARCH_DISABLED_RATIONALE,
            "native_audit_terminal_branches": {"terminal": 0, "sampled": 100},
            "native_audit_deterministic_classifications": False,
        },
        "runtime_source_sha256": dict(sorted(runtime_hashes.items())),
        "patched_source_sha256": dict(sorted(patches.items())),
        "build_constraints": {
            "temperature": 0,
            "model_retrained": False,
            "deck_changed": False,
            "games_run": False,
            "calibration_accessed": False,
            "linux_run": False,
            "upload_performed": False,
            "cloud_used": False,
        },
    }
    (destination / INTERNAL_MANIFEST_NAME).write_text(
        json.dumps(internal, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return internal


def raw_source_windows_smoke(archive: str | Path) -> dict[str, Any]:
    """Run import/handshake/policy smoke on Windows; this is not a game."""

    archive = Path(archive)
    with tempfile.TemporaryDirectory(prefix="grim-guardrail-smoke-") as directory:
        target = Path(directory)
        safe_extract(archive, target)
        code = f'''
import inspect
import json
import pathlib
import sys
sys.path.insert(0, {str(target)!r})
ns = {{"__name__": "submission_entry"}}
assert "__file__" not in ns
exec(compile(pathlib.Path("main.py").read_text(encoding="utf-8"), "main.py", "exec"), ns)
assert len(inspect.signature(ns["agent"]).parameters) == 1
policy = ns["_AGENT"].policy
assert type(policy.runtime_policy.proof).__name__ == "SearchDisabledProof"
assert not pathlib.Path("ptcg_ai/runtime_proof_director.py").exists()
import numpy as np
import ptcg_ai.model as model_module
from types import SimpleNamespace as NS
from cg.api import OptionType, SelectContext, SelectType
model_module.encode_observation = lambda _obs, _version: object()
policy.model.predict = lambda _features: (
    np.asarray([0.1, 0.9], dtype=np.float32),
    np.asarray([0.0, 1.0], dtype=np.float32),
    0.0,
)
obs = NS(
    select=NS(
        option=[NS(type=OptionType.YES), NS(type=OptionType.NO)],
        minCount=1,
        maxCount=1,
        context=SelectContext.ACTIVATE,
        type=SelectType.YES_NO,
    ),
    current=None,
    logs=[],
)
assert policy.choose(obs) == [1]
original_choose = policy.runtime_policy.choose
def broken(*_args, **_kwargs):
    raise RuntimeError("coordinator smoke fault")
policy.runtime_policy.choose = broken
assert policy.choose(obs) == [1]
policy.runtime_policy.choose = original_choose
original_reset = policy.reset
def broken_reset():
    raise RuntimeError("reset smoke fault")
policy.reset = broken_reset
deck = ns["agent"]({{"select": None, "current": None, "logs": [], "search_begin_input": None}})
assert len(deck) == 60
policy.reset = original_reset
deck = ns["agent"]({{"select": None, "current": None, "logs": [], "search_begin_input": None}})
assert len(deck) == 60
assert policy.runtime_policy.proof.telemetry["calls"] == 0
print(json.dumps({{
    "platform": sys.platform,
    "raw_source_without_file": True,
    "handshake_reset": True,
    "handshake_reset_failure_fallthrough": True,
    "exact_rank_count_forwarding": True,
    "frozen_exception_fallback": True,
    "native_search_enabled": False,
}}))
'''
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, "-I", "-c", code],
            cwd=target,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise BuildError(
                "raw-source Windows smoke failed: "
                + (result.stderr.strip() or result.stdout.strip())
            )
        try:
            payload = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise BuildError(f"malformed smoke output: {result.stdout!r}") from exc
        if not str(payload.get("platform", "")).startswith("win"):
            raise BuildError(f"Windows smoke ran on unexpected platform: {payload.get('platform')}")
        return {"passed": True, **payload}


def _safe_replace_generated_directory(target: Path, output_dir: Path) -> None:
    if not target.exists():
        return
    resolved_target = target.resolve()
    resolved_output = output_dir.resolve()
    if resolved_target.parent != resolved_output or target.name != EXTRACTED_NAME:
        raise BuildError(f"unsafe generated extraction target: {target}")
    shutil.rmtree(target)


def build_candidate(
    *,
    base_archive: str | Path = DEFAULT_BASE,
    output_dir: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    base_archive = Path(base_archive).resolve()
    output_dir = Path(output_dir).resolve()
    if not base_archive.is_file():
        raise FileNotFoundError(base_archive)
    actual_base = sha256_file(base_archive)
    if actual_base != FROZEN_ARCHIVE_SHA256:
        raise BuildError(
            f"pinned base archive mismatch: expected {FROZEN_ARCHIVE_SHA256}, got {actual_base}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="grim-guardrail-build-", dir=output_dir) as directory:
        work = Path(directory)
        first = work / "first"
        second = work / "second"
        first.mkdir()
        second.mkdir()
        first_internal = stage_candidate(base_archive, first)
        second_internal = stage_candidate(base_archive, second)
        if first_internal != second_internal:
            raise BuildError("fresh stage manifests differ")
        first_tar = work / "first.tar.gz"
        second_tar = work / "second.tar.gz"
        deterministic_tar(first, first_tar)
        deterministic_tar(second, second_tar)
        first_hash = sha256_file(first_tar)
        second_hash = sha256_file(second_tar)
        if first_hash != second_hash:
            raise BuildError(
                f"deterministic double build mismatch: first={first_hash}, second={second_hash}"
            )

        smoke = raw_source_windows_smoke(first_tar)
        archive = output_dir / ARCHIVE_NAME
        shutil.copyfile(first_tar, archive)
        extracted = output_dir / EXTRACTED_NAME
        _safe_replace_generated_directory(extracted, output_dir)
        shutil.copytree(first, extracted)

    package_hashes = package_file_hashes(extracted)
    if any(_is_cache_path(Path(name)) for name in package_hashes):
        raise BuildError("cache artifact included in extracted candidate")
    result = {
        **first_internal,
        "archive_name": ARCHIVE_NAME,
        "archive_sha256": sha256_file(archive),
        "archive_bytes": archive.stat().st_size,
        "extracted_directory": EXTRACTED_NAME,
        "package_file_sha256": package_hashes,
        "package_tree_sha256": tree_digest(package_hashes),
        "verification": {
            "fresh_extraction_count": 2,
            "deterministic_double_build": True,
            "first_archive_sha256": first_hash,
            "second_archive_sha256": second_hash,
            "caches_excluded": True,
            "raw_source_execution_without_file": bool(smoke["raw_source_without_file"]),
            "windows_smoke": smoke,
        },
    }
    (output_dir / MANIFEST_NAME).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-archive", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = build_candidate(base_archive=args.base_archive, output_dir=args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
