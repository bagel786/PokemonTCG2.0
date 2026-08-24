#!/usr/bin/env python3
"""Bounded static stochastic-source audit for PEVL Levels 1 and 6.

The audit first checks the exact frozen artifact bytes and then scans Python
source in verified package trees for explicit source patterns.  It is a lexical
and AST-based inventory, not a proof of determinism: a zero-hit category means
only that this scanner found no explicit instance of its bounded patterns.

Restricted competition packages are reported with aggregate counts and
location fingerprints.  Their source paths, line numbers, and snippets are not
written to the public JSON.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import re
import subprocess
import tokenize
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "paper/data/stochastic_source_audit.json"
PROTOCOL = ROOT / "paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md"
PYTHON_SUFFIXES = frozenset({".py", ".pyi"})
MAX_PUBLIC_EVIDENCE_PER_CATEGORY = 100


@dataclass(frozen=True)
class ArtifactSpec:
    artifact_id: str
    label: str
    role: str
    population: str
    relative_path: str
    expected_sha256: str
    environment: Mapping[str, str]
    scan_python_source: bool
    redistributable_source: bool = False


ARTIFACTS: tuple[ArtifactSpec, ...] = (
    ArtifactSpec(
        "seeded_engine",
        "engine",
        "seeded engine",
        "all PEVL executions",
        "artifacts/deterministic_engine/bin/libcg_seeded.dylib",
        "867e3f9bb87e0b48889a44b5d4b04f5d2d434b2a0788d1b2bcfe0caebcb5ab78",
        {},
        False,
    ),
    ArtifactSpec(
        "production_engine",
        "production engine",
        "production sentinel engine",
        "all PEVL executions",
        "vendor/cg/libcg.dylib",
        "7a157f045d333f99d1996d49c12bdbdd148072a619af246385c7295518776e30",
        {},
        False,
    ),
    ArtifactSpec(
        "c1",
        "C1",
        "blind encoder, original weights",
        "trace preflight and factorial",
        "artifacts/grim_damage_conversion/winner/extracted",
        "13426288358d597ead809e45c364c7f7b9274a6eebf55ddd942142e3326535c3",
        {},
        True,
    ),
    ArtifactSpec(
        "c2",
        "C2",
        "identity encoder, original weights",
        "trace preflight and factorial",
        "artifacts/grim_play_identity/candidates/p0",
        "36e804ae6c593db57b595bfca9fd48592da10957f0e5f840a7e390edbeb39b63",
        {},
        True,
    ),
    ArtifactSpec(
        "c3",
        "C3",
        "blind encoder, trained weights",
        "trace preflight and factorial",
        "artifacts/paper_ablation/blind_trained_package",
        "236afa20b4ced63169736fea616849fa564281c05e9435e4dd77ecfb4ae5fd54",
        {},
        True,
    ),
    ArtifactSpec(
        "c4",
        "C4",
        "identity encoder, trained weights",
        "trace preflight and factorial",
        "artifacts/final_sprint/exp23_identity_trained",
        "83489e0c80c631763c65375d2a7a34d28d6aa9fbb1d11e89d130c83b1e27f1c0",
        {},
        True,
    ),
    ArtifactSpec(
        "opponent_b0",
        "B0",
        "opponent package",
        "five determinism-eligible opponents",
        "artifacts/grim_variance_floor/candidates/B0",
        "0c15b56adf3b09c654505a152309fdc9f8401579a495da714347d98ae735003c",
        {},
        True,
    ),
    ArtifactSpec(
        "opponent_d842_runtime",
        "d842-runtime",
        "opponent package",
        "five determinism-eligible opponents",
        "artifacts/overnight_20260816/d842_runtime",
        "7db753d6610930d8bd9694b4b9bece5ac48733b825422a3e399c18077b55e64e",
        {},
        True,
    ),
    ArtifactSpec(
        "opponent_master_v1",
        "master-v1",
        "opponent package",
        "five determinism-eligible opponents",
        "artifacts/grim_damage_conversion/opponents/master_v1",
        "8a06ebab47cc60ed981dfada85972eb8a62e732e349f01c2a3085262079f06e8",
        {},
        True,
    ),
    ArtifactSpec(
        "opponent_replay_refresh",
        "replay-refresh",
        "opponent package",
        "five determinism-eligible opponents",
        "artifacts/grim_damage_conversion/opponents/replay_refresh",
        "30e45955b67893514c8ee077cac15d46fc207efe781cbce1b94242defda4cbdc",
        {},
        True,
    ),
    ArtifactSpec(
        "opponent_alakazam_no_search",
        "Alakazam-no-search",
        "opponent package",
        "five determinism-eligible opponents",
        "artifacts/sprint_870/opponents/alakazam_2_4a",
        "5d44338891094988ca15f0c26d5187316549facd64a7bfbac04aa0048424e8c7",
        {"NO_SEARCH": "1"},
        True,
    ),
    ArtifactSpec(
        "opponent_starmie",
        "Starmie",
        "opponent package",
        "timed-search diagnostic opponents",
        "artifacts/sprint_870/opponents/starmie_v2_boss_atk",
        "1b73779da7dcc93c8f121090bb0f1ae2d9b10b798ca4c70447b0ce1d6d01c0db",
        {},
        True,
    ),
    ArtifactSpec(
        "opponent_dipplin",
        "Dipplin",
        "opponent package",
        "timed-search diagnostic opponents",
        "artifacts/sprint_870/opponents/dipplin_d1",
        "076ae8de12d2d6c4a170b47b2d2f9cf538c1d318a05bb2e81f13da9be2cd2026",
        {},
        True,
    ),
)


CATEGORY_DEFINITIONS: dict[str, str] = {
    "explicit_randomness": (
        "Imports and calls for common pseudorandom, entropy, UUID, sampling, "
        "shuffle, and process-randomized hash interfaces."
    ),
    "clock_or_deadline": (
        "Clock reads, time-module imports, and identifiers explicitly naming "
        "deadlines, timeouts, wall clocks, or time budgets."
    ),
    "process_or_thread_parallelism": (
        "Multiprocessing, threading, futures, asyncio, joblib, and fork APIs "
        "that can introduce scheduling or shared-state sensitivity."
    ),
    "module_global_state": (
        "Module-scope constructed or mutable bindings, state-like global names, "
        "module mutations, and explicit global statements."
    ),
    "native_pointer_or_state": (
        "ctypes/cffi/native-library references and pointer- or handle-like "
        "identifiers that may bridge process-local native state."
    ),
}


RANDOM_IMPORT_ROOTS = frozenset({"random", "secrets"})
RANDOM_CALL_PREFIXES = (
    "random.",
    "secrets.",
    "numpy.random.",
    "torch.random.",
)
RANDOM_CALL_NAMES = frozenset(
    {
        "os.urandom",
        "uuid.uuid1",
        "uuid.uuid4",
        "torch.rand",
        "torch.randn",
        "torch.randint",
        "torch.multinomial",
        "torch.bernoulli",
        "torch.normal",
        "torch.poisson",
    }
)
RANDOM_METHOD_NAMES = frozenset(
    {
        "choice",
        "choices",
        "default_rng",
        "gauss",
        "normal",
        "permutation",
        "rand",
        "randint",
        "randn",
        "random",
        "randrange",
        "sample",
        "shuffle",
        "uniform",
    }
)
CLOCK_IMPORT_ROOTS = frozenset({"time", "datetime"})
CLOCK_CALL_NAMES = frozenset(
    {
        "time.time",
        "time.time_ns",
        "time.monotonic",
        "time.monotonic_ns",
        "time.perf_counter",
        "time.perf_counter_ns",
        "time.process_time",
        "time.process_time_ns",
        "time.thread_time",
        "time.thread_time_ns",
        "datetime.datetime.now",
        "datetime.datetime.utcnow",
        "datetime.date.today",
    }
)
DEADLINE_IDENTIFIER = re.compile(
    r"(?:deadline|timeout|time_limit|time_budget|wall_clock|move_budget)", re.IGNORECASE
)
PARALLEL_IMPORT_ROOTS = frozenset(
    {"multiprocessing", "threading", "asyncio", "joblib"}
)
PARALLEL_CALL_TOKENS = frozenset(
    {
        "Process",
        "Pool",
        "ProcessPoolExecutor",
        "Thread",
        "ThreadPoolExecutor",
        "Lock",
        "RLock",
        "Semaphore",
        "Barrier",
        "Event",
        "create_task",
        "gather",
        "run_in_executor",
        "Parallel",
        "delayed",
        "fork",
    }
)
STATE_IDENTIFIER = re.compile(
    r"(?:^|_)(?:agent|rng|state|cache|counter|stats|pool|session|client|handle|"
    r"ptr|pointer|registry|memo)(?:$|_)",
    re.IGNORECASE,
)
NATIVE_IDENTIFIER = re.compile(
    r"(?:ptr|pointer|native_handle|battleptr|agent_ptr)", re.IGNORECASE
)
NATIVE_IMPORT_ROOTS = frozenset({"ctypes", "cffi"})
NATIVE_CALL_TOKENS = frozenset(
    {"CDLL", "LoadLibrary", "dlopen", "c_void_p", "POINTER", "byref", "cast"}
)


@dataclass(frozen=True, order=True)
class SourceHit:
    category: str
    pattern_id: str
    relative_path: str
    line: int
    snippet: str


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256_path(path: Path) -> str:
    """Match the evaluator's frozen file/tree digest contract exactly."""
    if path.is_file():
        return sha256_file(path)
    digest = hashlib.sha256()
    for child in sorted(
        item
        for item in path.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"
    ):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(child)))
    return digest.hexdigest()


