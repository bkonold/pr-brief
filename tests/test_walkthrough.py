"""Tests for the walkthrough's stops: how each resolves against the diff, the chunk it falls in and review.json's shape. All data here is invented. Run with `python3 -m unittest discover -s tests` from the tool's
folder."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from layout import LineSet  # noqa: E402
from render import Chunk, build_walkthrough, resolve_stops, review_json  # noqa: E402

FILES = ["api/ItemRepo.java", "web/Page.tsx", "web/Other.tsx"]
DIFF_LINES = {
    "api/ItemRepo.java": [("R", 12, "List<Item> findLive(long ownerId)"), ("R", 20, "return null;"), ("L", 31, "return null;")],
    "web/Page.tsx": [("R", 5, "export function Page() {")],
}
CHUNK_OF = {"api/ItemRepo.java": 2, "web/Page.tsx": 1}
LINE = {"file": "api/ItemRepo.java", "line_text": "List<Item> findLive(long ownerId)", "title": "The live query", "why": "The list reads from it."}


def resolve(raw) -> tuple[list[dict], list[str]]:
    return resolve_stops(raw, FILES, DIFF_LINES, CHUNK_OF)


class ResolveStops(unittest.TestCase):
    def test_a_stop_whose_line_is_found_once_points_at_that_line(self) -> None:
        stops, notes = resolve([LINE])
        self.assertEqual(stops, [{"i": 1, "title": "The live query", "why": "The list reads from it.", "path": "api/ItemRepo.java",
                                  "side": "R", "line": 12, "chunk": 2}])
        self.assertEqual(notes, ["1 stops, expected 3 to 10"])

    def test_a_removed_line_is_found_on_the_old_side(self) -> None:
        stops, _ = resolve([{**LINE, "line_text": "List<Item> findLive(long ownerId)"}, {**LINE, "line_text": "return null;"}])
        self.assertEqual([stop["line"] for stop in stops], [12, None])

    def test_a_stop_without_line_text_points_at_its_file(self) -> None:
        stops, notes = resolve([{"file": "web/Page.tsx", "title": "The screen", "why": "Where it starts."}])
        self.assertEqual((stops[0]["side"], stops[0]["line"], stops[0]["chunk"]), (None, None, 1))
        self.assertNotIn("line", " ".join(notes))

    def test_a_line_that_is_not_found_falls_back_to_the_file_with_a_note(self) -> None:
        stops, notes = resolve([{**LINE, "line_text": "nowhere"}])
        self.assertEqual((stops[0]["path"], stops[0]["side"], stops[0]["line"]), ("api/ItemRepo.java", None, None))
        self.assertIn("stop 1: line not found, pointing at the file", notes)

    def test_a_line_that_matches_twice_falls_back_to_the_file_with_a_note(self) -> None:
        stops, notes = resolve([{**LINE, "line_text": "return null;"}])
        self.assertEqual(stops[0]["line"], None)
        self.assertIn("stop 1: line matched 2 lines, pointing at the file", notes)

    def test_a_stop_in_a_file_outside_the_diff_is_dropped_with_a_note(self) -> None:
        stops, notes = resolve([{**LINE, "file": "other/File.java"}, LINE])
        self.assertEqual([stop["i"] for stop in stops], [1])
        self.assertEqual(stops[0]["path"], "api/ItemRepo.java")
        self.assertIn("stop 1: dropped, its file is not in the PR: other/File.java", notes)

    def test_a_file_of_the_diff_that_no_chunk_holds_has_no_chunk(self) -> None:
        stops, _ = resolve([{"file": "web/Other.tsx", "title": "t", "why": "w"}])
        self.assertIsNone(stops[0]["chunk"])

    def test_stops_may_return_to_a_file_at_another_line(self) -> None:
        stops, _ = resolve([LINE, {"file": "web/Page.tsx", "title": "t", "why": "w"}, {**LINE, "title": "Back", "line_text": "return null;"}])
        self.assertEqual([(stop["path"], stop["line"]) for stop in stops],
                         [("api/ItemRepo.java", 12), ("web/Page.tsx", None), ("api/ItemRepo.java", None)])

    def test_a_stop_at_a_place_an_earlier_stop_has_is_dropped(self) -> None:
        stops, notes = resolve([LINE, {**LINE, "title": "Again"}])
        self.assertEqual([stop["title"] for stop in stops], ["The live query"])
        self.assertIn("stop 2: dropped, an earlier stop is already at api/ItemRepo.java:12", notes)

    def test_the_stops_are_numbered_after_the_drops(self) -> None:
        stops, _ = resolve([{**LINE, "file": "nope"}, LINE, {"file": "web/Page.tsx", "title": "t", "why": "w"}])
        self.assertEqual([stop["i"] for stop in stops], [1, 2])

    def test_a_missing_title_is_the_files_name_and_a_long_title_or_reason_is_noted(self) -> None:
        stops, notes = resolve([{"file": "web/Page.tsx", "why": "w"}, {**LINE, "title": "one two three four five six seven", "why": " ".join(["w"] * 21)}])
        self.assertEqual(stops[0]["title"], "Page.tsx")
        self.assertIn("stop 1: no title, using the file's name", notes)
        self.assertIn("stop 2: title is longer than 6 words", notes)
        self.assertIn("stop 2: reason is longer than 20 words", notes)

    def test_a_count_outside_three_to_ten_is_noted_and_inside_it_is_not(self) -> None:
        three = [LINE, {"file": "web/Page.tsx", "title": "t", "why": "w"}, {"file": "api/ItemRepo.java", "title": "t", "why": "w"}]
        self.assertEqual(resolve(three)[1], [])
        self.assertEqual(resolve(three[:2])[1], ["2 stops, expected 3 to 10"])

    def test_something_that_is_not_a_list_gives_no_stops_and_a_note(self) -> None:
        for raw in (None, "text", {"file": "web/Page.tsx"}):
            self.assertEqual(resolve(raw), ([], ["no walkthrough"]))


class BuildWalkthrough(unittest.TestCase):
    def chunks(self) -> list[Chunk]:
        first = Chunk("Screen", "skim", "w", ["web/Page.tsx"], number=1)
        second = Chunk("Query", "verify", "w", ["api/ItemRepo.java"], number=2)
        third = Chunk("Other", "verify", "w", ["web/Other.tsx"], number=3)
        return [first, second, third]

    def test_a_verify_chunk_with_no_stop_adds_a_note_and_a_skim_chunk_does_not(self) -> None:
        notes: list[str] = []
        stops = build_walkthrough([LINE], self.chunks(), FILES, DIFF_LINES, notes)
        self.assertEqual(len(stops), 1)
        self.assertIn("chunk 'Other': a verify chunk with no walkthrough stop", notes)
        self.assertNotIn("chunk 'Query': a verify chunk with no walkthrough stop", notes)
        self.assertNotIn("chunk 'Screen': a verify chunk with no walkthrough stop", notes)


RUN = {"repo": "acme/widgets", "pr": 7, "pr_head_sha": "a" * 40, "variant": "v"}
PR = {"files": [{"path": "web/Page.tsx", "additions": 3, "deletions": 1}]}


class ReviewJson(unittest.TestCase):
    def chunks(self) -> list[Chunk]:
        return [Chunk("Screen", "read", "w", ["web/Page.tsx"], number=1)]

    def test_a_walkthrough_is_listed_before_the_chunks_and_a_chunk_has_no_start(self) -> None:
        stops = [{"i": 1, "title": "t", "why": "w", "path": "web/Page.tsx", "side": "R", "line": 5, "chunk": 1}]
        data = review_json(RUN, PR, self.chunks(), False, None, LineSet([], []), stops)
        self.assertEqual(data["walkthrough"], stops)
        self.assertNotIn("start", data["chunks"][0])
        self.assertLess(list(data).index("walkthrough"), list(data).index("chunks"))


if __name__ == "__main__":
    unittest.main()
