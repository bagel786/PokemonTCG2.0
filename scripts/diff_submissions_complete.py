#!/usr/bin/env python3
"""Comprehensive diff and audit between the user-attached 5k submission, historical 960+ overnight submission, and recent submissions."""

import difflib
import hashlib
import json
import tarfile
import tempfile
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def extract_archive_info(archive_path: Path):
    info = {"path": str(archive_path), "size": archive_path.stat().st_size, "files": {}, "text_files": {}}
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            if member.isfile():
                data = tar.extractfile(member).read()
                h = hashlib.sha256(data).hexdigest()
                info["files"][member.name] = {"size": len(data), "sha256": h}
                if member.name.endswith((".py", ".csv", ".json", ".txt", ".md")):
                    try:
                        info["text_files"][member.name] = data.decode("utf-8")
                    except Exception:
                        pass
    return info


def compare_npz(archive1: Path, archive2: Path):
    with tarfile.open(archive1, "r:gz") as tar1, tarfile.open(archive2, "r:gz") as tar2:
        if "policy_weights.npz" not in tar1.getnames() or "policy_weights.npz" not in tar2.getnames():
            return "policy_weights.npz missing in one archive"
        with tempfile.NamedTemporaryFile(suffix=".npz") as f1, tempfile.NamedTemporaryFile(suffix=".npz") as f2:
            f1.write(tar1.extractfile("policy_weights.npz").read()); f1.flush()
            f2.write(tar2.extractfile("policy_weights.npz").read()); f2.flush()
            npz1 = np.load(f1.name)
            npz2 = np.load(f2.name)
            
            keys1 = set(npz1.files)
            keys2 = set(npz2.files)
            if keys1 != keys2:
                return f"Keys mismatch: {keys1 ^ keys2}"
            
            diffs = []
            for k in keys1:
                arr1 = npz1[k]
                arr2 = npz2[k]
                if arr1.shape != arr2.shape:
                    diffs.append(f"Key {k} shape mismatch: {arr1.shape} vs {arr2.shape}")
                elif not np.array_equal(arr1, arr2):
                    max_diff = np.max(np.abs(arr1 - arr2))
                    diffs.append(f"Key {k} values mismatch (max diff: {max_diff})")
            if not diffs:
                return "IDENTICAL (all weights match exactly)"
            return "\n".join(diffs)


def main():
    archives = {
        "User-Attached (Root)": ROOT / "grimmsnarl_5k_reference.tar.gz",
        "Historical Overnight (960-1035 Elo)": ROOT / "artifacts" / "grimmsnarl-ppo-5k-overnight.tar.gz",
        "Recent 5k Proper (55189658)": ROOT / "artifacts" / "grimmsnarl_5k_reference_proper.tar.gz",
        "Recent Gen-5 Challenger (55189662)": ROOT / "artifacts" / "grimmsnarl_gen5_challenger.tar.gz",
    }

    print("=" * 80)
    print("SUBMISSION PACKAGES OVERVIEW")
    print("=" * 80)
    infos = {}
    for name, p in archives.items():
        if not p.exists():
            print(f"[-] {name}: File not found at {p}")
            continue
        info = extract_archive_info(p)
        infos[name] = info
        print(f"\n[+] {name} ({p.name})")
        print(f"    Size: {info['size']} bytes")
        print(f"    Archive SHA256: {hashlib.sha256(p.read_bytes()).hexdigest()}")
        print(f"    Members ({len(info['files'])} files):")
        for fname, finfo in sorted(info["files"].items()):
            print(f"      - {fname:<30} {finfo['size']:>10} bytes  sha256:{finfo['sha256'][:12]}")

    print("\n" + "=" * 80)
    print("DETAILED PAIRWISE COMPARISONS")
    print("=" * 80)

    # 1. Compare User-Attached vs Historical Overnight
    target_a = "User-Attached (Root)"
    target_b = "Historical Overnight (960-1035 Elo)"
    target_c = "Recent 5k Proper (55189658)"

    pairs = [
        (target_a, target_b),
        (target_a, target_c),
        (target_b, target_c),
    ]

    for name1, name2 in pairs:
        if name1 not in infos or name2 not in infos:
            continue
        print(f"\n--- DIFF: [{name1}] vs [{name2}] ---")
        info1 = infos[name1]
        info2 = infos[name2]

        files1 = set(info1["files"].keys())
        files2 = set(info2["files"].keys())

        if files1 != files2:
            print(f"  Only in {name1}: {files1 - files2}")
            print(f"  Only in {name2}: {files2 - files1}")

        common_files = files1 & files2
        for f in sorted(common_files):
            h1 = info1["files"][f]["sha256"]
            h2 = info2["files"][f]["sha256"]
            if h1 != h2:
                print(f"  * File changed: {f}")
                if f in info1["text_files"] and f in info2["text_files"]:
                    lines1 = info1["text_files"][f].splitlines(keepends=True)
                    lines2 = info2["text_files"][f].splitlines(keepends=True)
                    diff = list(difflib.unified_diff(lines1, lines2, fromfile=f"{name1}:{f}", tofile=f"{name2}:{f}"))
                    print("".join(diff[:30]))
                elif f == "policy_weights.npz":
                    p1 = Path(info1["path"])
                    p2 = Path(info2["path"])
                    print("    Weights diff:", compare_npz(p1, p2))
            else:
                print(f"  [✓] {f:<30} IDENTICAL")


if __name__ == "__main__":
    main()
