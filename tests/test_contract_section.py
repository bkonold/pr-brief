"""Tests for the "Contract and data" section of a brief. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import render  # noqa: E402
from render import build_body  # noqa: E402

FLOORS = {"floor": []}
PATHS = ["src/ui.js", "src/api.js", "db/V1__t.sql"]
FLOW = [{"name": "Screen", "review": "skim", "why": "w", "files": ["src/ui.js"]},
        {"name": "Endpoint", "review": "read", "why": "w", "files": ["src/api.js"]},
        {"name": "Table", "review": "skim", "why": "w", "files": ["db/V1__t.sql"]}]


RUN = {"repo": "acme/shop", "pr": 7, "with_body": False, "variant": "v", "pr_head_sha": "abc",
       "context": {"sections": {"contract": 0}, "dropped": {}}}
PR = {"title": "T", "body": "", "files": [
    {"path": path, "additions": 1, "deletions": 0, "changeType": "ADDED"} for path in PATHS]}
DIFF = ("diff --git a/db/V1__t.sql b/db/V1__t.sql\n--- /dev/null\n+++ b/db/V1__t.sql\n@@ -0,0 +1,2 @@\n"
        "+-- new\n+CREATE TABLE orders (id uuid);\n")
DATA = {"type": "Enhancement", "description": "does things", "chunks": FLOW}


def body(cfg: dict, diff: str = DIFF, contract: dict | None = None) -> str:
    notes: list[str] = []
    text, _, _, _ = build_body(RUN, PR, DATA, {"files": "chunks", **cfg}, FLOORS, {}, notes, contract, diff)
    return text


class ContractSection(unittest.TestCase):
    def setUp(self) -> None:
        patch = mock.patch.object(render, "MIGRATION_GLOBS", ["db/*.sql"])
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_section_follows_the_description_and_lists_the_migration_table(self) -> None:
        text = body({"contract_block": True})
        self.assertRegex(text, r"(?s)### \*\*Description\*\*\n.*___\n\n### \*\*Contract and data\*\*\n<ul class=\"contract\">")
        self.assertIn("<code>orders</code></a> <sub>table</sub> · ", text)
        self.assertIn(">CREATE TABLE</a>", text)
        self.assertIn("#diff-", text)

    def test_an_older_variant_renders_no_section(self) -> None:
        self.assertNotIn("Contract and data", body({}))

    def test_a_pr_with_no_changes_says_so(self) -> None:
        text = body({"contract_block": True}, diff="")
        self.assertIn("### **Contract and data**\nNo API or database changes\n", text)

    def test_no_migration_globs_marks_the_database_side_unchecked(self) -> None:
        with mock.patch.object(render, "MIGRATION_GLOBS", []):
            text = body({"contract_block": True})
        self.assertIn("No API changes. Database changes not checked", text)


if __name__ == "__main__":
    unittest.main()
