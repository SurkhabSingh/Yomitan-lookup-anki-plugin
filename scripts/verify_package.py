"""Validate an Anki add-on archive before distribution."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

REQUIRED_FILES = {"__init__.py", "config.json", "manifest.json"}
FORBIDDEN_PARTS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


@dataclass(frozen=True)
class PackageReport:
    package_name: str
    version: str
    file_count: int


def verify_package(archive_path: Path) -> PackageReport:
    """Validate package structure and return its metadata."""

    try:
        with ZipFile(archive_path) as archive:
            names = archive.namelist()
            name_set = set(names)

            missing = REQUIRED_FILES - name_set
            if missing:
                raise ValueError(f"Archive is missing required files: {sorted(missing)}")

            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError(f"Archive contains an unsafe path: {name}")
                if FORBIDDEN_PARTS.intersection(path.parts) or path.suffix in {".pyc", ".pyo"}:
                    raise ValueError(f"Archive contains a forbidden file: {name}")

            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            config = json.loads(archive.read("config.json").decode("utf-8"))
    except BadZipFile as error:
        raise ValueError(f"Invalid add-on archive: {archive_path}") from error

    package_name = manifest.get("package")
    version = manifest.get("human_version")
    if not isinstance(package_name, str) or not package_name:
        raise ValueError("Manifest package must be a non-empty string")
    if not isinstance(version, str) or not version:
        raise ValueError("Manifest human_version must be a non-empty string")
    if not isinstance(config.get("config_version"), int):
        raise ValueError("Config must contain an integer config_version")

    return PackageReport(package_name, version, len(names))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    arguments = parser.parse_args()

    report = verify_package(arguments.archive.resolve())
    print(f"Verified {report.package_name} {report.version}: {report.file_count} packaged files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
