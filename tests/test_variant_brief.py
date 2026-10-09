"""Tests that variant `brief` loads, and that its prompt asks for a walkthrough whose stops name a diagram box and for nothing
chunked. Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import variant_file  # noqa: E402
from run import build_prompts  # noqa: E402

BRIEF = Path(__file__).resolve().parent.parent / "variants" / "brief.toml"


class VariantBRIEF(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = tomllib.loads(BRIEF.read_text())
        self.text = self.brief["extra_instructions"] + self.brief["schema_additions"] + self.brief["example_additions"]

    def test_it_is_found_by_name(self) -> None:
        self.assertEqual(variant_file("brief"), BRIEF)

    def test_it_has_no_render_table(self) -> None:
        self.assertNotIn("render", self.brief)

    def test_the_prompt_asks_for_stops_that_name_a_box_and_for_node_files(self) -> None:
        self.assertIn("walkthrough", self.brief["schema_additions"])
        self.assertIn("node_files", self.brief["schema_additions"])
        self.assertIn("- node: |", self.brief["example_additions"])
        self.assertIn("node (str", self.brief["schema_additions"])

    def test_the_prompt_asks_for_nothing_chunked(self) -> None:
        for word in ("chunk", "checks", ":::save", "levels", "review:"):
            self.assertNotIn(word, self.text.lower())

    def test_the_prompt_no_longer_asks_for_the_per_file_summaries(self) -> None:
        pr = {"title": "T", "body": "", "headRefName": "b", "commits": [{"messageHeadline": "c"}], "files": [{"path": "a.py"}]}
        system, _ = build_prompts(self.brief, pr, "diff", False)
        self.assertNotIn("pr_files", system)
        self.assertIn("walkthrough: List[dict]", system)
        self.assertIn("changes_diagram", system)

    def test_it_asks_for_no_wiki_context(self) -> None:
        self.assertEqual(self.brief["context"], ["callers", "reach", "contract", "migrations"])
        self.assertNotIn("wiki_match", self.brief["context_options"])
        self.assertNotIn("wiki", (self.text + self.brief["extra_instructions"]).lower())


if __name__ == "__main__":
    unittest.main()
