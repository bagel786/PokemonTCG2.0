#!/usr/bin/env python3
"""Assemble a sanitized, exact-allow-list processed release transactionally."""

from __future__ import annotations

import ctypes
import hashlib
import importlib.metadata
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "release"

# These are the only hand-maintained files consumed from the current release
# scaffold. Everything else is rebuilt in a clean staging directory.
STATIC_INPUTS = {
    "README.md",
    "CITATION.cff",
    "LICENSE",
    "docs/environment_access.md",
    "evaluation/verify_processed.py",
    "src/abstract_engine.py",
}
PROTOCOL_FILES = {
    "FRESH_CONFIRMATION_PROTOCOL.md",
    "REPRESENTATION_ABLATION_PROTOCOL.md",
}
PROCESSED = {
    "paper/data/canonical_results.csv": "canonical_results.csv",
    "paper/data/statistical_summary.json": "statistical_summary.json",
    "paper/data/fresh_cell_summary.csv": "fresh_cell_summary.csv",
    "paper/data/historical_cell_summary.csv": "historical_cell_summary.csv",
    "paper/data/representation_audit.json": "representation_audit.json",
    "paper/data/representation_source_cards.csv": "representation_source_cards.csv",
    "paper/data/heldout_0813_summary.json": "heldout_0813_summary.json",
    "paper/data/negative_results.json": "negative_results.json",
    "paper/data/negative_results.csv": "negative_results.csv",
    "paper/data/ablation/canonical_ablation.csv": "ablation_canonical.csv",
    "paper/data/ablation/summary.json": "ablation_summary.json",
    "paper/data/ablation/contrasts.csv": "ablation_contrasts.csv",
    "paper/data/ablation/training_report.json": "ablation_training_report.json",
}
SUPPLEMENTS = {
    "DATA_CARD.md",
    "MODEL_CARD.md",
    "PROVENANCE_AUDIT.md",
    "REPRODUCIBILITY_CHECKLIST.md",
    "RIGHTS_AND_ACCESS_AUDIT.md",
}
RELEASE_SCRIPTS = {"build_figures.py", "generate_tables.py"}
GENERATED_FILES = {
    "generated/diagnostic_macros.tex",
    "generated/tables/ablation.tex",
    "generated/tables/heldout.tex",
    "generated/tables/negative.tex",
    "generated/tables/primary.tex",
    "generated/tables/representation.tex",
}
FIGURE_STEMS = {
    "fig01_pipeline",
    "fig02_action_aliasing",
    "fig03_dataset_provenance",
    "fig04_gameplay_forest",
    "fig05_gameplay_vs_expert",
    "fig06_negative_forest",
}

PROHIBITED_SUFFIXES = {
    ".dylib", ".dll", ".so", ".exe", ".npz", ".npy", ".pt", ".pth",
    ".onnx", ".pkl", ".pickle", ".joblib", ".tar", ".tgz", ".gz",
    ".zip", ".7z", ".rar", ".pyc", ".pyo", ".whl", ".egg",
    ".sqlite", ".db", ".png.tmp",
}
PROHIBITED_MAGIC = {
    b"\x7fELF": "ELF executable",
    b"MZ": "PE executable",
    b"\xca\xfe\xba\xbe": "Mach-O/universal binary",
    b"\xcf\xfa\xed\xfe": "Mach-O binary",
    b"\xfe\xed\xfa\xcf": "Mach-O binary",
    b"PK\x03\x04": "ZIP archive",
    b"\x1f\x8b": "gzip archive",
    b"\x93NUMPY": "NumPy binary",
    b"\x80\x02": "pickle payload",
    b"\x80\x03": "pickle payload",
    b"\x80\x04": "pickle payload",
    b"\x80\x05": "pickle payload",
}
ALLOWED_BINARY_SUFFIXES = {".pdf", ".png"}

