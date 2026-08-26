"""Create a stable SHA-256 manifest for the public release tree."""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "MANIFEST.sha256"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> None:
    paths = sorted(
        path for path in ROOT.rglob("*")
        if path.is_file() and path != OUT
    )
    lines = [f"{digest(path)}  {path.relative_to(ROOT).as_posix()}" for path in paths]
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT} with {len(lines)} entries")


if __name__ == "__main__":
    main()
