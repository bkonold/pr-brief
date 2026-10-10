"""Tests for the walkthrough's stops: how each resolves against the diff and the diagram box it lands on, and review.json's
shape. All data here is invented. Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render import Brief, resolve_stops, review_json  # noqa: E402

FILES = ["api/ItemRepo.java", "web/Page.tsx", "web/Other.tsx"]
DIFF_LINES = {
    "api/ItemRepo.java": [("R", 12, "List<Item> findLive(long ownerId)"), ("R", 20, "return null;"), ("L", 31, "return null;")],
    "web/Page.tsx": [("R", 5, "export function Page() {")],
}
NODE_FILES = {"Repo": ["api/ItemRepo.java"], "Screen": ["web/Page.tsx", "web/Other.tsx"], "Wire": ["web/Page.tsx"], "Db": []}
LINE = {"file": "api/ItemRepo.java", "line_text": "List<Item> findLive(long ownerId)", "title": "The live query",
        "why": "The list reads from it.", "node": "Repo"}


def resolve(raw, node_files=NODE_FILES) -> tuple[list[dict], list[str]]:
    return resolve_stops(raw, FILES, DIFF_LINES, node_files)


class ResolveStops(unittest.TestCase):
    def test_a_stop_whose_line_is_found_once_points_at_that_line(self) -> None:
        stops, notes = resolve([LINE])
        self.assertEqual(stops, [{"i": 1, "title": "The live query", "why": "The list reads from it.", "path": "api/ItemRepo.java",
                                  "side": "R", "line": 12, "node": "Repo"}])
        self.assertEqual(notes, ["1 stops, expected 3 to 10"])

    def test_a_removed_line_is_found_on_the_old_side(self) -> None:
        stops, _ = resolve([{**LINE, "line_text": "List<Item> findLive(long ownerId)"}, {**LINE, "line_text": "return null;"}])
        self.assertEqual([stop["line"] for stop in stops], [12, None])

    def test_a_stop_without_line_text_points_at_its_file(self) -> None:
        stops, notes = resolve([{"file": "web/Page.tsx", "title": "The screen", "why": "Where it starts.", "node": "Screen"}])
        self.assertEqual((stops[0]["side"], stops[0]["line"], stops[0]["node"]), (None, None, "Screen"))
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

    def test_stops_may_return_to_a_file_at_another_line(self) -> None:
        stops, _ = resolve([LINE, {"file": "web/Page.tsx", "title": "t", "why": "w", "node": "Screen"},
                            {**LINE, "title": "Back", "line_text": "return null;"}])
        self.assertEqual([(stop["path"], stop["line"]) for stop in stops],
                         [("api/ItemRepo.java", 12), ("web/Page.tsx", None), ("api/ItemRepo.java", None)])

    def test_a_stop_at_a_place_an_earlier_stop_has_is_dropped(self) -> None:
        stops, notes = resolve([LINE, {**LINE, "title": "Again"}])
        self.assertEqual([stop["title"] for stop in stops], ["The live query"])
        self.assertIn("stop 2: dropped, an earlier stop is already at api/ItemRepo.java:12", notes)

    def test_the_stops_are_numbered_after_the_drops(self) -> None:
        stops, _ = resolve([{**LINE, "file": "nope"}, LINE, {"file": "web/Page.tsx", "title": "t", "why": "w", "node": "Screen"}])
        self.assertEqual([stop["i"] for stop in stops], [1, 2])

    def test_a_missing_title_is_the_files_name_and_a_long_title_or_reason_is_noted(self) -> None:
        stops, notes = resolve([{"file": "web/Page.tsx", "why": "w", "node": "Screen"},
                                {**LINE, "title": "one two three four five six seven", "why": " ".join(["w"] * 21)}])
        self.assertEqual(stops[0]["title"], "Page.tsx")
        self.assertIn("stop 1: no title, using the file's name", notes)
        self.assertIn("stop 2: title is longer than 6 words", notes)
        self.assertIn("stop 2: reason is longer than 20 words", notes)

    def test_a_count_outside_three_to_ten_is_noted_and_inside_it_is_not(self) -> None:
        three = [LINE, {"file": "web/Page.tsx", "title": "t", "why": "w", "node": "Screen"},
                 {"file": "api/ItemRepo.java", "title": "t", "why": "w", "node": "Repo"}]
        self.assertEqual(resolve(three)[1], [])
        self.assertEqual(resolve(three[:2])[1], ["2 stops, expected 3 to 10"])

    def test_something_that_is_not_a_list_gives_no_stops_and_a_note(self) -> None:
        for raw in (None, "text", {"file": "web/Page.tsx"}):
            self.assertEqual(resolve(raw), ([], ["no walkthrough"]))


class StopNode(unittest.TestCase):
    def node_of(self, stop: dict, node_files=NODE_FILES) -> tuple[str | None, list[str]]:
        stops, notes = resolve([{"title": "t", "why": "w", **stop}], node_files)
        return stops[0]["node"], [note for note in notes if "stops, expected" not in note]

    def test_a_named_box_that_is_in_the_diagram_is_kept_without_a_note(self) -> None:
        self.assertEqual(self.node_of({"file": "web/Page.tsx", "node": "Wire"}), ("Wire", []))

    def test_a_missing_node_falls_back_to_the_first_box_holding_the_file(self) -> None:
        self.assertEqual(self.node_of({"file": "web/Page.tsx"}), ("Screen", ["stop 1: no node, using Screen"]))

    def test_a_node_that_is_not_in_the_diagram_falls_back_to_the_first_box_holding_the_file(self) -> None:
        self.assertEqual(self.node_of({"file": "web/Page.tsx", "node": "Nowhere"}),
                         ("Screen", ["stop 1: node 'Nowhere' is not a box in the diagram, using Screen"]))

    def test_a_context_box_holds_no_stop(self) -> None:
        self.assertEqual(self.node_of({"file": "web/Page.tsx", "node": "Db"}),
                         ("Screen", ["stop 1: node 'Db' covers no files, using Screen"]))

    def test_a_file_no_box_holds_gets_a_null_node_with_a_note(self) -> None:
        node_files = {"Repo": ["api/ItemRepo.java"]}
        self.assertEqual(self.node_of({"file": "web/Page.tsx", "node": "Repo"}, node_files),
                         ("Repo", []))
        self.assertEqual(self.node_of({"file": "web/Page.tsx", "node": "Nowhere"}, node_files),
                         (None, ["stop 1: node 'Nowhere' is not a box in the diagram, and no box holds web/Page.tsx"]))

    def test_quotes_and_backticks_around_the_id_are_ignored(self) -> None:
        self.assertEqual(self.node_of({"file": "web/Page.tsx", "node": "`Wire`"}), ("Wire", []))

    def test_without_a_diagram_every_node_is_null_and_nothing_is_noted(self) -> None:
        self.assertEqual(self.node_of({"file": "web/Page.tsx", "node": "Wire"}, {}), (None, []))


class ReviewJson(unittest.TestCase):
    RUN = {"repo": "acme/widgets", "pr": 7, "pr_head_sha": "a" * 40, "variant": "v"}

    def test_the_boxes_and_the_stops_are_listed_with_schema_4_and_no_chunks(self) -> None:
        stops = [{"i": 1, "title": "t", "why": "w", "path": "web/Page.tsx", "side": "R", "line": 5, "node": "Screen"}]
        nodes = {"Screen": {"title": "Screen", "files": ["web/Page.tsx"], "stops": [1]}}
        data = review_json(self.RUN, Brief("", (0, 0), nodes, stops, [], []), True)
        self.assertEqual(data, {"schema": 4, "repo": "acme/widgets", "pr": 7, "head_sha": "a" * 40, "variant": "v", "model": None,
                                "diagram": "diagram.svg", "nodes": nodes, "walkthrough": stops, "contract": [], "data": [],
                                "file_sets": {"contract": [], "data": []}})

    def test_a_run_with_no_diagram_has_no_diagram_key(self) -> None:
        self.assertNotIn("diagram", review_json(self.RUN, Brief("", (0, 0), {}, [], [], []), False))


if __name__ == "__main__":
    unittest.main()
