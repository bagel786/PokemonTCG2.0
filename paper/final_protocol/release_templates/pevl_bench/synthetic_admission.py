"""Route the frozen synthetic fixture audits through ``AdmissionProtocol``.

The copied synthetic source remains byte-for-byte frozen.  This adapter checks
its existing evidence digests, converts its seven gate rows to the common state
vocabulary, classifies each vector with the same admission engine, and retains
the fixture's original Level-8 disposition.  The latter remains authoritative
for each frozen fixture; the generic post-acquisition taxonomy can describe a
weaker class but does not retroactively loosen a fixture-specific suppression.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from . import synthetic
from .admission import (
    INPUT_SCHEMA_VERSION,
    PROTOCOL_ID,
    TRUSTED_INPUT_KIND,
    AdmissionProtocol,
    _object_sha256,
)


ADAPTER_ID = "pevl-synthetic-audit-adapter-1.0.0"
SCHEMA_VERSION = "synthetic-admission-decisions-1.0.0"
_STATE_MAP = {"pass": "pass", "fail": "fail", "blocked": "unavailable"}
_FIXTURE_DISPOSITION_BY_CLASS = {
    "event_aligned": "admit",
    "seed_matched_bounded": "downgrade",
    "execution_repeatable": "suppress",
    "schedule_matched": "suppress",
    "descriptive_unmatched": "suppress",
    "suppress": "suppress",
}


def _render_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _decision_for_mode(
    mode: Mapping[str, Any], protocol: AdmissionProtocol
) -> dict[str, Any]:
    audits = mode["audit"]
    gates = audits[:7]
    for row in gates:
        if row["evidence_sha256"] != synthetic.object_sha256(row["evidence"]):
            raise ValueError(
                f"{mode['mode']}: Level {row['level']} synthetic evidence digest mismatch"
            )
    states = {
        gate: _STATE_MAP[row["status"]]
        for gate, row in zip(protocol.gate_order, gates)
    }
    binding_payload = {
        "adapter_id": ADAPTER_ID,
        "mode": mode["mode"],
        "gate_evidence_sha256": [row["evidence_sha256"] for row in gates],
        "gate_states": states,
    }
    binding = _object_sha256(binding_payload)
    certificates = [
        {
            "gate": gate,
            "state": states[gate],
            "evidence_sha256": row["evidence_sha256"],
            "verifier_id": ADAPTER_ID,
            "reason": row["summary"],
        }
        for gate, row in zip(protocol.gate_order, gates)
    ]
    trusted = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "input_kind": TRUSTED_INPUT_KIND,
        "evidence": states,
        "trace_projection": {
            "id": "synthetic-public-trace",
            "version": synthetic.SCHEMA_VERSION,
            "fields": ["action", "public_state", "step"],
        },
    }
    decision = protocol._evaluate_verifier_states(
        trusted,
        evidence_binding_sha256=binding,
        verifier_id=ADAPTER_ID,
        gate_certificates=certificates,
        input_assurance="synthetic_fixture_adapter_checks_evaluated",
        classifier_scope="classification_after_in_memory_synthetic_adapter_checks",
        evidence_trust_anchor="self_asserted_synthetic_fixture_consistency",
        verification_scope=(
            "The adapter checked in-memory synthetic fixture evidence digests and mapped "
            "the declared synthetic mode states. It did not verify external acquisition files, "
            "execution-profile provenance, or scientific authenticity."
        ),
        verifier_implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    if not decision["input_valid"]:
        raise ValueError(f"{mode['mode']}: adapter produced invalid classifier input")
    fixture_disposition = _FIXTURE_DISPOSITION_BY_CLASS[
        decision["permitted_claim_class"]
    ]
    original_disposition = audits[7]["status"]
    if fixture_disposition != original_disposition:
        raise ValueError(
            f"{mode['mode']}: classifier-derived fixture disposition "
            f"{fixture_disposition!r} differs from frozen Level-8 {original_disposition!r}"
        )
    return {
        "mode": mode["mode"],
        "gate_vector": [states[gate] for gate in protocol.gate_order],
        "frozen_level_8_disposition": original_disposition,
        "derived_fixture_disposition": fixture_disposition,
        "fixture_disposition_mapping": (
            "event_aligned=admit; seed_matched_bounded=downgrade; every weaker "
            "generic class=suppress under the frozen fixture-specific rules"
        ),
        "admission_decision": decision,
    }


def build_report(protocol: AdmissionProtocol | None = None) -> dict[str, Any]:
    protocol = protocol or AdmissionProtocol.load()
    source = synthetic.build_report()
    failures = synthetic.validate_report(source)
    if failures:
        raise ValueError("invalid frozen synthetic report: " + "; ".join(failures))
    decisions = [_decision_for_mode(mode, protocol) for mode in source["modes"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "adapter_id": ADAPTER_ID,
        "protocol_bundle_sha256": protocol.bundle_sha256,
        "formalization_status": protocol.rules["formalization_provenance"]["status"],
        "frozen_fixture_authority": (
            "The frozen synthetic Level-8 disposition remains authoritative; "
            "the adapter does not retroactively replace fixture-specific suppression."
        ),
        "modes": decisions,
    }


def rendered_outputs(protocol: AdmissionProtocol | None = None) -> dict[str, str]:
    primary = {"synthetic_admission_decisions.json": _render_json(build_report(protocol))}
    manifest = "".join(
        f"{hashlib.sha256(content.encode('utf-8')).hexdigest()}  {name}\n"
        for name, content in sorted(primary.items())
    )
    return {**primary, "MANIFEST.sha256": manifest}


def write_outputs(output_dir: Path, protocol: AdmissionProtocol | None = None) -> None:
    if output_dir.is_symlink():
        raise ValueError(f"output directory must not be a symlink: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    expected = rendered_outputs(protocol)
    extras = {path.name for path in output_dir.iterdir()} - set(expected)
    if extras:
        raise ValueError(f"refusing to retain unexpected admission artifacts: {sorted(extras)}")
    for name, content in expected.items():
        path = output_dir / name
        if path.is_symlink():
            raise ValueError(f"refusing to overwrite symlink: {path}")
        path.write_bytes(content.encode("utf-8"))


def verify_outputs(
    output_dir: Path, protocol: AdmissionProtocol | None = None
) -> list[str]:
    expected = rendered_outputs(protocol)
    if output_dir.is_symlink():
        return [f"output directory is a symlink: {output_dir}"]
    if not output_dir.exists() or not output_dir.is_dir():
        return [f"missing {name}" for name in sorted(expected)]
    actual = {path.name for path in output_dir.iterdir()}
    failures = [
        f"unexpected entry: {name}" for name in sorted(actual - set(expected))
    ]
    for name, content in expected.items():
        path = output_dir / name
        if path.is_symlink():
            failures.append(f"symlink not allowed: {name}")
        elif not path.is_file():
            failures.append(f"missing {name}")
        elif path.read_bytes() != content.encode("utf-8"):
            failures.append(f"content mismatch: {name}")
    return failures
