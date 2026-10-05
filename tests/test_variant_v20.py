"""Tests that variant v20 parses and differs from v19 only in its start rule (a line when one clearly anchors the chunk,
else a file) and the render option that keeps a file-only start. Run with `python3 -m unittest discover -s tests` from
the tool's folder."""
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import compare  # noqa: E402

VARIANTS = Path(__file__).resolve().parent.parent / "variants"


def load(name: str) -> dict:
    return tomllib.loads((VARIANTS / f"{name}.toml").read_text())


def start_text(variant: dict) -> str:
    text: str = variant["schema_additions"]
    return text[text.index("start (object"):text.index(" Every changed file appears in exactly one chunk")]


class VariantV20(unittest.TestCase):
    def setUp(self) -> None:
        self.v19 = load("one_path_risk_chunked_v19")
        self.v20 = load("one_path_risk_chunked_v20")

    def test_it_keeps_every_v19_setting_except_the_description_the_start_text_and_one_render_option(self) -> None:
        for key in ("context", "extra_instructions", "context_options"):
            self.assertEqual(self.v20[key], self.v19[key], key)
        self.assertEqual({**self.v20["render"], "file_start": None}, {**self.v19["render"], "file_start": None})
        self.assertTrue(self.v20["render"]["file_start"])
        self.assertNotIn("file_start", self.v19["render"])
        self.assertEqual(self.v20["description"], "v19 with a start that is a line when one clearly anchors the chunk, else a file")

    def test_the_schema_differs_from_v19_only_in_the_start_description(self) -> None:
        before = self.v19["schema_additions"]
        after = self.v20["schema_additions"]
        cut = before.index("start (object")
        self.assertEqual(after[:cut], before[:cut])
        self.assertEqual(after[after.index(" Every changed file appears in exactly one chunk"):],
                         before[before.index(" Every changed file appears in exactly one chunk"):])
        self.assertNotEqual(start_text(self.v20), start_text(self.v19))

    def test_the_start_is_a_line_only_when_one_clearly_anchors_the_chunk_else_a_file(self) -> None:
        text = start_text(self.v20)
        self.assertIn("the keys file, why and, optionally, line_text", text)
        self.assertIn("the full path of one of the chunk's files, the one to open first", text)
        self.assertIn("include it ONLY when a single line clearly anchors the chunk", text)
        self.assertIn("the query, or the declaration the rest of the chunk builds on", text)
        self.assertIn("without its leading '+', '-' or space", text)
        self.assertIn("appears once in that file's diff", text)
        self.assertIn("omit line_text and the reviewer is pointed at the file", text)
        self.assertIn("one sentence, at most 15 words, saying what that line or file sets up", text)

    def test_the_example_lists_the_start_keys(self) -> None:
        example = self.v20["example_additions"]
        start = example[example.index("  start:"):example.index("node_files:")]
        for key in ("file:", "why:", "line_text:"):
            self.assertIn(key, start)

    def test_the_comparison_page_labels_it(self) -> None:
        self.assertEqual(compare.VARIANT_LABELS["one_path_risk_chunked_v20"], "20: file or line start")


if __name__ == "__main__":
    unittest.main()
