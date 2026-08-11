#!/usr/bin/env python3
"""Package a schema-2/3 policy in the authentic, hash-pinned A2 shield runtime.

This is deliberately a packaging-only command.  It copies the frozen A2
runtime byte for byte and replaces only ``policy_weights.npz``.  It cannot run
games, upload a submission, or start cloud resources.
"""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ARCHIVE = ROOT / "artifacts" / "recovery_probes" / "a2_v2_shield.tar.gz"
DEFAULT_OUTPUT_DIR = ROOT / "artifacts" / "a2_finalists"

FROZEN_SOURCE_ARCHIVE_SHA256 = "0958BD8847266EFBC38658D62B9AC4DCD62A9AAED3D1098F093A677AFCBFED4C"
FROZEN_SOURCE_TREE_SHA256 = "854D8D016F545635711CB0722820B2997E19C4A160797C70E6415BCCCF0BD1AE"
FROZEN_RUNTIME_SOURCE_TREE_SHA256 = "A25F9F0FEE304C6DE8811BB3E268D0A1BB7E5F60C961C3AAA005C590E51CEA12"
FROZEN_SOURCE_MODEL_SHA256 = "B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8"
FROZEN_RAW_DECK_SHA256 = "92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D"
FROZEN_CANONICAL_DECK_SHA256 = "C20A8A46F5C635773754F03103652F5C534B13DC622448ED2255A97234C103AF"
FROZEN_MAIN_SHA256 = "028B1946969C62491B04E89B031AFB36F01E06994DCA7ECAFD1EB0AD85B0055E"
FROZEN_MODEL_RUNTIME_SHA256 = "89A427365CE2BC5A16E4EDFBEA48F5E921989D91F9A8AC7EEF280D5E79C68440"
FROZEN_TACTICAL_SHIELD_SHA256 = "3C9678418A8CFE1758752C9E21F1D254EFF398D911F260545317673D746946B5"

