"""Tests that variant v23 loads: its render settings are the renderer's, its prompt asks for stops and no chunk start.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import compare  # noqa: E402
from render import RENDER_SETTINGS, AnswerError, check_render_settings  # noqa: E402

V23 = Path(__file__).resolve().parent.parent / "variants" / "one_path_risk_chunked_v23.toml"


class VariantV23(unittest.TestCase):
    def setUp(self) -> None:
        self.v23 = tomllib.loads(V23.read_text())

    def test_the_render_settings_are_the_renderers(self) -> None:
        self.assertEqual(self.v23["render"], RENDER_SETTINGS)
        check_render_settings(self.v23["render"])

    def test_the_prompt_asks_for_stops_and_no_chunk_start(self) -> None:
        text = self.v23["extra_instructions"] + self.v23["schema_additions"] + self.v23["example_additions"]
        self.assertIn("walkthrough", self.v23["schema_additions"])
        self.assertIn("walkthrough:", self.v23["example_additions"])
        self.assertNotIn("start:", self.v23["example_additions"])
        self.assertNotIn("start (object", self.v23["schema_additions"])
        self.assertNotIn("chunk's start", text)

    def test_the_comparison_labels_it(self) -> None:
        self.assertEqual(compare.VARIANT_LABELS["one_path_risk_chunked_v23"], "23: walkthrough stops")


class RenderSettings(unittest.TestCase):
    def test_a_variant_may_set_none_of_them(self) -> None:
        check_render_settings({})

    def test_a_setting_the_renderer_does_not_have_is_refused(self) -> None:
        with self.assertRaisesRegex(AnswerError, "unknown render setting 'start_line'"):
            check_render_settings({"start_line": True})

    def test_a_setting_has_one_legal_value(self) -> None:
        for key, value in (("diagram", "force_lr"), ("files", "table"), ("contract_layout", "flat"), ("walkthrough", False)):
            with self.assertRaisesRegex(AnswerError, f"render setting '{key}' can only be"):
                check_render_settings({key: value})


if __name__ == "__main__":
    unittest.main()
