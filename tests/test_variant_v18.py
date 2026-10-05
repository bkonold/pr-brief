"""Tests that variant v18 parses and differs from v17 only in the diagram's main-path cap. Run with
`python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import compare  # noqa: E402

VARIANTS = Path(__file__).resolve().parent.parent / "variants"


def load(name: str) -> dict:
    return tomllib.loads((VARIANTS / f"{name}.toml").read_text())


class VariantV18(unittest.TestCase):
    def setUp(self) -> None:
        self.v17 = load("one_path_risk_chunked_v17")
        self.v18 = load("one_path_risk_chunked_v18")

    def test_it_keeps_every_v17_setting_except_the_description_and_the_instructions(self) -> None:
        for key in ("context", "schema_additions", "example_additions", "context_options", "render"):
            self.assertEqual(self.v18[key], self.v17[key], key)

    def test_the_instructions_differ_only_in_the_cap(self) -> None:
        self.assertEqual(self.v18["extra_instructions"],
                         self.v17["extra_instructions"].replace("at most 7 nodes", "at most 10 nodes")
                         .replace("The 7-box cap", "The 10-box cap"))
        self.assertNotEqual(self.v18["extra_instructions"], self.v17["extra_instructions"])

    def test_the_comparison_page_labels_it(self) -> None:
        self.assertIn("one_path_risk_chunked_v18", compare.VARIANT_LABELS)


if __name__ == "__main__":
    unittest.main()
