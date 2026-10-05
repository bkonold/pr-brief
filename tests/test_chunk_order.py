"""Tests for the order of the review list after the floors apply. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render import build_chunks  # noqa: E402

FLOORS = {"floor": [{"name": "schema file", "level": "read carefully", "globs": ["**/schema.json"]}]}
PATHS = ["src/a.js", "src/b.js", "src/c.js", "src/d.js", "api/schema.json"]
COUNTS = {path.lower(): (1, 0) for path in PATHS}


def raw(name: str, review: str, path: str) -> dict:
    return {"name": name, "review": review, "why": "w", "files": [path]}


def build(chunks: list[dict], paths: list[str] = PATHS) -> list:
    return build_chunks(chunks, COUNTS, paths, FLOORS, [], {})


class ChunkOrder(unittest.TestCase):
    def test_a_chunk_the_floor_raises_moves_above_lower_levels(self) -> None:
        chunks = build([raw("A", "read", "src/a.js"), raw("B", "skim", "src/b.js"), raw("C", "read", "api/schema.json")],
                       ["src/a.js", "src/b.js", "api/schema.json"])
        self.assertEqual([(c.name, c.review) for c in chunks],
                         [("C", "read carefully"), ("A", "read"), ("B", "skim")])
        self.assertEqual(chunks[0].raised_by, ["schema file"])

    def test_the_models_order_holds_within_a_level(self) -> None:
        chunks = build([raw("A", "skim", "src/a.js"), raw("B", "read", "src/b.js"), raw("C", "skim", "src/c.js"),
                        raw("D", "read", "src/d.js")], PATHS[:4])
        self.assertEqual([c.name for c in chunks], ["B", "D", "A", "C"])

    def test_the_numbers_are_sequential_after_the_sort(self) -> None:
        chunks = build([raw("A", "skim", "src/a.js"), raw("B", "read", "src/b.js"), raw("C", "skim", "api/schema.json")],
                       ["src/a.js", "src/b.js", "api/schema.json"])
        self.assertEqual([(c.number, c.name) for c in chunks], [(1, "C"), (2, "B"), (3, "A")])

    def test_files_the_model_left_out_stay_last(self) -> None:
        chunks = build([raw("A", "skim", "src/a.js")], ["src/a.js", "src/b.js"])
        self.assertEqual([c.name for c in chunks], ["A", "Unchunked"])


if __name__ == "__main__":
    unittest.main()
