"""Deterministic publication plots from frozen analysis summaries only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .analysis import verify_frozen_analysis_summary
from .canonical import (
    canonical_json_bytes,
    hash_file,
    hash_json,
    write_canonical_json,
)


PLOT_VERSION = "resource-envelope-publication-plots-1.0.0"


def _read_canonical_json_object(path: str | Path, *, role: str) -> dict[str, Any]:
    artifact_path = Path(path)
    if artifact_path.suffix.lower() in {".jsonl", ".csv", ".tsv"}:
        raise ValueError(f"plotting refuses raw {role} input: {artifact_path.name}")
    try:
        raw = artifact_path.read_bytes()
        value = json.loads(raw.decode("ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {role} JSON artifact") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{role} artifact must be a JSON object")
    if canonical_json_bytes(value) != raw:
        raise ValueError(f"{role} artifact is not canonical JSON bytes")
    return value


def build_plot_source_inventory(
    summary_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Bind the one frozen summary artifact that plotting may consume."""

    summary_file = Path(summary_path)
    summary = _read_canonical_json_object(summary_file, role="analysis summary")
    verify_frozen_analysis_summary(summary)
    payload: dict[str, Any] = {
        "schema_version": "plot-source-inventory-1.0.0",
        "freeze_status": "FROZEN_PLOT_INPUT",
        "plot_version": PLOT_VERSION,
        "summary_filename": summary_file.name,
        "summary_schema_version": summary["schema_version"],
        "summary_file_sha256": hash_file(summary_file),
        "summary_content_hash": summary["content_hash"],
        "analysis_lock_hash": summary["analysis_lock_hash"],
        "protocol_freeze_hash": summary["protocol_freeze_hash"],
    }
    payload["content_hash"] = hash_json(payload)
    write_canonical_json(output_path, payload)
    return payload


def _verify_plot_source_inventory(
    inventory: Mapping[str, Any],
    summary: Mapping[str, Any],
    summary_path: Path,
) -> None:
    required = {
        "schema_version",
        "freeze_status",
        "plot_version",
        "summary_filename",
        "summary_schema_version",
        "summary_file_sha256",
        "summary_content_hash",
        "analysis_lock_hash",
        "protocol_freeze_hash",
        "content_hash",
    }
    if set(inventory) != required:
        raise ValueError("plot source inventory schema drift")
    if inventory.get("schema_version") != "plot-source-inventory-1.0.0":
        raise ValueError("unsupported plot source inventory schema")
    if inventory.get("freeze_status") != "FROZEN_PLOT_INPUT":
        raise ValueError("plot source inventory is not frozen")
    if inventory.get("plot_version") != PLOT_VERSION:
        raise ValueError("plot source inventory targets different plotting code")
    payload = dict(inventory)
    supplied = payload.pop("content_hash", None)
    if supplied != hash_json(payload):
        raise ValueError("plot source inventory content hash mismatch")
    expected = {
        "summary_filename": summary_path.name,
        "summary_schema_version": summary["schema_version"],
        "summary_file_sha256": hash_file(summary_path),
        "summary_content_hash": summary["content_hash"],
        "analysis_lock_hash": summary["analysis_lock_hash"],
        "protocol_freeze_hash": summary["protocol_freeze_hash"],
    }
    mismatched = [key for key, value in expected.items() if inventory.get(key) != value]
    if mismatched:
        raise ValueError(f"plot summary differs from frozen source inventory: {mismatched}")


def render_publication_plots(
    summary_path: str | Path,
    inventory_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Render deterministic SVG interval plots without opening raw outcomes."""

    summary_file = Path(summary_path)
    inventory_file = Path(inventory_path)
    summary = _read_canonical_json_object(summary_file, role="analysis summary")
    verify_frozen_analysis_summary(summary)
    inventory = _read_canonical_json_object(inventory_file, role="plot source inventory")
    _verify_plot_source_inventory(inventory, summary, summary_file)

    import matplotlib

    matplotlib.use("Agg", force=True)
    matplotlib.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.unicode_minus": False,
            "svg.hashsalt": "resource-envelope-publication-plots-1.0.0",
        }
    )
    import matplotlib.pyplot as plt

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    plot_records: list[dict[str, str]] = []
    for plot_group, filename, xlabel in (
        ("work_relative", "confirmatory_work_ratios.svg", "Loaded / idle mean work - 1"),
        (
            "probability_difference",
            "confirmatory_probability_effects.svg",
            "Probability / score difference",
        ),
    ):
        records = [
            record for record in summary["estimands"] if record["plot_group"] == plot_group
        ]
        if not records:
            raise ValueError(f"frozen summary lacks plot group {plot_group}")
        labels = [str(record["display_label"]) for record in records]
        estimates = [float(record["estimate"]) for record in records]
        lower = [
            estimate - float(record["interval"][0])
            for estimate, record in zip(estimates, records)
        ]
        upper = [
            float(record["interval"][1]) - estimate
            for estimate, record in zip(estimates, records)
        ]
        figure, axis = plt.subplots(figsize=(7.2, 0.55 * len(records) + 1.5))
        positions = list(range(len(records)))
        axis.errorbar(
            estimates,
            positions,
            xerr=[lower, upper],
            fmt="o",
            color="#24415a",
            ecolor="#4f7896",
            elinewidth=1.4,
            capsize=3,
            markersize=4.5,
        )
        axis.axvline(0.0, color="#777777", linewidth=0.9, linestyle="--")
        axis.set_yticks(positions, labels)
        axis.set_xlabel(xlabel)
        axis.set_title(
            f"Confirmatory effects ({summary['familywise_confidence_level']:.0%} familywise coverage)"
        )
        axis.invert_yaxis()
        axis.grid(axis="x", color="#dddddd", linewidth=0.6)
        figure.tight_layout()
        output_path = destination / filename
        figure.savefig(
            output_path,
            format="svg",
            metadata={"Date": None, "Creator": PLOT_VERSION},
        )
        plt.close(figure)
        plot_records.append(
            {
                "filename": filename,
                "plot_group": plot_group,
                "sha256": hash_file(output_path),
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": "publication-plot-manifest-1.0.0",
        "plot_version": PLOT_VERSION,
        "input_kind": "frozen_analysis_summary_only",
        "summary_file_sha256": inventory["summary_file_sha256"],
        "summary_content_hash": summary["content_hash"],
        "analysis_lock_hash": summary["analysis_lock_hash"],
        "source_inventory_file_sha256": hash_file(inventory_file),
        "source_inventory_content_hash": inventory["content_hash"],
        "plots": sorted(plot_records, key=lambda record: record["filename"]),
    }
    manifest["content_hash"] = hash_json(manifest)
    write_canonical_json(destination / "plot-manifest.json", manifest)
    return manifest
