"""Tests that variant v22 is v21 with the Contract and Data sections grouped by chunk, and that older variants render
the single block as before. Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import compare  # noqa: E402

VARIANTS = Path(__file__).resolve().parent.parent / "variants"
NAMES = [f"one_path_risk_chunked_v{n}" for n in range(17, 23)]


def load(name: str) -> dict:
    return tomllib.loads((VARIANTS / f"{name}.toml").read_text())


class VariantV22(unittest.TestCase):
    def setUp(self) -> None:
        self.v21 = load("one_path_risk_chunked_v21")
        self.v22 = load("one_path_risk_chunked_v22")

    def test_the_prompt_is_v21s(self) -> None:
        for key in ("context", "context_options", "extra_instructions", "schema_additions", "example_additions"):
            self.assertEqual(self.v22[key], self.v21[key], key)

    def test_only_the_layout_flag_differs_in_the_render_settings(self) -> None:
        self.assertEqual(self.v22["render"], {**self.v21["render"], "contract_layout": "by_chunk"})

    def test_no_older_variant_sets_the_flag(self) -> None:
        for name in NAMES[:-1]:
            self.assertNotIn("contract_layout", load(name).get("render", {}), name)

    def test_the_comparison_labels_it(self) -> None:
        self.assertEqual(compare.VARIANT_LABELS["one_path_risk_chunked_v22"], "22: contract and data by chunk")


if __name__ == "__main__":
    unittest.main()
