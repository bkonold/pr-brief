"""Tests for the chunks of a brief: how the answer's chunks resolve against the diff's hunks, how the Chunks section draws and
how review.json lists them. All data here is invented. Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import render  # noqa: E402
from hunks import Hunk, hunk_json, parse_hunks  # noqa: E402
from layout import chunks_section, hunk_target  # noqa: E402
from render import AnswerError, Brief, build_body, resolve_chunks, review_json  # noqa: E402

DIFF = """diff --git a/api/Item.java b/api/Item.java
--- a/api/Item.java
+++ b/api/Item.java
@@ -3,4 +3,5 @@ class Item {
   int a;
-  int b;
+  int b2;
+  int c;
   int d;
@@ -30,3 +31,3 @@ void run() {
   one();
-  two();
+  three();
   four();
diff --git a/api/ItemTest.java b/api/ItemTest.java
new file mode 100644
--- /dev/null
+++ b/api/ItemTest.java
@@ -0,0 +1,2 @@
+class ItemTest {
+}
diff --git a/api/Gone.java b/api/Gone.java
deleted file mode 100644
--- a/api/Gone.java
+++ /dev/null
@@ -1,2 +0,0 @@
-class Gone {
-}
diff --git a/api/Before.java b/api/After.java
similarity index 100%
rename from api/Before.java
rename to api/After.java
"""
HUNKS = parse_hunks(DIFF)
ALL = [hunk.id for hunk in HUNKS]


def chunk(title: str = "Title", hunks: list[str] | None = None, **rest) -> dict:
    return {"title": title, "summary": "What it does.", "hunks": hunks if hunks is not None else ["h01"], "depends_on": [],
            "risk": "low", **rest}


def resolve(raw, hunks: list[Hunk] = HUNKS) -> tuple[list[dict], list[str]]:
    return resolve_chunks(raw, hunks)


def without(notes: list[str], *fragments: str) -> list[str]:
    return [note for note in notes if not any(fragment in note for fragment in fragments)]


class ResolveChunks(unittest.TestCase):
    def test_a_chunk_resolves_to_its_fields_and_the_chunks_are_numbered_from_1(self) -> None:
        chunks, notes = resolve([chunk("Model", ["h01", "h02"], depends_on=[], risk="medium", risk_reason="Touches the key."),
                                 chunk("Tests", ["h03", "h04"], depends_on=[1])])
        self.assertEqual(chunks, [
            {"i": 1, "title": "Model", "summary": "What it does.", "risk": "medium", "risk_reason": "Touches the key.",
             "depends_on": [], "hunks": ["h01", "h02"]},
            {"i": 2, "title": "Tests", "summary": "What it does.", "risk": "low", "risk_reason": "", "depends_on": [1],
             "hunks": ["h03", "h04"]}])
        self.assertEqual(notes, [])

    def test_something_that_is_not_a_list_gives_no_chunks_and_a_note(self) -> None:
        for raw in (None, "text", {"title": "t", "hunks": ["h01"]}):
            self.assertEqual(resolve(raw), ([], ["no chunks"]))

    def test_an_unknown_hunk_is_dropped_with_a_note(self) -> None:
        chunks, notes = resolve([chunk(hunks=["h01", "h99", "nonsense"]), chunk("B", ["h02", "h03", "h04"])])
        self.assertEqual(chunks[0]["hunks"], ["h01"])
        self.assertEqual(notes, ["chunk 1: unknown hunk h99 dropped", "chunk 1: unknown hunk nonsense dropped"])

    def test_a_hunk_an_earlier_chunk_has_stays_there_and_is_dropped_from_the_later_one(self) -> None:
        chunks, notes = resolve([chunk("A", ["h01", "h02"]), chunk("B", ["h02", "h03", "h04"])])
        self.assertEqual([c["hunks"] for c in chunks], [["h01", "h02"], ["h03", "h04"]])
        self.assertEqual(notes, ["chunk 2: h02 dropped, it is already in chunk 1"])

    def test_a_hunk_listed_twice_in_one_chunk_is_kept_once(self) -> None:
        chunks, notes = resolve([chunk("A", ["h01", "h01", "h02", "h03", "h04"])])
        self.assertEqual(chunks[0]["hunks"], ["h01", "h02", "h03", "h04"])
        self.assertEqual(notes, ["chunk 1: h01 dropped, it is listed twice"])

    def test_a_hunk_id_in_brackets_or_capitals_is_read(self) -> None:
        chunks, notes = resolve([chunk(hunks=["[h01]", "H02", " h03 ", "`h04`"])])
        self.assertEqual((chunks[0]["hunks"], notes), (["h01", "h02", "h03", "h04"], []))

    def test_a_chunk_left_with_no_hunk_is_dropped_and_the_rest_are_renumbered(self) -> None:
        chunks, notes = resolve([chunk("A", ["h01", "h02"]), chunk("Empty", ["h99"]), chunk("C", ["h03", "h04"])])
        self.assertEqual([(c["i"], c["title"]) for c in chunks], [(1, "A"), (2, "C")])
        self.assertIn("chunk 2: dropped, no hunks left", notes)

    def test_a_chunk_with_no_hunks_key_or_one_that_is_not_an_object_is_dropped(self) -> None:
        chunks, notes = resolve([{"title": "t"}, "text", chunk("A", ALL)])
        self.assertEqual([c["title"] for c in chunks], ["A"])
        self.assertIn("chunk 1: dropped, no hunks left", notes)
        self.assertIn("chunk 2: dropped, it is not an object", notes)

    def test_a_missing_title_is_numbered_by_its_place_after_the_drops(self) -> None:
        chunks, notes = resolve([chunk("Gone", ["h99"]), chunk("", ["h01", "h02"]), {"summary": "s", "hunks": ["h03", "h04"]}])
        self.assertEqual([c["title"] for c in chunks], ["Chunk 1", "Chunk 2"])
        self.assertIn("chunk 2: no title, using Chunk 1", notes)
        self.assertIn("chunk 3: no title, using Chunk 2", notes)

    def test_a_title_over_8_words_is_noted_and_kept(self) -> None:
        chunks, notes = resolve([chunk("one two three four five six seven eight nine", ALL)])
        self.assertEqual(chunks[0]["title"], "one two three four five six seven eight nine")
        self.assertEqual(notes, ["chunk 1: title is longer than 8 words"])
        self.assertEqual(resolve([chunk("one two three four five six seven eight", ALL)])[1], [])

    def test_a_missing_summary_is_noted(self) -> None:
        chunks, notes = resolve([{**chunk(hunks=ALL), "summary": ""}])
        self.assertEqual((chunks[0]["summary"], notes), ("", ["chunk 1: no summary"]))

    def test_a_risk_that_is_not_low_medium_or_high_is_low_with_a_note(self) -> None:
        chunks, notes = resolve([chunk("A", ["h01"], risk="severe"), chunk("B", ["h02"], risk=None), chunk("C", ["h03", "h04"], risk="High")])
        self.assertEqual([c["risk"] for c in chunks], ["low", "low", "high"])
        self.assertEqual(notes, ["chunk 1: risk 'severe' is not low, medium or high, using low", "chunk 2: no risk, using low"])

    def test_the_risk_reason_is_one_line_and_empty_when_there_is_none(self) -> None:
        chunks, _ = resolve([chunk("A", ["h01"], risk_reason="  A\n  reason. "), chunk("B", ["h02", "h03", "h04"])])
        self.assertEqual([c["risk_reason"] for c in chunks], ["A reason.", ""])

    def test_depends_on_entries_that_are_not_whole_numbers_are_dropped(self) -> None:
        chunks, notes = resolve([chunk("A", ["h01"]), chunk("B", ["h02", "h03", "h04"], depends_on=["1", 1.0, None, True, 1])])
        self.assertEqual(chunks[1]["depends_on"], [1])
        self.assertEqual(without(notes, "2 chunks"), [
            "chunk 2: depends_on '1' dropped, it is not a chunk number", "chunk 2: depends_on 1.0 dropped, it is not a chunk number",
            "chunk 2: depends_on None dropped, it is not a chunk number", "chunk 2: depends_on True dropped, it is not a chunk number"])

    def test_depends_on_that_points_at_itself_forward_or_past_the_end_is_dropped(self) -> None:
        chunks, notes = resolve([chunk("A", ["h01"], depends_on=[1, 2, 9, 0]), chunk("B", ["h02", "h03", "h04"], depends_on=[1, 2, 3])])
        self.assertEqual([c["depends_on"] for c in chunks], [[], [1]])
        self.assertEqual(without(notes, "2 chunks"), [
            "chunk 1: depends_on 1 dropped, a chunk cannot depend on itself", "chunk 1: depends_on 2 dropped, it is a later chunk",
            "chunk 1: depends_on 9 dropped, there is no chunk 9", "chunk 1: depends_on 0 dropped, there is no chunk 0",
            "chunk 2: depends_on 2 dropped, a chunk cannot depend on itself", "chunk 2: depends_on 3 dropped, there is no chunk 3"])

    def test_depends_on_is_renumbered_after_a_chunk_is_dropped_and_a_dependency_on_a_dropped_chunk_is_dropped(self) -> None:
        chunks, notes = resolve([chunk("A", ["h01"]), chunk("Gone", ["h99"]), chunk("C", ["h02"], depends_on=[1, 2]),
                                 chunk("D", ["h03", "h04"], depends_on=[3, 1])])
        self.assertEqual([(c["i"], c["depends_on"]) for c in chunks], [(1, []), (2, [1]), (3, [1, 2])])
        self.assertIn("chunk 3: depends_on 2 dropped, that chunk was dropped", notes)

    def test_depends_on_that_is_not_a_list_is_empty_with_a_note_and_duplicates_collapse(self) -> None:
        chunks, notes = resolve([chunk("A", ["h01"]), chunk("B", ["h02"], depends_on=1), chunk("C", ["h03", "h04"], depends_on=[2, 1, 2])])
        self.assertEqual([c["depends_on"] for c in chunks], [[], [], [1, 2]])
        self.assertIn("chunk 2: depends_on is not a list", notes)

    def test_hunks_no_chunk_has_are_gathered_into_a_final_unassigned_chunk(self) -> None:
        chunks, notes = resolve([chunk("A", ["h01", "h03"])])
        self.assertEqual(chunks[-1], {"i": 2, "title": "Unassigned", "summary": "Hunks the model left out.", "risk": "low",
                                      "risk_reason": "", "depends_on": [], "hunks": ["h02", "h04"]})
        self.assertIn("unassigned hunks gathered into the last chunk: h02, h04", notes)

    def test_an_empty_list_leaves_every_hunk_unassigned(self) -> None:
        chunks, notes = resolve([])
        self.assertEqual([(c["title"], c["hunks"]) for c in chunks], [("Unassigned", ALL)])
        self.assertIn("unassigned hunks gathered into the last chunk: h01, h02, h03, h04", notes)

    def test_every_hunk_assigned_gives_no_unassigned_chunk(self) -> None:
        chunks, _ = resolve([chunk("A", ["h01"]), chunk("B", ["h02", "h03", "h04"])])
        self.assertEqual([c["title"] for c in chunks], ["A", "B"])

    def test_a_count_outside_1_to_7_is_noted_and_inside_it_is_not(self) -> None:
        many = [chunk(f"C{n}", [f"h{n:02d}"]) for n in range(1, 5)]
        self.assertEqual(resolve(many)[1], [])
        eight = parse_hunks("diff --git a/f b/f\n" + "".join(f"@@ -{n} +{n} @@\n-a\n+b\n" for n in range(1, 9)))
        raw = [chunk(f"C{n}", [f"h{n:02d}"]) for n in range(1, 9)]
        self.assertEqual(resolve(raw, eight)[1], ["8 chunks, expected 1 to 7"])
        self.assertEqual(resolve([], [])[1], ["0 chunks, expected 1 to 7"])


class HunkTarget(unittest.TestCase):
    def test_a_hunk_is_shown_at_its_new_lines_and_a_deleted_files_hunk_at_its_old_lines(self) -> None:
        self.assertEqual([hunk_target(hunk) for hunk in HUNKS], [("R", 3, 7), ("R", 31, 33), ("R", 1, 2), ("L", 1, 2)])


def link_of(hunk: Hunk) -> str:
    side, start, _ = hunk_target(hunk)
    return f"https://x/{hunk.path}#{side}{start}"


class ChunksSection(unittest.TestCase):
    BY_ID = {hunk.id: hunk for hunk in HUNKS}
    CHUNKS = [
        {"i": 1, "title": "The <item> model", "summary": "Adds a field.", "risk": "medium", "risk_reason": "Key changes.",
         "depends_on": [], "hunks": ["h01", "h02"]},
        {"i": 2, "title": "Tests", "summary": "Covers it.", "risk": "low", "risk_reason": "", "depends_on": [1], "hunks": ["h03", "h04"]}]

    def test_it_draws_a_count_then_one_details_per_chunk_with_a_link_per_hunk(self) -> None:
        self.assertEqual(chunks_section(self.CHUNKS, self.BY_ID, link_of), "\n".join([
            "### Chunks",
            "",
            "2 chunks, in review order.",
            "",
            "<details>",
            "<summary><b>1. The &lt;item&gt; model</b> · medium · <i>Key changes.</i></summary>",
            "",
            "Adds a field.",
            "",
            "- [`api/Item.java:3–7`](https://x/api/Item.java#R3) (h01)",
            "- [`api/Item.java:31–33`](https://x/api/Item.java#R31) (h02)",
            "",
            "</details>",
            "",
            "<details>",
            "<summary><b>2. Tests</b> · low</summary>",
            "",
            "Covers it.",
            "",
            "- [`api/ItemTest.java:1–2`](https://x/api/ItemTest.java#R1) (h03)",
            "- [`api/Gone.java:1–2`](https://x/api/Gone.java#L1) (h04)",
            "",
            "</details>"]))

    def test_one_chunk_is_counted_in_the_singular(self) -> None:
        self.assertIn("\n1 chunk, in review order.\n", chunks_section(self.CHUNKS[:1], self.BY_ID, link_of))

    def test_files_with_no_hunk_are_listed_after_the_chunks(self) -> None:
        found = chunks_section(self.CHUNKS, self.BY_ID, link_of, [("api/After.java", "https://x/after"), ("img/logo.png", "https://x/logo")])
        self.assertTrue(found.endswith("</details>\n\nAlso in this PR, with no hunks to assign:\n\n"
                                       "- [api/After.java](https://x/after)\n- [img/logo.png](https://x/logo)"))
        self.assertNotIn("no hunks to assign", chunks_section(self.CHUNKS, self.BY_ID, link_of, []))

    def test_a_chunk_with_no_summary_has_no_blank_sentence(self) -> None:
        found = chunks_section([{**self.CHUNKS[0], "summary": ""}], self.BY_ID, link_of)
        self.assertIn("</summary>\n\n- [", found)

    def test_no_chunk_gives_no_section(self) -> None:
        self.assertEqual(chunks_section([], self.BY_ID, link_of, [("a", "u")]), "")


RUN = {"repo": "acme/shop", "pr": 7, "with_body": False, "variant": "brief", "pr_head_sha": "abc"}
PATHS = ["api/Item.java", "api/ItemTest.java", "api/Gone.java", "api/After.java"]
PR = {"title": "T", "body": "", "files": [{"path": p, "additions": 2, "deletions": 1, "changeType": "MODIFIED"} for p in PATHS]}
STOPS = [{"file": path, "title": "t", "why": "w"} for path in PATHS[:3]]
ANSWER = {"description": "does things", "walkthrough": STOPS,
          "chunks": [chunk("The model", ["h01", "h02"], risk="medium", risk_reason="Key."), chunk("Tests", ["h03", "h04"], depends_on=[1])]}


class ChunksInTheBody(unittest.TestCase):
    def build(self, data: dict, diff: str = DIFF) -> tuple[Brief, list[str]]:
        notes: list[str] = []
        return build_body(RUN, PR, data, render.diff_lines_by_path(diff), notes, None, diff), notes

    def test_the_chunks_section_comes_after_the_data_section_and_before_the_closing_rule(self) -> None:
        brief, _ = self.build(ANSWER)
        self.assertLess(brief.body.index("### Data"), brief.body.index("### Chunks"))
        self.assertLess(brief.body.index("### Chunks"), brief.body.index("Also in this PR, with no hunks to assign:"))
        self.assertTrue(brief.body.endswith(")\n\n\n___\n\n"))
        self.assertIn("2 chunks, in review order.", brief.body)
        self.assertEqual([chunk["title"] for chunk in brief.chunks or []], ["The model", "Tests"])

    def test_the_hunk_links_point_at_the_hunks_lines_in_the_pr(self) -> None:
        brief, _ = self.build(ANSWER)
        self.assertRegex(brief.body, r"- \[`api/Item\.java:3–7`\]\(https://github\.com/acme/shop/pull/7/changes#diff-[0-9a-f]{64}R3\) \(h01\)")
        self.assertRegex(brief.body, r"- \[`api/Gone\.java:1–2`\]\(https://github\.com/acme/shop/pull/7/changes#diff-[0-9a-f]{64}L1\) \(h04\)")

    def test_a_missing_diagram_is_noted_as_it_is_without_chunks(self) -> None:
        brief, notes = self.build(ANSWER)
        self.assertEqual(notes, ["no changes_diagram"])
        self.assertEqual(([stop["path"] for stop in brief.stops], brief.nodes), (PATHS[:3], {}))
        self.assertNotIn("Diagram Walkthrough", brief.body)

    def test_a_walkthrough_that_is_present_but_broken_is_still_noted(self) -> None:
        with self.assertRaises(AnswerError) as caught:
            self.build({**ANSWER, "walkthrough": "text", "changes_diagram": ""})
        self.assertIn("- no walkthrough", str(caught.exception))

    def test_the_resolution_notes_are_kept(self) -> None:
        _, notes = self.build({**ANSWER, "chunks": [chunk("A", ["h01", "h99"])]})
        self.assertEqual(notes, ["no changes_diagram", "chunk 1: unknown hunk h99 dropped",
                                 "unassigned hunks gathered into the last chunk: h02, h03, h04"])

    def test_an_answer_with_no_chunks_key_has_no_chunks_section(self) -> None:
        data = {"description": "d", "walkthrough": [{"file": "api/Item.java", "title": "t", "why": "w"}]}
        brief, notes = self.build(data)
        self.assertNotIn("### Chunks", brief.body)
        self.assertIsNone(brief.chunks)
        self.assertEqual(notes, ["no changes_diagram", "1 stops, expected 3 to 10"])

    def test_an_answer_with_no_stops_is_an_error_whatever_its_chunks(self) -> None:
        for data in ({"description": "d"}, {"description": "d", "chunks": "text"}, {"description": "d", "chunks": ANSWER["chunks"]}):
            with self.assertRaises(AnswerError) as caught:
                self.build(data)
            self.assertIn("The walkthrough has no stop left", str(caught.exception))
        with self.assertRaises(AnswerError) as caught:
            self.build({"description": "d", "chunks": "text"})
        self.assertIn("- no chunks", str(caught.exception))

    def test_stops_are_enough_without_chunks(self) -> None:
        self.assertEqual(self.build({"description": "d", "walkthrough": STOPS, "chunks": "text"})[0].chunks, [])


class ReviewJsonChunks(unittest.TestCase):
    RUN = {"repo": "acme/shop", "pr": 7, "pr_head_sha": "a" * 40, "variant": "brief"}

    def test_the_chunks_are_listed_with_their_hunks_as_objects(self) -> None:
        chunks, _ = resolve([chunk("A", ["h01", "h02"], risk="high", risk_reason="Why."), chunk("B", ["h03", "h04"], depends_on=[1])])
        data = review_json(self.RUN, Brief("", (0, 0), {}, [], [], [], chunks=chunks, hunks=HUNKS), False)
        self.assertEqual(data["schema"], 4)
        self.assertEqual(data["chunks"], [
            {"i": 1, "title": "A", "summary": "What it does.", "risk": "high", "risk_reason": "Why.", "depends_on": [],
             "hunks": [hunk_json(HUNKS[0]), hunk_json(HUNKS[1])]},
            {"i": 2, "title": "B", "summary": "What it does.", "risk": "low", "risk_reason": "", "depends_on": [1],
             "hunks": [hunk_json(HUNKS[2]), hunk_json(HUNKS[3])]}])
        self.assertEqual(data["chunks"][0]["hunks"][0], {"id": "h01", "path": "api/Item.java", "change": "modified",
                                                        "old": [3, 4], "new": [3, 5]})

    def test_a_brief_with_no_chunks_has_no_chunks_key_and_an_empty_list_is_kept(self) -> None:
        self.assertNotIn("chunks", review_json(self.RUN, Brief("", (0, 0), {}, [], [], []), False))
        self.assertEqual(review_json(self.RUN, Brief("", (0, 0), {}, [], [], [], chunks=[]), False)["chunks"], [])


if __name__ == "__main__":
    unittest.main()
