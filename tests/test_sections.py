"""Tests for the Contract and Data sections of a brief, the diagram caption and badges, and their review.json fields.
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
from render import build_body, node_titles, review_json, stop_badges  # noqa: E402
from contract_fixtures import SPEC, contract_of, document, make_diff  # noqa: E402
from test_contract_impact import operation, props  # noqa: E402

CONTROLLER = "api/ItemController.java"
MODEL = "api/models/Widget.java"
MIGRATION = "db/V9__items.sql"
SDK = "web/sdk/generated.ts"
PATHS = [CONTROLLER, MODEL, MIGRATION, SPEC, SDK]
RUN = {"repo": "acme/shop", "pr": 7, "with_body": False, "variant": "brief", "pr_head_sha": "abc",
       "context": {"sections": {"contract": 0}, "dropped": {}}}
PR = {"title": "T", "body": "", "files": [{"path": p, "additions": 2, "deletions": 1, "changeType": "MODIFIED"} for p in PATHS]}
DIAGRAM = """```mermaid
flowchart LR
  Items["1 · Item endpoints<br/>makes items"] --> Tbl["Items table"]
  Tbl --> Ctx["Search index"]
```"""
DATA = {"type": "Enhancement", "description": "does things", "changes_diagram": DIAGRAM,
        "node_files": {"Items": [CONTROLLER, MODEL], "Tbl": [MIGRATION]},
        "walkthrough": [{"file": CONTROLLER, "line_text": "makeItem(ItemRequest request)", "title": "Make an item", "why": "w", "node": "Items"},
                        {"file": MODEL, "title": "The model", "why": "w", "node": "Items"},
                        {"file": MIGRATION, "title": "The table", "why": "w", "node": "Tbl"}]}

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
    return build_body(run, PR, DATA, CODE_LINES, notes, contract, diff() if text is None else text), notes


class Sections(unittest.TestCase):
    def setUp(self) -> None:
        patch = mock.patch.object(render, "MIGRATION_GLOBS", ["db/*.sql"])
        patch.start()
        self.addCleanup(patch.stop)

    def section_of(self, text: str, name: str) -> str:
        return re.search(rf'(?s)<details class="section">\n<summary><strong>{name}</strong>.*?</details>', text).group()

    def test_two_closed_sections_follow_the_description_and_no_rule_separates_them(self) -> None:
        brief, _ = render_body()
        text = brief.body
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
        brief, _ = render_body()
        text, lineset = brief.body, brief
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

    def test_the_data_section_lists_every_line_in_one_table(self) -> None:
        brief, _ = render_body()
        text = brief.body
        data = self.section_of(text, "Data")
        summary = re.search(r"<summary>(.*?)</summary>", data).group(1)
        self.assertEqual(re.sub(r"<[^>]+>", "", summary), "Data destructive additive 2 changes")
        self.assertEqual(data.count("<details"), 1)
        self.assertIn("| Impact | Change | Table | ↗ |", data)
        self.assertIn("| <code>− old</code> | <code>legacy</code> |", data)
        self.assertNotIn("Items table", data)

    def test_review_json_lists_the_boxes_the_stops_and_every_line(self) -> None:
        brief, _ = render_body()
        data = review_json(RUN, brief, True)
        self.assertEqual(data["schema"], 4)
        self.assertNotIn("chunks", data)
        self.assertNotIn("unchunked", data)
        first = next(line for line in data["contract"] if line["on"] == "`ItemRequest`")
        self.assertEqual(set(first), {"impact", "text", "change", "on", "reaches", "path", "side", "line"})
        self.assertEqual((first["change"], first["on"], first["reaches"]), ("`+ owner` required", "`ItemRequest`", "request"))
        self.assertEqual((first["impact"], first["path"], first["side"]), ("callers must change", SPEC, "R"))
        self.assertIsInstance(first["line"], int)
        self.assertEqual(len(data["contract"]), 3)
        self.assertEqual([l["impact"] for l in data["data"]], ["destructive", "additive"])
        self.assertEqual(data["nodes"], {
            "Items": {"title": "Item endpoints", "files": [CONTROLLER, MODEL], "stops": [1, 2]},
            "Tbl": {"title": "Items table", "files": [MIGRATION], "stops": [3]},
            "Ctx": {"title": "Search index", "files": [], "stops": []}})
        self.assertEqual([(stop["i"], stop["node"]) for stop in data["walkthrough"]], [(1, "Items"), (2, "Items"), (3, "Tbl")])

    def test_each_box_carries_the_numbers_of_its_stops_and_a_box_with_none_carries_none(self) -> None:
        brief, _ = render_body()
        self.assertIn('Items["1 · 2 · Item endpoints<br/>makes items"]', brief.body)
        self.assertIn('Tbl["3 · Items table"]', brief.body)
        self.assertIn('Ctx["Search index"]', brief.body)

    def test_a_dashed_box_gets_the_caption_under_the_diagram_and_no_dashed_box_gets_none(self) -> None:
        brief, _ = render_body()
        self.assertRegex(brief.body, r"```\n\nDashed boxes are unchanged context\n\n")
        self.assertIn("class Ctx context", brief.body)
        covered = {**DATA, "node_files": {"Items": [CONTROLLER], "Tbl": [MIGRATION], "Ctx": [MODEL]}}
        brief = build_body(RUN, PR, covered, CODE_LINES, [], contract_of(BASE, HEAD), diff())
        self.assertNotIn("Dashed boxes", brief.body)
        self.assertNotIn("classDef context", brief.body)

    def test_a_brief_with_no_diagram_has_no_caption_and_every_stop_has_no_node(self) -> None:
        notes: list[str] = []
        brief = build_body(RUN, PR, {**DATA, "changes_diagram": None}, CODE_LINES, notes, None, "")
        self.assertNotIn("Dashed boxes", brief.body)
        self.assertEqual(brief.nodes, {})
        self.assertIn("no changes_diagram", notes)
        self.assertEqual({stop["node"] for stop in brief.stops}, {None})

    def test_a_stop_naming_no_box_lands_on_the_first_box_holding_its_file(self) -> None:
        raw = {**DATA, "walkthrough": [{"file": MODEL, "title": "The model", "why": "w"}]}
        notes: list[str] = []
        brief = build_body(RUN, PR, raw, CODE_LINES, notes, None, "")
        self.assertEqual(brief.nodes["Items"]["stops"], [1])
        self.assertIn("stop 1: no node, using Items", notes)

    def test_no_changes_keeps_the_old_sentences(self) -> None:
        brief, _ = render_body(contract=document({}, {}) | {"path": SPEC}, text="")
        text = brief.body
        self.assertIn("### **Contract**\nNo API changes\n", text)
        self.assertIn("### **Data**\nNo database changes\n", text)

    def test_a_side_that_could_not_be_checked_is_named(self) -> None:
        unchecked = {**RUN, "context": {"sections": {}, "dropped": {}}}
        with mock.patch.object(render, "MIGRATION_GLOBS", []):
            brief, _ = build_body_for(unchecked)
            text = brief.body
        self.assertIn("### **Contract**\nAPI changes not checked\n", text)
        self.assertIn("### **Data**\nDatabase changes not checked\n", text)

    def test_the_page_styles_the_three_chip_levels(self) -> None:
        page = render.markdown_page("# T")
        for rank in ("p0", "p1"):
            self.assertIn(f".pill.{rank} {{", page)
        self.assertIn(".pill {", page)

    def test_the_body_has_no_review_order_table(self) -> None:
        brief, _ = render_body()
        text = brief.body
        self.assertNotIn("Review order", text)
        self.assertNotIn("<table", text)

    def test_the_body_ends_after_the_diagram(self) -> None:
        brief, _ = render_body()
        text = brief.body
        headings = re.findall(r"^### (?:\*\*)?(.*?)(?:\*\*)?$", text, re.M)
        self.assertEqual(headings, ["PR Type", "Description", "Diagram Walkthrough"])
        self.assertEqual(text.count("<summary><strong>"), 2)
        self.assertTrue(text.rstrip().endswith("___"))


class DiagramText(unittest.TestCase):
    def test_a_badge_replaces_the_number_the_model_wrote(self) -> None:
        text = 'A["1 · Title<br/>sub"] --> B["Other"]'
        self.assertEqual(stop_badges(text, {"A": [4], "B": []}), 'A["4 · Title<br/>sub"] --> B["Other"]')

    def test_class_and_style_lines_are_left_alone(self) -> None:
        text = '  class A context\n  style A fill:#fff'
        self.assertEqual(stop_badges(text, {"A": [1]}), text)

    def test_the_title_is_the_first_label_line_as_plain_text(self) -> None:
        diagram = 'flowchart LR\n  A["2 · 5 · <b>Add</b> a thing<br/>detail"] --> B["Next"]\n  class A context'
        self.assertEqual(node_titles(diagram), {"A": "Add a thing", "B": "Next"})


def build_body_for(run: dict):
    notes: list[str] = []
    return build_body(run, PR, DATA, {}, notes, None, ""), notes


if __name__ == "__main__":
    unittest.main()
