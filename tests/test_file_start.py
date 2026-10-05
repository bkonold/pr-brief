"""Tests for a chunk's start: a line when its quoted text is found exactly once, else (with the file_start option)
the file alone. All data here is invented. Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render import Chunk, resolve_start, review_json, start_cell  # noqa: E402

FILES = ["api/ItemRepo.java", "web/Page.tsx"]
DIFF_LINES = {
    "api/ItemRepo.java": [("R", 12, "List<Item> findLive(long ownerId)"), ("R", 20, "return null;"), ("L", 31, "return null;")],
}
LINE = {"file": "api/ItemRepo.java", "line_text": "List<Item> findLive(long ownerId)", "why": "The query the list reads from."}


def resolve(raw, file_start: bool = True) -> tuple[dict | None, list[str]]:
    notes: list[str] = []
    return resolve_start(raw, "Items", FILES, DIFF_LINES, notes, file_start), notes


class ResolveStart(unittest.TestCase):
    def test_a_start_with_no_line_text_is_a_file_level_start(self) -> None:
        start, notes = resolve({"file": "web/Page.tsx", "why": "Where the screen is built."})
        self.assertEqual(start, {"path": "web/Page.tsx", "side": None, "line": None, "why": "Where the screen is built."})
        self.assertEqual(notes, [])

    def test_a_blank_line_text_is_a_file_level_start(self) -> None:
        start, notes = resolve({"file": "web/Page.tsx", "line_text": "  ", "why": "w"})
        self.assertEqual(start, {"path": "web/Page.tsx", "side": None, "line": None, "why": "w"})
        self.assertEqual(notes, [])

    def test_a_line_that_resolves_is_the_same_with_or_without_the_option(self) -> None:
        expected = {"path": "api/ItemRepo.java", "side": "R", "line": 12, "text": "List<Item> findLive(long ownerId)",
                    "why": "The query the list reads from."}
        for file_start in (True, False):
            self.assertEqual(resolve(LINE, file_start), (expected, []))

    def test_a_line_that_is_not_found_becomes_a_file_start_with_a_note(self) -> None:
        start, notes = resolve({**LINE, "line_text": "nowhere"})
        self.assertEqual(start, {"path": "api/ItemRepo.java", "side": None, "line": None, "why": "The query the list reads from."})
        self.assertEqual(notes, ["chunk 'Items': start line not found, pointing at the file"])

    def test_a_line_that_matches_twice_becomes_a_file_start_with_a_note(self) -> None:
        start, notes = resolve({**LINE, "line_text": "return null;"})
        self.assertEqual((start["path"], start["line"]), ("api/ItemRepo.java", None))
        self.assertEqual(notes, ["chunk 'Items': start line matched 2 lines, pointing at the file"])

    def test_without_the_option_an_unresolved_line_drops_the_start(self) -> None:
        self.assertEqual(resolve({**LINE, "line_text": "nowhere"}, False), (None, ["chunk 'Items': start line not found"]))
        self.assertEqual(resolve({"file": "web/Page.tsx", "why": "w"}, False), (None, ["chunk 'Items': start line not found"]))

    def test_a_file_that_is_not_one_of_the_chunks_files_drops_the_start(self) -> None:
        start, notes = resolve({"file": "other/File.java", "why": "w"})
        self.assertIsNone(start)
        self.assertEqual(notes, ["chunk 'Items': start file is not one of the chunk's files: other/File.java"])

    def test_a_file_start_without_a_file_drops_the_start(self) -> None:
        self.assertEqual(resolve({"why": "w"}), (None, ["chunk 'Items': start line not found"]))

    def test_a_missing_or_long_reason_leaves_it_out_of_a_file_start(self) -> None:
        start, notes = resolve({"file": "web/Page.tsx"})
        self.assertEqual(start, {"path": "web/Page.tsx", "side": None, "line": None})
        start, notes = resolve({"file": "web/Page.tsx", "why": " ".join(["word"] * 16)})
        self.assertEqual(start, {"path": "web/Page.tsx", "side": None, "line": None})
        self.assertEqual(notes, ["chunk 'Items': start reason is longer than 15 words, dropped"])


class FileStartOutput(unittest.TestCase):
    def chunk(self, start: dict) -> Chunk:
        return Chunk("Items", "read", "w", FILES, number=1, start=start)

    def test_review_json_carries_null_side_and_line(self) -> None:
        run = {"repo": "acme/widgets", "pr": "7", "pr_head_sha": "abc", "variant": "v"}
        pr = {"files": [{"path": path, "additions": 1, "deletions": 0} for path in FILES]}
        start = {"path": "web/Page.tsx", "side": None, "line": None, "why": "w"}
        chunks = review_json(run, pr, [self.chunk(start)], False, None)["chunks"]
        self.assertEqual(chunks[0]["start"], start)

    def test_the_review_order_cell_links_the_file_and_shows_the_reason_without_a_line(self) -> None:
        cell = start_cell(self.chunk({"path": "web/Page.tsx", "side": None, "line": None, "why": "Where <it> starts."}),
                          "acme/widgets", "7")
        self.assertRegex(cell, r'^<br><sub>start <a href="https://github.com/acme/widgets/pull/7/files#diff-[0-9a-f]{64}" '
                               r'title="web/Page.tsx">Page.tsx</a></sub><br><em>Where &lt;it&gt; starts.</em>$')

    def test_the_review_order_cell_of_a_file_start_without_a_reason_is_just_the_link(self) -> None:
        cell = start_cell(self.chunk({"path": "web/Page.tsx", "side": None, "line": None}), "acme/widgets", "7")
        self.assertTrue(cell.endswith("Page.tsx</a></sub>"))

    def test_the_review_order_cell_of_a_line_start_is_unchanged(self) -> None:
        cell = start_cell(self.chunk({"path": "api/ItemRepo.java", "side": "R", "line": 12, "text": "a < b"}), "acme/widgets", "7")
        self.assertRegex(cell, r'ItemRepo\.java:12</a></sub><br><code>a &lt; b</code>$')


if __name__ == "__main__":
    unittest.main()