MODEL_MEMBER = "policy_weights.npz"
SUPPORTED_MODEL_SCHEMAS = frozenset({2, 3})
RUNTIME_CONTROLS = {
    "PTCG_SEARCH": "0",
    "PTCG_TACTICAL_SHIELD": "1",
    "PTCG_TEMP": "0",
}
BEHAVIOR_ENV_KEYS = frozenset(
    {
        "PTCG_DIRECTOR_ARM",
        "PTCG_DIRECTOR_HORIZON",
        "PTCG_DIRECTOR_SWAP_FALLBACK",
        "PTCG_DIRECTOR_TRIGGER",
        "PTCG_POLICY",
        "PTCG_SEARCH",
        "PTCG_TACTICAL_SHIELD",
        "PTCG_TEMP",
        "PTCG_WAVE1_RAIL",
    }
)
EXPECTED_MODEL_SHAPES = {
    "area_embedding": (16, 8),
    "attack_embedding": (1600, 16),
    "card_embedding": (1300, 32),
    "context_embedding": (64, 16),
    "count_b": (61,),
    "count_w": (144, 61),
    "global_b": (64,),
    "global_w": (118, 64),
    "model_schema_version": (),
    "numeric_b": (32,),
    "numeric_w": (12, 32),
    "option_b": (128,),
    "option_w": (280, 128),
    "score_b": (1,),
    "score_w": (128, 1),
    "state_embedding": (20800, 64),
    "type_embedding": (18, 8),
    "value_b": (1,),
    "value_w": (128, 1),
}
_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class PackageError(RuntimeError):
    """A fail-closed finalist packaging error."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _is_cache_name(parts: Iterable[str]) -> bool:
    names = tuple(parts)
    lowered = tuple(part.lower() for part in names)
    return (
        any(
            part in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
            for part in lowered
        )
        or (bool(names) and Path(names[-1]).suffix.lower() in {".pyc", ".pyo"})
    )


def _safe_member_parts(name: str, *, kind: str) -> tuple[str, ...]:
    if not name or "\x00" in name or "\\" in name:
        raise PackageError(f"unsafe {kind} member: {name!r}")
    pure = PurePosixPath(name)
    parts = pure.parts
    if pure.is_absolute() or not parts or any(part in {"", ".", ".."} for part in parts):
        raise PackageError(f"unsafe {kind} member: {name!r}")
    if ":" in parts[0]:
        raise PackageError(f"unsafe {kind} member: {name!r}")
    if _is_cache_name(parts):
        raise PackageError(f"cache {kind} member is forbidden: {name!r}")
    return tuple(parts)


def safe_extract(archive: str | Path, destination: str | Path) -> None:
    """Extract regular files/directories without trusting tar extraction paths."""

    archive_path = Path(archive)
    destination_path = Path(destination)
    destination_path.mkdir(parents=True, exist_ok=True)
    root = destination_path.resolve()
    seen: set[str] = set()
    try:
        handle_context = tarfile.open(archive_path, "r:gz")
    except (tarfile.TarError, OSError) as exc:
        raise PackageError(f"could not open source archive: {exc}") from exc
    with handle_context as handle:
        for member in handle.getmembers():
            parts = _safe_member_parts(member.name, kind="tar")
            normalized = "/".join(parts)
            if normalized in seen:
                raise PackageError(f"duplicate tar member: {member.name!r}")
            seen.add(normalized)
            target = destination_path.joinpath(*parts)
            resolved = target.resolve()
            if resolved != root and root not in resolved.parents:
                raise PackageError(f"unsafe tar member: {member.name!r}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=False)
                continue
            if not member.isfile():
                raise PackageError(f"unsupported tar member type: {member.name!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = handle.extractfile(member)
            if source is None:
                raise PackageError(f"could not read tar member: {member.name!r}")
            try:
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
            except OSError as exc:
                raise PackageError(f"could not extract tar member {member.name!r}: {exc}") from exc


def _tree_files(root: Path) -> list[Path]:
    result: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if _is_cache_name(relative.parts):
            raise PackageError(f"cache artifact is forbidden: {relative.as_posix()}")
        if path.is_symlink():
            raise PackageError(f"symlink is forbidden: {relative.as_posix()}")
        if path.is_file():
            result.append(path)
    return sorted(result, key=lambda path: path.relative_to(root).as_posix())


def package_file_hashes(root: str | Path) -> dict[str, str]:
    package_root = Path(root)
    return {
        path.relative_to(package_root).as_posix(): sha256_file(path)
        for path in _tree_files(package_root)
    }


def package_tree_sha256(root: str | Path) -> str:
    """Match the repository's length-delimited extracted-tree identity."""

    package_root = Path(root)
    digest = hashlib.sha256()
    for path in _tree_files(package_root):
        relative = path.relative_to(package_root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest().upper()


def runtime_source_tree_sha256(root: str | Path) -> tuple[str, list[str]]:
    """Hash executable Python/config sources exactly as the policy audits do."""

    package_root = Path(root)
    paths: list[Path] = []
    if (package_root / "main.py").is_file():
        paths.append(package_root / "main.py")
    paths.extend(path for path in package_root.glob("*.json") if path.is_file())
    ai_root = package_root / "ptcg_ai"
    if ai_root.is_dir():
        paths.extend(
            path
            for path in ai_root.rglob("*")
            if path.is_file() and path.suffix in {".py", ".json"}
        )
    paths = sorted(set(paths), key=lambda path: path.relative_to(package_root).as_posix())
    if not paths:
        raise PackageError("source runtime contains no executable/config sources")
    digest = hashlib.sha256()
    names: list[str] = []
    for path in paths:
        relative = path.relative_to(package_root).as_posix()
        names.append(relative)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest().upper(), names


def canonical_deck_sha256(cards: Iterable[int]) -> str:
    normalized = tuple(sorted(map(int, cards)))
    if len(normalized) != 60:
        raise PackageError(f"expected exactly 60 deck cards, got {len(normalized)}")
    return hashlib.sha256(",".join(map(str, normalized)).encode("ascii")).hexdigest().upper()


def _entrypoint_controls(main_path: Path) -> dict[str, str]:
    try:
        parsed = ast.parse(main_path.read_text(encoding="utf-8"), filename=str(main_path))
    except (OSError, SyntaxError) as exc:
        raise PackageError(f"could not parse pinned A2 entrypoint: {exc}") from exc
    found: dict[str, str] = {}
    for node in ast.walk(parsed):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Subscript):
            continue
        value = target.value
        if not (
            isinstance(value, ast.Attribute)
            and value.attr == "environ"
            and isinstance(value.value, ast.Name)
            and value.value.id == "os"
        ):
            continue
        key_node = target.slice
        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
            if key_node.value in found:
                raise PackageError(f"duplicate runtime control in main.py: {key_node.value}")
            if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
                raise PackageError(f"non-literal runtime control in main.py: {key_node.value}")
            found[key_node.value] = node.value.value
    controls = {key: found.get(key, "") for key in RUNTIME_CONTROLS}
    if controls != RUNTIME_CONTROLS:
        raise PackageError(f"pinned A2 runtime controls changed: {controls}")
    return dict(sorted(controls.items()))


