"""Tests for prompt_doc.py, which writes docs/prompt.md from the prompt sources. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import prompt_doc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class PromptDocTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.doc = Path(self.tmp.name) / "prompt.md"

    def test_the_document_has_its_sections_in_order(self) -> None:
        text = prompt_doc.build()
        headings = ["## The brief's rules", "## The answer's shape", "## Repository context", "## The user prompt",
                    "## The full system prompt"]
        positions = [text.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertTrue(text.index("![How the prompt is assembled](prompt-assembly.svg)") < positions[0])

    def test_it_holds_the_walkthrough_field_the_variant_adds_and_the_example_diff(self) -> None:
        text = prompt_doc.build()
        self.assertIn("    walkthrough: List[dict] = Field(", text)
        self.assertIn("    node_files: Dict[str, List[str]] = Field(", text)
        self.assertIn('+    [input.displayName, input.nickname, id],', text)
        self.assertIn("Previous title: 'Add a nickname to the profile page'", text)

    def test_the_system_prompt_sits_in_a_details_block_with_a_blank_line_after_the_summary(self) -> None:
        text = prompt_doc.build()
        self.assertIn("<details><summary>Full system prompt for the example PR</summary>\n\n", text)
        self.assertTrue(text.rstrip().endswith("</details>"))

    def test_the_rules_are_the_variants_extra_instructions_verbatim(self) -> None:
        import tomllib
        rules = tomllib.loads((ROOT / "variants" / "brief.toml").read_text())["extra_instructions"].strip("\n")
        self.assertIn(rules, prompt_doc.build())

    def test_the_example_context_has_the_intro_text_of_the_real_pack(self) -> None:
        import context_pack
        self.assertIn(context_pack.INTROS["callers"], prompt_doc.CONTEXT)
        self.assertIn(context_pack.INTROS["reach"], prompt_doc.CONTEXT)

    def test_a_fence_is_longer_than_any_backtick_run_inside_it(self) -> None:
        self.assertEqual(prompt_doc.fenced("a"), "```\na\n```")
        self.assertEqual(prompt_doc.fenced("```x```", "python"), "````python\n```x```\n````")

    def test_check_passes_on_a_fresh_build_and_fails_after_a_one_character_edit(self) -> None:
        self.assertEqual(prompt_doc.main([], self.doc), 0)
        self.assertEqual(prompt_doc.main(["--check"], self.doc), 0)
        self.doc.write_text(self.doc.read_text() + "x")
        self.assertEqual(prompt_doc.main(["--check"], self.doc), 1)
        self.assertEqual(prompt_doc.main(["--check"], self.doc.with_name("missing.md")), 1)

    def test_the_committed_document_is_current(self) -> None:
        self.assertEqual(prompt_doc.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
