"""Tests for the Contract and Data sections of a v22 brief, the labels they set and their review.json fields.
All data here is invented. Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import render  # noqa: E402
from render import build_body, review_json  # noqa: E402
from contract_fixtures import SPEC, contract_of, document, make_diff  # noqa: E402
from test_contract_impact import operation, props  # noqa: E402

CONTROLLER = "api/ItemController.java"
MODEL = "api/models/Widget.java"
MIGRATION = "db/V9__items.sql"
SDK = "web/sdk/generated.ts"
PATHS = [CONTROLLER, MODEL, MIGRATION, SPEC, SDK]
FLOORS = {"tag": [{"name": "generated", "globs": [SPEC, SDK]}]}
RUN = {"repo": "acme/shop", "pr": 7, "with_body": False, "variant": "v22", "pr_head_sha": "abc",
       "context": {"sections": {"contract": 0}, "dropped": {}}}
PR = {"title": "T", "body": "", "files": [{"path": p, "additions": 2, "deletions": 1, "changeType": "MODIFIED"} for p in PATHS]}
CHUNKS = [
    {"name": "Item endpoints", "review": "read", "why": "w", "files": [CONTROLLER], "checks": ["contract"]},
    {"name": "Widget model", "review": "read", "why": "w", "files": [MODEL], "checks": []},
    {"name": "Items table", "review": "skim", "why": "w", "files": [MIGRATION], "checks": ["data"]},
    {"name": "Generated", "review": "skim", "why": "w", "files": [SPEC, SDK], "checks": []},
]
DATA = {"type": "Enhancement", "description": "does things", "chunks": CHUNKS}

PATHS_BEFORE = {"/items": {"post": operation("makeItem", "item-controller", request="ItemRequest", response="Item")},
                "/gone": {"get": operation("gone", "orphan-controller")}}
BASE = document(PATHS_BEFORE, {"ItemRequest": props("a"), "Item": props("a"), "Widget": props("a", "b")})
HEAD = document({"/items": PATHS_BEFORE["/items"]},
                {"ItemRequest": props("a", "owner", required=("owner",)), "Item": props("a"), "Widget": props("a")})
CODE_LINES = {CONTROLLER: [("R", 3, "makeItem(ItemRequest request)")]}
MIGRATION_SQL = "CREATE TABLE items (id uuid);\nALTER TABLE legacy DROP COLUMN old;\n"


def diff(sql: str = MIGRATION_SQL) -> str:
    return (make_diff(SPEC, json.dumps(BASE, indent=2), json.dumps(HEAD, indent=2)) + "\n"
            + make_diff(MIGRATION, "", sql))


def render_body(contract: dict | None = None, text: str | None = None, run: dict = RUN):
    notes: list[str] = []
    contract = contract_of(BASE, HEAD) if contract is None else contract
    return build_body(run, PR, DATA, FLOORS, CODE_LINES, notes, contract, diff() if text is None else text), notes


class ChunkedSections(unittest.TestCase):
    def setUp(self) -> None:
        patch = mock.patch.object(render, "MIGRATION_GLOBS", ["db/*.sql"])
        patch.start()
        self.addCleanup(patch.stop)

    def section_of(self, text: str, name: str) -> str:
        return re.search(rf'(?s)<details class="section">\n<summary><strong>{name}</strong>.*?</details>', text).group()

    def test_two_closed_sections_follow_the_description_and_no_rule_separates_them(self) -> None:
        (text, _, _, _, _), _ = render_body()
        self.assertRegex(text, r'(?s)### \*\*Description\*\*\n.*___\n\n<details class="section">\n<summary><strong>Contract</strong> '
                               r'.*</details>\n+<details class="section">\n<summary><strong>Data</strong> ')
        self.assertNotIn("Contract and data", text)
        self.assertNotIn("### **Contract**", text)
        self.assertEqual(text.count('<details class="section">'), 2)
        contract_to_data = text[text.index("<summary><strong>Contract</strong>"):text.index("<summary><strong>Data</strong>")]
        self.assertNotIn("___", contract_to_data)
        after_data = text[text.index("<summary><strong>Data</strong>"):]
        self.assertEqual(after_data.count("___"), 1)
        self.assertTrue(after_data.rstrip().endswith("___"))
        self.assertEqual(text.count("___"), 3)

    def test_the_contract_summary_has_the_chips_and_the_table_every_line_worst_first(self) -> None:
        (text, _, _, _, lineset), _ = render_body()
        contract = self.section_of(text, "Contract")
        summary = re.search(r"<summary>(.*?)</summary>", contract).group(1)
        self.assertEqual(re.sub(r"<[^>]+>", "", summary), "Contract callers must change consumers may break 3 changes")
        rows = [re.sub(r"<[^>]+>", "", row) for row in contract.splitlines() if row.startswith("| <span")]
        self.assertEqual([re.sub(r" \| \[↗\].*", "", row) for row in rows],
                         ["| callers must change | request | + owner required | ItemRequest",
                          "| callers must change |  | removed | GET /gone",
                          "| consumers may break |  | − b | Widget"])
        self.assertEqual(len(lineset.contract), 3)
        for gone in ("chunk", "Not in any", "group-row", "<strong><code>"):
            self.assertNotIn(gone, contract)
        self.assertEqual([l.text for l in lineset.loose_contract], ["`GET /gone` removed"])

    def test_the_data_section_lists_every_line_in_one_table(self) -> None:
        (text, _, _, _, _), _ = render_body()
        data = self.section_of(text, "Data")
        summary = re.search(r"<summary>(.*?)</summary>", data).group(1)
        self.assertEqual(re.sub(r"<[^>]+>", "", summary), "Data destructive additive 2 changes")
        self.assertEqual(data.count("<details"), 1)
        self.assertIn("| Impact | Change | Table | ↗ |", data)
        self.assertIn("| <code>− old</code> | <code>legacy</code> |", data)
        self.assertNotIn("Items table", data)

    def test_labels_come_from_the_lines_a_chunk_owns(self) -> None:
        (_, _, chunks, _, _), _ = render_body()
        labelled = {c.name: c.labels for c in chunks}
        self.assertEqual(labelled["Item endpoints"], ["breaking"])
        self.assertEqual(labelled["Items table"], ["destructive"])
        self.assertEqual(labelled["Widget model"], ["breaking"])
        self.assertEqual(labelled["Generated"], ["generated"])
        raised = {c.name: c.review for c in chunks}
        self.assertEqual((raised["Item endpoints"], raised["Items table"]), ("verify", "verify"))

    def test_review_json_lists_each_chunks_lines_and_the_unchunked_ones(self) -> None:
        (_, _, chunks, _, lineset), _ = render_body()
        data = review_json(RUN, PR, chunks, False, None, lineset, [])
        by_name = {c["name"]: c for c in data["chunks"]}
        self.assertEqual(set(by_name["Item endpoints"]), {"n", "name", "review", "raised_by", "why", "nodes", "labels", "contract", "data", "files"})
        first = by_name["Item endpoints"]["contract"][0]
        self.assertEqual(set(first), {"impact", "text", "change", "on", "reaches", "path", "side", "line"})
        self.assertEqual((first["change"], first["on"], first["reaches"]), ("`+ owner` required", "`ItemRequest`", "request"))
        self.assertEqual((first["impact"], first["path"], first["side"]), ("callers must change", SPEC, "R"))
        self.assertIsInstance(first["line"], int)
        self.assertEqual([l["impact"] for l in by_name["Items table"]["data"]], ["destructive", "additive"])
        self.assertEqual(by_name["Generated"]["contract"], [])
        self.assertEqual([l["text"] for l in data["unchunked"]["contract"]], ["`GET /gone` removed"])
        self.assertEqual(data["unchunked"]["data"], [])
        self.assertEqual(data["schema"], 3)

    def test_no_changes_keeps_the_old_sentences(self) -> None:
        (text, _, _, _, _), _ = render_body(contract=document({}, {}) | {"path": SPEC}, text="")
        self.assertIn("### **Contract**\nNo API changes\n", text)
        self.assertIn("### **Data**\nNo database changes\n", text)

    def test_a_side_that_could_not_be_checked_is_named(self) -> None:
        unchecked = {**RUN, "context": {"sections": {}, "dropped": {}}}
        with mock.patch.object(render, "MIGRATION_GLOBS", []):
            (text, _, _, _, _), _ = build_body_for(unchecked)
        self.assertIn("### **Contract**\nAPI changes not checked\n", text)
        self.assertIn("### **Data**\nDatabase changes not checked\n", text)

    def test_the_page_styles_the_three_chip_levels(self) -> None:
        page = render.markdown_page("# T")
        for rank in ("p0", "p1"):
            self.assertIn(f".pill.{rank} {{", page)
        self.assertIn(".pill {", page)

    def test_the_body_has_no_review_order_table(self) -> None:
        (text, _, _, _, _), _ = render_body()
        self.assertNotIn("Review order", text)
        self.assertNotIn("review-order", text)
        self.assertNotIn("<table", text)

    def test_the_body_ends_after_the_diagram(self) -> None:
        (text, _, _, _, _), _ = render_body()
        headings = re.findall(r"^### (?:\*\*)?(.*?)(?:\*\*)?$", text, re.M)
        self.assertEqual(headings, ["PR Type", "Description"])
        self.assertEqual(text.count("<summary><strong>"), 2)
        self.assertTrue(text.rstrip().endswith("___"))


def build_body_for(run: dict):
    notes: list[str] = []
    return build_body(run, PR, DATA, FLOORS, {}, notes, None, ""), notes


if __name__ == "__main__":
    unittest.main()
