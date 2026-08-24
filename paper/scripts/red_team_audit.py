#!/usr/bin/env python3
"""Fail-closed final audit of manuscript, claims, figures, data, and release."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "paper"
RELEASE = ROOT / "release"
REQUIRED_CLAIM_FIELDS = [
    "claim_id", "manuscript_section", "proposed_claim", "status", "raw_source",
    "json_or_line_locator", "branch", "commit", "artifact_sha256",
    "calculation_script", "verified_value", "unit", "sample_size",
    "statistical_method", "limitations", "include_or_omit",
]
RELEASE_STATIC_FILES = {
    "README.md", "CITATION.cff", "LICENSE", "docs/environment_access.md",
    "evaluation/verify_processed.py", "src/abstract_engine.py",
    "environment.yml", "requirements-lock.txt",
}
RELEASE_PROCESSED_FILES = {
    "canonical_results.csv", "statistical_summary.json", "fresh_cell_summary.csv",
    "historical_cell_summary.csv", "representation_audit.json",
    "representation_source_cards.csv", "heldout_0813_summary.json",
    "negative_results.json", "negative_results.csv", "ablation_canonical.csv",
    "ablation_summary.json", "ablation_contrasts.csv", "ablation_training_report.json",
}
RELEASE_DOC_FILES = {
    "DATA_CARD.md", "MODEL_CARD.md", "PROVENANCE_AUDIT.md",
    "REPRODUCIBILITY_CHECKLIST.md", "RIGHTS_AND_ACCESS_AUDIT.md",
}
RELEASE_PROTOCOL_FILES = {
    "FRESH_CONFIRMATION_PROTOCOL.md",
    "REPRESENTATION_ABLATION_PROTOCOL.md",
}
RELEASE_GENERATED_FILES = {
    "generated/diagnostic_macros.tex",
    "generated/tables/ablation.tex",
    "generated/tables/heldout.tex",
    "generated/tables/negative.tex",
    "generated/tables/primary.tex",
    "generated/tables/representation.tex",
}
RELEASE_FIGURE_STEMS = {
    "fig01_pipeline", "fig02_action_aliasing", "fig03_dataset_provenance",
    "fig04_gameplay_forest", "fig05_gameplay_vs_expert", "fig06_negative_forest",
}
RELEASE_PROHIBITED_SUFFIXES = {
    ".dylib", ".dll", ".so", ".exe", ".npz", ".npy", ".pt", ".pth",
    ".onnx", ".pkl", ".pickle", ".joblib", ".tar", ".tgz", ".gz", ".zip",
    ".7z", ".rar", ".pyc", ".pyo", ".whl", ".egg", ".sqlite", ".db",
    ".png.tmp",
}
RELEASE_PROHIBITED_IDENTIFIERS = (
    r"grim_d842_runtime", r"grim_replay_refresh", r"grim_master_v1", r"grim_b0",
    r"starmie_v2_boss_atk", r"alakazam_2_4a_no_search", r"alakazam_2_4a",
    r"alakazam_no_search", r"dipplin_d1",
    r"starmie", r"dipplin", r"alakazam", r"d842_runtime", r"replay_refresh",
    r"replay-refresh", r"master_v1", r"master-v1", r"az24_auth", r"az24",
    r"ctl_m1", r"ctl_rr",
    r"(?<![A-Za-z0-9])d842(?![A-Za-z0-9])",
    r"(?<![A-Za-z0-9])B0(?![A-Za-z0-9])",
    r"(?<![A-Za-z0-9])Grim(?![A-Za-z0-9])",
    r"Dreamer", r"GrimmsnaRL", r"Mint120", r"TMTA", r"lollipop947", r"matsurih",
)
RELEASE_SECRET_PATTERNS = (
    r"AKIA[0-9A-Z]{16}",
    r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]+",
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
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


def validate_regular_within(root: Path, path: Path) -> str | None:
    if root.is_symlink() or not root.is_dir():
        return f"trusted root is missing, not a directory, or a symlink: {root}"
    try:
        relative = path.relative_to(root)
    except ValueError:
        return f"path is outside trusted root: {path}"
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return f"symlinked path component prohibited: {current}"
    if not path.is_file() or path.stat().st_nlink != 1:
        return f"regular single-link file required: {path}"
    if not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        return f"resolved path escapes trusted root: {path}"
    return None


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


def prose_tokens(value: str) -> list[str]:
    value = re.sub(
        r"\\(?:cite|ref|eqref|label|input|include|includegraphics|bibliography|bibliographystyle)"
        r"\*?(?:\[[^]]*\])?\{[^{}]*\}",
        " ",
        value,
    )
    value = re.sub(r"\\[A-Za-z@]+\*?", " ", value)
    return re.findall(r"[a-z0-9]+", value.lower())


def tracked_markdown_overlap(tex: str, width: int = 12) -> dict:
    try:
        tracked_raw = subprocess.check_output(
            ["git", "ls-files", "-z", "--", "*.md"],
            cwd=ROOT,
            stderr=subprocess.PIPE,
        )
        tracked = [path for path in tracked_raw.decode("utf-8").split("\0") if path]
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        return {
            "width_words": width,
            "sources_scanned": 0,
            "overlaps": [],
            "errors": [f"could not enumerate tracked Markdown with git ls-files: {exc}"],
        }
    sources = [path for path in tracked if not path.startswith(("paper/", "release/"))]
    main_tokens = prose_tokens(tex)
    main_ngrams = {
        tuple(main_tokens[index:index + width])
        for index in range(max(0, len(main_tokens) - width + 1))
    }
    overlaps = []
    errors = []
    for relative in sources:
        path = ROOT / relative
        path_error = validate_regular_within(ROOT, path)
        if path_error:
            errors.append(f"{relative}: {path_error}")
            continue
        try:
            source_text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"{relative}: could not read tracked UTF-8 Markdown: {exc}")
            continue
        tokens = prose_tokens(source_text)
        source_ngrams = {
            tuple(tokens[index:index + width])
            for index in range(max(0, len(tokens) - width + 1))
        }
        for phrase in sorted(main_ngrams & source_ngrams):
            overlaps.append({"path": relative, "phrase": " ".join(phrase)})
    return {
        "width_words": width,
        "sources_scanned": len(sources),
        "overlaps": overlaps,
        "errors": errors,
    }


def citation_keys() -> set[str]:
    return set(re.findall(r"^@[^{]+\{([^,]+),", (PAPER / "references.bib").read_text(encoding="utf-8"), re.M))


def used_citations(tex: str) -> set[str]:
    keys = set()
    for group in re.findall(r"\\cite\{([^}]+)\}", tex):
        keys.update(key.strip() for key in group.split(","))
    return keys


def defined_commands() -> set[str]:
    commands = set()
    for path in (PAPER / "main.tex", PAPER / "results_macros.tex", PAPER / "diagnostic_macros.tex"):
        text = path.read_text(encoding="utf-8")
        commands.update(re.findall(r"\\newcommand\{\\([A-Za-z]+)\}", text))
    return commands


def safe_release_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
        and "\\" not in value
        and not path.is_absolute()
        and value == path.as_posix()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def expected_release_files() -> set[str]:
    files = set(RELEASE_STATIC_FILES)
    files.update(f"data/processed/{name}" for name in RELEASE_PROCESSED_FILES)
    files.update(f"docs/{name}" for name in RELEASE_DOC_FILES)
    files.add("docs/claim_ledger.csv")
    files.update(f"docs/protocols/{name}" for name in RELEASE_PROTOCOL_FILES)
    files.update({"scripts/build_figures.py", "scripts/generate_tables.py"})
    files.update(RELEASE_GENERATED_FILES)
    files.update(
        f"figures/{stem}.{suffix}"
        for stem in RELEASE_FIGURE_STEMS
        for suffix in ("pdf", "png")
    )
    files.add("MANIFEST.sha256")
    return files


def expected_release_directories(files: set[str]) -> set[str]:
    directories: set[str] = set()
    for name in files:
        parent = PurePosixPath(name).parent
        while parent != PurePosixPath("."):
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories


def audit_release_manifest() -> list[str]:
    """Independently reject malformed, incomplete, or overbroad releases."""

    errors: list[str] = []
    expected = expected_release_files()
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    if RELEASE.is_symlink() or not RELEASE.is_dir():
        return ["release root is missing, not a directory, or a symlink"]
    for path in RELEASE.rglob("*"):
        relative = path.relative_to(RELEASE).as_posix()
        if path.is_symlink():
            errors.append(f"symlink prohibited: {relative}")
        elif path.is_file():
            if path.stat().st_nlink != 1:
                errors.append(f"hard-linked file prohibited: {relative}")
            actual_files.add(relative)
        elif path.is_dir():
            actual_directories.add(relative)
        else:
            errors.append(f"special filesystem object prohibited: {relative}")
    if actual_files != expected:
        errors.append(
            "release file allow-list mismatch: "
            f"missing={sorted(expected - actual_files)}, extra={sorted(actual_files - expected)}"
        )
    expected_directories = expected_release_directories(expected)
    if actual_directories != expected_directories:
        errors.append(
            "release directory allow-list mismatch: "
            f"missing={sorted(expected_directories - actual_directories)}, "
            f"extra={sorted(actual_directories - expected_directories)}"
        )

    manifest = RELEASE / "MANIFEST.sha256"
    if manifest.is_symlink() or not manifest.is_file():
        errors.append("MANIFEST.sha256 missing, not regular, or a symlink")
        return errors
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        errors.append(f"manifest is not readable UTF-8: {exc}")
        return errors
    entries: dict[str, str] = {}
    for number, line in enumerate(lines, 1):
        match = MANIFEST_LINE.fullmatch(line)
        if not match:
            errors.append(f"malformed manifest line {number}")
            continue
        digest, relative = match.groups()
        if not safe_release_path(relative) or relative == "MANIFEST.sha256":
            errors.append(f"unsafe manifest path on line {number}: {relative!r}")
            continue
        if relative in entries:
            errors.append(f"duplicate manifest path: {relative}")
            continue
        entries[relative] = digest
    expected_entries = expected - {"MANIFEST.sha256"}
    if set(entries) != expected_entries:
        errors.append(
            "manifest entry set mismatch: "
            f"missing={sorted(expected_entries - set(entries))}, "
            f"extra={sorted(set(entries) - expected_entries)}"
        )
    for relative, expected_digest in entries.items():
        path = RELEASE / relative
        if relative not in actual_files or path.is_symlink() or not path.is_file():
            errors.append(f"manifest target missing/not regular: {relative}")
        elif sha256(path) != expected_digest:
            errors.append(f"manifest digest mismatch: {relative}")
    return errors


def audit_release_content() -> list[str]:
    errors: list[str] = []
    if not RELEASE.is_dir() or RELEASE.is_symlink():
        return ["release root unavailable for content audit"]
    for path in RELEASE.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(RELEASE).as_posix()
        lower = relative.lower()
        if any(lower.endswith(suffix) for suffix in RELEASE_PROHIBITED_SUFFIXES):
            errors.append(f"prohibited release suffix: {relative}")
        data = path.read_bytes()
        is_figure_binary = path.suffix.lower() in {".pdf", ".png"}
        if not is_figure_binary:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                errors.append(f"non-UTF-8 payload outside figure allow-list: {relative}")
                text = ""
        else:
            figure_error = validate_figure_binary(relative, data)
            if figure_error:
                errors.append(f"invalid released figure {relative}: {figure_error}")
            text = data.decode("utf-8", errors="ignore")
        searchable = relative + "\n" + text
        if is_figure_binary:
            if (
                str(ROOT).encode() in data
                or re.search(rb"/(?:Users|home|root|private|tmp|var)/", data)
                or RESTRICTED_URI_PATTERN.search(text)
                or WINDOWS_ABSOLUTE_PATTERN.search(text)
            ):
                errors.append(f"absolute/restricted local reference in binary figure: {relative}")
        else:
            references = local_reference_hits(searchable)
            if references:
                errors.append(
                    f"absolute/restricted local reference in {relative}: {references[:3]}"
                )
        for pattern in RELEASE_PROHIBITED_IDENTIFIERS:
            if re.search(pattern, searchable, re.I):
                errors.append(f"identifying opponent/team token in {relative}: {pattern}")
        for pattern in RELEASE_SECRET_PATTERNS:
            if re.search(pattern, text):
                errors.append(f"secret-like pattern in {relative}")
        if data.startswith((
            b"\x7fELF", b"MZ", b"PK\x03\x04", b"\x1f\x8b", b"\x93NUMPY",
            b"\xca\xfe\xba\xbe", b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
        )):
            errors.append(f"prohibited binary/archive magic: {relative}")
        if len(data) >= 2 and data[:2] in {b"\x80\x02", b"\x80\x03", b"\x80\x04", b"\x80\x05"}:
            errors.append(f"prohibited pickle payload: {relative}")
    return sorted(set(errors))


def main() -> int:
    checks = {}
    failures = []
    required = [
        "main.tex", "main.pdf", "references.bib", "results.tex", "results_macros.tex",
        "diagnostic_macros.tex", "claim_ledger.csv", "cover_letter.md",
        "data_availability.md", "ai_disclosure.md", "author_contributions.md",
        "conflict_of_interest.md", "limitations.md", "word_count.json",
    ]
    missing = [name for name in required if not (PAPER / name).is_file()]
    checks["required_paper_files"] = not missing
    if missing:
        failures.append(f"missing paper files: {missing}")

    tex = (PAPER / "main.tex").read_text(encoding="utf-8")
    forbidden = {
        "historical_4_5": r"(?:approximately|~|\\sim)\s*\+?4\.5",
        "unsupported_macro_1_8": r"\+1\.8",
        "unsupported_meta_2_0": r"\+2\.0",
        "false_cert_decisive": r"529\s+decisive",
        "private_team": r"Dreamer|GrimmsnaRL|Mint120|TMTA|lollipop947",
    }
    hits = {name: bool(re.search(pattern, tex, re.I)) for name, pattern in forbidden.items()}
    checks["unsupported_values_absent"] = not any(hits.values())
    if any(hits.values()):
        failures.append(f"forbidden manuscript strings: {hits}")

    available = citation_keys()
    used = used_citations(tex)
    checks["citations_resolve"] = used <= available
    checks["all_bibliography_entries_used"] = available <= used
    if not used <= available:
        failures.append(f"undefined citation keys: {sorted(used - available)}")
    if not available <= used:
        failures.append(f"unused bibliography keys: {sorted(available - used)}")

    generated = defined_commands()
    used_commands = set(re.findall(r"\\([A-Z][A-Za-z]+)", tex))
    builtins = {"Delta", "LaTeX"}
    unresolved = used_commands - generated - builtins
    checks["generated_macros_resolve"] = not unresolved
    if unresolved:
        failures.append(f"unresolved manuscript macros: {sorted(unresolved)}")

    with (PAPER / "claim_ledger.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        claims = list(reader)
        fields_ok = reader.fieldnames == REQUIRED_CLAIM_FIELDS
    statuses = {"VERIFIED", "VERIFIED_WITH_CAVEAT", "CONFLICT", "UNSUPPORTED", "REQUIRES_RERUN"}
    bad_status = [row["claim_id"] for row in claims if row["status"] not in statuses]
    bad_include = [row["claim_id"] for row in claims
                   if row["include_or_omit"] == "INCLUDE"
                   and row["status"] not in {"VERIFIED", "VERIFIED_WITH_CAVEAT"}]
    duplicate_ids = [key for key, count in __import__("collections").Counter(
        row["claim_id"] for row in claims
    ).items() if count > 1]
    checks["claim_schema"] = fields_ok
    checks["claim_statuses"] = not bad_status
    checks["claim_gate"] = not bad_include
    checks["claim_ids_unique"] = not duplicate_ids
    if not all((fields_ok, not bad_status, not bad_include, not duplicate_ids)):
        failures.append(
            f"claim ledger error: fields={fields_ok}, statuses={bad_status}, "
            f"included={bad_include}, duplicates={duplicate_ids}"
        )

    figures = sorted((PAPER / "figures").glob("fig*.pdf"))
    pngs = sorted((PAPER / "figures").glob("fig*.png"))
    checks["six_figures_two_formats"] = len(figures) == 6 and len(pngs) == 6
    if not checks["six_figures_two_formats"]:
        failures.append(f"figure count pdf/png = {len(figures)}/{len(pngs)}")

    overlap_report = tracked_markdown_overlap(tex, width=12)
    overlap_ok = not overlap_report["overlaps"] and not overlap_report["errors"]
    checks["no_exact_12_word_overlap_with_tracked_markdown"] = overlap_ok
    if not overlap_ok:
        failures.append(
            "exact 12-word tracked-Markdown overlap audit failed: "
            f"overlaps={overlap_report['overlaps'][:20]}, errors={overlap_report['errors']}"
        )

    stats = load_json_strict(PAPER / "data/statistical_summary.json")
    source_hashes = {
        item["path"]: sha256(ROOT / item["path"])
        for item in stats["source_inventory"]
    }
    drift = [item["path"] for item in stats["source_inventory"]
             if source_hashes[item["path"]] != item["sha256"]]
    checks["statistical_sources_unchanged"] = not drift
    if drift:
        failures.append(f"source digest drift: {drift}")

    manifest = RELEASE / "MANIFEST.sha256"
    manifest_errors = audit_release_manifest()
    checks["release_exact_allowlist_and_manifest"] = not manifest_errors
    if manifest_errors:
        failures.append(f"release manifest errors: {manifest_errors}")

    release_content_errors = audit_release_content()
    checks["release_sanitization_and_binary_gate"] = not release_content_errors
    if release_content_errors:
        failures.append(f"release content errors: {release_content_errors}")

    verifier = RELEASE / "evaluation/verify_processed.py"
    verifier_path_error = validate_regular_within(RELEASE, verifier)
    verifier_gate_ok = not manifest_errors and not release_content_errors and not verifier_path_error
    checks["release_verifier_execution_gate"] = verifier_gate_ok
    if verifier_gate_ok:
        verification = subprocess.run(
            [sys.executable, "-B", "evaluation/verify_processed.py"],
            cwd=RELEASE,
            text=True,
            capture_output=True,
            check=False,
        )
        verifier_ok = verification.returncode == 0
        verifier_detail = (verification.stderr or verification.stdout).strip()[-2000:]
    else:
        verifier_ok = False
        verifier_detail = (
            "release verifier execution blocked until manifest, content, and ancestry checks pass: "
            f"manifest_errors={manifest_errors}, content_errors={release_content_errors}, "
            f"path_error={verifier_path_error}"
        )
    checks["release_processed_verifier"] = verifier_ok
    if not verifier_ok:
        failures.append(f"release processed verifier failed: {verifier_detail}")

    license_text = (RELEASE / "LICENSE").read_text(encoding="utf-8") \
        if (RELEASE / "LICENSE").is_file() else ""
    citation_text = (RELEASE / "CITATION.cff").read_text(encoding="utf-8") \
        if (RELEASE / "CITATION.cff").is_file() else ""
    rights_blocker_preserved = "NO LICENSE GRANTED" in license_text
    authorship_blocker_preserved = bool(re.search(
        r"(?m)^\s+(?:family-names|given-names)\s*:\s*[\"']?\[REQUIRED\]",
        citation_text,
    ))
    doi_value = re.search(r"(?m)^doi\s*:\s*([^\r\n#]*)", citation_text)
    doi_blocker_preserved = (
        doi_value is None
        or not doi_value.group(1).strip().strip("\"'")
        or "[REQUIRED]" in doi_value.group(1)
    )
    citation_blocker_preserved = authorship_blocker_preserved and doi_blocker_preserved
    checks["release_rights_blocker_preserved"] = rights_blocker_preserved
    checks["release_authorship_blocker_preserved"] = authorship_blocker_preserved
    checks["release_doi_blocker_preserved"] = doi_blocker_preserved
    checks["release_authorship_doi_blocker_preserved"] = citation_blocker_preserved
    if not rights_blocker_preserved:
        failures.append("release rights-review/no-license blocker was removed without authorization")
    if not citation_blocker_preserved:
        failures.append("release authorship/DOI placeholder blocker was removed without authorization")

    release_blockers = []
    if rights_blocker_preserved:
        release_blockers.append("approved release license is absent")
    if authorship_blocker_preserved:
        release_blockers.append("author metadata are incomplete")
    if doi_blocker_preserved:
        release_blockers.append("archival identifier/DOI metadata are absent")
    tracked_historical = subprocess.check_output(
        ["git", "diff", "--name-only", "ee567ed5b75029b3785c3b44725c5d55f94f9abd", "--"],
        cwd=ROOT, text=True,
    ).splitlines()
    unexpected = [path for path in tracked_historical if not (path.startswith("paper/") or path.startswith("release/"))]
    checks["historical_tree_untouched"] = not unexpected
    if unexpected:
        failures.append(f"non-paper/release tracked changes: {unexpected}")

    release_readiness = "BLOCKED" if release_blockers or failures else "READY_FOR_AUTHORIZED_RELEASE"

    report = {
        "status": "PASS" if not failures else "FAIL",
        "release_readiness": release_readiness,
        "release_blockers": release_blockers,
        "checks": checks,
        "failures": failures,
        "tracked_markdown_overlap": overlap_report,
        "claim_count": len(claims),
        "claim_status_counts": dict(__import__("collections").Counter(row["status"] for row in claims)),
        "paper_pdf_sha256": sha256(PAPER / "main.pdf") if (PAPER / "main.pdf").is_file() else None,
        "release_manifest_sha256": sha256(manifest) if manifest.is_file() else None,
    }
    output = PAPER / "supplement/FINAL_RED_TEAM.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
