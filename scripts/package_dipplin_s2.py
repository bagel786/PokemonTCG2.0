#!/usr/bin/env python3
"""Build the deterministic, minimal FESTIVAL-S2 competition submission.

This dedicated packager deliberately has no policy-variant switch.  It stages
the audited D1 runtime allowlist from :mod:`scripts.package_dipplin`, adds a
generated entrypoint that pins every S2 competition control, and proves two
fresh stages produce one byte-identical archive.  It does not run matches,
upload the archive, or start external resources.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import package_dipplin as audited  # noqa: E402


if audited.ROOT != ROOT:
    raise RuntimeError("audited Dipplin packager resolved a different repository root")

DEFAULT_OUTPUT_DIR = ROOT / "artifacts" / "dipplin_s2"
DEFAULT_NAME = audited.DEFAULT_NAME
OFFICIAL_CG_ROOT = audited.OFFICIAL_CG_ROOT
OFFICIAL_CG_SHA256 = audited.OFFICIAL_CG_SHA256
D1_DIPPLIN_MODULES = audited.D1_DIPPLIN_MODULES
S2_DIPPLIN_MODULES = frozenset(D1_DIPPLIN_MODULES)
S2_SOURCE_MARKERS = {
    "policy.py": ("PTCG_DIPPLIN_S2", "s2_enabled"),
    "search.py": ("s2_enabled", "s2_pre_attack_sequence_proof"),
}
ENTRYPOINT_CONTROLS = (
    ("PTCG_DIPPLIN_SEARCH", "1"),
    ("PTCG_DIPPLIN_SECOND_OPENING_V2", "1"),
    ("PTCG_DIPPLIN_S2", "1"),
    ("PTCG_DIPPLIN_GO_FIRST", "1"),
    ("PTCG_DIPPLIN_ROUTE_V2", "0"),
    ("PTCG_DIPPLIN_WORLDS", "2"),
)

PackageError = audited.PackageError
sha256_file = audited.sha256_file
safe_extract = audited.safe_extract
package_file_manifest = audited.package_file_manifest
package_tree_sha256 = audited.package_tree_sha256
runtime_source_tree_sha256 = audited.runtime_source_tree_sha256
deterministic_tar = audited.deterministic_tar
audit_archive = audited.audit_archive


def _entrypoint_bytes() -> bytes:
    """Return an entrypoint that overwrites every inherited policy control."""

    control = "\n".join(
        f"os.environ[{json.dumps(name)}] = {json.dumps(value)}"
        for name, value in ENTRYPOINT_CONTROLS
    )
    return (
        '"""Direct Festival S2 competition entry point."""\n\n'
        "import os\n\n"
        f"{control}\n\n"
        "from ptcg_ai.dipplin.policy import DipplinCompetitionAgent\n\n"
        "_AGENT = DipplinCompetitionAgent()\n\n\n"
        "def agent(obs_dict: dict) -> list[int]:\n"
        "    return _AGENT(obs_dict)\n"
    ).encode("utf-8")


def _source_manifest_entry(relative: str, source: Path | bytes) -> dict[str, int | str]:
    if isinstance(source, bytes):
        if relative == "main.py":
            origin = "generated:s2_entrypoint"
        elif relative == "deck.csv":
            origin = "generated:audited_exact_deck"
        else:
            origin = "generated"
        payload = source
    else:
        try:
            origin = source.relative_to(ROOT).as_posix()
        except ValueError as exc:
            raise PackageError(f"S2 source escaped repository root: {source}") from exc
        payload = source.read_bytes()
    return {
        "origin": origin,
        "bytes": len(payload),
        "sha256": audited._sha256_bytes(payload),
    }


def _stage_sources() -> dict[str, Path | bytes]:
    if S2_DIPPLIN_MODULES != D1_DIPPLIN_MODULES:
        raise PackageError("S2 module allowlist diverged from audited D1 allowlist")
    if not set(S2_SOURCE_MARKERS).issubset(S2_DIPPLIN_MODULES):
        raise PackageError("S2-gated modules are absent from the D1 allowlist")

    sources: dict[str, Path | bytes] = {
        "main.py": _entrypoint_bytes(),
        "ptcg_ai/__init__.py": audited._validated_source(
            ROOT / "ptcg_ai" / "__init__.py"
        ),
        "ptcg_ai/safety.py": audited._validated_source(
            ROOT / "ptcg_ai" / "safety.py"
        ),
    }
    deck, _, _, _ = audited._deck_bytes()
    sources["deck.csv"] = deck
    for member in sorted(S2_DIPPLIN_MODULES):
        source = audited._validated_source(ROOT / "ptcg_ai" / "dipplin" / member)
        markers = S2_SOURCE_MARKERS.get(member, ())
        if markers:
            text = source.read_text(encoding="utf-8")
            missing = [marker for marker in markers if marker not in text]
            if missing:
                raise PackageError(
                    f"S2 source gate is missing from {member}: {missing}"
                )
        sources[f"ptcg_ai/dipplin/{member}"] = source
    for member, expected_hash in sorted(OFFICIAL_CG_SHA256.items()):
        sources[f"cg/{member}"] = audited._validated_source(
            OFFICIAL_CG_ROOT / member,
            expected_sha256=expected_hash,
        )
    return sources


def stage_package(destination: str | Path) -> dict[str, Any]:
    """Copy the exact S2 runtime allowlist into a new empty directory."""

    destination_path = Path(destination)
    destination_path.mkdir(parents=True, exist_ok=True)
    if any(destination_path.iterdir()):
        raise PackageError(f"Dipplin S2 stage must be empty: {destination_path}")

    sources = _stage_sources()
    source_manifest: dict[str, dict[str, int | str]] = {}
    seen: set[str] = set()
    for relative, source in sorted(sources.items()):
        parts = audited._safe_member_parts(relative, kind="stage")
        normalized = "/".join(parts)
        if normalized in seen:
            raise PackageError(f"duplicate staged member: {normalized}")
        seen.add(normalized)
        source_manifest[normalized] = _source_manifest_entry(normalized, source)
        target = destination_path.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(source, bytes):
            target.write_bytes(source)
        else:
            shutil.copyfile(source, target)

    file_manifest = package_file_manifest(destination_path)
    if set(file_manifest) != set(sources):
        raise PackageError("staged S2 runtime member set changed")
    forbidden = [
        name
        for name in file_manifest
        if name.endswith((".npz", ".npy", ".pkl", ".pickle"))
        or any(token in name.lower() for token in ("grim", "a2_", "policy_weights"))
    ]
    if forbidden:
        raise PackageError(f"forbidden learned/legacy S2 runtime members: {forbidden}")
    for relative, details in source_manifest.items():
        staged = file_manifest[relative]
        if (
            staged["bytes"] != details["bytes"]
            or staged["sha256"] != details["sha256"]
        ):
            raise PackageError(f"staging changed S2 source bytes: {relative}")

    runtime_hash, runtime_members = runtime_source_tree_sha256(destination_path)
    return {
        "variant": "s2",
        "module_allowlist": sorted(S2_DIPPLIN_MODULES),
        "source_file_manifest": source_manifest,
        "file_manifest": file_manifest,
        "member_count": len(file_manifest),
        "extracted_tree_sha256": package_tree_sha256(destination_path),
        "runtime_source_tree_sha256": runtime_hash,
        "runtime_source_members": runtime_members,
    }


def sterile_import_smoke(archive: str | Path) -> dict[str, Any]:
    """Import S2 from a safe extraction under isolated, bytecode-free Python."""

    deck, deck_id, deck_sha256, deck_count = audited._deck_bytes()
    with tempfile.TemporaryDirectory(prefix="dipplin-s2-sterile-") as directory:
        stage = Path(directory)
        safe_extract(archive, stage)
        before = package_file_manifest(stage)
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
controller = runtime._search_controller()
assert type(runtime).__name__ == "DipplinCompetitionAgent"
assert type(runtime).__module__ == "ptcg_ai.dipplin.policy"
assert len(deck) == {deck_count!r}
assert tuple(deck) == tuple(runtime.deck)
print(json.dumps({{
    "agent_class": type(runtime).__name__,
    "agent_module": type(runtime).__module__,
    "deck_card_count": len(deck),
    "search_enabled": bool(runtime.search_enabled),
    "second_opening_v2": bool(runtime.planner.second_opening_v2),
    "s2_enabled": bool(runtime.s2_enabled),
    "search_controller_s2_enabled": bool(controller.s2_enabled),
    "go_first": bool(runtime.go_first),
    "route_v2_enabled": bool(runtime.planner.route_v2_enabled),
    "search_worlds": int(controller.config.worlds),
}}))
'''
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        # Begin with the opposite of every evaluated control.  main.py must
        # overwrite all six values before importing policy code.
        environment.update(
            {
                "PTCG_DIPPLIN_SEARCH": "0",
                "PTCG_DIPPLIN_SECOND_OPENING_V2": "0",
                "PTCG_DIPPLIN_S2": "0",
                "PTCG_DIPPLIN_GO_FIRST": "0",
                "PTCG_DIPPLIN_ROUTE_V2": "1",
                "PTCG_DIPPLIN_WORLDS": "4",
            }
        )
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
            raise PackageError(f"sterile Dipplin S2 import failed: {details}")
        try:
            payload = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise PackageError(
                f"malformed sterile S2 smoke output: {result.stdout!r}"
            ) from exc
        expected = {
            "search_enabled": True,
            "second_opening_v2": True,
            "s2_enabled": True,
            "search_controller_s2_enabled": True,
            "go_first": True,
            "route_v2_enabled": False,
            "search_worlds": 2,
        }
        mismatches = {
            key: {"expected": value, "actual": payload.get(key)}
            for key, value in expected.items()
            if payload.get(key) != value
        }
        if mismatches:
            raise PackageError(f"S2 entrypoint controls failed closed: {mismatches}")
        if (stage / "deck.csv").read_bytes() != deck:
            raise PackageError("sterile S2 extraction changed deck.csv")
        if sha256_file(stage / "deck.csv") != deck_sha256:
            raise PackageError("sterile S2 extraction changed deck.csv identity")
        cache_members = [
            path.relative_to(stage).as_posix()
            for path in stage.rglob("*")
            if audited._is_cache_name(path.relative_to(stage).parts)
        ]
        if cache_members:
            raise PackageError(f"sterile S2 import generated cache files: {cache_members}")
        if package_file_manifest(stage) != before:
            raise PackageError("sterile S2 import mutated extracted package files")
        return {
            "passed": True,
            "isolated_python": True,
            "bytecode_disabled": True,
            "command_flags": ["-I", "-B"],
            "opposite_inherited_controls_overridden": True,
            "cache_free_after_import": True,
            "package_files_unchanged_after_import": True,
            "deck_id": deck_id,
            "deck_csv_sha256": deck_sha256,
            **payload,
        }


def build_package(
    *,
    name: str = DEFAULT_NAME,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Build and audit one deterministic S2 archive and manifest."""

    package_name = audited._validate_name(name)
    output_path = Path(output_dir or DEFAULT_OUTPUT_DIR).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    archive_path = output_path / f"{package_name}.tar.gz"
    manifest_path = output_path / f"{package_name}.manifest.json"

    with tempfile.TemporaryDirectory(prefix="dipplin-s2-", dir=output_path) as directory:
        work = Path(directory)
        first_stage = work / "first"
        second_stage = work / "second"
        first = stage_package(first_stage)
        second = stage_package(second_stage)
        if first != second:
            raise PackageError("fresh Dipplin S2 package stages differ")

        first_archive = work / "first.tar.gz"
        second_archive = work / "second.tar.gz"
        deterministic_tar(first_stage, first_archive)
        deterministic_tar(second_stage, second_archive)
        first_hash = sha256_file(first_archive)
        second_hash = sha256_file(second_archive)
        if (
            first_hash != second_hash
            or first_archive.read_bytes() != second_archive.read_bytes()
        ):
            raise PackageError(
                "deterministic Dipplin S2 build mismatch: "
                f"first={first_hash}, second={second_hash}"
            )

        archive_audit = audit_archive(first_archive, first["file_manifest"])
        smoke = sterile_import_smoke(first_archive)
        verify_stage = work / "verified"
        safe_extract(first_archive, verify_stage)
        verified_file_manifest = package_file_manifest(verify_stage)
        if verified_file_manifest != first["file_manifest"]:
            raise PackageError("fresh S2 archive extraction changed package files")
        verified_tree_hash = package_tree_sha256(verify_stage)
        if verified_tree_hash != first["extracted_tree_sha256"]:
            raise PackageError("fresh S2 archive extraction changed package tree")
        verified_runtime_hash, verified_runtime_members = runtime_source_tree_sha256(
            verify_stage
        )
        if verified_runtime_hash != first["runtime_source_tree_sha256"]:
            raise PackageError("fresh S2 archive extraction changed runtime source tree")
        if verified_runtime_members != first["runtime_source_members"]:
            raise PackageError("fresh S2 archive extraction changed runtime source members")

        staged_output = work / "final.tar.gz"
        shutil.copyfile(first_archive, staged_output)
        deck, deck_id, deck_sha256, deck_count = audited._deck_bytes()
        manifest = {
            "schema": "dipplin-s2-package-manifest-v1",
            "schema_version": 1,
            "status": "packaged",
            "variant": "s2",
            "runtime": {
                "family": "dedicated_dipplin",
                "direct_entrypoint": True,
                "search_default": True,
                "second_opening_v2_default": True,
                "s2_default": True,
                "entrypoint_forces_evaluated_mode": True,
                "evaluated_configuration": {
                    "search": True,
                    "second_opening_v2": True,
                    "s2": True,
                    "go_first": True,
                    "route_v2": False,
                    "search_worlds": 2,
                },
                "module_allowlist": first["module_allowlist"],
                "learned_weights_included": False,
                "grim_runtime_included": False,
                "runtime_source_tree_sha256": first["runtime_source_tree_sha256"],
                "runtime_source_members": first["runtime_source_members"],
            },
            "source": {
                "allowlist_origin": "scripts.package_dipplin.D1_DIPPLIN_MODULES",
                "s2_gate_markers": {
                    key: list(value) for key, value in sorted(S2_SOURCE_MARKERS.items())
                },
                "source_file_manifest": first["source_file_manifest"],
            },
            "deck": {
                "deck_id": deck_id,
                "card_count": deck_count,
                "deck_csv_sha256": deck_sha256,
                "newline_terminated": deck.endswith(b"\n"),
            },
            "engine": {
                "source": OFFICIAL_CG_ROOT.relative_to(ROOT).as_posix(),
                "official_template_file_sha256": dict(
                    sorted(OFFICIAL_CG_SHA256.items())
                ),
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
                "fresh_stage_manifests_identical": True,
                "deterministic_double_build": True,
                "byte_identical_double_build": True,
                "first_archive_sha256": first_hash,
                "second_archive_sha256": second_hash,
                "safe_archive_extraction": True,
                "verified_extracted_tree_sha256": verified_tree_hash,
                "verified_runtime_source_tree_sha256": verified_runtime_hash,
                "verified_file_manifest": verified_file_manifest,
                "archive_structure": archive_audit,
                "sterile_import": smoke,
                "linux_amd64_complete_game": audited._host_linux_amd64_gate(),
            },
            "deployment": {
                "games_run_by_packager": False,
                "uploaded": False,
                "cloud_started": False,
            },
        }
        staged_manifest = work / "final.manifest.json"
        audited._write_json(staged_manifest, manifest)
        os.replace(staged_output, archive_path)
        os.replace(staged_manifest, manifest_path)
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=DEFAULT_NAME, help="portable archive basename")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="default: artifacts/dipplin_s2",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = build_package(name=args.name, output_dir=args.output_dir)
    except (
        PackageError,
        FileNotFoundError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        print(
            json.dumps({"status": "failed_closed", "error": str(exc)}),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