# Identifying opponent/card-derived labels are replaced consistently in every
# released text file, including data keys, path strings, protocols, and scripts.
# Longer patterns must precede their substrings.
IDENTIFIER_REPLACEMENTS = (
    (r"grim_d842_runtime", "Matched2"),
    (r"grim_replay_refresh", "Matched4"),
    (r"grim_master_v1", "Matched3"),
    (r"grim_b0", "Matched1"),
    (r"starmie_v2_boss_atk", "Broader1"),
    (r"alakazam_2_4a_no_search", "Broader3"),
    (r"alakazam_2_4a", "Broader3"),
    (r"alakazam_no_search", "Broader3"),
    (r"dipplin_d1", "Broader2"),
    (r"d842_runtime", "Matched2"),
    (r"replay_refresh", "Matched4"),
    (r"replay-refresh", "Matched4"),
    (r"master_v1", "Matched3"),
    (r"master-v1", "Matched3"),
    (r"az24_auth", "Broader3Auth"),
    (r"az24", "Broader3"),
    (r"ctl_m1", "ctl_Matched3"),
    (r"ctl_rr", "ctl_Matched4"),
    (r"starmie", "Broader1"),
    (r"dipplin", "Broader2"),
    (r"alakazam", "Broader3"),
    (r"(?<![A-Za-z0-9])d842(?![A-Za-z0-9])", "Matched2"),
    (r"(?<![A-Za-z0-9])B0(?![A-Za-z0-9])", "Matched1"),
    (r"(?<![A-Za-z0-9])Grim(?![A-Za-z0-9])", "Matched"),
    (r"Dreamer", "Team1"),
    (r"GrimmsnaRL", "Team2"),
    (r"Mint120", "Team3"),
    (r"TMTA", "Team4"),
    (r"lollipop947", "Team5"),
    (r"matsurih", "Team6"),
)
PROHIBITED_IDENTITY_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE) for pattern, _ in IDENTIFIER_REPLACEMENTS
)
SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]+"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
RESTRICTED_URI_PATTERN = re.compile(
    r"(?i)\b(?:"
    r"(?!(?:https?)://)[a-z][a-z0-9+.-]*://[^\s\"'`<>|]+"
    r"|https?://(?:localhost|127(?:\.[0-9]{1,3}){3}|\[::1\])(?:[:/][^\s\"'`<>|]*)?"
    r")"
)
WINDOWS_ABSOLUTE_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:"
    r"[A-Za-z]:[\\/][^\s\"'`<>|]+"
    r"|\\\\[^\\/\s\"'`<>|]+\\[^\\/\s\"'`<>|]+(?:\\[^\s\"'`<>|]+)*"
    r")"
)
UNIX_ABSOLUTE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_:/)\]}])/(?!/)(?=[A-Za-z0-9._~-])[^\s\"'`<>|]+"
)
ALLOWED_ABSOLUTE_PATHS = {"/usr/bin/env"}
MANIFEST_LINE = re.compile(r"([0-9a-f]{64})  ([^\r\n]+)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reject_json_constant(value: str):
    raise ValueError(f"non-finite JSON constant prohibited: {value}")


def parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number prohibited: {value}")
    return parsed


def reject_duplicate_json_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key prohibited: {key}")
        value[key] = item
    return value


def load_json_strict(path: Path):
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_json_pairs,
        parse_constant=reject_json_constant,
        parse_float=parse_finite_json_float,
    )


def safe_relative(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
        and "\\" not in value
        and not path.is_absolute()
        and value == path.as_posix()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def validate_regular_within(root: Path, path: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"trusted root is missing, not a directory, or a symlink: {root}")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"path is outside trusted root: {path}") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeError(f"symlinked path component prohibited: {current}")
    if not path.is_file() or path.stat().st_nlink != 1:
        raise RuntimeError(f"regular single-link file required: {path}")
    if not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        raise RuntimeError(f"resolved path escapes trusted root: {path}")


def replace_local_reference(match: re.Match) -> str:
    value = match.group(0)
    return value if value in ALLOWED_ABSOLUTE_PATHS else "restricted/path"


def local_reference_hits(value: str) -> list[str]:
    hits = [match.group(0) for match in RESTRICTED_URI_PATTERN.finditer(value)]
    hits.extend(match.group(0) for match in WINDOWS_ABSOLUTE_PATTERN.finditer(value))
    hits.extend(
        match.group(0)
        for match in UNIX_ABSOLUTE_PATTERN.finditer(value)
        if match.group(0) not in ALLOWED_ABSOLUTE_PATHS
    )
    return hits


