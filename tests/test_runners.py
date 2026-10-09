"""Tests for runners.py (how a prompt is sent to claude or copilot, where the run is written and how a copilot answer is
cleaned) and for compare.py's copilot column. No model is called. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import compare  # noqa: E402
import run  # noqa: E402
import runners  # noqa: E402

SYSTEM = "You write PR descriptions."
USER = "Describe this diff."
ANSWER = "type:\n  - Enhancement\ndescription: |\n  Adds a thing.\n"
TOKENS = {"GH_TOKEN": "ghp_classic", "GITHUB_TOKEN": "ghp_other", "COPILOT_GITHUB_TOKEN": "keep", "PATH": "/bin", "HOME": "/home/x"}


class CommandTest(unittest.TestCase):
    def test_claude_keeps_its_command_with_the_user_prompt_on_stdin_and_the_environment_untouched(self) -> None:
        call = runners.invocation("claude", SYSTEM, USER, "opus", TOKENS)
        self.assertEqual(call.argv, ["claude", "-p", "--system-prompt", SYSTEM, "--tools", "", "--model", "opus"])
        self.assertEqual((call.input, call.env), (USER, None))

    def test_the_copilot_command_line_is_shell_quoted_and_holds_neither_a_token_nor_a_prompt(self) -> None:
        line = runners.command_line(runners.invocation("copilot", SYSTEM, USER, "claude-opus-5.5", TOKENS))
        self.assertTrue(line.startswith("copilot -p '"))
        self.assertIn("--model claude-opus-5.5 -s --available-tools=", line)
        for secret in ("ghp_classic", "ghp_other", "keep", SYSTEM, USER):
            self.assertNotIn(secret, line)

    def test_copilot_sends_the_model_and_silent_flags_with_no_tools_and_no_prompt_text_in_the_arguments(self) -> None:
        call = runners.invocation("copilot", SYSTEM, USER, "claude-opus-5.5", TOKENS)
        self.assertEqual(call.argv[:2], ["copilot", "-p"])
        self.assertEqual(call.argv[2], runners.COPILOT_PROMPT)
        self.assertEqual(call.argv[3:6], ["--model", "claude-opus-5.5", "-s"])
        self.assertIn("--available-tools=", call.argv)
        for flag in ("--allow-all-tools", "--allow-all", "--yolo"):
            self.assertNotIn(flag, call.argv)
        for argument in call.argv:
            self.assertNotIn(SYSTEM, argument)
            self.assertNotIn(USER, argument)

    def test_copilot_gets_the_system_prompt_in_its_own_block_ahead_of_the_user_prompt_on_stdin(self) -> None:
        text = runners.invocation("copilot", SYSTEM, USER, "m", TOKENS).input
        self.assertEqual(
            text,
            f"{runners.SYSTEM_OPEN}\n{SYSTEM}\n{runners.SYSTEM_CLOSE}\n\n{runners.USER_OPEN}\n\n{USER}",
        )
        self.assertLess(text.index(SYSTEM), text.index(USER))

    def test_copilot_runs_without_the_github_tokens_and_with_the_rest_of_the_environment(self) -> None:
        env = runners.invocation("copilot", SYSTEM, USER, "m", TOKENS).env
        self.assertEqual(env, {"COPILOT_GITHUB_TOKEN": "keep", "PATH": "/bin", "HOME": "/home/x"})
        self.assertEqual(TOKENS["GH_TOKEN"], "ghp_classic")

    def test_no_token_value_appears_in_the_command_or_the_input(self) -> None:
        call = runners.invocation("copilot", SYSTEM, USER, "m", TOKENS)
        for value in TOKENS.values():
            if value.startswith("ghp_"):
                self.assertNotIn(value, " ".join(call.argv) + call.input)

    def test_an_unknown_runner_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            runners.invocation("gemini", SYSTEM, USER, "m", {})

    def test_each_runner_has_a_default_model(self) -> None:
        self.assertEqual(runners.DEFAULT_MODELS, {"claude": "claude-opus-5-5", "copilot": "claude-opus-5.5"})

    def test_the_flag_wins_over_local_toml_which_wins_over_the_default(self) -> None:
        local = {"model": {"claude": "claude-from-local"}}
        self.assertEqual(runners.resolve_model("claude", "from-flag", local), "from-flag")
        self.assertEqual(runners.resolve_model("claude", None, local), "claude-from-local")
        self.assertEqual(runners.resolve_model("copilot", None, local), "claude-opus-5.5")
        self.assertEqual(runners.resolve_model("claude", None, {}), "claude-opus-5-5")

    def test_a_local_toml_model_that_is_not_a_table_of_runners_is_refused(self) -> None:
        for bad in ("claude-opus-5-5", {"gemini": "m"}, {"claude": ""}, {"claude": 5}):
            with self.assertRaises(ValueError):
                runners.resolve_model("claude", None, {"model": bad})


class RunDirTest(unittest.TestCase):
    def test_a_claude_run_keeps_the_variant_name_and_a_copilot_run_sits_beside_it(self) -> None:
        self.assertEqual(runners.run_dir_name("diagram_walkthrough_v24", "claude"), "diagram_walkthrough_v24")
        self.assertEqual(runners.run_dir_name("diagram_walkthrough_v24", "copilot"), "diagram_walkthrough_v24_copilot")


class CleanAnswerTest(unittest.TestCase):
    def test_claude_output_is_never_changed(self) -> None:
        text = f"Here you go:\n```yaml\n{ANSWER}```\n"
        self.assertEqual(runners.clean_answer("claude", text), (text, None))

    def test_a_copilot_answer_that_is_already_yaml_is_used_as_it_is(self) -> None:
        self.assertEqual(runners.clean_answer("copilot", ANSWER), (ANSWER, None))

    def test_a_fence_around_the_whole_answer_is_left_for_the_renderer_to_strip(self) -> None:
        fenced = f"```yaml\n{ANSWER}```"
        self.assertEqual(runners.clean_answer("copilot", fenced), (fenced, None))

    def test_a_fenced_block_inside_prose_is_taken_out_and_the_removal_is_named(self) -> None:
        wrapped = f"Sure, here is the description.\n\n```yaml\n{ANSWER}```\n\nLet me know if you want changes.\n"
        cleaned, note = runners.clean_answer("copilot", wrapped)
        self.assertEqual(cleaned, ANSWER)
        self.assertEqual(note, "took the first fenced yaml block out of the text around it")

    def test_text_with_no_yaml_in_it_is_passed_on_unchanged_to_fail_in_the_renderer(self) -> None:
        text = "I cannot do that.\n"
        self.assertEqual(runners.clean_answer("copilot", text), (text, None))


class CompareColumnTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.runs = self.home / "runs"
        (self.home / "compare.toml").write_text('variants = ["one", "two"]\n')
        for name, extra in (("one", {}), ("one_copilot", {"runner": "copilot", "model": "claude-opus-5.5"}), ("two", {})):
            run_dir = self.runs / "fj-7" / name
            run_dir.mkdir(parents=True)
            (run_dir / "body.md").write_text("# t\n")
            (run_dir / "pr.json").write_text(json.dumps({"title": "A PR"}))
            variant = name.removesuffix("_copilot")
            (run_dir / "run.json").write_text(json.dumps({"variant": variant, "started": "2026-10-08T10:00:00+00:00", "with_body": False, **extra}))
        for name, value in (("HOME", self.home), ("RUNS", self.runs), ("ARCHETYPES", None)):
            patch = mock.patch.object(compare, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def page(self, *argv: str) -> str:
        with mock.patch.object(sys, "argv", ["compare.py", "fj-7", *argv]):
            self.assertEqual(compare.main(), 0)
        return (self.runs / "fj-7" / "index.html").read_text()

    def test_the_copilot_run_is_its_own_column_right_after_its_variant_with_the_runner_and_model_named(self) -> None:
        html = self.page()
        positions = [html.index(f"<strong>{n}</strong>") for n in ("one", "one_copilot", "two")]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('src="one_copilot/body.html"', html)
        self.assertIn("copilot claude-opus-5.5", html)
        self.assertEqual(html.count("copilot claude-opus-5.5"), 1)
        self.assertIn("repeat(3,", html)

    def test_a_claude_only_pr_shows_no_runner(self) -> None:
        import shutil
        shutil.rmtree(self.runs / "fj-7" / "one_copilot")
        html = self.page()
        self.assertIn("repeat(2,", html)
        self.assertNotIn("claude-opus", html)

    def test_the_variants_list_for_the_extension_does_not_gain_the_copilot_run(self) -> None:
        (self.runs / "fj-7" / "one" / "review.json").write_text("{}")
        (self.runs / "fj-7" / "one_copilot" / "review.json").write_text("{}")
        self.page()
        listed = [entry["variant"] for entry in json.loads((self.runs / "fj-7" / "variants.json").read_text())]
        self.assertEqual(listed, ["one"])


class FakeHost:
    def pr(self, owner: str, name: str, number: str) -> dict:
        return {"title": "A PR", "body": "", "headRefName": "feature", "headRefOid": "a" * 40, "baseRefOid": "b" * 40,
                "commits": [{"messageHeadline": "Add a thing"}], "files": [{"path": "a.js"}]}

    def diff(self, owner: str, name: str, number: str) -> str:
        return "diff --git a/a.js b/a.js\n"


class RunTest(unittest.TestCase):
    """run.py with the host and the subprocesses replaced: where a copilot run is written and what it records."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        variant = self.home / "v.toml"
        variant.write_text('description = "x"\n')
        self.calls: list[dict] = []
        self.model_output = ANSWER

        def fake_run(argv, **kwargs):
            self.calls.append({"argv": argv, **kwargs})
            if argv[0] == "copilot":
                return subprocess.CompletedProcess(argv, 0, self.model_output, "")
            return subprocess.CompletedProcess(argv, 0)

        patches = [
            mock.patch.object(run, "HOME", self.home),
            mock.patch.object(run, "variant_file", lambda name: variant),
            mock.patch.object(run, "get_host", lambda *args: FakeHost()),
            mock.patch.object(run, "load_local", lambda: {}),
            mock.patch.object(run, "write_variants_json", lambda *args: None),
            mock.patch.object(run.subprocess, "run", fake_run),
            mock.patch.dict(run.os.environ, {"GH_TOKEN": "ghp_classic", "GITHUB_TOKEN": "ghp_other"}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def execute(self, *extra: str) -> int:
        with mock.patch.object(sys, "argv", ["run.py", "7", "--variant", "v", "--repo", "acme/widgets", *extra]):
            return run.execute(run.Progress())

    def test_a_copilot_run_is_written_beside_the_claude_run_and_records_its_runner_and_model(self) -> None:
        claude_dir = self.home / "runs" / "7" / "v"
        claude_dir.mkdir(parents=True)
        (claude_dir / "answer.yaml").write_text("claude's answer")
        self.assertEqual(self.execute("--runner", "copilot"), 0)
        self.assertEqual((claude_dir / "answer.yaml").read_text(), "claude's answer")
        run_dir = self.home / "runs" / "7" / "v_copilot"
        record = json.loads((run_dir / "run.json").read_text())
        self.assertEqual((record["variant"], record["runner"], record["model"], record["exit_status"]), ("v", "copilot", "claude-opus-5.5", 0))
        self.assertNotIn("answer_cleanup", record)
        self.assertEqual((run_dir / "answer.yaml").read_text(), ANSWER)
        self.assertEqual(self.calls[1]["argv"][-1], str(run_dir))

    def test_the_copilot_command_gets_the_prompt_on_stdin_and_no_github_token(self) -> None:
        self.execute("--runner", "copilot")
        call = self.calls[0]
        self.assertEqual(call["argv"][:5], ["copilot", "-p", runners.COPILOT_PROMPT, "--model", "claude-opus-5.5"])
        self.assertTrue(call["input"].startswith(runners.SYSTEM_OPEN))
        self.assertIn(runners.USER_OPEN, call["input"])
        self.assertNotIn("GH_TOKEN", call["env"])
        self.assertNotIn("GITHUB_TOKEN", call["env"])

    def test_a_model_flag_overrides_the_runner_default(self) -> None:
        self.execute("--runner", "copilot", "--model", "gpt-5")
        self.assertEqual(self.calls[0]["argv"][3:5], ["--model", "gpt-5"])

    def test_prose_around_the_yaml_is_stripped_into_answer_yaml_and_recorded_with_the_raw_text_kept(self) -> None:
        self.model_output = f"Here it is:\n```yaml\n{ANSWER}```\nDone.\n"
        self.execute("--runner", "copilot")
        run_dir = self.home / "runs" / "7" / "v_copilot"
        self.assertEqual((run_dir / "answer.yaml").read_text(), ANSWER)
        self.assertEqual((run_dir / "answer.raw.txt").read_text(), self.model_output)
        self.assertEqual(json.loads((run_dir / "run.json").read_text())["answer_cleanup"], "took the first fenced yaml block out of the text around it")

    def test_local_toml_picks_the_model_a_run_records_and_passes(self) -> None:
        with mock.patch.object(run, "load_local", lambda: {"model": {"claude": "claude-from-local"}}), \
                mock.patch.object(run.subprocess, "run", lambda argv, **kwargs: (self.calls.append({"argv": argv, **kwargs}), subprocess.CompletedProcess(argv, 0, ANSWER, ""))[1]):
            self.assertEqual(self.execute(), 0)
        self.assertEqual(self.calls[0]["argv"][-2:], ["--model", "claude-from-local"])
        self.assertEqual(json.loads((self.home / "runs" / "7" / "v" / "run.json").read_text())["model"], "claude-from-local")

    def test_a_pr_with_no_files_stops_before_the_model_is_called(self) -> None:
        empty = FakeHost()
        empty.pr = lambda *args: {**FakeHost.pr(empty, *args), "files": []}
        with mock.patch.object(run, "get_host", lambda *args: empty):
            with self.assertRaises(SystemExit) as stopped:
                self.execute()
        self.assertIn("lists no files for PR 7", str(stopped.exception))
        self.assertEqual(self.calls, [])

    def test_a_claude_run_keeps_its_folder_and_its_command(self) -> None:
        with mock.patch.object(run.subprocess, "run", lambda argv, **kwargs: (self.calls.append({"argv": argv, **kwargs}), subprocess.CompletedProcess(argv, 0, ANSWER, ""))[1]):
            self.assertEqual(self.execute(), 0)
        self.assertEqual(self.calls[0]["argv"][:2], ["claude", "-p"])
        self.assertIsNone(self.calls[0]["env"])
        record = json.loads((self.home / "runs" / "7" / "v" / "run.json").read_text())
        self.assertEqual((record["runner"], record["model"]), ("claude", "claude-opus-5-5"))
        self.assertEqual(self.calls[0]["argv"][-2:], ["--model", "claude-opus-5-5"])
        self.assertFalse((self.home / "runs" / "7" / "v_copilot").exists())


if __name__ == "__main__":
    unittest.main()