def _validate_npz_member_names(path: Path) -> None:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            seen: set[str] = set()
            for info in archive.infolist():
                parts = _safe_member_parts(info.filename, kind="npz")
                if len(parts) != 1 or not parts[0].endswith(".npy") or info.is_dir():
                    raise PackageError(f"unsupported npz member: {info.filename!r}")
                if parts[0] in seen:
                    raise PackageError(f"duplicate npz member: {info.filename!r}")
                if info.flag_bits & 0x1:
                    raise PackageError(f"encrypted npz member is forbidden: {info.filename!r}")
                seen.add(parts[0])
    except (zipfile.BadZipFile, OSError) as exc:
        raise PackageError(f"candidate model is not a readable npz archive: {exc}") from exc


def validate_model(path: str | Path, *, expected_source: bool = False) -> dict[str, Any]:
    model_path = Path(path)
    if not model_path.is_file() or model_path.is_symlink():
        raise PackageError(f"candidate model must be a regular file: {model_path}")
    _validate_npz_member_names(model_path)
    try:
        with np.load(model_path, allow_pickle=False) as arrays:
            keys = set(arrays.files)
            expected_keys = set(EXPECTED_MODEL_SHAPES)
            if keys != expected_keys:
                missing = sorted(expected_keys - keys)
                extra = sorted(keys - expected_keys)
                raise PackageError(f"model array keys changed; missing={missing}, extra={extra}")
            schema_array = np.asarray(arrays["model_schema_version"])
            if schema_array.shape != () or not np.issubdtype(schema_array.dtype, np.number):
                raise PackageError("model_schema_version must be a numeric scalar")
            schema_value = float(schema_array.item())
            schema = int(schema_value)
            if not np.isfinite(schema_value) or schema_value != schema:
                raise PackageError("model_schema_version must be a finite integer")
            if schema not in SUPPORTED_MODEL_SCHEMAS:
                raise PackageError(f"A2 finalist model must use schema 2 or 3, got {schema}")
            if expected_source and schema != 2:
                raise PackageError(f"pinned A2 source model must use schema 2, got {schema}")
            shapes: dict[str, list[int]] = {}
            dtypes: dict[str, str] = {}
            for name in sorted(expected_keys):
                value = np.asarray(arrays[name])
                expected_shape = EXPECTED_MODEL_SHAPES[name]
                if name == "numeric_w" and schema == 3:
                    expected_shape = (13, expected_shape[1])
                if tuple(value.shape) != expected_shape:
                    raise PackageError(
                        f"model array {name} has shape {tuple(value.shape)}, expected {expected_shape}"
                    )
                if not np.issubdtype(value.dtype, np.number):
                    raise PackageError(f"model array {name} is not numeric: {value.dtype}")
                if not np.all(np.isfinite(value)):
                    raise PackageError(f"model array {name} contains non-finite values")
                shapes[name] = list(value.shape)
                dtypes[name] = str(value.dtype)
    except PackageError:
        raise
    except (OSError, ValueError, KeyError) as exc:
        raise PackageError(f"could not load candidate model safely: {exc}") from exc
    return {
        "sha256": sha256_file(model_path),
        "bytes": model_path.stat().st_size,
        "model_schema_version": schema,
        "array_count": len(shapes),
        "array_shapes": shapes,
        "array_dtypes": dtypes,
        "allow_pickle": False,
    }


