"""Tests for post.py: the comment built from a run folder, the anchors in it, the size fallbacks and the upsert through a
fake `gh`. Nothing is posted. All data here is invented. Run with `python3 -m unittest discover -s tests` from the tool's
folder."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import post  # noqa: E402

REPO = "octo/widgets"
HEAD = "d" * 40
BODY = (
    "# Add a widget cache\n\n<!-- pr-agent-generated -->\n### **PR Type**\nEnhancement\n\n\n___\n\n"
    "### **Description**\n- Cache widgets\n\n\n___\n\n### **Contract**\nNo API changes\n\n\n### **Data**\nNo database changes\n\n\n"
    "### Diagram Walkthrough\n\n\n```mermaid\nflowchart TD\n  a[\"Cache\"] --> b[\"Store\"]\n```\n\nDashed boxes are unchanged context\n\n\n___\n\n")


def stop(i: int, path: str = "src/Cache.java", line: int | None = 10, why: str = "Start here.") -> dict:
    return {"i": i, "title": f"Stop {i}", "why": why, "path": path, "side": "R" if line else None, "line": line, "node": "a"}


def review(stops: list[dict]) -> dict:
    return {"schema": 4, "repo": REPO, "pr": 7, "head_sha": HEAD, "variant": "v", "nodes": {}, "walkthrough": stops, "contract": [], "data": []}


class RunFolderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def run_dir(self, stops: list[dict], body: str = BODY, name: str = "run") -> Path:
        folder = self.dir / name
        folder.mkdir()
        (folder / "body.md").write_text(body)
        (folder / "review.json").write_text(json.dumps(review(stops)))
        return folder


class AnchorTest(unittest.TestCase):
    def test_a_line_anchor_is_the_sha256_of_the_path_then_the_side_and_the_line(self) -> None:
        digest = hashlib.sha256(b"src/Cache.java").hexdigest()
        self.assertEqual(post.diff_anchor(REPO, 7, "src/Cache.java", "R", 42), f"https://github.com/{REPO}/pull/7/files#diff-{digest}R42")
        self.assertEqual(post.diff_anchor(REPO, 7, "src/Cache.java", "L", 3), f"https://github.com/{REPO}/pull/7/files#diff-{digest}L3")

    def test_a_file_anchor_has_no_line_part(self) -> None:
        digest = hashlib.sha256("docs/ünï.md".encode()).hexdigest()
        self.assertEqual(post.diff_anchor(REPO, "7", "docs/ünï.md"), f"https://github.com/{REPO}/pull/7/files#diff-{digest}")

    def test_the_hash_matches_the_one_render_py_puts_in_the_brief(self) -> None:
        import render
        self.assertEqual(post.diff_anchor(REPO, 7, "a/b.java"), render.diff_link(REPO, "7", "a/b.java"))


class BodyTest(RunFolderTest):
    def test_the_comment_has_the_brief_the_diagram_fence_the_walkthrough_and_the_hidden_payload_in_that_order(self) -> None:
        comment = post.build_comment(self.run_dir([stop(1), stop(2, "src/Store.java", None)]))
        order = ["## PR Brief", "### **Description**", "### **Contract**", "### **Data**", "```mermaid", "### Walkthrough", "1. [Stop 1](",
                 "2. [Stop 2](", "<sub>pr-brief · v · ddddddd</sub>", post.MARKER]
        positions = [comment.index(part) for part in order]
        self.assertEqual(positions, sorted(positions))
        self.assertTrue(comment.rstrip().endswith("-->"))

    def test_the_title_and_the_tool_marker_of_body_md_are_left_out(self) -> None:
        comment = post.build_comment(self.run_dir([stop(1)]))
        self.assertNotIn("# Add a widget cache", comment)
        self.assertNotIn("pr-agent-generated", comment)

    def test_each_stop_links_its_line_and_a_stop_without_a_line_links_its_file(self) -> None:
        comment = post.build_comment(self.run_dir([stop(1, line=10), stop(2, "src/Store.java", None)]))
        line_link = post.diff_anchor(REPO, 7, "src/Cache.java", "R", 10)
        file_link = post.diff_anchor(REPO, 7, "src/Store.java")
        self.assertIn(f"1. [Stop 1]({line_link}) — Start here.  \n   <sub>`src/Cache.java:10`</sub>", comment)
        self.assertIn(f"2. [Stop 2]({file_link}) — Start here.  \n   <sub>`src/Store.java`</sub>", comment)

    def test_the_repo_and_pr_arguments_win_over_the_run_s_own(self) -> None:
        comment = post.build_comment(self.run_dir([stop(1)]), "me/other", 9)
        self.assertIn("https://github.com/me/other/pull/9/files#diff-", comment)

    def test_the_hidden_payload_holds_review_json_exactly(self) -> None:
        stops = [stop(1), stop(2, why="Ünïcode — ok")]
        comment = post.build_comment(self.run_dir(stops))
        self.assertEqual(post.unpack(comment), review(stops))

    def test_the_payload_is_the_same_text_every_time(self) -> None:
        self.assertEqual(post.payload(review([stop(1)])), post.payload(review([stop(1)])))

    def test_a_contract_table_in_the_brief_is_kept(self) -> None:
        table = "<details><summary>Contract</summary>\n\n| Impact | Change |\n|---|---|\n| p0 | removed `GET /w` |\n\n</details>\n"
        body = BODY.replace("### **Contract**\nNo API changes\n", table)
        comment = post.build_comment(self.run_dir([stop(1)], body))
        self.assertIn(table, comment)

    def test_unpack_of_a_comment_without_a_payload_or_marker_is_none(self) -> None:
        self.assertIsNone(post.unpack("just a comment"))
        self.assertIsNone(post.unpack(f"text\n{post.MARKER} -->"))


class SizeTest(RunFolderTest):
    def test_a_comment_within_the_limit_is_whole(self) -> None:
        comment = post.build_comment(self.run_dir([stop(1)]))
        self.assertLessEqual(len(comment), post.COMMENT_LIMIT)
        self.assertNotIn("size limit", comment)
        self.assertIsNotNone(post.unpack(comment))

    def test_over_the_limit_the_hidden_payload_goes_first_with_a_note_and_the_walkthrough_stays_whole(self) -> None:
        stops = [stop(i, why="x" * 200) for i in range(1, 6)]
        run_dir = self.run_dir(stops)
        whole = post.build_comment(run_dir)
        limit = len(whole) - 1
        comment = post.build_comment(run_dir, limit=limit)
        self.assertLessEqual(len(comment), limit)
        self.assertIn(post.PAYLOAD_DROPPED, comment)
        self.assertIsNone(post.unpack(comment))
        self.assertIn(f"{post.MARKER} -->", comment)
        for i in range(1, 6):
            self.assertIn(f"{i}. [Stop {i}](", comment)

    def test_still_over_the_walkthrough_loses_its_last_stops_with_a_note(self) -> None:
        stops = [stop(i, why="x" * 300) for i in range(1, 11)]
        run_dir = self.run_dir(stops)
        limit = len(post.build_comment(run_dir, limit=10**9)) - 2000
        comment = post.build_comment(run_dir, limit=limit)
        self.assertLessEqual(len(comment), limit)
        self.assertIn(post.PAYLOAD_DROPPED, comment)
        shown = comment.count("](https://github.com/")
        self.assertTrue(0 < shown < 10)
        self.assertIn(f"The walkthrough shows the first {shown} of 10 stops", comment)
        self.assertIn(f"{shown}. [Stop {shown}](", comment)
        self.assertNotIn(f"{shown + 1}. [Stop", comment)
        self.assertIn(f"{post.MARKER} -->", comment)

    def test_a_brief_too_large_even_without_a_walkthrough_is_cut_at_a_line_with_its_fences_closed_and_still_posted(self) -> None:
        huge = BODY.replace("- Cache widgets", "- Cache widgets\n" + "\n".join(f"- line {n}" for n in range(3000)))
        run_dir = self.run_dir([stop(1)], huge)
        comment = post.build_comment(run_dir, limit=3000)
        self.assertLessEqual(len(comment), 3000)
        self.assertEqual(comment.count("```") % 2, 0)
        self.assertIn(post.TRIMMED, comment)
        self.assertIn(f"{post.MARKER} -->", comment)
        self.assertTrue(comment.startswith("## PR Brief"))

    def test_a_real_limit_is_never_exceeded_by_a_run_of_a_thousand_stops(self) -> None:
        stops = [stop(i, why="because " * 40) for i in range(1, 1001)]
        comment = post.build_comment(self.run_dir(stops))
        self.assertLessEqual(len(comment), post.COMMENT_LIMIT)
        self.assertIn(post.MARKER, comment)


class FakeGh:
    def __init__(self, login: str | None = "octocat", comments: str = "") -> None:
        self.login, self.comments, self.calls = login, comments, []

    def __call__(self, args: list[str], stdin: str | None = None) -> str:
        self.calls.append((args, stdin))
        if args[:2] == ["api", "user"]:
            if self.login is None:
                raise subprocess.CalledProcessError(1, "gh")
            return self.login + "\n"
        if args[:2] == ["api", "--paginate"]:
            return self.comments
        return ""

    def writes(self) -> list[tuple[list[str], str | None]]:
        return [call for call in self.calls if call[0][:2] not in (["api", "user"], ["api", "--paginate"])]


class UpsertTest(unittest.TestCase):
    def test_with_no_earlier_comment_a_new_one_is_posted_on_the_pr(self) -> None:
        gh = FakeGh()
        self.assertEqual(post.upsert(REPO, 7, "the body", gh), "created")
        self.assertEqual(gh.writes(), [(["api", f"repos/{REPO}/issues/7/comments", "--input", "-"], json.dumps({"body": "the body"}))])

    def test_an_earlier_comment_by_the_token_s_user_is_patched(self) -> None:
        gh = FakeGh(comments="31\toctocat\n")
        self.assertEqual(post.upsert(REPO, 7, "new", gh), "updated")
        self.assertEqual(gh.writes(), [(["api", "-X", "PATCH", f"repos/{REPO}/issues/comments/31", "--input", "-"], json.dumps({"body": "new"}))])

    def test_a_marker_comment_by_someone_else_is_not_touched(self) -> None:
        gh = FakeGh(comments="31\tsomeone-else\n")
        self.assertEqual(post.upsert(REPO, 7, "new", gh), "created")

    def test_with_several_the_lowest_id_of_the_user_s_is_patched(self) -> None:
        gh = FakeGh(comments="90\toctocat\n12\tsomeone-else\n45\toctocat\n")
        post.upsert(REPO, 7, "new", gh)
        self.assertTrue(gh.writes()[0][0][3].endswith("comments/45"))

    def test_the_search_asks_only_for_comments_holding_the_marker(self) -> None:
        gh = FakeGh()
        post.upsert(REPO, 7, "b", gh)
        listing = next(call for call in gh.calls if call[0][:2] == ["api", "--paginate"])
        self.assertIn(post.MARKER, listing[0][-1])

    def test_a_token_that_cannot_read_its_user_is_the_actions_bot(self) -> None:
        gh = FakeGh(login=None, comments=f"8\t{post.ACTIONS_LOGIN}\n")
        self.assertEqual(post.upsert(REPO, 7, "new", gh), "updated")


class FindOnlyTest(unittest.TestCase):
    def find(self, gh: FakeGh, *extra: str) -> tuple[int, str]:
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = post.main(["--find-only", "--repo", REPO, "--pr", "7", *extra], gh)
        return code, out.getvalue()

    def test_a_brief_comment_by_the_token_s_user_exits_0_and_prints_its_id(self) -> None:
        gh = FakeGh(comments="31\toctocat\n")
        self.assertEqual(self.find(gh), (0, "31\n"))
        self.assertEqual(gh.writes(), [])

    def test_no_brief_comment_exits_with_the_not_found_code_and_prints_nothing(self) -> None:
        gh = FakeGh()
        self.assertEqual(self.find(gh), (post.NOT_FOUND_EXIT, ""))
        self.assertEqual(gh.writes(), [])

    def test_a_brief_comment_by_someone_else_does_not_count(self) -> None:
        self.assertEqual(self.find(FakeGh(comments="31\tsomeone-else\n")), (post.NOT_FOUND_EXIT, ""))

    def test_it_needs_no_run_folder_and_both_the_repo_and_the_pr(self) -> None:
        with self.assertRaises(SystemExit) as stop:
            post.main(["--find-only", "--repo", REPO], FakeGh())
        self.assertEqual(stop.exception.code, 2)

    def test_a_failing_gh_is_an_error_and_not_a_missing_comment(self) -> None:
        def refused(args: list[str], stdin: str | None = None) -> str:
            raise subprocess.CalledProcessError(1, "gh")
        with self.assertRaises(subprocess.CalledProcessError):
            post.main(["--find-only", "--repo", REPO, "--pr", "7", "--dry-run"], refused)


class FindRunTest(RunFolderTest):
    def test_a_run_folder_is_itself(self) -> None:
        run_dir = self.run_dir([stop(1)])
        self.assertEqual(post.find_run(run_dir), run_dir)

    def test_a_pr_folder_gives_its_newest_run(self) -> None:
        older = self.run_dir([stop(1)], name="older")
        newer = self.run_dir([stop(1)], name="newer")
        import os
        os.utime(older / "review.json", (1, 1))
        self.assertEqual(post.find_run(self.dir), newer)

    def test_a_folder_with_no_run_is_an_error(self) -> None:
        with self.assertRaises(SystemExit):
            post.find_run(self.dir)


if __name__ == "__main__":
    unittest.main()
