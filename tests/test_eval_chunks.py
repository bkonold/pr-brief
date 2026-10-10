"""Tests for the chunk eval: how an expected entry resolves to hunk ids, the pair agreement arithmetic and the report. All data
here is invented. Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import eval_chunks as ev  # noqa: E402
import render  # noqa: E402
from hunks import hunk_json, parse_hunks, tag_headers  # noqa: E402

DIFF = """diff --git a/src/A.java b/src/A.java
--- a/src/A.java
+++ b/src/A.java
@@ -10,4 +10,5 @@ class A {
   int a;
-  int b;
+  int b2;
+  int c;
   int d;
@@ -50,3 +51,3 @@ void run() {
   one();
-  two();
+  three();
   four();
@@ -90,5 +91,2 @@ void end() {
   keep();
-  drop1();
-  drop2();
-  drop3();
   keep2();
diff --git a/src/B.java b/src/B.java
new file mode 100644
--- /dev/null
+++ b/src/B.java
@@ -0,0 +1,3 @@
+class B {
+  int x;
+}
diff --git a/src/Gone.java b/src/Gone.java
deleted file mode 100644
--- a/src/Gone.java
+++ /dev/null
@@ -1,20 +0,0 @@
-gone
"""
HUNKS = parse_hunks(DIFF)


class ResolveEntry(unittest.TestCase):
    def test_a_bare_path_is_every_hunk_of_the_file_in_diff_order(self) -> None:
        self.assertEqual(ev.resolve_entry("src/A.java", HUNKS), ["h01", "h02", "h03"])
        self.assertEqual(ev.resolve_entry("src/B.java", HUNKS), ["h04"])

    def test_a_range_is_the_hunks_whose_new_lines_it_overlaps(self) -> None:
        self.assertEqual(ev.resolve_entry("src/A.java:10-40", HUNKS), ["h01"])
        self.assertEqual(ev.resolve_entry("src/A.java:51-53", HUNKS), ["h02"])
        self.assertEqual(ev.resolve_entry("src/A.java:1-1000", HUNKS), ["h01", "h02", "h03"])

    def test_a_range_may_touch_a_hunks_first_or_last_line_and_must_not_stop_short_of_it(self) -> None:
        self.assertEqual(ev.resolve_entry("src/A.java:5-10", HUNKS), ["h01"])
        self.assertEqual(ev.resolve_entry("src/A.java:14-20", HUNKS), ["h01"])
        self.assertEqual(ev.resolve_entry("src/A.java:15-20", HUNKS), [])
        self.assertEqual(ev.resolve_entry("src/A.java:1-9", HUNKS), [])

    def test_a_single_line_is_a_range_of_one(self) -> None:
        self.assertEqual(ev.resolve_entry("src/A.java:52", HUNKS), ["h02"])

    def test_a_hunk_that_adds_no_lines_is_matched_by_its_old_lines(self) -> None:
        self.assertEqual(ev.resolve_entry("src/A.java:93-94", HUNKS), ["h03"])
        self.assertEqual(ev.resolve_entry("src/A.java:95-96", HUNKS), [])
        self.assertEqual(ev.resolve_entry("src/Gone.java:15", HUNKS), ["h05"])

    def test_a_hunk_that_adds_lines_is_matched_by_its_new_lines_not_its_old_ones(self) -> None:
        self.assertEqual(ev.resolve_entry("src/A.java:14", HUNKS), ["h01"])
        self.assertEqual(ev.resolve_entry("src/A.java:50", HUNKS), [])
        self.assertEqual(ev.resolve_entry("src/A.java:53", HUNKS), ["h02"])
        self.assertEqual(ev.resolve_entry("src/A.java:54", HUNKS), [])

    def test_a_new_files_hunk_is_matched_by_its_new_lines(self) -> None:
        self.assertEqual(ev.resolve_entry("src/B.java:3", HUNKS), ["h04"])
        self.assertEqual(ev.resolve_entry("src/B.java:4", HUNKS), [])

    def test_a_path_or_range_in_no_hunk_gives_none(self) -> None:
        self.assertEqual(ev.resolve_entry("src/Nope.java", HUNKS), [])
        self.assertEqual(ev.resolve_entry("src/Nope.java:1-9", HUNKS), [])

    def test_a_tagged_diff_gives_the_same_resolution(self) -> None:
        self.assertEqual(ev.resolve_entry("src/A.java:93-94", parse_hunks(tag_headers(DIFF))), ["h03"])


class ResolveExpected(unittest.TestCase):
    def test_each_hunk_goes_with_the_chunk_that_names_it(self) -> None:
        placed, errors = ev.resolve_expected({"Model": ["src/A.java:10-40", "src/B.java"], "Rest": ["src/A.java:50-100"]}, HUNKS)
        self.assertEqual((placed, errors), ({"h01": "Model", "h04": "Model", "h02": "Rest", "h03": "Rest"}, []))

    def test_an_entry_that_hits_no_hunk_is_an_error(self) -> None:
        placed, errors = ev.resolve_expected({"Model": ["src/A.java:200-300", "src/Nope.java"]}, HUNKS)
        self.assertEqual(placed, {})
        self.assertEqual(errors, ['Model: "src/A.java:200-300" matches no hunk', 'Model: "src/Nope.java" matches no hunk'])

    def test_a_hunk_named_by_two_chunks_stays_with_the_first_and_is_an_error(self) -> None:
        placed, errors = ev.resolve_expected({"One": ["src/A.java:10-12"], "Two": ["src/A.java"]}, HUNKS)
        self.assertEqual(placed, {"h01": "One", "h02": "Two", "h03": "Two"})
        self.assertEqual(errors, ["Two: h01 is already in One"])

    def test_the_same_hunk_named_twice_by_one_chunk_is_not_an_error(self) -> None:
        self.assertEqual(ev.resolve_expected({"One": ["src/B.java", "src/B.java:1-3"]}, HUNKS), ({"h04": "One"}, []))


class PairAgreement(unittest.TestCase):
    def test_identical_groupings_agree_on_every_pair(self) -> None:
        expected = {"h01": "X", "h02": "X", "h03": "Y"}
        self.assertEqual(ev.pair_agreement(expected, {"h01": 1, "h02": 1, "h03": 2}), (3, 3))

    def test_chunk_names_and_numbers_do_not_matter_only_who_is_with_whom(self) -> None:
        expected = {"h01": "X", "h02": "Y", "h03": "Y"}
        self.assertEqual(ev.pair_agreement(expected, {"h01": 7, "h02": 3, "h03": 3}), (3, 3))

    def test_a_pair_split_by_one_grouping_and_joined_by_the_other_disagrees(self) -> None:
        expected = {"h01": "X", "h02": "X", "h03": "X", "h04": "Y"}
        actual = {"h01": 1, "h02": 1, "h03": 2, "h04": 2}
        self.assertEqual(ev.pair_agreement(expected, actual), (3, 6))

    def test_everything_in_one_chunk_agrees_only_on_the_pairs_the_expected_file_joins(self) -> None:
        expected = {"h01": "X", "h02": "X", "h03": "Y", "h04": "Z"}
        self.assertEqual(ev.pair_agreement(expected, {name: 1 for name in expected}), (1, 6))

    def test_only_hunks_both_groupings_place_make_pairs(self) -> None:
        expected = {"h01": "X", "h02": "X", "h09": "Y"}
        self.assertEqual(ev.pair_agreement(expected, {"h01": 1, "h02": 2, "h03": 1}), (0, 1))

    def test_fewer_than_two_shared_hunks_make_no_pair(self) -> None:
        self.assertEqual(ev.pair_agreement({"h01": "X"}, {"h01": 1}), (0, 0))
        self.assertEqual(ev.pair_agreement({}, {}), (0, 0))


class Landed(unittest.TestCase):
    def test_each_expected_chunk_counts_its_hunks_per_actual_chunk_and_the_ones_not_placed(self) -> None:
        expected = {"h01": "X", "h02": "X", "h03": "X", "h04": "X", "h05": "Y"}
        self.assertEqual(ev.landed(expected, {"h01": 1, "h02": 1, "h03": 3, "h05": 2}),
                         {"X": {1: 2, 3: 1, "none": 1}, "Y": {2: 1}})


class Report(unittest.TestCase):
    def test_it_prints_the_agreement_the_spread_and_the_hunks_not_mentioned(self) -> None:
        expected = {"Payment terms": ["src/A.java:10-40", "src/A.java:50-100"], "The class": ["src/B.java"]}
        placed, _ = ev.resolve_expected(expected, HUNKS)
        actual = {"h01": 1, "h02": 1, "h03": 3, "h04": 2, "h05": 2}
        self.assertEqual(ev.report(expected, placed, actual, HUNKS), "\n".join([
            "Pair agreement: 66.7% (4 of 6 pairs)",
            "",
            "Payment terms → 1 (2 hunks), 3 (1 hunk)",
            "The class → 2 (1 hunk)",
            "",
            "Hunks the expected file does not mention (1): h05"]))

    def test_it_says_so_when_there_is_no_pair(self) -> None:
        text = ev.report({"X": ["src/B.java"]}, {"h04": "X"}, {"h04": 1}, HUNKS)
        self.assertTrue(text.startswith("Pair agreement: no pairs to compare\n"))


def write_run(folder: Path, assignment: list[list[str]]) -> None:
    (folder / "prompt.txt").write_text(f"x\n{render.DIFF_START}{tag_headers(DIFF)}{render.DIFF_END} are prefixed\n")
    by_id = {hunk.id: hunk for hunk in HUNKS}
    chunks = [{"i": i, "hunks": [hunk_json(by_id[name]) for name in names]} for i, names in enumerate(assignment, 1)]
    (folder / "review.json").write_text(json.dumps({"chunks": chunks}))


class Command(unittest.TestCase):
    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.folder = Path(holder.name)

    def run_eval(self, expected: str, *assignment: list[str]) -> tuple[int, str, str]:
        write_run(self.folder, list(assignment))
        (self.folder / "expected.toml").write_text(expected)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ev.main([str(self.folder), str(self.folder / "expected.toml")])
        return code, out.getvalue(), err.getvalue()

    def test_a_clean_run_prints_the_report_and_exits_0(self) -> None:
        code, out, err = self.run_eval('[chunks."Model"]\nhunks = ["src/A.java"]\n[chunks."Class"]\nhunks = ["src/B.java:1-2"]\n',
                                       ["h01", "h02", "h03"], ["h04", "h05"])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Pair agreement: 100.0% (6 of 6 pairs)", out)
        self.assertIn("Model → 1 (3 hunks)", out)
        self.assertIn("Class → 2 (1 hunk)", out)

    def test_a_range_that_hits_no_hunk_is_printed_as_an_error_and_exits_1(self) -> None:
        code, out, err = self.run_eval('[chunks."Model"]\nhunks = ["src/A.java:500-600"]\n', ["h01", "h02", "h03"], ["h04", "h05"])
        self.assertEqual(code, 1)
        self.assertEqual(err, 'error: Model: "src/A.java:500-600" matches no hunk\n')
        self.assertIn("Model → no hunks", out)

    def test_a_run_with_no_chunks_is_an_error(self) -> None:
        write_run(self.folder, [])
        (self.folder / "review.json").write_text("{}")
        (self.folder / "expected.toml").write_text('[chunks."X"]\nhunks = ["src/A.java"]\n')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(ev.main([str(self.folder), str(self.folder / "expected.toml")]), 1)
        self.assertIn("has no chunks", err.getvalue())

    def test_an_expected_file_with_no_chunk_tables_is_an_error(self) -> None:
        code, _, err = self.run_eval("x = 1\n", ["h01", "h02", "h03", "h04", "h05"])
        self.assertEqual(code, 1)
        self.assertIn("has no [chunks.", err)


if __name__ == "__main__":
    unittest.main()
