import unittest
from pathlib import Path

from scripts.build_package import build_package
from scripts.verify_package import verify_package


class PackageTests(unittest.TestCase):
    def test_package_builds_and_verifies(self) -> None:
        root = Path(__file__).parents[1]
        output_path = root / "artifacts" / "test-anki-lookup.ankiaddon"

        build_package(root, output_path)
        report = verify_package(output_path)

        self.assertEqual(report.package_name, "anki_lookup")
        self.assertGreater(report.file_count, 0)


if __name__ == "__main__":
    unittest.main()
