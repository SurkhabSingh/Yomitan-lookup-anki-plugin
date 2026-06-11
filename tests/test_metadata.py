import json
import unittest
from pathlib import Path

from anki_lookup.metadata import ADDON_NAME, PACKAGE_NAME, VERSION


class MetadataTests(unittest.TestCase):
    def test_manifest_matches_python_metadata(self) -> None:
        manifest_path = Path(__file__).parents[1] / "src" / "anki_lookup" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["name"], ADDON_NAME)
        self.assertEqual(manifest["package"], PACKAGE_NAME)
        self.assertEqual(manifest["human_version"], VERSION)

    def test_version_is_semantic(self) -> None:
        parts = VERSION.split(".")

        self.assertEqual(len(parts), 3)
        self.assertTrue(all(part.isdigit() for part in parts))

    def test_project_version_matches_runtime_metadata(self) -> None:
        project_path = Path(__file__).parents[1] / "pyproject.toml"
        project_text = project_path.read_text(encoding="utf-8")

        self.assertIn(f'version = "{VERSION}"', project_text)


if __name__ == "__main__":
    unittest.main()
