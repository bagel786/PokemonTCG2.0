#!/usr/bin/env python3
"""Build a deterministic R0 + Turn Director submission without uploading it."""

from __future__ import annotations

import gzip
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
R0_ARCHIVE = ROOT / "artifacts" / "recovery_r0_package" / "r0_play_binding.tar.gz"
A2_ARCHIVE = ROOT / "artifacts" / "recovery_probes" / "a2_v2_shield.tar.gz"
D842_ARCHIVE = ROOT / "artifacts" / "recovery_probes" / "d842_control_exact.tar.gz"
EXPECTED = {
    "r0": "AC0E9B174AE99911AD9E04F82E912E43AB7E9FFA130D297C04FEDCF34247058B",
    "a2": "0958BD8847266EFBC38658D62B9AC4DCD62A9AAED3D1098F093A677AFCBFED4C",
    "d842": "3ECB0BBF119E23C31905E39E19ECA8F6145104AAEFFC0A5675D2FE03855BB458",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def verify_sources() -> None:
    for label, path in (("r0", R0_ARCHIVE), ("a2", A2_ARCHIVE), ("d842", D842_ARCHIVE)):
        if not path.is_file():
            raise FileNotFoundError(path)
        actual = sha256(path)
        if actual != EXPECTED[label]:
            raise RuntimeError(f"{label} hash mismatch: expected {EXPECTED[label]}, got {actual}")


def deterministic_tar(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in sorted(item for item in source.rglob("*") if item.is_file()):
                    info = archive.gettarinfo(str(path), arcname=path.relative_to(source).as_posix())
                    info.mtime = info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)


def extract_member(archive: Path, suffix: str, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as handle:
        matches = [member for member in handle.getmembers() if member.isfile() and member.name.endswith(suffix)]
        if len(matches) != 1:
            raise RuntimeError(f"expected one {suffix} in {archive}, got {len(matches)}")
        source = handle.extractfile(matches[0])
        if source is None:
            raise RuntimeError(f"cannot extract {matches[0].name}")
        destination.write_bytes(source.read())


def build(output: Path, discovery: Path | None = None) -> dict:
    verify_sources()
    r0_root = ROOT / "artifacts" / "recovery_r0_package" / "extracted" / "r0_play_binding"
    if not r0_root.is_dir():
        raise FileNotFoundError(r0_root)
    with tempfile.TemporaryDirectory(prefix="grim-director-") as temporary:
        stage = Path(temporary) / "agent"
        shutil.copytree(r0_root, stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        # Preserve the exact R0 policy/feature/runtime implementation.  Only the
        # competition wrapper and the new isolated Director are overlaid; this
        # is what makes non-routed behavior genuinely byte-identical to R0.
        shutil.copy2(ROOT / "ptcg_ai" / "agent.py", stage / "ptcg_ai" / "agent.py")
        shutil.copy2(ROOT / "ptcg_ai" / "director.py", stage / "ptcg_ai" / "director.py")
        config = json.loads((ROOT / "training" / "director_policy.json").read_text(encoding="utf-8"))
        fallback_archive, secondary_archive = A2_ARCHIVE, D842_ARCHIVE
        discovery_payload = None
        if discovery is not None:
            discovery_payload = json.loads(discovery.read_text(encoding="utf-8"))
            if discovery_payload.get("status") != "frozen" or discovery_payload.get("behavior_clones_used") is not False:
                raise RuntimeError("discovery manifest is not a frozen clone-free result")
            winner = discovery_payload.get("winner_config") or {}
            config["trigger"] = winner["PTCG_DIRECTOR_TRIGGER"]
            config["horizon"] = winner["PTCG_DIRECTOR_HORIZON"]
            if winner.get("PTCG_DIRECTOR_SWAP_FALLBACK") == "1":
                fallback_archive, secondary_archive = D842_ARCHIVE, A2_ARCHIVE
                config["routed_fallback"] = "d842"
        config_text = json.dumps(config, indent=2, sort_keys=True) + "\n"
        config_hash = hashlib.sha256(config_text.encode("utf-8")).hexdigest().upper()
        (stage / "director_config.json").write_text(config_text, encoding="utf-8")
        shutil.copy2(ROOT / "training" / "marnie_hypotheses.json", stage / "marnie_hypotheses.json")
        extract_member(fallback_archive, "policy_weights.npz", stage / "director_fallback.npz")
        extract_member(secondary_archive, "policy_weights.npz", stage / "director_secondary.npz")

        env = dict(**__import__("os").environ)
        env["PYTHONPATH"] = str(stage)
        check = subprocess.run(
            [sys.executable, "-c", (
                "import json,main; d=main.agent({'select':None,'logs':[],'current':None}); "
                "a=main._AGENT; assert len(d)==60; assert a.director is not None; "
                "assert a.routed_fallback is not a.policy; assert len(a.director.hypotheses)>=2; "
                "print(json.dumps({'deck':len(d),'hypotheses':len(a.director.hypotheses),'errors':a.errors}))"
            )],
            cwd=stage,
            env=env,
            text=True,
            capture_output=True,
            timeout=120,
        )
        if check.returncode:
            raise RuntimeError(f"sterile load failed:\n{check.stdout}\n{check.stderr}")
        validation = json.loads(check.stdout.strip().splitlines()[-1])
        deterministic_tar(stage, output)
    manifest = {
        "status": "packaged_not_promoted",
        "created_unix": time.time(),
        "archive": str(output.resolve()),
        "archive_sha256": sha256(output),
        "archive_size_bytes": output.stat().st_size,
        "source_archives": {key: value for key, value in EXPECTED.items()},
        "director_config_sha256": config_hash,
        "hypotheses_sha256": sha256(ROOT / "training" / "marnie_hypotheses.json"),
        "sterile_load": validation,
        "upload_allowed": False,
        "discovery_manifest": str(discovery.resolve()) if discovery else None,
        "discovery_sha256": sha256(discovery) if discovery else None,
        "discovery_winner": discovery_payload.get("winner") if discovery_payload else None,
    }
    manifest_path = output.with_suffix(output.suffix + ".json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "turn_director" / "grim_turn_director.tar.gz")
    parser.add_argument("--discovery", type=Path)
    args = parser.parse_args()
    result = build(args.output, args.discovery)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