def verify_source_runtime(stage: str | Path) -> dict[str, Any]:
    source = Path(stage)
    hashes = package_file_hashes(source)
    required = {
        "deck.csv",
        "main.py",
        MODEL_MEMBER,
        "ptcg_ai/__init__.py",
        "ptcg_ai/model.py",
        "ptcg_ai/tactical_shield.py",
    }
    if not required.issubset(hashes):
        raise PackageError(f"pinned A2 source is missing: {sorted(required - hashes.keys())}")
    exact = {
        "deck.csv": FROZEN_RAW_DECK_SHA256,
        "main.py": FROZEN_MAIN_SHA256,
        MODEL_MEMBER: FROZEN_SOURCE_MODEL_SHA256,
        "ptcg_ai/model.py": FROZEN_MODEL_RUNTIME_SHA256,
        "ptcg_ai/tactical_shield.py": FROZEN_TACTICAL_SHIELD_SHA256,
    }
    for name, expected in exact.items():
        if hashes[name] != expected:
            raise PackageError(f"pinned A2 hash mismatch for {name}: {hashes[name]}")
    full_tree = package_tree_sha256(source)
    if full_tree != FROZEN_SOURCE_TREE_SHA256:
        raise PackageError(f"pinned A2 extracted tree mismatch: {full_tree}")
    runtime_tree, runtime_files = runtime_source_tree_sha256(source)
    if runtime_tree != FROZEN_RUNTIME_SOURCE_TREE_SHA256:
        raise PackageError(f"pinned A2 runtime source tree mismatch: {runtime_tree}")
    try:
        cards = [
            int(line)
            for line in (source / "deck.csv").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, ValueError) as exc:
        raise PackageError(f"invalid pinned A2 deck: {exc}") from exc
    canonical = canonical_deck_sha256(cards)
    if canonical != FROZEN_CANONICAL_DECK_SHA256:
        raise PackageError(f"pinned A2 canonical deck mismatch: {canonical}")
    source_model = validate_model(source / MODEL_MEMBER, expected_source=True)
    return {
        "extracted_tree_sha256": full_tree,
        "runtime_source_tree_sha256": runtime_tree,
        "runtime_source_files": runtime_files,
        "file_count": len(hashes),
        "file_sha256": hashes,
        "source_model": source_model,
        "deck": {
            "raw_sha256": hashes["deck.csv"],
            "canonical_sha256": canonical,
            "card_count": len(cards),
            "multiset": {str(card): count for card, count in sorted(Counter(cards).items())},
        },
        "entrypoint_sha256": hashes["main.py"],
        "model_runtime_sha256": hashes["ptcg_ai/model.py"],
        "tactical_shield_sha256": hashes["ptcg_ai/tactical_shield.py"],
        "runtime_controls": _entrypoint_controls(source / "main.py"),
    }


def stage_finalist(
    source_archive: str | Path,
    candidate_model: str | Path,
    destination: str | Path,
) -> dict[str, Any]:
    destination_path = Path(destination)
    destination_path.mkdir(parents=True, exist_ok=True)
    if any(destination_path.iterdir()):
        raise PackageError(f"finalist stage must be empty: {destination_path}")
    safe_extract(source_archive, destination_path)
    source = verify_source_runtime(destination_path)
    before = dict(source["file_sha256"])
    candidate = validate_model(candidate_model)
    shutil.copyfile(candidate_model, destination_path / MODEL_MEMBER)
    if sha256_file(destination_path / MODEL_MEMBER) != candidate["sha256"]:
        raise PackageError("candidate model copy hash mismatch")
    packaged_model = validate_model(destination_path / MODEL_MEMBER)
    if packaged_model["sha256"] != candidate["sha256"] or packaged_model["model_schema_version"] != candidate["model_schema_version"]:
        raise PackageError("packaged model identity changed")
    after = package_file_hashes(destination_path)
    if set(after) != set(before):
        raise PackageError("runtime member set changed while replacing candidate model")
    altered = sorted(name for name in before if before[name] != after[name])
    if any(name != MODEL_MEMBER for name in altered):
        raise PackageError(f"non-model runtime files changed: {altered}")
    for name in before:
        if name != MODEL_MEMBER and before[name] != after[name]:  # pragma: no cover - explicit invariant
            raise PackageError(f"source runtime changed unexpectedly: {name}")
    runtime_tree, _ = runtime_source_tree_sha256(destination_path)
    if runtime_tree != FROZEN_RUNTIME_SOURCE_TREE_SHA256:
        raise PackageError("candidate changed the A2 runtime source tree")
    if sha256_file(destination_path / "deck.csv") != FROZEN_RAW_DECK_SHA256:
        raise PackageError("candidate changed the pinned A2 deck")
    return {
        "candidate_model": candidate,
        "candidate_tree_sha256": package_tree_sha256(destination_path),
        "candidate_file_sha256": after,
        "altered_source_members": altered,
        "only_policy_weights_replaced": all(name == MODEL_MEMBER for name in altered),
        "non_model_file_count": len(after) - 1,
        "source": source,
    }


