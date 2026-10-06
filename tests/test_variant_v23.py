"""Tests that variant v23 is v22 with a walkthrough of stops in place of the chunk start, and that no older variant has
one. Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import compare  # noqa: E402

VARIANTS = Path(__file__).resolve().parent.parent / "variants"


def load(name: str) -> dict:
    return tomllib.loads((VARIANTS / f"{name}.toml").read_text())


class VariantV23(unittest.TestCase):
    def setUp(self) -> None:
        self.v22 = load("one_path_risk_chunked_v22")
        self.v23 = load("one_path_risk_chunked_v23")

    def test_the_render_settings_are_v22s_with_the_walkthrough_and_without_the_start_flags(self) -> None:
        expected = {key: value for key, value in self.v22["render"].items() if key not in ("start_line", "file_start")}
        self.assertEqual(self.v23["render"], {**expected, "walkthrough": True})

    def test_no_older_variant_sets_the_flag(self) -> None:
        for number in range(10, 23):
            for path in VARIANTS.glob(f"one_path_risk_chunked_v{number}*.toml"):
                self.assertNotIn("walkthrough", tomllib.loads(path.read_text()).get("render", {}), path.name)

    def test_the_prompt_asks_for_stops_and_no_chunk_start(self) -> None:
        text = self.v23["extra_instructions"] + self.v23["schema_additions"] + self.v23["example_additions"]
        self.assertIn("walkthrough", self.v23["schema_additions"])
        self.assertIn("walkthrough:", self.v23["example_additions"])
        self.assertNotIn("start:", self.v23["example_additions"])
        self.assertNotIn("start (object", self.v23["schema_additions"])
        self.assertNotIn("chunk's start", text)

    def test_the_comparison_labels_it(self) -> None:
        self.assertEqual(compare.VARIANT_LABELS["one_path_risk_chunked_v23"], "23: walkthrough stops")


if __name__ == "__main__":
    unittest.main()
