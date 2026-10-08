"""Tests that variant v24 loads, and that its prompt asks for a walkthrough whose stops name a diagram box and for nothing
chunked. Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import compare  # noqa: E402
from config import variant_file  # noqa: E402
from run import build_prompts  # noqa: E402

V24 = Path(__file__).resolve().parent.parent / "variants" / "diagram_walkthrough_v24.toml"


class VariantV24(unittest.TestCase):
    def setUp(self) -> None:
        self.v24 = tomllib.loads(V24.read_text())
        self.text = self.v24["extra_instructions"] + self.v24["schema_additions"] + self.v24["example_additions"]

    def test_it_is_found_by_name(self) -> None:
        self.assertEqual(variant_file("diagram_walkthrough_v24"), V24)

    def test_it_has_no_render_table(self) -> None:
        self.assertNotIn("render", self.v24)

    def test_the_prompt_asks_for_stops_that_name_a_box_and_for_node_files(self) -> None:
        self.assertIn("walkthrough", self.v24["schema_additions"])
        self.assertIn("node_files", self.v24["schema_additions"])
        self.assertIn("- node: |", self.v24["example_additions"])
        self.assertIn("node (str", self.v24["schema_additions"])

    def test_the_prompt_asks_for_nothing_chunked(self) -> None:
        for word in ("chunk", "checks", ":::save", "levels", "review:"):
            self.assertNotIn(word, self.text.lower())

    def test_the_prompt_no_longer_asks_for_the_per_file_summaries(self) -> None:
        pr = {"title": "T", "body": "", "headRefName": "b", "commits": [{"messageHeadline": "c"}], "files": [{"path": "a.py"}]}
        system, _ = build_prompts(self.v24, pr, "diff", False)
        self.assertNotIn("pr_files", system)
        self.assertIn("walkthrough: List[dict]", system)
        self.assertIn("changes_diagram", system)

    def test_the_comparison_labels_it(self) -> None:
        self.assertEqual(compare.VARIANT_LABELS["diagram_walkthrough_v24"], "24: diagram and walkthrough")


if __name__ == "__main__":
    unittest.main()
