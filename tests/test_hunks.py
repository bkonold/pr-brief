"""Tests for the hunk parser, the tags that name hunks in a prompt, and the pins that tie hunks together. All data here is
invented. Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import context_pack  # noqa: E402
import render  # noqa: E402
from contract_fixtures import SPEC, contract_of, document, make_diff, operation  # noqa: E402
from contract_lines import Line, Source, contract_lines  # noqa: E402
from data_lines import data_lines  # noqa: E402
from diff_lines import file_diff_lines  # noqa: E402
from hunks import Hunk, hunk_at, hunk_json, parse_hunks, pins, pins_markdown, tag_headers  # noqa: E402

TWO_HUNKS = """diff --git a/src/Widget.java b/src/Widget.java
index 1111111..2222222 100644
--- a/src/Widget.java
+++ b/src/Widget.java
@@ -3,4 +3,5 @@ public class Widget {
   int a;
-  int b;
+  int b2;
+  int c;
   int d;
@@ -20,3 +21,3 @@ public void run() {
   one();
-  two();
+  three();
   four();
"""
ADDED = """diff --git a/src/Gadget.java b/src/Gadget.java
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/src/Gadget.java
@@ -0,0 +1,2 @@
+class Gadget {
+}
"""
DELETED = """diff --git a/src/Old.java b/src/Old.java
deleted file mode 100644
index 4444444..0000000
--- a/src/Old.java
+++ /dev/null
@@ -1,2 +0,0 @@
-class Old {
-}
"""
RENAMED = """diff --git a/src/Before.java b/src/After.java
similarity index 100%
rename from src/Before.java
rename to src/After.java
"""
RENAMED_EDITED = """diff --git a/src/Before.java b/src/After.java
similarity index 90%
rename from src/Before.java
rename to src/After.java
--- a/src/Before.java
+++ b/src/After.java
@@ -1 +1 @@
-a
+b
"""
BINARY = """diff --git a/img/logo.png b/img/logo.png
index 5555555..6666666 100644
Binary files a/img/logo.png and b/img/logo.png differ
"""
NO_NEWLINE = """diff --git a/notes.txt b/notes.txt
--- a/notes.txt
+++ b/notes.txt
@@ -1 +1 @@
-old
\\ No newline at end of file
+new
\\ No newline at end of file
"""
NO_COUNTS = """diff --git a/one.txt b/one.txt
--- a/one.txt
+++ b/one.txt
@@ -7 +7 @@
-a
+b
"""
EVERYTHING = TWO_HUNKS + ADDED + DELETED + RENAMED + BINARY + NO_NEWLINE + NO_COUNTS


class ParseHunks(unittest.TestCase):
    def test_a_file_with_several_hunks_gives_one_hunk_each_numbered_in_order(self) -> None:
        found = parse_hunks(TWO_HUNKS)
        self.assertEqual([(h.id, h.path, h.header, h.old_start, h.old_count, h.new_start, h.new_count, h.change) for h in found],
                         [("h01", "src/Widget.java", "@@ -3,4 +3,5 @@ public class Widget {", 3, 4, 3, 5, "modified"),
                          ("h02", "src/Widget.java", "@@ -20,3 +21,3 @@ public void run() {", 20, 3, 21, 3, "modified")])
        self.assertEqual(found[0].lines, ["   int a;", "-  int b;", "+  int b2;", "+  int c;", "   int d;"])
        self.assertEqual(found[1].lines, ["   one();", "-  two();", "+  three();", "   four();"])

    def test_the_ids_run_across_files_in_the_order_of_the_diff(self) -> None:
        self.assertEqual([(h.id, h.path) for h in parse_hunks(EVERYTHING)],
                         [("h01", "src/Widget.java"), ("h02", "src/Widget.java"), ("h03", "src/Gadget.java"),
                          ("h04", "src/Old.java"), ("h05", "notes.txt"), ("h06", "one.txt")])

    def test_ids_have_two_digits_and_more_when_there_are_more_than_99_hunks(self) -> None:
        diff = "diff --git a/f b/f\n" + "".join(f"@@ -{n} +{n} @@\n-a\n+b\n" for n in range(1, 102))
        found = parse_hunks(diff)
        self.assertEqual([found[0].id, found[8].id, found[98].id, found[99].id, found[100].id], ["h01", "h09", "h99", "h100", "h101"])

    def test_a_new_file_is_added_and_its_range_starts_at_zero(self) -> None:
        (hunk,) = parse_hunks(ADDED)
        self.assertEqual((hunk.change, hunk.path, hunk.old_start, hunk.old_count, hunk.new_start, hunk.new_count),
                         ("added", "src/Gadget.java", 0, 0, 1, 2))

    def test_a_deleted_file_is_deleted_and_keeps_its_old_path(self) -> None:
        (hunk,) = parse_hunks(DELETED)
        self.assertEqual((hunk.change, hunk.path, hunk.old_start, hunk.old_count, hunk.new_start, hunk.new_count),
                         ("deleted", "src/Old.java", 1, 2, 0, 0))

    def test_a_renamed_file_that_is_edited_is_renamed_and_has_its_new_path(self) -> None:
        (hunk,) = parse_hunks(RENAMED_EDITED)
        self.assertEqual((hunk.change, hunk.path), ("renamed", "src/After.java"))

    def test_a_rename_without_edits_and_a_binary_file_have_no_hunk(self) -> None:
        self.assertEqual(parse_hunks(RENAMED + BINARY), [])

    def test_a_file_that_comes_after_a_deleted_or_renamed_one_is_modified(self) -> None:
        self.assertEqual([h.change for h in parse_hunks(DELETED + RENAMED_EDITED + NO_COUNTS)], ["deleted", "renamed", "modified"])

    def test_new_and_deleted_files_are_told_from_dev_null_when_the_mode_line_is_missing(self) -> None:
        added = ADDED.replace("new file mode 100644\n", "")
        deleted = DELETED.replace("deleted file mode 100644\n", "")
        self.assertEqual([h.change for h in parse_hunks(added + deleted)], ["added", "deleted"])

    def test_the_no_newline_marker_stays_in_the_hunk(self) -> None:
        (hunk,) = parse_hunks(NO_NEWLINE)
        self.assertEqual(hunk.lines, ["-old", "\\ No newline at end of file", "+new", "\\ No newline at end of file"])

    def test_a_header_without_counts_has_counts_of_one(self) -> None:
        (hunk,) = parse_hunks(NO_COUNTS)
        self.assertEqual((hunk.old_start, hunk.old_count, hunk.new_start, hunk.new_count), (7, 1, 7, 1))

    def test_text_before_the_first_file_is_ignored(self) -> None:
        self.assertEqual([h.id for h in parse_hunks("noise\n@@ -1 +1 @@\n-a\n+b\n" + NO_COUNTS)], ["h01"])

    def test_a_diff_with_no_files_has_no_hunk(self) -> None:
        self.assertEqual(parse_hunks(""), [])

    def test_the_trailing_newline_of_the_diff_is_not_a_line_of_the_last_hunk(self) -> None:
        self.assertEqual(parse_hunks(NO_COUNTS)[0].lines, ["-a", "+b"])
        self.assertEqual(parse_hunks(NO_COUNTS.rstrip("\n"))[0].lines, ["-a", "+b"])

    def test_hunk_json_lists_the_id_file_change_and_both_ranges(self) -> None:
        self.assertEqual(hunk_json(parse_hunks(TWO_HUNKS)[1]),
                         {"id": "h02", "path": "src/Widget.java", "change": "modified", "old": [20, 3], "new": [21, 3]})


class TagHeaders(unittest.TestCase):
    def test_each_hunk_header_ends_with_its_id(self) -> None:
        tagged = tag_headers(TWO_HUNKS)
        self.assertEqual([line for line in tagged.split("\n") if line.startswith("@@")],
                         ["@@ -3,4 +3,5 @@ public class Widget { [h01]", "@@ -20,3 +21,3 @@ public void run() { [h02]"])

    def test_only_the_header_lines_change(self) -> None:
        tagged = tag_headers(EVERYTHING)
        before = EVERYTHING.split("\n")
        after = tagged.split("\n")
        self.assertEqual(len(before), len(after))
        self.assertEqual([a for a, b in zip(before, after) if a != b], [a for a in before if a.startswith("@@")])
        self.assertEqual(tagged.count(" [h"), 6)

    def test_a_header_with_no_trailing_context_is_tagged_too(self) -> None:
        self.assertIn("@@ -7 +7 @@ [h01]\n", tag_headers(NO_COUNTS))

    def test_a_diff_without_hunks_is_returned_as_it_is(self) -> None:
        self.assertEqual(tag_headers(RENAMED + BINARY), RENAMED + BINARY)

    def test_tagging_a_tagged_diff_gives_the_same_tags(self) -> None:
        self.assertEqual(tag_headers(tag_headers(EVERYTHING)), tag_headers(EVERYTHING))

    def test_a_tagged_diff_parses_to_the_hunks_of_the_untagged_one(self) -> None:
        self.assertEqual(parse_hunks(tag_headers(EVERYTHING)), parse_hunks(EVERYTHING))

    def test_the_header_of_a_hunk_of_a_tagged_diff_has_no_tag(self) -> None:
        self.assertEqual(parse_hunks(tag_headers(TWO_HUNKS))[0].header, "@@ -3,4 +3,5 @@ public class Widget {")


class HunkAt(unittest.TestCase):
    HUNKS = parse_hunks(TWO_HUNKS + ADDED + DELETED)

    def test_the_new_range_holds_the_lines_of_the_right_side(self) -> None:
        self.assertEqual(hunk_at(self.HUNKS, "src/Widget.java", "R", 3).id, "h01")
        self.assertEqual(hunk_at(self.HUNKS, "src/Widget.java", "R", 7).id, "h01")
        self.assertIsNone(hunk_at(self.HUNKS, "src/Widget.java", "R", 8))
        self.assertEqual(hunk_at(self.HUNKS, "src/Widget.java", "R", 23).id, "h02")

    def test_the_old_range_holds_the_lines_of_the_left_side(self) -> None:
        self.assertEqual(hunk_at(self.HUNKS, "src/Widget.java", "L", 20).id, "h02")
        self.assertIsNone(hunk_at(self.HUNKS, "src/Widget.java", "L", 23))
        self.assertEqual(hunk_at(self.HUNKS, "src/Old.java", "L", 2).id, "h04")

    def test_a_range_of_no_lines_holds_none(self) -> None:
        self.assertIsNone(hunk_at(self.HUNKS, "src/Gadget.java", "L", 0))
        self.assertIsNone(hunk_at(self.HUNKS, "src/Old.java", "R", 0))

    def test_the_path_must_match(self) -> None:
        self.assertIsNone(hunk_at(self.HUNKS, "src/Other.java", "R", 4))


def hunk(number: int, path: str) -> Hunk:
    return Hunk(f"h{number:02d}", path, "@@", number * 10, 5, number * 10, 5, [])


def line(path: str, loc: tuple[str, int] | None, sources: list[Source] | None = None) -> Line:
    return Line("additive", "t", path, loc, sources=sources or [])


class Pins(unittest.TestCase):
    HUNKS = [hunk(1, "spec.json"), hunk(2, "A.java"), hunk(3, "B.java"), hunk(4, "mig.sql"), hunk(5, "C.java"), hunk(6, "spec.json"),
             hunk(12, "D.java"), hunk(100, "E.java")]

    def test_a_line_and_its_source_in_two_hunks_make_a_group(self) -> None:
        api = [line("spec.json", ("R", 10), [Source("A.java", "R", 21)])]
        self.assertEqual(pins(api, [], self.HUNKS), [["h01", "h02"]])

    def test_a_line_whose_places_are_in_one_hunk_makes_no_group(self) -> None:
        api = [line("spec.json", ("R", 10), [Source("spec.json", "R", 12)]), line("spec.json", ("R", 60))]
        self.assertEqual(pins(api, [], self.HUNKS), [])

    def test_a_place_the_hunks_do_not_hold_is_left_out(self) -> None:
        api = [line("spec.json", ("R", 10), [Source("A.java", "R", 99), Source("Z.java", "R", 1)]), line("spec.json", None)]
        self.assertEqual(pins(api, [], self.HUNKS), [])

    def test_a_removed_source_is_found_on_the_old_side(self) -> None:
        api = [line("spec.json", ("L", 10), [Source("A.java", "L", 24)])]
        self.assertEqual(pins(api, [], self.HUNKS), [["h01", "h02"]])

    def test_a_line_with_several_sources_groups_all_their_hunks(self) -> None:
        api = [line("spec.json", ("R", 10), [Source("A.java", "R", 20), Source("B.java", "R", 30)])]
        self.assertEqual(pins(api, [], self.HUNKS), [["h01", "h02", "h03"]])

    def test_data_lines_make_groups_too(self) -> None:
        data = [line("mig.sql", ("R", 40), [Source("C.java", "R", 50)])]
        self.assertEqual(pins([], data, self.HUNKS), [["h04", "h05"]])

    def test_groups_that_share_a_hunk_are_merged(self) -> None:
        api = [line("spec.json", ("R", 10), [Source("A.java", "R", 20)]), line("spec.json", ("R", 11), [Source("B.java", "R", 30)])]
        data = [line("mig.sql", ("R", 40), [Source("A.java", "R", 21)]), line("mig.sql", ("R", 41), [Source("C.java", "R", 50)])]
        self.assertEqual(pins(api, data, self.HUNKS), [["h01", "h02", "h03", "h04", "h05"]])

    def test_groups_that_share_nothing_stay_apart_and_are_sorted_by_their_first_hunk(self) -> None:
        api = [line("mig.sql", ("R", 40), [Source("C.java", "R", 50)]), line("spec.json", ("R", 10), [Source("A.java", "R", 20)])]
        self.assertEqual(pins(api, [], self.HUNKS), [["h01", "h02"], ["h04", "h05"]])

    def test_the_ids_are_sorted_by_number_not_as_text(self) -> None:
        api = [line("D.java", ("R", 120), [Source("E.java", "R", 1000), Source("spec.json", "R", 10)])]
        self.assertEqual(pins(api, [], self.HUNKS), [["h01", "h12", "h100"]])

    def test_the_same_group_found_twice_is_one_group(self) -> None:
        one = line("spec.json", ("R", 10), [Source("A.java", "R", 20)])
        self.assertEqual(pins([one, one], [], self.HUNKS), [["h01", "h02"]])

    def test_markdown_lists_one_group_per_line_under_a_heading(self) -> None:
        self.assertEqual(pins_markdown([["h03", "h07", "h12"], ["h20", "h21"]]),
                         "### Hunks that belong together\n"
                         "These hunks declare the same API or database change, so they must be in the same chunk.\n\n"
                         "- h03, h07, h12\n- h20, h21")

    def test_markdown_is_empty_without_a_group(self) -> None:
        self.assertEqual(pins_markdown([]), "")


class OneParser(unittest.TestCase):
    def test_diff_lines_by_path_keeps_a_file_with_no_hunk_as_an_empty_entry(self) -> None:
        self.assertEqual(render.diff_lines_by_path(RENAMED + NO_COUNTS), {"src/After.java": [], "one.txt": [("L", 7, "a"), ("R", 7, "b")]})

    def test_diff_lines_by_path_numbers_each_side_from_the_header_and_strips_the_text(self) -> None:
        found = render.diff_lines_by_path(TWO_HUNKS)["src/Widget.java"]
        self.assertEqual(found[:4], [("R", 3, "int a;"), ("L", 4, "int b;"), ("R", 4, "int b2;"), ("R", 5, "int c;")])
        self.assertEqual(found[-2:], [("R", 22, "three();"), ("R", 23, "four();")])

    def test_diff_lines_by_path_skips_the_no_newline_marker(self) -> None:
        self.assertEqual(render.diff_lines_by_path(NO_NEWLINE)["notes.txt"], [("L", 1, "old"), ("R", 1, "new")])

    def test_file_diff_lines_numbers_the_hunks_of_each_file_from_zero(self) -> None:
        diff = TWO_HUNKS + NO_COUNTS
        self.assertEqual([line.hunk for line in file_diff_lines(diff, "src/Widget.java")], [0] * 5 + [1] * 4)
        self.assertEqual({line.hunk for line in file_diff_lines(diff, "one.txt")}, {0})

    def test_file_diff_lines_reads_only_the_named_file_and_its_trailing_space_is_dropped(self) -> None:
        found = file_diff_lines("diff --git a/f b/f\n@@ -1 +1 @@\n-a  \n+b \n", "f")
        self.assertEqual([(line.side, line.number, line.kind, line.text) for line in found], [("L", 1, "-", "a"), ("R", 1, "+", "b")])
        self.assertEqual(file_diff_lines("diff --git a/f b/f\n@@ -1 +1 @@\n-a\n+b\n", "g"), [])


class TagsBreakNoParser(unittest.TestCase):
    TAGGED = tag_headers(TWO_HUNKS + ADDED + NO_COUNTS)

    def test_the_diff_is_still_found_in_a_prompt(self) -> None:
        prompt = f"{render.DIFF_START}{self.TAGGED}{render.DIFF_END} are prefixed with numbers"
        self.assertEqual(render.diff_from_prompt(prompt), self.TAGGED)

    def test_the_lines_of_every_file_are_the_same_with_or_without_tags(self) -> None:
        plain = TWO_HUNKS + ADDED + NO_COUNTS
        self.assertEqual(render.diff_lines_by_path(self.TAGGED), render.diff_lines_by_path(plain))
        for path in ("src/Widget.java", "src/Gadget.java", "one.txt"):
            self.assertEqual(file_diff_lines(self.TAGGED, path), file_diff_lines(plain, path))

    def test_context_pack_reads_the_same_files_and_declarations(self) -> None:
        plain = TWO_HUNKS + ADDED + NO_COUNTS
        tagged_files = context_pack.parse_diff(self.TAGGED)
        self.assertEqual([f.path for f in tagged_files], [f.path for f in context_pack.parse_diff(plain)])
        tagged = [(d.name, d.path, d.kind) for d in context_pack.declarations(tagged_files)]
        self.assertEqual(tagged, [(d.name, d.path, d.kind) for d in context_pack.declarations(context_pack.parse_diff(plain))])
        self.assertNotIn("h01", [name for name, _, _ in tagged])

    def test_a_tag_is_not_read_as_a_symbol_of_the_hunk_header(self) -> None:
        for context in ("public class Widget { [h01]", "[h01]", "export function f() { [h02]"):
            found = context_pack.header_symbol(context, "src/A.java", True)
            self.assertNotIn(found.name if found else "", ("h01", "h02"))
        self.assertEqual(context_pack.HUNK_HEADER.match("@@ -1 +1 @@ [h01]").group(1), "[h01]")

    def test_contract_and_data_lines_are_the_same_with_or_without_tags(self) -> None:
        base = document({}, {})
        head = document({"/widgets": {"get": operation("listWidgets")}}, {})
        spec_diff = make_diff(SPEC, json.dumps(base, indent=2), json.dumps(head, indent=2))
        contract = contract_of(base, head)
        sql = "diff --git a/db/V9__w.sql b/db/V9__w.sql\n@@ -0,0 +1,2 @@\n+CREATE TABLE widget (id bigint);\n+DROP TABLE old;\n"
        before = contract_lines(contract, file_diff_lines(spec_diff, SPEC), SPEC)
        after = contract_lines(contract, file_diff_lines(tag_headers(spec_diff), SPEC), SPEC)
        self.assertEqual(before, after)
        self.assertTrue(before)
        before_rows = data_lines({"db/V9__w.sql": file_diff_lines(sql, "db/V9__w.sql")})
        after_rows = data_lines({"db/V9__w.sql": file_diff_lines(tag_headers(sql), "db/V9__w.sql")})
        self.assertEqual(before_rows, after_rows)
        self.assertTrue(before_rows)


if __name__ == "__main__":
    unittest.main()
