"""Tests of how diagram.svg is drawn: which Chrome is used and in what order it is looked for, that Mermaid is the pinned
local build and nothing is fetched, and that a run without a drawn diagram fails instead of shipping a brief without one.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import json
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import render  # noqa: E402

ANSWER = """type:
- Enhancement
description: |
  - One change
title: |
  A change
changes_diagram: |
  ```mermaid
  flowchart TD
    a["First<br/>does one thing"]
    b["Second<br/>does another"]
    a --> b
  ```
node_files:
  a:
  - a.py
  b:
  - b.py
walkthrough:
- node: |
    a
  file: |
    a.py
  title: |
    First stop
  why: |
    Where it starts.
  line_text: |
    x = 1
"""
DIFF = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-x = 0\n+x = 1\n"
PR = {"title": "T", "body": "", "headRefName": "b", "baseRefOid": "1", "headRefOid": "2", "commits": [],
      "files": [{"path": "a.py", "additions": 1, "deletions": 1, "changeType": "MODIFIED"},
                {"path": "b.py", "additions": 1, "deletions": 0, "changeType": "ADDED"}]}
SVG_DOM = '<html><body><pre id="svg-out"><svg id="mermaid-123" viewBox="0 0 1 1"></svg></pre></body></html>'
BRIEF_FILES = ("body.md", "review.json", "diagram.svg")


def script(folder: Path, name: str, body: str) -> Path:
    path: Path = folder / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class FindChrome(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.macos = str(self.dir / "macos-chrome")

    def find(self, environ: dict[str, str] | None = None, local: dict | None = None) -> str:
        return render.find_chrome({"PATH": str(self.bin), **(environ or {})}, local or {}, self.macos)

    def test_the_environment_variable_wins_over_everything(self) -> None:
        env_chrome = script(self.dir, "env-chrome", "")
        local_chrome = script(self.dir, "local-chrome", "")
        script(self.bin, "google-chrome", "")
        script(self.dir, "macos-chrome", "")
        self.assertEqual(self.find({render.CHROME_ENV: str(env_chrome)}, {"chrome": str(local_chrome)}), str(env_chrome))

    def test_the_local_toml_key_comes_next(self) -> None:
        local_chrome = script(self.dir, "local-chrome", "")
        script(self.bin, "google-chrome", "")
        self.assertEqual(self.find(local={"chrome": str(local_chrome)}), str(local_chrome))

    def test_then_the_first_program_on_path_in_the_listed_order(self) -> None:
        for name in ("chromium-browser", "chromium", "google-chrome-stable"):
            script(self.bin, name, "")
        script(self.dir, "macos-chrome", "")
        self.assertEqual(self.find(), str(self.bin / "google-chrome-stable"))
        (self.bin / "google-chrome-stable").unlink()
        self.assertEqual(self.find(), str(self.bin / "chromium"))
        (self.bin / "chromium").unlink()
        self.assertEqual(self.find(), str(self.bin / "chromium-browser"))

    def test_the_macos_install_is_last(self) -> None:
        script(self.dir, "macos-chrome", "")
        self.assertEqual(self.find(), self.macos)

    def test_a_configured_path_that_is_not_an_executable_is_an_error_even_when_a_later_place_has_chrome(self) -> None:
        script(self.bin, "google-chrome", "")
        for environ, local in (({render.CHROME_ENV: str(self.dir / "missing")}, {}), ({}, {"chrome": str(self.dir / "missing")})):
            with self.assertRaises(render.AnswerError) as caught:
                self.find(environ, local)
            self.assertIn("is not an executable file", str(caught.exception))
            self.assertIn(render.chrome_order(), str(caught.exception))

    def test_with_none_the_error_names_every_place_tried_in_order(self) -> None:
        with self.assertRaises(render.AnswerError) as caught:
            self.find()
        message = str(caught.exception)
        places = [render.CHROME_ENV, "`chrome` key in local.toml", "google-chrome", "google-chrome-stable", "chromium",
                  "chromium-browser", render.CHROME_MACOS]
        positions = [message.index(place) for place in places]
        self.assertEqual(positions, sorted(positions))


class Page(unittest.TestCase):
    def test_the_page_loads_the_local_mermaid_and_references_no_network_address(self) -> None:
        page = render.svg_page("flowchart TD\n  a --> b")
        self.assertIn(render.MERMAID_JS.as_uri(), page)
        self.assertIsNone(re.search(r"https?://", page))

    def test_a_missing_mermaid_says_to_run_npm_ci(self) -> None:
        with mock.patch.object(render, "MERMAID_JS", Path("/nonexistent/mermaid.min.js")):
            with self.assertRaises(render.AnswerError) as caught:
                render.mermaid_version()
        self.assertIn("run `npm ci`", str(caught.exception))

    def test_the_installed_version_is_the_one_pinned_in_package_json(self) -> None:
        pinned = json.loads((render.ROOT / "package.json").read_text())["dependencies"]["mermaid"]
        self.assertRegex(pinned, r"^\d+\.\d+\.\d+$")
        self.assertEqual(render.mermaid_version(), pinned)


class Render(unittest.TestCase):
    """render.py's main on a run folder, with Chrome and Mermaid replaced by files in a temporary folder."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.run_dir = self.dir / "run"
        self.run_dir.mkdir()
        (self.run_dir / "run.json").write_text(json.dumps(
            {"variant": "v", "pr": 1, "host": "github", "repo": "o/r", "pr_head_sha": "2", "with_body": False, "exit_status": 0}))
        (self.run_dir / "pr.json").write_text(json.dumps(PR))
        (self.run_dir / "answer.yaml").write_text(ANSWER)
        (self.run_dir / "prompt.txt").write_text(f"=====USER=====\n\n{DIFF}")
        mermaid = self.dir / "node_modules" / "mermaid"
        (mermaid / "dist").mkdir(parents=True)
        (mermaid / "dist" / "mermaid.min.js").write_text("")
        (mermaid / "package.json").write_text('{"version": "9.8.7"}')
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        patches = [
            mock.patch.object(render, "MERMAID_JS", mermaid / "dist" / "mermaid.min.js"),
            mock.patch.object(render, "MERMAID_PACKAGE", mermaid / "package.json"),
            mock.patch.object(render, "CHROME_MACOS", str(self.dir / "no-macos-chrome")),
            mock.patch.object(render, "load_local", lambda: {}),
            mock.patch.dict(render.os.environ, {"PATH": str(self.bin)}, clear=True),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def main(self) -> int:
        with mock.patch.object(sys, "argv", ["render.py", str(self.run_dir)]), mock.patch.object(sys, "stderr"):
            return render.main()

    def files(self) -> set[str]:
        return {path.name for path in self.run_dir.iterdir()}

    def test_a_drawn_diagram_is_written_and_the_mermaid_version_recorded(self) -> None:
        render.os.environ[render.CHROME_ENV] = str(script(self.dir, "chrome", f"echo '{SVG_DOM}'"))
        self.assertEqual(self.main(), 0)
        self.assertEqual((self.run_dir / "diagram.svg").read_text(), f'<svg id="{render.SVG_ID}" viewBox="0 0 1 1"></svg>\n')
        self.assertEqual(json.loads((self.run_dir / "run.json").read_text())["mermaid"], "9.8.7")
        self.assertEqual(json.loads((self.run_dir / "review.json").read_text())["diagram"], "diagram.svg")

    def test_no_chrome_fails_the_run_and_ships_no_brief(self) -> None:
        self.assertEqual(self.main(), 1)
        error = (self.run_dir / "error.txt").read_text()
        self.assertIn("No Chrome was found", error)
        self.assertIn(render.chrome_order(), error)
        self.assertFalse(set(BRIEF_FILES) & self.files())

    def test_a_chrome_that_draws_nothing_fails_the_run_and_ships_no_brief(self) -> None:
        render.os.environ[render.CHROME_ENV] = str(script(self.dir, "chrome", "exit 0"))
        self.assertEqual(self.main(), 1)
        self.assertIn("did not produce diagram.svg", (self.run_dir / "error.txt").read_text())
        self.assertFalse(set(BRIEF_FILES) & self.files())

    def test_a_failed_draw_removes_the_brief_an_earlier_run_left(self) -> None:
        for stale in BRIEF_FILES:
            (self.run_dir / stale).write_text("old")
        self.assertEqual(self.main(), 1)
        self.assertFalse(set(BRIEF_FILES) & self.files())

    def test_without_mermaid_the_run_fails_with_the_npm_ci_message(self) -> None:
        render.os.environ[render.CHROME_ENV] = str(script(self.dir, "chrome", f"echo '{SVG_DOM}'"))
        with mock.patch.object(render, "MERMAID_JS", self.dir / "absent.js"):
            self.assertEqual(self.main(), 1)
        self.assertIn("run `npm ci`", (self.run_dir / "error.txt").read_text())
        self.assertFalse(set(BRIEF_FILES) & self.files())

    def test_a_pr_with_no_files_fails_the_run(self) -> None:
        (self.run_dir / "pr.json").write_text(json.dumps({**PR, "files": []}))
        self.assertEqual(self.main(), 1)
        self.assertIn("has no files", (self.run_dir / "error.txt").read_text())
        self.assertFalse(set(BRIEF_FILES) & self.files())

    def test_a_walkthrough_whose_every_stop_is_dropped_fails_the_run(self) -> None:
        render.os.environ[render.CHROME_ENV] = str(script(self.dir, "chrome", f"echo '{SVG_DOM}'"))
        (self.run_dir / "answer.yaml").write_text(ANSWER.replace("    a.py\n  title", "    elsewhere.py\n  title"))
        self.assertEqual(self.main(), 1)
        error = (self.run_dir / "error.txt").read_text()
        self.assertIn("no stop left", error)
        self.assertIn("elsewhere.py", error)
        self.assertFalse(set(BRIEF_FILES) & self.files())

    def test_an_answer_with_no_diagram_still_renders_without_chrome(self) -> None:
        (self.run_dir / "answer.yaml").write_text(re.sub(r"changes_diagram: \|\n(?:  .*\n)+", "", ANSWER))
        self.assertEqual(self.main(), 0)
        self.assertNotIn("diagram.svg", self.files())
        self.assertNotIn("mermaid", json.loads((self.run_dir / "run.json").read_text()))


def run_node(script_text: str) -> str:
    return subprocess.run(["node", "-e", script_text], capture_output=True, text=True, check=True).stdout.strip()


class DiagramSize(unittest.TestCase):
    def test_the_diagram_is_drawn_in_a_16px_font_and_a_280_wrapping_width(self) -> None:
        text = render.render_diagram("```mermaid\nflowchart TD\n  a[\"A\"] --> b[\"B\"]\n```")
        self.assertIn('"themeVariables": {"fontSize": "16px"}', text)
        self.assertIn('"wrappingWidth": 280', text)

    def test_the_theme_sets_the_label_size_itself_and_undoes_a_page_s_label_class(self) -> None:
        self.assertRegex(render.DIAGRAM_STYLE, r"\.nodeLabel, \.edgeLabel, \.edgeLabel p \{ font-size: 16px;")
        self.assertRegex(render.DIAGRAM_STYLE, r"\.label \{ padding: 0; font: inherit; white-space: normal; border: 0; border-radius: 0; \}")
        self.assertNotIn("__", render.DIAGRAM_STYLE)

    def test_badges_scale_with_the_text_and_never_wrap(self) -> None:
        self.assertNotRegex(render.DIAGRAM_STYLE, r"\.badge \{[^}]*font-size: \d+px")
        self.assertRegex(render.DIAGRAM_STYLE, r"\.badge \{[^}]*white-space: nowrap")

    def test_cluster_titles_are_three_quarters_of_the_text(self) -> None:
        self.assertRegex(render.DIAGRAM_STYLE, r"\.cluster-label[^}]*font-size: 12px")

    def test_the_theme_never_breaks_a_word_anywhere(self) -> None:
        self.assertNotIn("overflow-wrap", render.DIAGRAM_STYLE)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the diagram's label script")
class BreakPoints(unittest.TestCase):
    def broken(self, text: str) -> str:
        return run_node(render.DIAGRAM_STYLE + f"console.log(breakable({json.dumps(text)}));")

    def test_a_pascal_case_name_may_wrap_before_each_hump(self) -> None:
        self.assertEqual(self.broken("UntaggedInventoryUploadController"), "Untagged<wbr>Inventory<wbr>Upload<wbr>Controller")

    def test_a_camel_case_name_and_digits_may_wrap_at_the_humps(self) -> None:
        self.assertEqual(self.broken("applyRows2Bucket"), "apply<wbr>Rows2<wbr>Bucket")

    def test_an_acronym_stays_whole_before_the_next_word(self) -> None:
        self.assertEqual(self.broken("parseJSONBody"), "parse<wbr>JSON<wbr>Body")

    def test_a_dot_or_an_underscore_may_wrap_after_it(self) -> None:
        self.assertEqual(self.broken("pkg.Class_name"), "pkg.<wbr>Class_<wbr>name")

    def test_plain_words_are_left_alone(self) -> None:
        self.assertEqual(self.broken("builds the attribute row"), "builds the attribute row")

    def test_a_label_gets_the_break_points_in_its_second_line_only(self) -> None:
        text = "flowchart TD\n  a[\"1 · UploadControl<br/>CreatesNewBucket\"]"
        script_text = (render.DIAGRAM_STYLE + f"console.log(styleDiagramText({json.dumps(text)}));")
        out = run_node(script_text)
        self.assertIn("<span class='t'>UploadControl</span>", out)
        self.assertIn("<span class='s'>Creates<wbr>New<wbr>Bucket</span>", out)


if __name__ == "__main__":
    unittest.main()