def validate_figure_binary(relative: str, data: bytes) -> str | None:
    suffix = Path(relative).suffix.lower()
    if suffix == ".pdf":
        if len(data) < 100 or not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]:
            return "invalid PDF signature, size, or EOF marker"
    elif suffix == ".png":
        if (
            len(data) < 32
            or not data.startswith(b"\x89PNG\r\n\x1a\n")
            or not data.endswith(b"\x00\x00\x00\x00IEND\xaeB\x60\x82")
        ):
            return "invalid PNG signature, size, or IEND marker"
    else:
        return f"binary suffix is not allow-listed: {suffix}"
    return None


def printable_binary_text(data: bytes, minimum_run: int = 6) -> str:
    """Extract printable runs without treating compressed bytes as UTF-8 prose."""
    pattern = rb"[\x20-\x7e]{" + str(minimum_run).encode("ascii") + rb",}"
    return "\n".join(
        match.group(0).decode("ascii") for match in re.finditer(pattern, data)
    )


def expected_files(protocol_names: set[str], *, include_manifest: bool) -> set[str]:
    files = set(STATIC_INPUTS)
    files.update({"environment.yml", "requirements-lock.txt"})
    files.update(f"data/processed/{destination}" for destination in PROCESSED.values())
    files.update(f"docs/{name}" for name in SUPPLEMENTS)
    files.add("docs/claim_ledger.csv")
    files.update(f"docs/protocols/{name}" for name in protocol_names)
    files.update(f"scripts/{name}" for name in RELEASE_SCRIPTS)
    files.update(GENERATED_FILES)
    files.update(
        f"figures/{stem}.{suffix}"
        for stem in FIGURE_STEMS
        for suffix in ("pdf", "png")
    )
    if include_manifest:
        files.add("MANIFEST.sha256")
    return files


def expected_directories(files: set[str]) -> set[str]:
    directories: set[str] = set()
    for name in files:
        parent = PurePosixPath(name).parent
        while parent != PurePosixPath("."):
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories


def inspect_tree(root: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise RuntimeError(f"symlink prohibited in release: {relative}")
        if path.is_file():
            if path.stat().st_nlink != 1:
                raise RuntimeError(f"hard-linked file prohibited in release: {relative}")
            files.add(relative)
        elif path.is_dir():
            directories.add(relative)
        else:
            raise RuntimeError(f"special filesystem object prohibited: {relative}")
    return files, directories


def validate_exact_tree(root: Path, expected: set[str]) -> None:
    actual_files, actual_directories = inspect_tree(root)
    missing = sorted(expected - actual_files)
    extra = sorted(actual_files - expected)
    expected_dirs = expected_directories(expected)
    missing_dirs = sorted(expected_dirs - actual_directories)
    extra_dirs = sorted(actual_directories - expected_dirs)
    if missing or extra or missing_dirs or extra_dirs:
        raise RuntimeError(
            "release allow-list mismatch: "
            f"missing_files={missing}, extra_files={extra}, "
            f"missing_dirs={missing_dirs}, extra_dirs={extra_dirs}"
        )


def capture_file_digests(root: Path) -> dict[str, str]:
    files, _ = inspect_tree(root)
    return {relative: sha256(root / relative) for relative in files}


def validate_unchanged(root: Path, expected: dict[str, str], label: str) -> None:
    changed = []
    for relative, digest in expected.items():
        path = root / relative
        try:
            validate_regular_within(root, path)
        except (OSError, RuntimeError) as exc:
            changed.append(f"{relative} ({exc})")
            continue
        if sha256(path) != digest:
            changed.append(relative)
    if changed:
        raise RuntimeError(f"{label} modified protected staged files: {sorted(changed)}")


def validate_source_path(source: Path) -> None:
    try:
        relative = source.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError(f"source is outside the repository: {source}") from exc
    current = ROOT
    if current.is_symlink():
        raise RuntimeError(f"repository root must not be a symlink: {ROOT}")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeError(f"symlinked source path component prohibited: {current}")
    if not source.resolve(strict=True).is_relative_to(ROOT.resolve(strict=True)):
        raise RuntimeError(f"resolved source escapes the repository: {source}")


def copy_required(source: Path, destination: Path, *, sanitize: bool = False) -> None:
    validate_source_path(source)
    if source.is_symlink() or not source.is_file():
        raise FileNotFoundError(f"regular non-symlink source required: {source}")
    if source.stat().st_nlink != 1:
        raise RuntimeError(f"hard-linked source prohibited: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if sanitize:
        text = source.read_text(encoding="utf-8")
        destination.write_text(sanitize_text(text), encoding="utf-8")
    else:
        shutil.copy2(source, destination)


def sanitize_text(value: str) -> str:
    sanitized = value.replace(str(ROOT) + "/", "")
    sanitized = RESTRICTED_URI_PATTERN.sub("restricted/path", sanitized)
    sanitized = WINDOWS_ABSOLUTE_PATTERN.sub("restricted/path", sanitized)
    sanitized = UNIX_ABSOLUTE_PATTERN.sub(replace_local_reference, sanitized)
    for pattern, replacement in IDENTIFIER_REPLACEMENTS:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
    return sanitized


def sanitize_json(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            clean_key = sanitize_text(str(key))
            if clean_key in sanitized:
                raise ValueError(f"identifier sanitization created duplicate JSON key: {clean_key}")
            sanitized[clean_key] = sanitize_json(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value


def copy_processed(source: Path, destination: Path) -> None:
    validate_source_path(source)
    if source.is_symlink() or not source.is_file():
        raise FileNotFoundError(f"regular non-symlink processed source required: {source}")
    if source.stat().st_nlink != 1:
        raise RuntimeError(f"hard-linked processed source prohibited: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix == ".json":
        payload = load_json_strict(source)
        destination.write_text(
            json.dumps(sanitize_json(payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    else:
        destination.write_text(sanitize_text(source.read_text(encoding="utf-8")), encoding="utf-8")


def update_release_summary(stage: Path) -> None:
    canonical = stage / "data/processed/canonical_results.csv"
    summary_path = stage / "data/processed/statistical_summary.json"
    summary = load_json_strict(summary_path)
    source_digest = summary.get("canonical_sha256")
    if not isinstance(source_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", source_digest):
        raise ValueError("source statistical summary has no valid canonical_sha256")
    actual_source_digest = sha256(ROOT / "paper/data/canonical_results.csv")
    if source_digest != actual_source_digest:
        raise ValueError(
            "source statistical summary/canonical digest mismatch: "
            f"summary={source_digest}, actual={actual_source_digest}"
        )
    summary["source_canonical_sha256"] = source_digest
    summary["canonical_sha256"] = sha256(canonical)
    summary["release_sanitization"] = {
        "absolute_local_paths_removed": True,
        "opponent_and_team_identifiers": "neutralized",
        "restricted_local_uris_removed": True,
        "schema_version": 1,
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def purge_python_caches(root: Path) -> None:
    for path in sorted(root.rglob("__pycache__"), reverse=True):
        if path.is_symlink():
            raise RuntimeError(f"symlinked Python cache prohibited: {path}")
        if path.is_dir():
            shutil.rmtree(path)


def write_environment(stage: Path) -> None:
    python_version = ".".join(map(str, sys.version_info[:3]))
    numpy_version = importlib.metadata.version("numpy")
    matplotlib_version = importlib.metadata.version("matplotlib")
    (stage / "environment.yml").write_text(
        "name: representation-repair-processed\n"
        "channels:\n  - conda-forge\n"
        "dependencies:\n"
        f"  - python={python_version}\n"
        f"  - numpy={numpy_version}\n"
        f"  - matplotlib={matplotlib_version}\n",
        encoding="utf-8",
    )
    (stage / "requirements-lock.txt").write_text(
        f"numpy=={numpy_version}\nmatplotlib=={matplotlib_version}\n",
        encoding="utf-8",
    )


def scan_release(root: Path) -> dict[str, int]:
    problems: list[str] = []
    files, _ = inspect_tree(root)
    for relative in sorted(files):
        path = root / relative
        lower = relative.lower()
        suffix = path.suffix.lower()
        if any(lower.endswith(item) for item in PROHIBITED_SUFFIXES):
            problems.append(f"prohibited binary/archive suffix: {relative}")
        data = path.read_bytes()
        for magic, label in PROHIBITED_MAGIC.items():
            if data.startswith(magic):
                problems.append(f"prohibited {label}: {relative}")
        if suffix in ALLOWED_BINARY_SUFFIXES:
            binary_problem = validate_figure_binary(relative, data)
            if binary_problem:
                problems.append(f"{binary_problem}: {relative}")
            text = printable_binary_text(data)
        else:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                problems.append(f"non-UTF-8 payload outside figure allow-list: {relative}")
                text = ""
        searchable = relative + "\n" + text
        if suffix in ALLOWED_BINARY_SUFFIXES:
            if (
                str(ROOT).encode() in data
                or re.search(rb"/(?:Users|home|root|private|tmp|var)/", data)
                or RESTRICTED_URI_PATTERN.search(text)
                or WINDOWS_ABSOLUTE_PATTERN.search(text)
            ):
                problems.append(f"absolute/restricted local reference in binary figure: {relative}")
        else:
            hits = local_reference_hits(searchable)
            if hits:
                problems.append(f"absolute local path/restricted URI in {relative}: {hits[:3]}")
        for pattern in PROHIBITED_IDENTITY_PATTERNS:
            if pattern.search(searchable):
                problems.append(f"identifying opponent/team token in {relative}: {pattern.pattern}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                problems.append(f"secret-like pattern in {relative}")
    if problems:
        raise RuntimeError("release scan failed:\n" + "\n".join(sorted(set(problems))))
    return {"files_scanned": len(files), "problems": 0}


def write_manifest(root: Path, files: set[str]) -> None:
    manifest = root / "MANIFEST.sha256"
    if manifest.exists():
        raise RuntimeError("refusing to overwrite a pre-existing staged manifest")
    rows = [f"{sha256(root / name)}  {name}" for name in sorted(files)]
    manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")


def verify_manifest(root: Path, expected: set[str]) -> dict[str, int]:
    manifest = root / "MANIFEST.sha256"
    if manifest.is_symlink() or not manifest.is_file():
        raise RuntimeError("regular MANIFEST.sha256 is required")
    lines = manifest.read_text(encoding="utf-8").splitlines()
    entries: dict[str, str] = {}
    for number, line in enumerate(lines, 1):
        match = MANIFEST_LINE.fullmatch(line)
        if not match:
            raise RuntimeError(f"malformed manifest line {number}")
        digest, relative = match.groups()
        if not safe_relative(relative) or relative == "MANIFEST.sha256":
            raise RuntimeError(f"unsafe manifest path on line {number}: {relative!r}")
        if relative in entries:
            raise RuntimeError(f"duplicate manifest path: {relative}")
        entries[relative] = digest
    expected_entries = expected - {"MANIFEST.sha256"}
    if set(entries) != expected_entries:
        raise RuntimeError(
            "manifest entry set mismatch: "
            f"missing={sorted(expected_entries - set(entries))}, "
            f"extra={sorted(set(entries) - expected_entries)}"
        )
    validate_exact_tree(root, expected)
    for relative, digest in entries.items():
        path = root / relative
        if path.is_symlink() or not path.is_file() or sha256(path) != digest:
            raise RuntimeError(f"manifest digest/type mismatch: {relative}")
    return {"entries": len(entries), "files_including_manifest": len(expected)}


def protocol_names() -> set[str]:
    names = {path.name for path in (ROOT / "paper/protocol").glob("*.md")}
    if names != PROTOCOL_FILES:
        raise RuntimeError(
            "frozen protocol allow-list mismatch: "
            f"missing={sorted(PROTOCOL_FILES - names)}, extra={sorted(names - PROTOCOL_FILES)}"
        )
    if any(not safe_relative(name) for name in PROTOCOL_FILES):
        raise RuntimeError(f"unsafe protocol filename: {sorted(PROTOCOL_FILES)}")
    return set(PROTOCOL_FILES)


def build_stage(stage: Path, protocols: set[str]) -> tuple[dict[str, int], dict[str, int]]:
    for relative in sorted(STATIC_INPUTS):
        copy_required(RELEASE / relative, stage / relative)
    verifier = stage / "evaluation/verify_processed.py"
    expected_verifier_sha256 = sha256(verifier)
    for source, destination in PROCESSED.items():
        copy_processed(ROOT / source, stage / "data/processed" / destination)
    update_release_summary(stage)
    copy_required(ROOT / "paper/claim_ledger.csv", stage / "docs/claim_ledger.csv", sanitize=True)
    for name in sorted(SUPPLEMENTS):
        copy_required(ROOT / "paper/supplement" / name, stage / "docs" / name, sanitize=True)
    for name in sorted(protocols):
        copy_required(ROOT / "paper/protocol" / name, stage / "docs/protocols" / name, sanitize=True)
    for name in sorted(RELEASE_SCRIPTS):
        copy_required(ROOT / "paper/scripts" / name, stage / "scripts" / name, sanitize=True)
    write_environment(stage)

    protected_inputs = capture_file_digests(stage)
    subprocess.run([sys.executable, "-B", "scripts/generate_tables.py"], cwd=stage, check=True)
    subprocess.run([sys.executable, "-B", "scripts/build_figures.py"], cwd=stage, check=True)
    purge_python_caches(stage)
    validate_unchanged(stage, protected_inputs, "release generators")

    without_manifest = expected_files(protocols, include_manifest=False)
    validate_exact_tree(stage, without_manifest)
    scan = scan_release(stage)
    validate_regular_within(stage, verifier)
    if sha256(verifier) != expected_verifier_sha256:
        raise RuntimeError("released verifier changed during staged generation")
    protected_release = capture_file_digests(stage)
    subprocess.run([sys.executable, "-B", "evaluation/verify_processed.py"], cwd=stage, check=True)
    purge_python_caches(stage)
    validate_exact_tree(stage, without_manifest)
    validate_unchanged(stage, protected_release, "release verifier")
    scan = scan_release(stage)
    write_manifest(stage, without_manifest)
    with_manifest = expected_files(protocols, include_manifest=True)
    manifest_report = verify_manifest(stage, with_manifest)
    return scan, manifest_report


def publish_transactionally(stage: Path) -> str:
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        renameatx_np = libc.renameatx_np
        renameatx_np.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameatx_np.restype = ctypes.c_int
        at_fdcwd = -2
        rename_swap = 0x00000002
        result = renameatx_np(
            at_fdcwd,
            os.fsencode(stage),
            at_fdcwd,
            os.fsencode(RELEASE),
            rename_swap,
        )
        if result != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), f"{stage} <-> {RELEASE}")
        # The old release now occupies the former staging path.
        shutil.rmtree(stage)
        return "atomic directory exchange after full staged verification"

    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise RuntimeError("atomic renameat2 directory exchange is unavailable")
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        at_fdcwd = -100
        rename_exchange = 0x00000002
        result = renameat2(
            at_fdcwd,
            os.fsencode(stage),
            at_fdcwd,
            os.fsencode(RELEASE),
            rename_exchange,
        )
        if result != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), f"{stage} <-> {RELEASE}")
        shutil.rmtree(stage)
        return "atomic Linux directory exchange after full staged verification"

    raise RuntimeError(
        "atomic directory exchange is unsupported on this platform; release was not published"
    )


def main() -> int:
    if RELEASE.is_symlink() or not RELEASE.is_dir():
        raise RuntimeError("release scaffold must be an existing non-symlink directory")
    protocols = protocol_names()
    stage = Path(tempfile.mkdtemp(prefix=".release-stage-", dir=ROOT))
    try:
        scan, manifest_report = build_stage(stage, protocols)
        manifest_sha = sha256(stage / "MANIFEST.sha256")
        publication = publish_transactionally(stage)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    print(json.dumps({
        "release": str(RELEASE.relative_to(ROOT)),
        "manifest_sha256": manifest_sha,
        "manifest": manifest_report,
        "scan": scan,
        "publication": publication,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
