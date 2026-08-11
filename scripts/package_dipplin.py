#!/usr/bin/env python3
"""Build deterministic, minimal FESTIVAL-D0/FESTIVAL-D1 submissions.

This command is packaging-only: it does not run matches, upload an archive, or
start external resources.  Every package is assembled twice from audited
source files and the two byte identities must agree before either is emitted.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_CG_ROOT = ROOT / "freshstart" / "submission_template" / "cg"
DEFAULT_OUTPUT_DIRS = {
    "d0": ROOT / "artifacts" / "dipplin_d0",
    "d1": ROOT / "artifacts" / "dipplin_d1",
}
DEFAULT_NAME = "submission"

# These are the exact files in the current official competition template.  In
# particular, do not silently fall back to vendor/cg: that directory contains
# an older set of native binaries in this repository.
OFFICIAL_CG_SHA256 = {
    "__init__.py": "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855",
    "api.py": "593F1298E52A635F90F8F505A52113E9AF114F444C293404E37906F18EE06CED",
    "cg.dll": "9EA2B0A751029689BFF3DDCCB5F29A98EDD46961DAD264490ED121EF704FB500",
    "game.py": "3BD3D4F4A369A11E6D2F5DA9094CF15EBC410A2221835E6417B7CFF4883F1FC2",
    "libcg-arm64.so": "030B4728CE9FB9E90B75830B7CF7236F71859732A05EC4A377078EEE0421BBE5",
    "libcg.dylib": "77BB978A8129B094452679E0DAF0DA69593AFDA7331685F4642C0D4A94D39D82",
    "libcg.so": "FFD89BF923525A3E6FEB5E6201E96A866C0F456895499ED5C4A566303CAAE67C",
    "sim.py": "1555F57F5D22BF4C09D70E0E667A916E575E68C9DD1DE9EAD34BA5E7E4968655",
    "utils.py": "60F29665CEE0A88525D6F0383BC45959A6262D16FE35EF380AECE1E0EA13C49B",
}

D0_DIPPLIN_MODULES = frozenset(
    {
        "__init__.py",
        "cards.py",
        "damage.py",
        "imitation.py",
        "plan.py",
        "policy.py",
        "resolvers.py",
        "snapshot.py",
        "telemetry.py",
    }
)
D1_DIPPLIN_MODULES = D0_DIPPLIN_MODULES | {"search.py"}
_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
)


class PackageError(RuntimeError):
    """A fail-closed Dipplin package construction error."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _is_cache_name(parts: Iterable[str]) -> bool:
    names = tuple(parts)
    lowered = tuple(part.lower() for part in names)
    return (
        any(part in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"} for part in lowered)
        or (bool(names) and Path(names[-1]).suffix.lower() in {".pyc", ".pyo"})
        or (bool(names) and names[-1] == ".DS_Store")
    )


def _windows_safe_part(part: str) -> bool:
    if not part or part[-1:] in {" ", "."}:
        return False
    if any(ord(character) < 32 for character in part):
        return False
    if any(character in '<>:"|?*' for character in part):
        return False
    stem = part.split(".", 1)[0].upper()
    return stem not in _WINDOWS_RESERVED


def _safe_member_parts(name: str, *, kind: str) -> tuple[str, ...]:
    if not name or "\x00" in name or "\\" in name:
        raise PackageError(f"unsafe {kind} member: {name!r}")
    pure = PurePosixPath(name)
    parts = pure.parts
    if pure.is_absolute() or not parts or any(part in {"", ".", ".."} for part in parts):
        raise PackageError(f"unsafe {kind} member: {name!r}")
    if not all(_windows_safe_part(part) for part in parts):
        raise PackageError(f"Windows-incompatible {kind} member: {name!r}")
    if _is_cache_name(parts):
        raise PackageError(f"cache {kind} member is forbidden: {name!r}")
    return tuple(parts)


def safe_extract(archive: str | Path, destination: str | Path) -> None:
    """Extract only unique, portable regular files/directories from a tar."""

    archive_path = Path(archive)
    destination_path = Path(destination)
    destination_path.mkdir(parents=True, exist_ok=True)
    root = destination_path.resolve()
    seen: set[str] = set()
    try:
        opened = tarfile.open(archive_path, "r:gz")
    except (tarfile.TarError, OSError) as exc:
        raise PackageError(f"could not open archive: {exc}") from exc
    with opened as handle:
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
                try:
                    target.mkdir(parents=True, exist_ok=False)
                except OSError as exc:
                    raise PackageError(f"could not extract directory {member.name!r}: {exc}") from exc
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


def _tree_files(root: str | Path) -> list[Path]:
    package_root = Path(root)
    if not package_root.is_dir():
        raise PackageError(f"package tree does not exist: {package_root}")
    result: list[Path] = []
    for path in package_root.rglob("*"):
        relative = path.relative_to(package_root)
        _safe_member_parts(relative.as_posix(), kind="tree")
        if path.is_symlink():
            raise PackageError(f"symlink is forbidden: {relative.as_posix()}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise PackageError(f"unsupported package entry: {relative.as_posix()}")
        result.append(path)
    return sorted(result, key=lambda item: item.relative_to(package_root).as_posix())


def package_file_manifest(root: str | Path) -> dict[str, dict[str, int | str]]:
    package_root = Path(root)
    return {
        path.relative_to(package_root).as_posix(): {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in _tree_files(package_root)
    }


def package_tree_sha256(root: str | Path) -> str:
    """Return a length-delimited identity for all extracted package files."""

    package_root = Path(root)
    digest = hashlib.sha256()
    for path in _tree_files(package_root):
        relative = path.relative_to(package_root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest().upper()


def runtime_source_tree_sha256(root: str | Path) -> tuple[str, list[str]]:
    """Hash executable Python/config sources separately from native binaries."""

    package_root = Path(root)
    paths = [
        path
        for path in _tree_files(package_root)
        if path.suffix in {".py", ".json"}
    ]
    if not paths:
        raise PackageError("package contains no executable/config runtime sources")
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


def _deck_bytes() -> tuple[bytes, str, str, int]:
    # Importing cards is safe here (it has no engine dependency), and prevents
    # the packager from maintaining a second copy of the audited 60-card list.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from ptcg_ai.dipplin.cards import DECK_CSV_SHA256, DECK_ID, EXACT_DECK, deck_csv_bytes

    payload = deck_csv_bytes()
    if len(EXACT_DECK) != 60:
        raise PackageError(f"audited Dipplin deck has {len(EXACT_DECK)} cards, expected 60")
    if _sha256_bytes(payload) != DECK_CSV_SHA256.upper():
        raise PackageError("audited Dipplin deck.csv identity changed")
    return payload, DECK_ID, DECK_CSV_SHA256.upper(), len(EXACT_DECK)


def _validated_source(path: Path, *, expected_sha256: str | None = None) -> Path:
    if path.is_symlink():
        raise PackageError(f"source symlink is forbidden: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    if expected_sha256 is not None:
        actual = sha256_file(path)
        if actual != expected_sha256:
            raise PackageError(
                f"official source hash mismatch for {path.name}: "
                f"expected {expected_sha256}, got {actual}"
            )
    return path


def _entrypoint_bytes(variant: str) -> bytes:
    if variant == "d0":
        control = 'os.environ["PTCG_DIPPLIN_SEARCH"] = "0"'
    elif variant == "d1":
        # D1 defaults on but remains explicitly disableable.  With the value
        # set to zero it instantiates the exact same D0 planner/runtime.
        control = 'os.environ.setdefault("PTCG_DIPPLIN_SEARCH", "1")'
    else:  # pragma: no cover - guarded by the public builder
        raise PackageError(f"unsupported Dipplin variant: {variant!r}")
    return (
        '"""Direct Festival Lead competition entry point."""\n\n'
        "import os\n\n"
        f"{control}\n\n"
        "from ptcg_ai.dipplin.policy import DipplinCompetitionAgent\n\n"
        "_AGENT = DipplinCompetitionAgent()\n\n\n"
        "def agent(obs_dict: dict) -> list[int]:\n"
        "    return _AGENT(obs_dict)\n"
    ).encode("utf-8")


def _stage_sources(variant: str) -> dict[str, Path | bytes]:
    modules = D0_DIPPLIN_MODULES if variant == "d0" else D1_DIPPLIN_MODULES
    sources: dict[str, Path | bytes] = {
        "main.py": _entrypoint_bytes(variant),
        "ptcg_ai/__init__.py": _validated_source(ROOT / "ptcg_ai" / "__init__.py"),
        "ptcg_ai/safety.py": _validated_source(ROOT / "ptcg_ai" / "safety.py"),
    }
    deck, _, _, _ = _deck_bytes()
    sources["deck.csv"] = deck
    sources["ptcg_ai/dipplin/imitation_weights.json"] = ROOT / "ptcg_ai" / "dipplin" / "imitation_weights.json"
    for member in sorted(modules):
        sources[f"ptcg_ai/dipplin/{member}"] = _validated_source(ROOT / "ptcg_ai" / "dipplin" / member)
    for member, expected_hash in sorted(OFFICIAL_CG_SHA256.items()):
        sources[f"cg/{member}"] = _validated_source(
            OFFICIAL_CG_ROOT / member,
            expected_sha256=expected_hash,
        )
    return sources


def stage_package(variant: str, destination: str | Path) -> dict[str, Any]:
    """Copy the allowlisted runtime into a new, empty package directory."""

    normalized_variant = variant.lower()
    if normalized_variant not in DEFAULT_OUTPUT_DIRS:
        raise PackageError(f"unsupported Dipplin variant: {variant!r}")
    destination_path = Path(destination)
    destination_path.mkdir(parents=True, exist_ok=True)
    if any(destination_path.iterdir()):
        raise PackageError(f"Dipplin stage must be empty: {destination_path}")
    sources = _stage_sources(normalized_variant)
    seen: set[str] = set()
    for relative, source in sorted(sources.items()):
        parts = _safe_member_parts(relative, kind="stage")
        normalized = "/".join(parts)
        if normalized in seen:
            raise PackageError(f"duplicate staged member: {normalized}")
        seen.add(normalized)
        target = destination_path.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(source, bytes):
            target.write_bytes(source)
        else:
            shutil.copyfile(source, target)

    manifest = package_file_manifest(destination_path)
    forbidden = [
        name
        for name in manifest
        if name.endswith((".npz", ".npy", ".pkl", ".pickle"))
        or any(token in name.lower() for token in ("grim", "a2_", "policy_weights"))
    ]
    if forbidden:
        raise PackageError(f"forbidden learned/legacy runtime members: {forbidden}")
    expected_members = set(sources)
    if set(manifest) != expected_members:
        raise PackageError("staged Dipplin runtime member set changed")
    runtime_hash, runtime_members = runtime_source_tree_sha256(destination_path)
    return {
        "variant": normalized_variant,
        "file_manifest": manifest,
        "member_count": len(manifest),
        "extracted_tree_sha256": package_tree_sha256(destination_path),
        "runtime_source_tree_sha256": runtime_hash,
        "runtime_source_members": runtime_members,
    }


def deterministic_tar(stage: str | Path, output: str | Path) -> None:
    stage_path = Path(stage)
    output_path = Path(output)
    files = _tree_files(stage_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in files:
                    relative = path.relative_to(stage_path).as_posix()
                    info = archive.gettarinfo(str(path), arcname=relative)
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mode = 0o644
                    info.pax_headers = {}
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)


def audit_archive(archive: str | Path, expected_members: Iterable[str]) -> dict[str, Any]:
    """Verify archive paths, member types/order, and normalized tar metadata."""

    archive_path = Path(archive)
    expected = sorted(expected_members)
    with tarfile.open(archive_path, "r:gz") as handle:
        members = handle.getmembers()
        names = ["/".join(_safe_member_parts(member.name, kind="tar")) for member in members]
        if len(names) != len(set(names)):
            raise PackageError("archive contains duplicate members")
        if names != sorted(names):
            raise PackageError("archive members are not sorted")
        if names != expected:
            raise PackageError("archive member set differs from staged runtime")
        for member in members:
            if not member.isfile():
                raise PackageError(f"archive member is not a regular file: {member.name}")
            if (
                member.mtime != 0
                or member.uid != 0
                or member.gid != 0
                or member.uname != ""
                or member.gname != ""
                or member.mode != 0o644
                or member.pax_headers
            ):
                raise PackageError(f"archive metadata is not normalized: {member.name}")
    header = archive_path.read_bytes()[:10]
    if len(header) != 10 or header[:2] != b"\x1f\x8b" or header[4:8] != b"\0\0\0\0":
        raise PackageError("gzip header is not deterministic (mtime must be zero)")
    # FNAME is bit 3.  The package path must not leak into the gzip header.
    if header[3] & 0x08:
        raise PackageError("gzip header contains a filename")
    return {
        "passed": True,
        "regular_files_only": True,
        "sorted_members": True,
        "portable_member_names": True,
        "normalized_tar_metadata": True,
        "gzip_mtime_zero": True,
        "gzip_filename_empty": True,
        "member_count": len(expected),
    }


def sterile_import_smoke(archive: str | Path, variant: str) -> dict[str, Any]:
    """Safely extract and import the direct entrypoint under ``python -I -B``."""

    deck, deck_id, deck_sha256, deck_count = _deck_bytes()
    with tempfile.TemporaryDirectory(prefix=f"dipplin-{variant}-sterile-") as directory:
        stage = Path(directory)
        safe_extract(archive, stage)
        code = f'''
import json
import pathlib
import sys
sys.path.insert(0, {str(stage)!r})
namespace = {{"__name__": "submission_entry"}}
source = pathlib.Path("main.py").read_text(encoding="utf-8")
exec(compile(source, "main.py", "exec"), namespace)
runtime = namespace["_AGENT"]
deck = namespace["agent"]({{"select": None, "current": None, "logs": []}})
assert type(runtime).__name__ == "DipplinCompetitionAgent"
assert type(runtime).__module__ == "ptcg_ai.dipplin.policy"
assert len(deck) == {deck_count!r}
assert tuple(deck) == tuple(runtime.deck)
print(json.dumps({{
    "agent_class": type(runtime).__name__,
    "agent_module": type(runtime).__module__,
    "deck_card_count": len(deck),
    "search_enabled": bool(runtime.search_enabled),
}}))
'''
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        if variant == "d0":
            # Prove that the D0 archive cannot accidentally be enabled by a
            # deployment environment inherited from a previous D1 run.
            environment["PTCG_DIPPLIN_SEARCH"] = "1"
        else:
            environment.pop("PTCG_DIPPLIN_SEARCH", None)
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
            raise PackageError(f"sterile Dipplin import failed: {details}")
        try:
            payload = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise PackageError(f"malformed sterile smoke output: {result.stdout!r}") from exc
        expected_search = variant == "d1"
        if payload.get("search_enabled") is not expected_search:
            raise PackageError(f"{variant} entrypoint selected the wrong search mode")
        if (stage / "deck.csv").read_bytes() != deck:
            raise PackageError("sterile extraction changed deck.csv")
        if sha256_file(stage / "deck.csv") != deck_sha256:
            raise PackageError("sterile extraction changed deck.csv identity")
        cache_members = [
            path.relative_to(stage).as_posix()
            for path in stage.rglob("*")
            if _is_cache_name(path.relative_to(stage).parts)
        ]
        if cache_members:
            raise PackageError(f"sterile import generated cache files: {cache_members}")
        return {
            "passed": True,
            "isolated_python": True,
            "bytecode_disabled": True,
            "command_flags": ["-I", "-B"],
            "cache_free_after_import": True,
            "deck_id": deck_id,
            "deck_csv_sha256": deck_sha256,
            **payload,
        }


def _host_linux_amd64_gate() -> dict[str, Any]:
    system = platform.system()
    machine = platform.machine()
    eligible = system == "Linux" and machine.lower() in {"x86_64", "amd64"}
    reason = (
        "packager does not run games; attach a complete-game evaluator result"
        if eligible
        else f"build host is {system}/{machine}, not Linux/amd64"
    )
    return {
        "required_for_release": True,
        "host_system": system,
        "host_machine": machine,
        "eligible_build_host": eligible,
        "complete_game_attempted": False,
        "complete_game_verified": False,
        "status": "pending_external_complete_game",
        "reason": reason,
    }


def _validate_name(name: str) -> str:
    candidate = name[:-7] if name.endswith(".tar.gz") else name
    if not _NAME_PATTERN.fullmatch(candidate) or candidate in {".", ".."}:
        raise PackageError(f"invalid package name: {name!r}")
    if not _windows_safe_part(candidate):
        raise PackageError(f"Windows-incompatible package name: {name!r}")
    return candidate


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_package(
    *,
    variant: str = "d0",
    name: str = DEFAULT_NAME,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Build and audit one deterministic Dipplin submission archive."""

    normalized_variant = variant.lower()
    if normalized_variant not in DEFAULT_OUTPUT_DIRS:
        raise PackageError(f"unsupported Dipplin variant: {variant!r}")
    package_name = _validate_name(name)
    output_path = Path(output_dir or DEFAULT_OUTPUT_DIRS[normalized_variant]).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    archive_path = output_path / f"{package_name}.tar.gz"
    manifest_path = output_path / f"{package_name}.manifest.json"

    with tempfile.TemporaryDirectory(prefix=f"dipplin-{normalized_variant}-", dir=output_path) as directory:
        work = Path(directory)
        first_stage = work / "first"
        second_stage = work / "second"
        first = stage_package(normalized_variant, first_stage)
        second = stage_package(normalized_variant, second_stage)
        if first != second:
            raise PackageError("fresh Dipplin package stages differ")

        first_archive = work / "first.tar.gz"
        second_archive = work / "second.tar.gz"
        deterministic_tar(first_stage, first_archive)
        deterministic_tar(second_stage, second_archive)
        first_hash = sha256_file(first_archive)
        second_hash = sha256_file(second_archive)
        if first_hash != second_hash:
            raise PackageError(
                f"deterministic Dipplin build mismatch: first={first_hash}, second={second_hash}"
            )
        archive_audit = audit_archive(first_archive, first["file_manifest"])
        smoke = sterile_import_smoke(first_archive, normalized_variant)

        verify_stage = work / "verified"
        safe_extract(first_archive, verify_stage)
        if package_file_manifest(verify_stage) != first["file_manifest"]:
            raise PackageError("fresh archive extraction changed package files")
        if package_tree_sha256(verify_stage) != first["extracted_tree_sha256"]:
            raise PackageError("fresh archive extraction changed package tree")
        verified_runtime_hash, verified_runtime_members = runtime_source_tree_sha256(verify_stage)
        if verified_runtime_hash != first["runtime_source_tree_sha256"]:
            raise PackageError("fresh archive extraction changed runtime source tree")
        if verified_runtime_members != first["runtime_source_members"]:
            raise PackageError("fresh archive extraction changed runtime source members")

        staged_output = work / "final.tar.gz"
        shutil.copyfile(first_archive, staged_output)
        deck, deck_id, deck_sha256, deck_count = _deck_bytes()
        manifest = {
            "schema_version": 1,
            "status": "packaged",
            "variant": normalized_variant,
            "runtime": {
                "family": "dedicated_dipplin",
                "direct_entrypoint": True,
                "search_default": normalized_variant == "d1",
                "d1_disable_environment": "PTCG_DIPPLIN_SEARCH=0" if normalized_variant == "d1" else None,
                "learned_weights_included": True,
                "grim_runtime_included": False,
                "runtime_source_tree_sha256": first["runtime_source_tree_sha256"],
                "runtime_source_members": first["runtime_source_members"],
            },
            "deck": {
                "deck_id": deck_id,
                "card_count": deck_count,
                "deck_csv_sha256": deck_sha256,
                "newline_terminated": deck.endswith(b"\n"),
            },
            "engine": {
                "source": str(OFFICIAL_CG_ROOT),
                "official_template_file_sha256": dict(sorted(OFFICIAL_CG_SHA256.items())),
                "linux_amd64_member": "cg/libcg.so",
                "linux_amd64_sha256": OFFICIAL_CG_SHA256["libcg.so"],
            },
            "output": {
                "archive": str(archive_path),
                "manifest": str(manifest_path),
                "archive_bytes": staged_output.stat().st_size,
                "archive_sha256": first_hash,
                "extracted_tree_sha256": first["extracted_tree_sha256"],
                "member_count": first["member_count"],
                "file_manifest": first["file_manifest"],
            },
            "verification": {
                "fresh_stage_count": 2,
                "deterministic_double_build": True,
                "first_archive_sha256": first_hash,
                "second_archive_sha256": second_hash,
                "safe_archive_extraction": True,
                "archive_structure": archive_audit,
                "sterile_import": smoke,
                "linux_amd64_complete_game": _host_linux_amd64_gate(),
            },
            "deployment": {
                "games_run_by_packager": False,
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
    parser.add_argument("--variant", choices=sorted(DEFAULT_OUTPUT_DIRS), default="d0")
    parser.add_argument("--name", default=DEFAULT_NAME, help="portable archive basename")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="default: artifacts/dipplin_<variant>",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = build_package(variant=args.variant, name=args.name, output_dir=args.output_dir)
    except (PackageError, FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "failed_closed", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