def deterministic_tar(stage: str | Path, output: str | Path) -> None:
    stage_path = Path(stage)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in _tree_files(stage_path):
                    relative = path.relative_to(stage_path).as_posix()
                    info = archive.gettarinfo(str(path), arcname=relative)
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mode = 0o644
                    info.pax_headers = {}
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)


def sterile_init_smoke(archive: str | Path, expected_model_sha256: str, expected_schema: int) -> dict[str, Any]:
    """Import raw package source and perform only the 60-card/init handshake."""

    with tempfile.TemporaryDirectory(prefix="a2-finalist-smoke-") as directory:
        stage = Path(directory)
        safe_extract(archive, stage)
        code = f'''
import json
import os
import pathlib
import sys
sys.path.insert(0, {str(stage)!r})
namespace = {{"__name__": "submission_entry"}}
source = pathlib.Path("main.py").read_text(encoding="utf-8")
exec(compile(source, "main.py", "exec"), namespace)
agent = namespace["_AGENT"]
deck = namespace["agent"]({{"select": None, "current": None, "logs": []}})
policy = agent.policy
assert type(policy).__name__ == "NeuralPolicy"
assert len(deck) == 60
assert len(agent.deck) == 60
assert int(policy.model.feature_version) == {expected_schema!r}
controls = {{key: os.environ.get(key) for key in {sorted(RUNTIME_CONTROLS)!r}}}
assert controls == {dict(sorted(RUNTIME_CONTROLS.items()))!r}
print(json.dumps({{
    "deck_card_count": len(deck),
    "initialized_policy": type(policy).__name__,
    "model_schema_version": int(policy.model.feature_version),
    "runtime_controls": controls,
}}))
'''
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        for key in BEHAVIOR_ENV_KEYS:
            environment.pop(key, None)
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code],
            cwd=stage,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode:
            details = result.stderr.strip() or result.stdout.strip()
            raise PackageError(f"sterile A2 finalist init smoke failed: {details}")
        try:
            payload = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise PackageError(f"malformed sterile smoke output: {result.stdout!r}") from exc
        if sha256_file(stage / MODEL_MEMBER) != expected_model_sha256:
            raise PackageError("sterile smoke extracted the wrong candidate model")
        cache_free = not any(_is_cache_name(path.relative_to(stage).parts) for path in stage.rglob("*"))
        if not cache_free:
            raise PackageError("sterile smoke generated cache files")
        return {
            "passed": True,
            "isolated_python": True,
            "bytecode_disabled": True,
            "cache_free_after_smoke": True,
            **payload,
        }


