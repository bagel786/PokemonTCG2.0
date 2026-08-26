"""Canonical serialization, hashing, and independently keyed seed derivation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, MutableSequence, TypeVar

T = TypeVar("T")


def canonical_json_bytes(value: Any) -> bytes:
    """Return the study's only canonical JSON representation."""

    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def hash_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def derive_u64(master_seed: int, stream: str, *labels: object) -> int:
    """Derive a stable 64-bit seed without Python's randomized ``hash``."""

    payload = {
        "master_seed": int(master_seed),
        "stream": str(stream),
        "labels": [str(label) for label in labels],
    }
    return int.from_bytes(hashlib.sha256(canonical_json_bytes(payload)).digest()[:8], "big")


def derive_u32(master_seed: int, stream: str, *labels: object) -> int:
    return derive_u64(master_seed, stream, *labels) & 0xFFFF_FFFF


def deterministic_shuffle(values: Iterable[T], seed: int, label: str) -> list[T]:
    """Fisher-Yates using rejection-sampled SHA-256 words.

    This avoids depending on the implementation details of ``random.shuffle``
    or NumPy and is used only while constructing manifests, never in timed code.
    """

    result: MutableSequence[T] = list(values)
    counter = 0
    for upper in range(len(result) - 1, 0, -1):
        modulus = upper + 1
        limit = (1 << 64) - ((1 << 64) % modulus)
        while True:
            word = derive_u64(seed, "schedule_shuffle", label, counter)
            counter += 1
            if word < limit:
                index = word % modulus
                break
        result[upper], result[index] = result[index], result[upper]
    return list(result)


def write_canonical_json(path: str | Path, value: Any) -> str:
    """Write canonical JSON and return its SHA-256.

    Callers use this only for generated study artifacts.  Scientific source
    files themselves are edited through the repository patch workflow.
    """

    payload = canonical_json_bytes(value)
    Path(path).write_bytes(payload)
    return sha256_bytes(payload)
