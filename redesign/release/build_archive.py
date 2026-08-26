"""Create a deterministic local archive and companion digest."""

from __future__ import annotations

import gzip
import hashlib
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST = ROOT.parent / "dist"
ARCHIVE = DIST / "claim-specific-validation-release-0.1.0-rc1.tar.gz"
SUMS = DIST / "SHA256SUMS"


def add_stable(tar: tarfile.TarFile, path: Path) -> None:
    relative = path.relative_to(ROOT)
    info = tar.gettarinfo(str(path), arcname=(Path("release") / relative).as_posix())
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = 0
    with path.open("rb") as stream:
        tar.addfile(info, stream)


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> None:
    if not (ROOT / "MANIFEST.sha256").exists():
        raise SystemExit("run build_manifest.py before build_archive.py")
    DIST.mkdir(parents=True, exist_ok=True)
    paths = sorted(path for path in ROOT.rglob("*") if path.is_file())
    with ARCHIVE.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as tar:
                for path in paths:
                    add_stable(tar, path)
    digest = sha256(ARCHIVE)
    SUMS.write_text(f"{digest}  {ARCHIVE.name}\n")
    print(f"wrote {ARCHIVE} ({digest})")


if __name__ == "__main__":
    main()
