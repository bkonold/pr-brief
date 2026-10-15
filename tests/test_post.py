"""Tests for post.py: the comment built from a run folder, the size fallbacks and the upsert through a
fake `gh`. Nothing is posted. All data here is invented. Run with `python3 -m unittest discover -s tests` from the tool's
folder."""
import base64
import gzip
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
DIAGRAM = "```mermaid\nflowchart TD\n  a[\"1 · Cache\"] --> b[\"Store\"]\n```\n"


def unpack(comment: str) -> dict | None:
    block = post.DATA_BLOCK.search(comment)
    return json.loads(gzip.decompress(base64.b64decode("".join(block["data"].split())))) if block else None


def stop(i: int, path: str = "src/Cache.java", line: int | None = 10, why: str = "Start here.") -> dict:
    return {"i": i, "title": f"Stop {i}", "why": why, "path": path, "side": "R" if line else None, "line": line, "node": "a"}


def review(stops: list[dict]) -> dict:
    return {"schema": 4, "repo": REPO, "pr": 7, "head_sha": HEAD, "variant": "v", "nodes": {}, "walkthrough": stops}


class RunFolderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def run_dir(self, stops: list[dict], diagram: str | None = DIAGRAM, name: str = "run", svg: str | None = None) -> Path:
        folder = self.dir / name
        folder.mkdir()
        (folder / "review.json").write_text(json.dumps(review(stops)))
        if diagram is not None:
            (folder / "diagram.md").write_text(diagram)
        if svg is not None:
            (folder / "diagram.svg").write_text(svg)
        return folder


class BodyTest(RunFolderTest):
    def test_the_comment_has_the_summary_the_diagram_fence_the_data_block_and_the_marker_in_that_order(self) -> None:
        comment = post.build_comment(self.run_dir([stop(1), stop(2, "src/Store.java", None)]))
        order = ["<details>\n<summary><b>PR Brief · AI-generated</b> · v · ddddddd</summary>", "```mermaid",
                 "<details><summary>Brief data</summary>", "</details>\n\n</details>", f"{post.MARKER} -->"]
        positions = [comment.index(part) for part in order]
        self.assertEqual(positions, sorted(positions))
        self.assertTrue(comment.rstrip().endswith(f"</details>\n\n{post.MARKER} -->"))

    def test_the_diagram_is_the_run_s_diagram_md_as_it_is(self) -> None:
        self.assertIn(DIAGRAM.strip(), post.build_comment(self.run_dir([stop(1)])))

    def test_the_walkthrough_is_not_written_out_in_the_comment(self) -> None:
        comment = post.build_comment(self.run_dir([stop(1)]))
        self.assertNotIn("Stop 1", comment.split("<details><summary>Brief data</summary>")[0])

    def test_a_run_without_a_diagram_has_only_the_data_block(self) -> None:
        comment = post.build_comment(self.run_dir([stop(1)], diagram=None))
        self.assertNotIn("```mermaid", comment)
        self.assertIsNotNone(post.DATA_BLOCK.search(comment))

    def test_the_data_block_sits_inside_the_one_outer_fold(self) -> None:
        comment = post.build_comment(self.run_dir([stop(1)]))
        self.assertEqual(comment.count("<details"), 2)
        self.assertLess(comment.index("<summary><b>PR Brief · AI-generated</b>"), comment.index("<details><summary>Brief data</summary>"))
        self.assertLess(comment.index("<details><summary>Brief data</summary>"), comment.rindex("</details>"))

    def test_the_marker_holds_no_payload_and_the_data_block_is_a_closed_details_with_one_unfenced_line_of_base64(self) -> None:
        comment = post.build_comment(self.run_dir([stop(1)]))
        self.assertEqual(comment.count(f"{post.MARKER} -->"), 1)
        match = post.DATA_BLOCK.search(comment)
        assert match is not None
        self.assertRegex(match["data"], r"^[A-Za-z0-9+/=]+$")
        self.assertNotIn("<details open", comment)

    def test_the_data_block_holds_review_json_and_the_diagram(self) -> None:
        stops = [stop(1), stop(2, why="Ünïcode — ok")]
        comment = post.build_comment(self.run_dir(stops, svg="<svg><text>Ünï</text></svg>"))
        self.assertEqual(unpack(comment), {**review(stops), "diagram_svg": "<svg><text>Ünï</text></svg>"})

    def test_a_run_without_a_diagram_svg_has_null_for_it(self) -> None:
        payload = unpack(post.build_comment(self.run_dir([stop(1)])))
        assert payload is not None
        self.assertIsNone(payload["diagram_svg"])

    def test_the_payload_is_the_same_text_every_time(self) -> None:
        self.assertEqual(post.payload(review([stop(1)]), "<svg/>"), post.payload(review([stop(1)]), "<svg/>"))


class SizeTest(RunFolderTest):
    def test_a_comment_within_the_limit_is_whole(self) -> None:
        comment = post.build_comment(self.run_dir([stop(1)]))
        self.assertLessEqual(len(comment), post.COMMENT_LIMIT)
        self.assertNotIn("size limit", comment)
        self.assertIsNotNone(post.DATA_BLOCK.search(comment))

    def test_over_the_limit_the_data_block_goes_first_with_a_note_and_the_diagram_stays(self) -> None:
        run_dir = self.run_dir([stop(i, why="x" * 200) for i in range(1, 6)])
        limit = len(post.build_comment(run_dir)) - 1
        comment = post.build_comment(run_dir, limit=limit)
        self.assertLessEqual(len(comment), limit)
        self.assertIn(post.PAYLOAD_DROPPED, comment)
        self.assertIsNone(post.DATA_BLOCK.search(comment))
        self.assertIn(DIAGRAM.strip(), comment)
        self.assertIn(f"{post.MARKER} -->", comment)

    def test_still_over_the_diagram_goes_too_with_a_note_and_the_comment_is_still_posted(self) -> None:
        huge = "```mermaid\nflowchart TD\n" + "\n".join(f'  n{n}["Box {n}"]' for n in range(3000)) + "\n```\n"
        comment = post.build_comment(self.run_dir([stop(1)], huge), limit=3000)
        self.assertLessEqual(len(comment), 3000)
        self.assertIn(post.DIAGRAM_DROPPED, comment)
        self.assertNotIn("```mermaid", comment)
        self.assertIn(f"{post.MARKER} -->", comment)
        self.assertTrue(comment.startswith("<details>\n<summary><b>PR Brief · AI-generated</b>"))


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
