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
from render import AnswerError, build_body, review_json  # noqa: E402
from test_contract_block import SPEC, contract_of, document, make_diff  # noqa: E402
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
CFG = {"files": "chunks", "contract_block": True, "contract_layout": "by_chunk", "review_labels": True}

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


def render_body(cfg: dict | None = None, contract: dict | None = None, text: str | None = None, run: dict = RUN):
    notes: list[str] = []
    contract = contract_of(BASE, HEAD) if contract is None else contract
    return build_body(run, PR, DATA, {**CFG, **(cfg or {})}, FLOORS, CODE_LINES, notes, contract, diff() if text is None else text), notes


class ChunkedSections(unittest.TestCase):
    def setUp(self) -> None:
        patch = mock.patch.object(render, "MIGRATION_GLOBS", ["db/*.sql"])
        patch.start()
        self.addCleanup(patch.stop)

    def test_two_sections_follow_the_description_in_place_of_the_old_block(self) -> None:
        (text, _, _, _, _), _ = render_body()
        self.assertRegex(text, r"(?s)### \*\*Description\*\*\n.*___\n\n### \*\*Contract\*\*\nContract: .*___\n\n### \*\*Data\*\*\nData: ")
        self.assertNotIn("Contract and data", text)

    def test_the_contract_glance_line_and_groups(self) -> None:
        (text, _, chunks, _, lineset), _ = render_body()
        glance_line = re.search(r"^Contract: .*$", text, re.M).group()
        self.assertEqual(glance_line, "Contract: 2 callers must change · 1 consumer may break")
        heads = [re.sub(r"<[^>]+>", "", h) for h in re.findall(r"<summary>(.*?)</summary>", text)]
        self.assertEqual(heads[:3], ["1 · Item endpoints callers must change request: owner added and required on ItemRequest",
                                     "2 · Widget model consumers may break b removed on Widget",
                                     "Not in any chunk callers must change 1 change in 1 controller"])
        self.assertEqual([l.text for l in lineset.loose_contract], ["`GET /gone` removed"])

    def test_data_lines_are_grouped_by_their_migration_chunk(self) -> None:
        (text, _, chunks, _, _), _ = render_body()
        data = text.split("### **Data**")[1]
        self.assertIn("Data: 1 destructive · 1 additive", data)
        self.assertRegex(data, r"<summary>\d · Items table <span class=\"pill p0\"><strong>destructive</strong></span> ")
        self.assertIn("drop column <code>legacy.old</code>", data)

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
        data = review_json(RUN, PR, chunks, False, None, True, lineset)
        by_name = {c["name"]: c for c in data["chunks"]}
        first = by_name["Item endpoints"]["contract"][0]
        self.assertEqual(set(first), {"impact", "text", "path", "side", "line"})
        self.assertEqual((first["impact"], first["path"], first["side"]), ("callers must change", SPEC, "R"))
        self.assertIsInstance(first["line"], int)
        self.assertEqual([l["impact"] for l in by_name["Items table"]["data"]], ["destructive", "additive"])
        self.assertEqual(by_name["Generated"]["contract"], [])
        self.assertEqual([l["text"] for l in data["unchunked"]["contract"]], ["`GET /gone` removed"])
        self.assertEqual(data["unchunked"]["data"], [])
        self.assertEqual(data["schema"], 2)

    def test_an_older_variant_has_none_of_these_fields(self) -> None:
        (text, _, chunks, _, lineset), _ = render_body({"contract_layout": None})
        self.assertIsNone(lineset)
        self.assertIn("### **Contract and data**\n<ul class=\"contract\">", text)
        data = review_json(RUN, PR, chunks, False, None, True)
        self.assertNotIn("unchunked", data)
        self.assertTrue(all("contract" not in c and "data" not in c for c in data["chunks"]))

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

    def test_the_review_order_is_in_the_body_unless_the_option_is_off(self) -> None:
        (text, _, chunks, _, _), _ = render_body()
        self.assertIn("Review order", text)
        self.assertIn('<table class="review-order">', text)
        (text, _, _, _, _), _ = render_body({"review_order": False})
        self.assertNotIn("Review order", text)
        self.assertNotIn("review-order", text)
        self.assertNotIn("<table", text)

    def test_without_the_review_order_the_body_ends_after_the_diagram(self) -> None:
        (text, _, _, _, _), _ = render_body({"review_order": False})
        headings = re.findall(r"^### (?:\*\*)?(.*?)(?:\*\*)?$", text, re.M)
        self.assertEqual(headings, ["PR Type", "Description", "Contract", "Data"])
        self.assertTrue(text.rstrip().endswith("___"))

    def test_the_option_does_not_touch_review_json(self) -> None:
        (_, _, shown, _, lineset), _ = render_body()
        (_, _, hidden, _, hidden_lineset), _ = render_body({"review_order": False})
        self.assertEqual(review_json(RUN, PR, hidden, False, None, True, hidden_lineset),
                         review_json(RUN, PR, shown, False, None, True, lineset))

    def test_the_option_must_be_a_boolean_and_needs_chunks(self) -> None:
        with self.assertRaises(AnswerError):
            render_body({"review_order": "no"})
        with self.assertRaises(AnswerError):
            render_body({"files": "labels", "contract_layout": None, "contract_block": False, "review_order": False})

    def test_the_layout_needs_chunks(self) -> None:
        with self.assertRaises(AnswerError):
            render_body({"files": "table"})
        with self.assertRaises(AnswerError):
            render_body({"contract_layout": "flat"})


def build_body_for(run: dict):
    notes: list[str] = []
    return build_body(run, PR, DATA, CFG, FLOORS, {}, notes, None, ""), notes


if __name__ == "__main__":
    unittest.main()
