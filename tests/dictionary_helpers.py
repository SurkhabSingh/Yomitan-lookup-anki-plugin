from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def write_dictionary(
    path: Path,
    *,
    title: str = "Synthetic Dictionary",
    revision: str = "1",
    terms: list[list[object]] | None = None,
    index_extra: dict[str, object] | None = None,
    extra_files: dict[str, object] | None = None,
) -> None:
    rows = (
        [
            [
                "Example",
                "example",
                "common",
                "",
                10,
                ["A representative sample."],
                1,
                "noun",
            ]
        ]
        if terms is None
        else terms
    )
    index: dict[str, object] = {"title": title, "revision": revision, "format": 3}
    if index_extra:
        index.update(index_extra)
    files: dict[str, object] = {
        "index.json": index,
        "term_bank_1.json": rows,
        "tag_bank_1.json": [["common", "frequency", 0, "Common term", 1]],
    }
    if extra_files:
        files.update(extra_files)

    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, json.dumps(value, ensure_ascii=False))


def artifact_path(name: str) -> Path:
    root = Path(__file__).parents[1] / "artifacts" / "tests"
    root.mkdir(parents=True, exist_ok=True)
    return root / name
