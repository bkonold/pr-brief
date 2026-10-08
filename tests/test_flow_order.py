"""Tests for flow-ordered chunks and the step field. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render import build_body, build_chunks, clean_step  # noqa: E402

FLOORS = {"floor": [{"name": "schema file", "level": "verify", "globs": ["db/*.sql"]}]}
PATHS = ["src/ui.js", "src/api.js", "db/V1__t.sql"]
COUNTS = {path.lower(): (1, 0) for path in PATHS}


def raw(name: str, review: str, path: str, step: str | None = None) -> dict:
    return {"name": name, "review": review, "why": "w", "files": [path], **({"step": step} if step else {})}


FLOW = [raw("Screen", "skim", "src/ui.js", "UI"), raw("Endpoint", "read", "src/api.js", "API"),
        raw("Table", "skim", "db/V1__t.sql", "Database")]


class FlowOrder(unittest.TestCase):
    def test_flow_order_keeps_the_models_order_even_after_a_floor_raises_a_chunk(self) -> None:
        chunks = build_chunks(FLOW, COUNTS, PATHS, FLOORS, [], {}, flow_order=True)
        self.assertEqual([(c.number, c.name, c.review) for c in chunks],
                         [(1, "Screen", "skim"), (2, "Endpoint", "read"), (3, "Table", "verify")])

    def test_risk_order_still_sorts_by_level(self) -> None:
        chunks = build_chunks(FLOW, COUNTS, PATHS, FLOORS, [], {})
        self.assertEqual([c.name for c in chunks], ["Table", "Endpoint", "Screen"])

    def test_flow_order_keeps_unchunked_last(self) -> None:
        chunks = build_chunks(FLOW[:2], COUNTS, PATHS, FLOORS, [], {}, flow_order=True)
        self.assertEqual([c.name for c in chunks], ["Screen", "Endpoint", "Unchunked"])

    def test_the_step_is_kept_when_it_is_one_or_two_words(self) -> None:
        chunks = build_chunks(FLOW, COUNTS, PATHS, FLOORS, [], {}, flow_order=True)
        self.assertEqual([c.step for c in chunks], ["UI", "API", "Database"])

    def test_a_long_or_blank_step_is_dropped_with_a_note(self) -> None:
        notes: list[str] = []
        self.assertIsNone(clean_step("the whole backend layer", "A", notes))
        self.assertIsNone(clean_step("  ", "B", notes))
        self.assertEqual(clean_step(" Data  model. ", "C", notes), "Data model")
        self.assertEqual(len(notes), 2)


RUN = {"repo": "acme/shop", "pr": 7, "with_body": False, "variant": "v", "pr_head_sha": "abc",
       "context": {"sections": {"contract": 0}, "dropped": {}}}
PR = {"title": "T", "body": "", "files": [
    {"path": path, "additions": 1, "deletions": 0, "changeType": "ADDED"} for path in PATHS]}
DIFF = ("diff --git a/db/V1__t.sql b/db/V1__t.sql\n--- /dev/null\n+++ b/db/V1__t.sql\n@@ -0,0 +1,2 @@\n"
        "+-- new\n+CREATE TABLE orders (id uuid);\n")
DATA = {"type": "Enhancement", "description": "does things", "chunks": FLOW}


def body(cfg: dict, diff: str = DIFF, contract: dict | None = None) -> str:
    notes: list[str] = []
    text, _, _, _, _ = build_body(RUN, PR, DATA, {"files": "chunks", **cfg}, FLOORS, {}, notes, contract, diff)
    return text


class FlowNumbering(unittest.TestCase):
    def test_flow_numbering_labels_each_box_with_its_chunks_flow_step(self) -> None:
        diagram = 'flowchart TD\n  a["Open screen"] --> b["Call endpoint"]\n  b --> c["Write row"]:::save'
        data = {**DATA, "changes_diagram": f"```mermaid\n{diagram}\n```",
                "chunks": [{**FLOW[0], "nodes": ["a"]}, {**FLOW[1], "nodes": ["b"]}, {**FLOW[2], "nodes": ["c"]}]}
        text, _, _, _, _ = build_body(RUN, PR, data, {"files": "chunks", "chunk_order": "flow", "numbering": "flow", "diagram": "force_td"},
                                   FLOORS, {}, [], None, "")
        self.assertIn('a["1 · Open screen"]', text)
        self.assertIn('c["3 · Write row"]', text)


if __name__ == "__main__":
    unittest.main()
