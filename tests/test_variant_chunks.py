"""Tests that variant `chunks` loads, that its prompt asks for chunks of hunk ids and for neither a diagram nor a walkthrough,
and that a variant with `hunk_ids` shows the model tagged hunk headers and the hunks that belong together. All data here is
invented. Run with `python3 -m unittest discover -s tests` from the tool's folder."""
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

CHUNKS = Path(__file__).resolve().parent.parent / "variants" / "chunks.toml"
BRIEF = Path(__file__).resolve().parent.parent / "variants" / "brief.toml"
PR = {"title": "T", "body": "", "headRefName": "b", "headRefOid": "a" * 40, "baseRefOid": "b" * 40,
      "commits": [{"messageHeadline": "c"}], "files": [{"path": "a.py"}]}
DIFF = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@ def f():\n x = 0\n-y = 0\n+y = 1\n@@ -9 +9 @@\n-a\n+b\n"


class VariantChunks(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks = tomllib.loads(CHUNKS.read_text())

    def test_it_is_found_by_name(self) -> None:
        self.assertEqual(variant_file("chunks"), CHUNKS)

    def test_it_tags_hunks_and_draws_no_diagram(self) -> None:
        self.assertIs(self.chunks["hunk_ids"], True)
        self.assertIs(self.chunks["diagram"], False)

    def test_it_has_the_brief_variants_context(self) -> None:
        brief = tomllib.loads(BRIEF.read_text())
        self.assertEqual(self.chunks["context"], brief["context"])
        self.assertEqual(self.chunks["context_options"], brief["context_options"])

    def test_the_brief_variant_is_not_tagged_and_keeps_its_diagram(self) -> None:
        brief = tomllib.loads(BRIEF.read_text())
        self.assertNotIn("hunk_ids", brief)
        self.assertNotIn("diagram", brief)

    def test_the_prompt_asks_for_chunks_and_for_neither_a_diagram_nor_a_walkthrough(self) -> None:
        system, _ = build_prompts(self.chunks, PR, tag_headers(DIFF), False)
        self.assertIn("chunks: List[dict]", system)
        self.assertNotIn("changes_diagram", system)
        self.assertNotIn("walkthrough: List[dict]", system)
        self.assertNotIn("node_files", system)
        self.assertNotIn("pr_files", system)

    def test_the_rules_are_in_the_prompt(self) -> None:
        system, _ = build_prompts(self.chunks, PR, tag_headers(DIFF), False)
        for rule in ("exactly one chunk", "Never invent an ID", "One idea per chunk", "Tests go with the code they test",
                     "Hunks that belong together", "Also in this PR", "depends only on earlier ones", "2 to 7 chunks",
                     "caller list is partial", "Do not summarize the Repository context"):
            self.assertIn(rule, system)

    def test_the_example_shows_one_chunk_with_every_key(self) -> None:
        for key in ("- title:", "summary:", "hunks:", "depends_on:", "risk:", "risk_reason:"):
            self.assertIn(key, self.chunks["example_additions"])
        for key in ("title (str", "summary (str", "hunks (list of str", "depends_on (list of int", "risk (str", "risk_reason (str"):
            self.assertIn(key, self.chunks["schema_additions"])

    def test_the_prompts_diff_carries_the_tags_when_the_tagged_diff_is_passed(self) -> None:
        _, user = build_prompts(self.chunks, PR, tag_headers(DIFF), False)
        self.assertIn("@@ -1,2 +1,2 @@ def f(): [h01]\n", user)
        self.assertIn("@@ -9 +9 @@ [h02]\n", user)
        _, plain = build_prompts(self.chunks, PR, DIFF, False)
        self.assertNotIn("[h01]", plain)

    def test_the_diagram_switch_alone_removes_only_the_diagram_fields(self) -> None:
        brief = tomllib.loads(BRIEF.read_text())
        on, _ = build_prompts(brief, PR, DIFF, False)
        off, _ = build_prompts({**brief, "diagram": False}, PR, DIFF, False)
        for field in ("changes_diagram: str = Field", "changes_diagram: |"):
            self.assertIn(field, on)
            self.assertNotIn(field, off)
        self.assertIn("walkthrough: List[dict]", off)
        self.assertIn("- node: |", off)

    def test_the_additions_land_whether_or_not_the_diagram_is_on(self) -> None:
        for diagram in (True, False):
            system, _ = build_prompts({**self.chunks, "diagram": diagram}, PR, DIFF, False)
            self.assertEqual(system.count("chunks: List[dict]"), 1)
            self.assertEqual(system.count("\nchunks:\n- title:"), 1)


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

    def prompt(self, variant: str) -> tuple[str, str]:
        pack = Pack(items={"contract": ["- one"]}, skipped_common={}, dropped={}, contract=contract_of(fixtures.BASE, fixtures.HEAD))
        files = {fixtures.ENTITY: fixtures.ENTITY_AFTER, fixtures.CONTROLLER: fixtures.CONTROLLER_AFTER}
        out, err = io.StringIO(), io.StringIO()
        argv = ["run.py", "7", "--variant", variant, "--prompt-only", "--repo", "acme/shop"]
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
        return out.getvalue(), err.getvalue()

    def test_the_chunks_variant_shows_tagged_headers_and_the_pins_after_the_pack(self) -> None:
        text, _ = self.prompt("chunks")
        for tag in ("h01", "h02", "h03", "h04", "h05"):
            self.assertRegex(text, rf"(?m)^@@ .* \[{tag}\]$")
        self.assertIn("- one\n\n### Hunks that belong together\nThese hunks declare the same API or database change, "
                      "so they must be in the same chunk.\n\n- h01, h02, h03\n- h04, h05\n", text)

    def test_the_brief_variant_shows_no_tags_and_no_pins(self) -> None:
        text, _ = self.prompt("brief")
        self.assertNotRegex(text, r"(?m)^@@ .* \[h\d+\]$")
        self.assertNotIn("Hunks that belong together", text)


if __name__ == "__main__":
    unittest.main()
