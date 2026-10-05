"""Tests that variant v17 parses and differs from v16 only in its start-line rule. Run with
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


class VariantV17(unittest.TestCase):
    def setUp(self) -> None:
        self.v16 = load("one_path_risk_chunked_v16")
        self.v17 = load("one_path_risk_chunked_v17")

    def test_it_keeps_every_v16_setting_except_the_description_and_the_start_rule(self) -> None:
        for key in ("context", "extra_instructions", "example_additions", "context_options", "render"):
            self.assertEqual(self.v17[key], self.v16[key], key)
        self.assertNotEqual(self.v17["schema_additions"], self.v16["schema_additions"])

    def test_the_schema_differs_only_inside_the_start_object(self) -> None:
        before = self.v16["schema_additions"]
        after = self.v17["schema_additions"]
        head = "start (object"
        self.assertEqual(before[:before.index(head)], after[:after.index(head)])
        tail = "Every changed file appears in exactly one chunk"
        self.assertEqual(before[before.index(tail):], after[after.index(tail):])

    def test_the_start_rule_asks_for_where_the_step_begins_and_drops_the_risk_wording(self) -> None:
        start = self.v17["schema_additions"]
        start = start[start.index("start (object"):start.index("Every changed file appears")]
        self.assertIn("where this step of the flow begins", start)
        self.assertIn("the endpoint, handler or method that the previous step calls into", start)
        self.assertIn("A method signature or a route declaration is often right", start)
        self.assertIn("copied verbatim from the diff", start)
        self.assertIn("appears once in that file's diff", start)
        self.assertIn("choose the nearest distinctive one", start)
        self.assertIn("at most 15 words", start)
        self.assertIn("what this line sets up for the rest of the chunk", start)
        for gone in ("risk is decided", "unless that is the risk", "should check"):
            self.assertNotIn(gone, start)

    def test_it_renders_like_v16(self) -> None:
        self.assertEqual(self.v17["render"]["chunk_order"], "flow")
        self.assertTrue(self.v17["render"]["contract_block"])
        self.assertTrue(self.v17["render"]["start_line"])

    def test_the_comparison_page_labels_it(self) -> None:
        self.assertIn("one_path_risk_chunked_v17", compare.VARIANT_LABELS)


if __name__ == "__main__":
    unittest.main()
