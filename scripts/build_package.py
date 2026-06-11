"""Build a deterministic Anki add-on archive."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

FIXED_TIMESTAMP = (2026, 1, 1, 0, 0, 0)
SOURCE_DIRECTORY = Path("src") / "anki_lookup"


def _load_version(source_directory: Path) -> str:
    manifest = json.loads((source_directory / "manifest.json").read_text(encoding="utf-8"))
    version = manifest.get("human_version")
    if not isinstance(version, str) or not version:
        raise ValueError("manifest.json must define a non-empty human_version")
    return version


def _package_files(source_directory: Path) -> list[Path]:
    return sorted(
        path
        for path in source_directory.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )


def build_package(root: Path, output_path: Path | None = None) -> Path:
    """Build and return the deterministic archive path."""

    source_directory = root / SOURCE_DIRECTORY
    if not source_directory.is_dir():
        raise FileNotFoundError(f"Add-on source directory not found: {source_directory}")

    version = _load_version(source_directory)
    destination = output_path or root / "artifacts" / f"anki-lookup-{version}.ankiaddon"
    destination.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in _package_files(source_directory):
            relative_path = path.relative_to(source_directory).as_posix()
            info = ZipInfo(relative_path, date_time=FIXED_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)

    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    archive_path = build_package(arguments.root.resolve(), arguments.output)
    print(archive_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