def _canonical_records_sha256(records: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records):
        encoded = record.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _collect_import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                aliases[local] = alias.name if alias.asname else local
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                aliases[local] = f"{module}.{alias.name}" if module else alias.name
    return aliases


def _assigned_names(target: ast.AST) -> Iterator[str]:
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for child in target.elts:
            yield from _assigned_names(child)


def _is_mutable_expression(node: ast.AST | None) -> bool:
    return isinstance(
        node,
        (
            ast.Dict,
            ast.DictComp,
            ast.List,
            ast.ListComp,
            ast.Set,
            ast.SetComp,
        ),
    )


class StochasticSourceVisitor(ast.NodeVisitor):
    """Collect bounded stochastic/state patterns from one Python syntax tree."""

    def __init__(
        self,
        relative_path: str,
        source_lines: Sequence[str],
        aliases: Mapping[str, str],
    ) -> None:
        self.relative_path = relative_path
        self.source_lines = source_lines
        self.aliases = dict(aliases)
        self._scope_depth = 0
        self._hits: dict[tuple[str, str, str, int], SourceHit] = {}

    @property
    def hits(self) -> list[SourceHit]:
        return sorted(self._hits.values())

    def _resolve(self, name: str | None) -> str:
        if not name:
            return ""
        first, separator, rest = name.partition(".")
        resolved = self.aliases.get(first, first)
        return f"{resolved}.{rest}" if separator else resolved

    def _emit(self, category: str, pattern_id: str, node: ast.AST) -> None:
        line = max(1, int(getattr(node, "lineno", 1)))
        raw = self.source_lines[line - 1].strip() if line <= len(self.source_lines) else ""
        snippet = re.sub(r"\s+", " ", raw)[:240]
        key = (category, pattern_id, self.relative_path, line)
        self._hits.setdefault(
            key,
            SourceHit(category, pattern_id, self.relative_path, line, snippet),
        )

    def _audit_import(self, module: str, node: ast.AST) -> None:
        root = module.split(".", 1)[0]
        if root in RANDOM_IMPORT_ROOTS or module.startswith("numpy.random"):
            self._emit("explicit_randomness", "rng.module_import", node)
        if root in CLOCK_IMPORT_ROOTS:
            self._emit("clock_or_deadline", "clock.module_import", node)
        if root in PARALLEL_IMPORT_ROOTS:
            self._emit(
                "process_or_thread_parallelism", "parallel.module_import", node
            )
        if module.startswith("concurrent.futures"):
            self._emit(
                "process_or_thread_parallelism",
                "parallel.concurrent_futures_import",
                node,
            )
        if root in NATIVE_IMPORT_ROOTS:
            self._emit("native_pointer_or_state", "native.ffi_import", node)

    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            self._audit_import(alias.name, node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        module = node.module or ""
        self._audit_import(module, node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        raw_name = _dotted_name(node.func)
        name = self._resolve(raw_name)
        final = name.rsplit(".", 1)[-1] if name else ""

        if (
            name.startswith(RANDOM_CALL_PREFIXES)
            or name in RANDOM_CALL_NAMES
            or final in RANDOM_METHOD_NAMES
        ):
            pattern = (
                "rng.resolved_api_call"
                if name.startswith(RANDOM_CALL_PREFIXES) or name in RANDOM_CALL_NAMES
                else "rng.random_like_method_call"
            )
            self._emit("explicit_randomness", pattern, node)
        if name == "hash":
            self._emit("explicit_randomness", "rng.process_hash_call", node)

        if name in CLOCK_CALL_NAMES:
            self._emit("clock_or_deadline", "clock.read_call", node)

        if (
            name.startswith("multiprocessing.")
            or name.startswith("threading.")
            or name.startswith("asyncio.")
            or name.startswith("joblib.")
            or name.startswith("concurrent.futures.")
            or name == "os.fork"
            or final in PARALLEL_CALL_TOKENS
        ):
            self._emit(
                "process_or_thread_parallelism", "parallel.api_call", node
            )

        if (
            name.startswith("ctypes.")
            or name.startswith("cffi.")
            or final in NATIVE_CALL_TOKENS
        ):
            self._emit("native_pointer_or_state", "native.ffi_call", node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> Any:
        if DEADLINE_IDENTIFIER.search(node.id):
            self._emit("clock_or_deadline", "clock.deadline_identifier", node)
        if NATIVE_IDENTIFIER.search(node.id):
            self._emit(
                "native_pointer_or_state", "native.pointer_identifier", node
            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        name = self._resolve(_dotted_name(node))
        if DEADLINE_IDENTIFIER.search(node.attr):
            self._emit("clock_or_deadline", "clock.deadline_identifier", node)
        if name.startswith("ctypes.") or name.startswith("cffi."):
            self._emit("native_pointer_or_state", "native.ffi_reference", node)
        if NATIVE_IDENTIFIER.search(node.attr):
            self._emit(
                "native_pointer_or_state", "native.pointer_identifier", node
            )
        self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> Any:
        if DEADLINE_IDENTIFIER.search(node.arg):
            self._emit("clock_or_deadline", "clock.deadline_identifier", node)
        if NATIVE_IDENTIFIER.search(node.arg):
            self._emit(
                "native_pointer_or_state", "native.pointer_identifier", node
            )
        self.generic_visit(node)

    def _audit_module_binding(
        self, names: Iterable[str], value: ast.AST | None, node: ast.AST
    ) -> None:
        if self._scope_depth:
            return
        names = tuple(names)
        if not names:
            return
        if _is_mutable_expression(value):
            self._emit(
                "module_global_state", "state.module_mutable_binding", node
            )
        if isinstance(value, ast.Call):
            self._emit(
                "module_global_state", "state.module_constructed_binding", node
            )
        if any(STATE_IDENTIFIER.search(name) for name in names):
            self._emit(
                "module_global_state", "state.module_state_named_binding", node
            )
        if any(NATIVE_IDENTIFIER.search(name) for name in names):
            self._emit(
                "native_pointer_or_state", "native.module_pointer_binding", node
            )

    def visit_Assign(self, node: ast.Assign) -> Any:
        names = [name for target in node.targets for name in _assigned_names(target)]
        self._audit_module_binding(names, node.value, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        self._audit_module_binding(_assigned_names(node.target), node.value, node)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> Any:
        if not self._scope_depth:
            self._emit("module_global_state", "state.module_mutation", node)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> Any:
        self._emit("module_global_state", "state.global_statement", node)
        if any(NATIVE_IDENTIFIER.search(name) for name in node.names):
            self._emit(
                "native_pointer_or_state", "native.global_pointer_statement", node
            )
        self.generic_visit(node)

    def _visit_nested_scope(self, node: ast.AST) -> None:
        self._scope_depth += 1
        try:
            self.generic_visit(node)
        finally:
            self._scope_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._visit_nested_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._visit_nested_scope(node)

    def visit_Lambda(self, node: ast.Lambda) -> Any:
        self._visit_nested_scope(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self._visit_nested_scope(node)


def _python_source_files(package: Path) -> list[Path]:
    return sorted(
        child
        for child in package.rglob("*")
        if child.is_file()
        and child.suffix in PYTHON_SUFFIXES
        and "__pycache__" not in child.parts
    )


def _decode_python(raw: bytes) -> str:
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    return raw.decode(encoding)


def _category_summary(
    hits: Sequence[SourceHit], *, redistributable_source: bool
) -> dict[str, Any]:
    records = [f"{hit.relative_path}:{hit.line}:{hit.pattern_id}" for hit in hits]
    result: dict[str, Any] = {
        "result": (
            "explicit_pattern_hits_found"
            if hits
            else "no_explicit_pattern_hit_found"
        ),
        "hit_count": len(hits),
        "distinct_source_files_with_hits": len(
            {hit.relative_path for hit in hits}
        ),
        "pattern_counts": dict(sorted(Counter(hit.pattern_id for hit in hits).items())),
        "location_fingerprint_sha256": (
            _canonical_records_sha256(records) if records else None
        ),
        "interpretation": (
            "Candidate source patterns were found; they require dynamic validation "
            "and do not by themselves establish run-to-run variation."
            if hits
            else "No explicit bounded scanner pattern was found; this is not evidence "
            "that the package or execution is deterministic."
        ),
    }
    if redistributable_source:
        public_hits = hits[:MAX_PUBLIC_EVIDENCE_PER_CATEGORY]
        result["evidence"] = [
            {
                "path": hit.relative_path,
                "line": hit.line,
                "category": hit.category,
                "pattern_id": hit.pattern_id,
                "snippet": hit.snippet,
            }
            for hit in public_hits
        ]
        result["evidence_truncated"] = len(public_hits) < len(hits)
    return result


def scan_python_package(
    package: Path, *, redistributable_source: bool = False
) -> dict[str, Any]:
    """Scan Python source and return a disclosure-aware bounded audit summary."""
    source_files = _python_source_files(package)
    hits: list[SourceHit] = []
    source_records: list[str] = []
    error_records: list[str] = []
    scanned_bytes = 0
    decoded_count = 0
    parsed_count = 0

    for source_path in source_files:
        relative_path = source_path.relative_to(package).as_posix()
        raw = source_path.read_bytes()
        scanned_bytes += len(raw)
        source_records.append(f"{relative_path}:{hashlib.sha256(raw).hexdigest()}")
        try:
            source = _decode_python(raw)
            decoded_count += 1
        except (LookupError, SyntaxError, UnicodeDecodeError) as exc:
            error_records.append(
                f"{relative_path}:decode:{type(exc).__name__}"
            )
            continue
        try:
            tree = ast.parse(source, filename=relative_path, type_comments=True)
            parsed_count += 1
        except SyntaxError as exc:
            error_records.append(
                f"{relative_path}:parse:{type(exc).__name__}:{exc.lineno or 0}"
            )
            continue
        visitor = StochasticSourceVisitor(
            relative_path,
            source.splitlines(),
            _collect_import_aliases(tree),
        )
        visitor.visit(tree)
        hits.extend(visitor.hits)

    hits = sorted(set(hits))
    category_hits = {
        category: [hit for hit in hits if hit.category == category]
        for category in CATEGORY_DEFINITIONS
    }
    return {
        "status": (
            "completed_static_python_ast_scan"
            if not error_records
            else "completed_with_unparsed_python_sources"
        ),
        "method": "Python AST plus bounded qualified-name and identifier patterns",
        "scanned_extensions": sorted(PYTHON_SUFFIXES),
        "python_source_file_count": len(source_files),
        "decoded_source_file_count": decoded_count,
        "parsed_source_file_count": parsed_count,
        "unparsed_source_file_count": len(error_records),
        "scanned_source_bytes": scanned_bytes,
        "python_source_set_sha256": _canonical_records_sha256(source_records),
        "parse_error_location_fingerprint_sha256": (
            _canonical_records_sha256(error_records) if error_records else None
        ),
        "evidence_disclosure": (
            "path_line_category_snippet_for_redistributable_source"
            if redistributable_source
            else "aggregate_counts_and_location_fingerprints_only_restricted_source"
        ),
        "source_paths_disclosed": redistributable_source,
        "source_line_numbers_disclosed": redistributable_source,
        "source_snippets_disclosed": redistributable_source,
        "categories": {
            category: _category_summary(
                category_hits[category],
                redistributable_source=redistributable_source,
            )
            for category in CATEGORY_DEFINITIONS
        },
        "scope_limits": [
            "The scan covers only .py and .pyi files inside the frozen package tree.",
            "AST and qualified-name patterns can miss aliases, dynamic imports, reflection, generated code, and behavior hidden behind wrappers.",
            "The scan does not execute code, resolve environment-selected branches, inspect native binary internals, or observe runtime scheduling.",
            "No explicit hit found is not a proof of deterministic behavior; dynamic repeat/worker trace checks remain necessary.",
        ],
    }


def _not_assessed_source(reason: str) -> dict[str, Any]:
    return {
        "status": "not_assessed",
        "reason": reason,
        "categories": {
            category: {
                "result": "not_assessed",
                "hit_count": None,
                "distinct_source_files_with_hits": None,
                "pattern_counts": None,
                "location_fingerprint_sha256": None,
                "interpretation": (
                    "No source-level inference is available for this artifact."
                ),
            }
            for category in CATEGORY_DEFINITIONS
        },
    }


def audit_artifact(
    root: Path, spec: ArtifactSpec, *, protocol_text: str
) -> dict[str, Any]:
    path = root / spec.relative_path
    exists = path.exists()
    kind = "file" if path.is_file() else "tree" if path.is_dir() else "missing"
    observed = canonical_sha256_path(path) if exists else None
    hash_match = observed == spec.expected_sha256

    if not hash_match:
        source_audit = _not_assessed_source(
            "Source scan skipped because the local bytes do not match the frozen artifact."
        )
    elif not spec.scan_python_source:
        source_audit = _not_assessed_source(
            "Frozen engine artifact is binary-only in this inventory; source internals were unavailable to the bounded Python scanner."
        )
    else:
        source_audit = scan_python_package(
            path, redistributable_source=spec.redistributable_source
        )

    return {
        "artifact_id": spec.artifact_id,
        "label": spec.label,
        "role": spec.role,
        "population": spec.population,
        "local_path": spec.relative_path,
        "artifact_kind": kind,
        "environment": dict(spec.environment),
        "expected_sha256": spec.expected_sha256,
        "observed_sha256": observed,
        "exists": exists,
        "hash_match": hash_match,
        "expected_digest_present_in_frozen_protocol": (
            spec.expected_sha256 in protocol_text
        ),
        "source_audit": source_audit,
    }


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def build_audit(root: Path = ROOT) -> dict[str, Any]:
    protocol = root / PROTOCOL.relative_to(ROOT)
    protocol_text = protocol.read_text(encoding="utf-8")
    inventory = [
        audit_artifact(root, spec, protocol_text=protocol_text) for spec in ARTIFACTS
    ]
    verified = [row for row in inventory if row["hash_match"]]
    package_rows = [
        row
        for row in inventory
        if row["source_audit"]["status"].startswith("completed_")
    ]
    category_artifact_counts = {
        category: sum(
            int(row["source_audit"]["categories"][category]["hit_count"] > 0)
            for row in package_rows
        )
        for category in CATEGORY_DEFINITIONS
    }
    category_hit_counts = {
        category: sum(
            int(row["source_audit"]["categories"][category]["hit_count"])
            for row in package_rows
        )
        for category in CATEGORY_DEFINITIONS
    }
    all_hashes_match = len(verified) == len(inventory)
    all_protocol_digests_bound = all(
        row["expected_digest_present_in_frozen_protocol"] for row in inventory
    )

    return {
        "schema_version": "pevl-stochastic-source-audit-v1",
        "audit_levels": [1, 6],
        "audit_claim": (
            "Bounded artifact-identity and static source-pattern inventory only; "
            "this report neither proves determinism nor treats an empty category "
            "as evidence that stochastic behavior is absent."
        ),
        "hash_contract": (
            "SHA-256 for files; for trees, sorted relative file names and file "
            "digests with __pycache__ directories and .pyc files excluded, exactly "
            "matching training/evaluate_deterministic_crn.py::sha256_path."
        ),
        "category_definitions": CATEGORY_DEFINITIONS,
        "level_results": {
            "level_1_artifact_identity": {
                "status": "pass" if all_hashes_match else "fail",
                "artifact_count": len(inventory),
                "verified_artifact_count": len(verified),
                "all_frozen_hashes_match": all_hashes_match,
                "all_expected_digests_present_in_frozen_protocol": (
                    all_protocol_digests_bound
                ),
            },
            "level_6_stochastic_source_audit": {
                "status": "bounded_audit_recorded",
                "verified_package_tree_count": len(package_rows),
                "artifacts_with_hits_by_category": category_artifact_counts,
                "aggregate_hits_by_category": category_hit_counts,
                "admission_interpretation": (
                    "Source hits identify mechanisms for dynamic testing. A clean "
                    "static category does not admit a paired contrast or establish "
                    "determinism."
                ),
            },
        },
        "disclosure_policy": {
            "restricted_package_source": (
                "Aggregate hit counts, generalized pattern counts, and salted-free "
                "canonical location fingerprints only."
            ),
            "source_paths_lines_snippets_included": False,
            "card_and_deck_material_included": False,
        },
        "scope_limits": [
            "The two engine artifacts are verified byte-for-byte but not source-audited; their native internals are unavailable here.",
            "Only frozen package .py and .pyi files are statically scanned; models, data files, native libraries, interpreter state, and operating-system behavior are outside scope.",
            "A static hit may be unreachable under the recorded environment (including NO_SEARCH=1), and a static no-hit may conceal indirect or dynamic behavior.",
            "The scanner does not establish event-level coupling, repeat parity, worker parity, or statistical admission; those require the separate prospective runtime gates.",
        ],
        "inventory": inventory,
        "provenance": {
            "script": Path(__file__).resolve().relative_to(ROOT).as_posix(),
            "script_sha256": sha256_file(Path(__file__).resolve()),
            "frozen_protocol": protocol.relative_to(root).as_posix(),
            "frozen_protocol_sha256": sha256_file(protocol),
            "git_commit": _git_commit(root),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT,
        help="JSON output path (default: paper/data/stochastic_source_audit.json)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_audit(ROOT)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = {
        "output": str(output),
        "level_1": result["level_results"]["level_1_artifact_identity"],
        "level_6": result["level_results"]["level_6_stochastic_source_audit"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if result["level_results"]["level_1_artifact_identity"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