def _validate_name(name: str) -> str:
    if not _NAME_PATTERN.fullmatch(name) or name in {".", ".."}:
        raise PackageError(f"invalid finalist name: {name!r}")
    return name


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_finalist(
    *,
    candidate_model: str | Path,
    name: str,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    source_archive: str | Path = DEFAULT_SOURCE_ARCHIVE,
) -> dict[str, Any]:
    candidate_path = Path(candidate_model).resolve()
    source_path = Path(source_archive).resolve()
    output_path = Path(output_dir).resolve()
    finalist_name = _validate_name(name)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if sha256_file(source_path) != FROZEN_SOURCE_ARCHIVE_SHA256:
        raise PackageError(
            "pinned authentic A2 source archive mismatch: "
            f"expected {FROZEN_SOURCE_ARCHIVE_SHA256}, got {sha256_file(source_path)}"
        )
    # Validate before creating output files.  Stage validation repeats this on
    # each fresh extraction and on the copied model.
    candidate = validate_model(candidate_path)
    output_path.mkdir(parents=True, exist_ok=True)
    archive_path = output_path / f"{finalist_name}.tar.gz"
    manifest_path = output_path / f"{finalist_name}.manifest.json"
    if archive_path.resolve() in {source_path, candidate_path} or manifest_path.resolve() in {source_path, candidate_path}:
        raise PackageError("output would overwrite a pinned input")

    with tempfile.TemporaryDirectory(prefix=f"a2-finalist-{finalist_name}-", dir=output_path) as directory:
        work = Path(directory)
        first_stage = work / "first"
        second_stage = work / "second"
        first = stage_finalist(source_path, candidate_path, first_stage)
        second = stage_finalist(source_path, candidate_path, second_stage)
        if first != second:
            raise PackageError("fresh A2 finalist stages differ")
        first_archive = work / "first.tar.gz"
        second_archive = work / "second.tar.gz"
        deterministic_tar(first_stage, first_archive)
        deterministic_tar(second_stage, second_archive)
        first_hash = sha256_file(first_archive)
        second_hash = sha256_file(second_archive)
        if first_hash != second_hash:
            raise PackageError(
                f"deterministic A2 finalist build mismatch: first={first_hash}, second={second_hash}"
            )
        smoke = sterile_init_smoke(first_archive, candidate["sha256"], candidate["model_schema_version"])
        with tempfile.TemporaryDirectory(prefix="a2-finalist-verify-", dir=work) as verify_directory:
            verified_stage = Path(verify_directory)
            safe_extract(first_archive, verified_stage)
            verified_hashes = package_file_hashes(verified_stage)
            if verified_hashes != first["candidate_file_sha256"]:
                raise PackageError("fresh finalist archive extraction changed package files")
            if package_tree_sha256(verified_stage) != first["candidate_tree_sha256"]:
                raise PackageError("fresh finalist archive extraction changed package tree")
        staged_output = work / "final.tar.gz"
        shutil.copyfile(first_archive, staged_output)

        manifest = {
            "schema_version": 1,
            "status": "packaged",
            "label": finalist_name,
            "source_runtime": {
                "archive": str(source_path),
                "archive_sha256": FROZEN_SOURCE_ARCHIVE_SHA256,
                "extracted_tree_sha256": first["source"]["extracted_tree_sha256"],
                "runtime_source_tree_sha256": first["source"]["runtime_source_tree_sha256"],
                "source_model_sha256": first["source"]["source_model"]["sha256"],
                "entrypoint_sha256": first["source"]["entrypoint_sha256"],
                "model_runtime_sha256": first["source"]["model_runtime_sha256"],
                "tactical_shield_sha256": first["source"]["tactical_shield_sha256"],
                "deck": first["source"]["deck"],
            },
            "candidate_model": {
                "input": str(candidate_path),
                **candidate,
            },
            "runtime": {
                "cloned_from_authentic_a2_shield": True,
                "runtime_controls": first["source"]["runtime_controls"],
                "temperature": 0,
                "native_search": False,
                "tactical_shield": True,
                "tactical_shield_interventions": [
                    "setup_bench_basic",
                    "nullified_attack",
                    "end_with_productive_attack",
                ],
                "only_policy_weights_replaced": first["only_policy_weights_replaced"],
                "altered_source_members": first["altered_source_members"],
                "non_model_file_count": first["non_model_file_count"],
                "runtime_source_tree_sha256": first["source"]["runtime_source_tree_sha256"],
            },
            "output": {
                "archive": str(archive_path),
                "archive_sha256": first_hash,
                "archive_bytes": staged_output.stat().st_size,
                "extracted_tree_sha256": first["candidate_tree_sha256"],
                "model_sha256": candidate["sha256"],
            },
            "verification": {
                "fresh_stage_count": 2,
                "deterministic_tar": True,
                "first_archive_sha256": first_hash,
                "second_archive_sha256": second_hash,
                "safe_archive_extraction": True,
                "path_traversal_rejected": True,
                "cache_members_rejected": True,
                "cache_free_package": True,
                "non_model_files_byte_identical": True,
                "sterile_init_smoke": smoke,
            },
            "deployment": {
                "games_run": False,
                "uploaded": False,
                "cloud_started": False,
            },
        }
        staged_manifest = work / "final.manifest.json"
        _write_json(staged_manifest, manifest)
        os.replace(staged_output, archive_path)
        os.replace(staged_manifest, manifest_path)
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-model", type=Path, required=True)
    parser.add_argument("--name", required=True, help="filesystem-safe finalist label")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--source-archive", type=Path, default=DEFAULT_SOURCE_ARCHIVE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = build_finalist(
            candidate_model=args.candidate_model,
            name=args.name,
            output_dir=args.output_dir,
            source_archive=args.source_archive,
        )
    except (PackageError, FileNotFoundError, OSError) as exc:
        print(json.dumps({"status": "failed_closed", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
