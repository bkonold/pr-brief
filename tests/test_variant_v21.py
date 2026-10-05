"""Tests that variant v21 parses and differs from v20 in its effort levels, its checks and the render option that turns
the labels on. Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import compare  # noqa: E402

VARIANTS = Path(__file__).resolve().parent.parent / "variants"


def load(name: str) -> dict:
    return tomllib.loads((VARIANTS / f"{name}.toml").read_text())


class VariantV21(unittest.TestCase):
    def setUp(self) -> None:
        self.v20 = load("one_path_risk_chunked_v20")
        self.v21 = load("one_path_risk_chunked_v21")

    def test_it_keeps_v20s_context_and_render_settings_and_turns_the_labels_on(self) -> None:
        for key in ("context", "context_options"):
            self.assertEqual(self.v21[key], self.v20[key], key)
        self.assertEqual({**self.v21["render"], "review_labels": None}, {**self.v20["render"], "review_labels": None})
        self.assertTrue(self.v21["render"]["review_labels"])
        self.assertNotIn("review_labels", self.v20["render"])

    def test_the_levels_are_verify_read_and_skim(self) -> None:
        schema = self.v21["schema_additions"]
        self.assertIn("exactly one of 'verify', 'read', 'skim'", schema)
        self.assertNotIn("read carefully", schema + self.v21["extra_instructions"] + self.v21["example_additions"])
        self.assertIn("Nothing is skipped", self.v21["extra_instructions"])

    def test_the_model_emits_checks_drawn_from_four_labels(self) -> None:
        self.assertIn("checks (List[str]: zero to three of 'logic', 'contract', 'data', 'access'", self.v21["schema_additions"])
        self.assertIn("  checks:\n", self.v21["example_additions"])

    def test_a_chunk_shares_one_level_and_generated_files_stand_alone(self) -> None:
        text = self.v21["extra_instructions"]
        self.assertIn("split the chunk", text)
        self.assertIn("never choose one as a chunk's start", text)

    def test_it_keeps_the_file_or_line_start_and_one_box_per_chunk(self) -> None:
        self.assertIn("the keys file, why and, optionally, line_text", self.v21["schema_additions"])
        self.assertTrue(self.v21["render"]["one_box_per_chunk"])
        self.assertTrue(self.v21["render"]["file_start"])

    def test_the_comparison_page_labels_it(self) -> None:
        self.assertEqual(compare.VARIANT_LABELS["one_path_risk_chunked_v21"], "21: effort levels + check labels")


if __name__ == "__main__":
    unittest.main()
