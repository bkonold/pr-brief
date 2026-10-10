"""Tests that variant `brief` loads, that its prompt asks for a diagram, a walkthrough whose stops name a diagram box and
chunks of hunk ids, and that its prompt's diff carries the hunk tags. All data here is invented. Run with
`python3 -m unittest discover -s tests` from the tool's folder."""
import contextlib
import io
import json
import sys
import tomllib
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import render  # noqa: E402
import run  # noqa: E402
import test_sources as fixtures  # noqa: E402
from config import variant_file  # noqa: E402
from context_pack import Pack  # noqa: E402
from contract_fixtures import SPEC, contract_of, make_diff  # noqa: E402
from hunks import tag_headers  # noqa: E402
from run import build_prompts, pin_groups  # noqa: E402

BRIEF = Path(__file__).resolve().parent.parent / "variants" / "brief.toml"
PR = {"title": "T", "body": "", "headRefName": "b", "headRefOid": "a" * 40, "baseRefOid": "b" * 40,
      "commits": [{"messageHeadline": "c"}], "files": [{"path": "a.py"}]}
DIFF = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@ def f():\n x = 0\n-y = 0\n+y = 1\n@@ -9 +9 @@\n-a\n+b\n"


class VariantBRIEF(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = tomllib.loads(BRIEF.read_text())
        self.text = self.brief["extra_instructions"] + self.brief["schema_additions"] + self.brief["example_additions"]

    def test_it_is_found_by_name(self) -> None:
        self.assertEqual(variant_file("brief"), BRIEF)

    def test_it_has_no_render_table(self) -> None:
        self.assertNotIn("render", self.brief)

    def test_it_tags_hunks_and_keeps_its_diagram(self) -> None:
        self.assertIs(self.brief["hunk_ids"], True)
        self.assertNotIn("diagram", self.brief)

    def test_there_is_no_chunks_variant(self) -> None:
        self.assertFalse((BRIEF.parent / "chunks.toml").exists())

    def test_the_prompt_asks_for_stops_that_name_a_box_and_for_node_files(self) -> None:
        self.assertIn("walkthrough", self.brief["schema_additions"])
        self.assertIn("node_files", self.brief["schema_additions"])
        self.assertIn("- node: |", self.brief["example_additions"])
        self.assertIn("node (str", self.brief["schema_additions"])

    def test_the_prompt_asks_for_chunks_but_for_none_of_the_older_sections(self) -> None:
        for word in ("checks", ":::save", "levels", "review:"):
            self.assertNotIn(word, self.text.lower())
        self.assertIn("chunk", self.text.lower())

    def test_the_prompt_no_longer_asks_for_the_per_file_summaries(self) -> None:
        system, _ = build_prompts(self.brief, PR, "diff", False)
        self.assertNotIn("pr_files", system)
        self.assertIn("walkthrough: List[dict]", system)
        self.assertIn("changes_diagram", system)

    def test_the_prompt_asks_for_chunks_once_with_their_example(self) -> None:
        system, _ = build_prompts(self.brief, PR, tag_headers(DIFF), False)
        self.assertEqual(system.count("chunks: List[dict]"), 1)
        self.assertEqual(system.count("\nchunks:\n- title:"), 1)
        self.assertEqual(system.count("Repository context section"), 1)

    def test_the_rules_are_in_the_prompt(self) -> None:
        system, _ = build_prompts(self.brief, PR, tag_headers(DIFF), False)
        for rule in ("exactly one chunk", "Never invent an ID", "One idea per chunk", "Tests go with the code they test",
                     "Hunks that belong together", "Also in this PR", "depends only on earlier ones", "2 to 7 chunks",
                     "caller list is partial", "Do not summarize the Repository context"):
            self.assertIn(rule, system)
        self.assertNotIn("do not write a walkthrough", system)

    def test_the_example_shows_one_chunk_with_every_key(self) -> None:
        for key in ("- title:", "summary:", "hunks:", "depends_on:", "risk:", "risk_reason:"):
            self.assertIn(key, self.brief["example_additions"])
        for key in ("title (str", "summary (str", "hunks (list of str", "depends_on (list of int", "risk (str", "risk_reason (str"):
            self.assertIn(key, self.brief["schema_additions"])

    def test_the_prompts_diff_carries_the_tags_when_the_tagged_diff_is_passed(self) -> None:
        _, user = build_prompts(self.brief, PR, tag_headers(DIFF), False)
        self.assertIn("@@ -1,2 +1,2 @@ def f(): [h01]\n", user)
        self.assertIn("@@ -9 +9 @@ [h02]\n", user)
        _, plain = build_prompts(self.brief, PR, DIFF, False)
        self.assertNotIn("[h01]", plain)

    def test_the_diagram_switch_alone_removes_only_the_diagram_fields(self) -> None:
        on, _ = build_prompts(self.brief, PR, DIFF, False)
        off, _ = build_prompts({**self.brief, "diagram": False}, PR, DIFF, False)
        for field in ("changes_diagram: str = Field", "changes_diagram: |"):
            self.assertIn(field, on)
            self.assertNotIn(field, off)
        self.assertIn("walkthrough: List[dict]", off)
        self.assertIn("- node: |", off)
        self.assertIn("chunks: List[dict]", off)

    def test_it_asks_for_no_wiki_context(self) -> None:
        self.assertEqual(self.brief["context"], ["callers", "reach", "contract", "migrations"])
        self.assertNotIn("wiki_match", self.brief["context_options"])
        self.assertNotIn("wiki", (self.text + self.brief["extra_instructions"]).lower())


SPEC_PATHS = [SPEC, fixtures.CUSTOMER, fixtures.CONTROLLER, fixtures.ENTITY, fixtures.MIGRATION]
FILES = [{"path": p, "additions": 1, "deletions": 0, "changeType": "ADDED" if p == fixtures.ENTITY else "MODIFIED"} for p in SPEC_PATHS]
FULL_PR = {**PR, "files": FILES}


def full_diff() -> str:
    return "\n".join([
        make_diff(SPEC, json.dumps(fixtures.BASE, indent=2), json.dumps(fixtures.HEAD, indent=2)),
        make_diff(fixtures.CUSTOMER, fixtures.RECORD_BEFORE, fixtures.RECORD_AFTER),
        make_diff(fixtures.CONTROLLER, fixtures.CONTROLLER_BEFORE, fixtures.CONTROLLER_AFTER),
        make_diff(fixtures.ENTITY, "", fixtures.ENTITY_AFTER),
        make_diff(fixtures.MIGRATION, "", "CREATE TABLE customers (id bigint);\n"),
    ])


class PinGroups(unittest.TestCase):
    def setUp(self) -> None:
        patch = mock.patch.object(render, "MIGRATION_GLOBS", ["db/*.sql"])
        patch.start()
        self.addCleanup(patch.stop)
        self.pack = Pack(items={}, skipped_common={}, dropped={}, contract=contract_of(fixtures.BASE, fixtures.HEAD))

    def groups(self, pack: Pack | None) -> list[list[str]]:
        files = {fixtures.ENTITY: fixtures.ENTITY_AFTER, fixtures.CONTROLLER: fixtures.CONTROLLER_AFTER}
        with mock.patch.object(run, "head_reader", return_value=lambda path: files.get(path)):
            return pin_groups(FULL_PR, pack, full_diff())

    def test_the_spec_hunk_its_model_and_controller_hunks_and_the_migration_and_entity_hunks_pair_up(self) -> None:
        self.assertEqual(self.groups(self.pack), [["h01", "h02", "h03"], ["h04", "h05"]])

    def test_without_a_pack_there_is_no_contract_so_only_the_data_side_pins(self) -> None:
        self.assertEqual(self.groups(None), [["h04", "h05"]])


class HunkIdsInThePrompt(unittest.TestCase):
    """`run.py --prompt-only` with a fake host."""

    class Host:
        def pr(self, owner: str, name: str, number: str) -> dict:
            return FULL_PR

        def diff(self, owner: str, name: str, number: str) -> str:
            return full_diff()

    def prompt(self) -> str:
        pack = Pack(items={"contract": ["- one"]}, skipped_common={}, dropped={}, contract=contract_of(fixtures.BASE, fixtures.HEAD))
        files = {fixtures.ENTITY: fixtures.ENTITY_AFTER, fixtures.CONTROLLER: fixtures.CONTROLLER_AFTER}
        out, err = io.StringIO(), io.StringIO()
        argv = ["run.py", "7", "--variant", "brief", "--prompt-only", "--repo", "acme/shop"]
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(sys, "argv", argv))
            stack.enter_context(mock.patch.object(run, "get_host", return_value=self.Host()))
            stack.enter_context(mock.patch.object(run, "ensure_commits"))
            stack.enter_context(mock.patch.object(run, "build", return_value=pack))
            stack.enter_context(mock.patch.object(run, "head_reader", return_value=lambda path: files.get(path)))
            stack.enter_context(mock.patch.object(render, "MIGRATION_GLOBS", ["db/*.sql"]))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            self.assertEqual(run.execute(run.Progress()), 0)
        return out.getvalue()

    def test_the_brief_variant_shows_tagged_headers_and_the_pins_after_the_pack(self) -> None:
        text: str = self.prompt()
        for tag in ("h01", "h02", "h03", "h04", "h05"):
            self.assertRegex(text, rf"(?m)^@@ .* \[{tag}\]$")
        self.assertIn("- one\n\n### Hunks that belong together\nThese hunks declare the same API or database change, "
                      "so they must be in the same chunk.\n\n- h01, h02, h03\n- h04, h05\n", text)


if __name__ == "__main__":
    unittest.main()
