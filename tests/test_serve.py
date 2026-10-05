"""Tests for serve.py and run_status.py: authentication, input checks, the allow-list, one run per key, the
cap on simultaneous runs, cancel and recovery. Runs are started with a fake runner script, never run.py.
Run with `python3 -m unittest discover -s tests` from the tool's folder. All data here is invented."""
import http.client
import json
import os
import stat
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run  # noqa: E402
import run_status  # noqa: E402
import serve  # noqa: E402

TOKEN = "invented-server-token"
ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
ROOT = Path(__file__).resolve().parent.parent

FAKE_RUNNER = textwrap.dedent(f"""
    import subprocess, sys, time
    from pathlib import Path
    sys.path.insert(0, {str(ROOT)!r})
    import run_status
    home, key, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    with open(home / "starts.txt", "a") as starts:
        starts.write(key + "\\n")
    if mode == "quick":
        for stage in run_status.STAGES:
            run_status.write_status(home, key, state="running", stage=stage)
        run_status.write_status(home, key, state="done", finished=time.time())
    elif mode == "silent":
        pass
    elif mode == "broken":
        print("first line")
        print("claude exited with status 1: invented failure")
        sys.exit(1)
    else:
        child = subprocess.Popen(["sleep", "60"])
        (home / f"child-{{key}}.pid").write_text(str(child.pid))
        time.sleep(60)
""")


class Client:
    def __init__(self, port: int) -> None:
        self.port = port

    def call(self, method: str, path: str, body: Any = None, *, token: str | None = TOKEN, origin: str | None = ORIGIN,
             raw: bytes | None = None) -> tuple[int, Any]:
        headers: dict[str, str] = {}
        if token is not None:
            headers[serve.TOKEN_HEADER] = token
        if origin is not None:
            headers["Origin"] = origin
        payload: bytes | None = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if payload is not None:
            headers["Content-Type"] = "application/json"
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            data: bytes = response.read()
            try:
                return response.status, json.loads(data)
            except ValueError:
                return response.status, data
        finally:
            connection.close()

    def run(self, host: str, repo: str, n: int, **options: Any) -> tuple[int, Any]:
        owner, _, name = repo.partition("/")
        return self.call("POST", "/api/run", {"host": host, "owner": owner, "repo": name, "n": n}, **options)


class ServeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / "runs").mkdir()
        (self.home / "hello.txt").write_text("static file")
        self.fake = self.home / "fake_runner.py"
        self.fake.write_text(FAKE_RUNNER)
        allowed = serve.parse_serve_repos({"github": ["acme/quick", "Acme/Slow", "acme/broken", "acme/silent"], "forgejo": ["me/slow"]})
        self.runner = serve.Runner(self.home, allowed, self.argv_for, max_running=2)
        self.server = serve.make_server(self.home, self.runner, TOKEN, 0)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        self.addCleanup(self.stop)
        self.client = Client(self.server.server_address[1])

    def stop(self) -> None:
        self.runner.stop_all()
        self.server.shutdown()
        self.server.server_close()

    def argv_for(self, host: str, owner: str, repo: str, n: int) -> list[str]:
        return [sys.executable, str(self.fake), str(self.home), serve.run_key(host, n), repo.lower()]

    def wait_for(self, condition: Any, what: str, seconds: float = 10) -> None:
        deadline: float = time.time() + seconds
        while time.time() < deadline:
            if condition():
                return
            time.sleep(0.05)
        self.fail(f"timed out waiting for {what}")

    def state(self, key: str) -> str:
        return self.client.call("GET", f"/api/status?key={key}")[1]["state"]

    def starts(self) -> list[str]:
        path = self.home / "starts.txt"
        return path.read_text().split() if path.exists() else []

    def test_static_files_need_no_token(self) -> None:
        status, body = self.client.call("GET", "/hello.txt", token=None, origin=None)
        self.assertEqual((status, body), (200, b"static file"))

    def test_api_needs_the_token_and_an_extension_origin(self) -> None:
        for token, origin in [(None, ORIGIN), ("wrong", ORIGIN), (TOKEN + "x", ORIGIN), ("", ORIGIN),
                              (TOKEN, None), (TOKEN, "https://github.com"), (TOKEN, "http://localhost:3300"),
                              (TOKEN, "chrome-extension:/x")]:
            with self.subTest(token=token, origin=origin):
                self.assertEqual(self.client.call("GET", "/api/status?key=7", token=token, origin=origin)[0], 403)
                self.assertEqual(self.client.run("github", "acme/quick", 7, token=token, origin=origin)[0], 403)
                self.assertEqual(self.client.call("POST", "/api/cancel", {"key": "7"}, token=token, origin=origin)[0], 403)
        self.assertEqual(self.starts(), [])
        self.assertEqual(self.client.call("GET", "/api/status?key=7")[0], 200)

    def test_unknown_endpoints_and_methods(self) -> None:
        self.assertEqual(self.client.call("GET", "/api/other")[0], 404)
        self.assertEqual(self.client.call("GET", "/api/run")[0], 405)
        self.assertEqual(self.client.call("POST", "/hello.txt", {})[0], 405)

    def test_input_is_validated(self) -> None:
        good: dict[str, Any] = {"host": "github", "owner": "acme", "repo": "quick", "n": 5}
        bad: list[dict[str, Any]] = [
            {**good, "host": "gitlab"}, {**good, "host": None}, {**good, "n": 0}, {**good, "n": -3}, {**good, "n": "5"},
            {**good, "n": 1.5}, {**good, "n": True}, {**good, "n": 10**12}, {**good, "owner": "a b"}, {**good, "owner": "../x"},
            {**good, "repo": "quick; rm -rf /"}, {**good, "repo": "-x"}, {**good, "owner": 3}, {**good, "repo": ""},
            {k: v for k, v in good.items() if k != "n"}, [1, 2],
        ]
        for body in bad:
            with self.subTest(body=body):
                status, answer = self.client.call("POST", "/api/run", body)
                self.assertEqual((status, answer["error"]), (400, "bad_request"))
        for raw in (b"not json", b"", b"x" * (serve.MAX_BODY_BYTES + 1)):
            with self.subTest(raw=raw[:10]):
                self.assertEqual(self.client.call("POST", "/api/run", raw=raw)[0], 400)
        self.assertEqual(self.starts(), [])
        self.assertEqual(self.client.call("GET", "/api/status?key=abc")[0], 400)
        self.assertEqual(self.client.call("GET", "/api/status?key=fj-")[0], 400)
        self.assertEqual(self.client.call("GET", "/api/status")[0], 400)
        self.assertEqual(self.client.call("POST", "/api/cancel", {"key": "../x"})[0], 400)

    def test_only_allow_listed_repos_start_runs(self) -> None:
        for host, repo in [("github", "acme/other"), ("github", "other/quick"), ("forgejo", "acme/quick"), ("github", "me/slow")]:
            with self.subTest(host=host, repo=repo):
                status, answer = self.client.run(host, repo, 5)
                self.assertEqual((status, answer["error"]), (403, "repo_not_allowed"))
        self.assertEqual(self.starts(), [])
        self.assertEqual(self.client.run("github", "ACME/quick", 5)[0], 200)

    def test_status_says_whether_a_repo_is_allowed(self) -> None:
        status, answer = self.client.call("GET", "/api/status?key=fj-3&host=forgejo&owner=me&repo=slow")
        self.assertEqual((status, answer["state"], answer["allowed"]), (200, "idle", True))
        self.assertFalse(self.client.call("GET", "/api/status?key=3&host=github&owner=me&repo=slow")[1]["allowed"])
        self.assertNotIn("allowed", self.client.call("GET", "/api/status?key=3")[1])
        self.assertEqual(self.client.call("GET", "/api/status?key=3&host=github&owner=a%20b&repo=x")[0], 400)

    def test_a_run_passes_through_its_stages_to_done(self) -> None:
        status, answer = self.client.run("github", "acme/quick", 41)
        self.assertEqual((status, answer), (200, {"key": "41", "state": "running"}))
        self.wait_for(lambda: self.state("41") == "done", "the run to finish")
        answer = self.client.call("GET", "/api/status?key=41")[1]
        self.assertEqual((answer["state"], answer["stage"], isinstance(answer["elapsed"], int), "error" in answer), ("done", "render", True, False))
        self.assertEqual(self.client.call("GET", "/api/status?key=99")[1], {"key": "99", "state": "idle"})

    def test_a_forgejo_run_is_keyed_with_its_prefix(self) -> None:
        self.assertEqual(self.client.run("forgejo", "me/slow", 12)[1], {"key": "fj-12", "state": "running"})
        self.wait_for(lambda: (self.home / "child-fj-12.pid").exists(), "the fake run to start")
        self.assertEqual(self.state("fj-12"), "running")
        self.assertEqual(self.state("12"), "idle")

    def test_a_second_post_for_a_running_key_starts_nothing(self) -> None:
        first = self.client.run("github", "acme/slow", 5)
        second = self.client.run("github", "acme/slow", 5)
        self.assertEqual((first, second), ((200, {"key": "5", "state": "running"}),) * 2)
        self.wait_for(lambda: self.starts() == ["5"], "one start")
        time.sleep(0.3)
        self.assertEqual(self.starts(), ["5"])

    def test_at_most_two_runs_at_once(self) -> None:
        self.assertEqual(self.client.run("github", "acme/slow", 1)[0], 200)
        self.assertEqual(self.client.run("github", "acme/slow", 2)[0], 200)
        status, answer = self.client.run("github", "acme/slow", 3)
        self.assertEqual((status, answer["error"], answer["message"]), (429, "busy", "2 briefs already running"))
        self.assertEqual(self.state("3"), "idle")
        self.assertEqual(self.client.run("github", "acme/slow", 1)[0], 200)
        self.client.call("POST", "/api/cancel", {"key": "1"})
        self.wait_for(lambda: not self.runner.jobs["1"].running(), "run 1 to end")
        self.assertEqual(self.client.run("github", "acme/slow", 3)[0], 200)

    def test_cancel_kills_the_whole_process_group(self) -> None:
        self.client.run("github", "acme/slow", 6)
        pid_file = self.home / "child-6.pid"
        self.wait_for(pid_file.exists, "the run's child to start")
        child: int = int(pid_file.read_text())
        os.kill(child, 0)
        status, answer = self.client.call("POST", "/api/cancel", {"key": "6"})
        self.assertEqual((status, answer), (200, {"key": "6", "state": "canceled"}))
        self.assertEqual(self.state("6"), "canceled")

        def gone() -> bool:
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                return True
            return False

        self.wait_for(gone, "the child to die")
        self.wait_for(lambda: not self.runner.jobs["6"].running(), "the run to end")
        time.sleep(0.2)
        self.assertEqual(self.state("6"), "canceled")

    def test_cancel_of_a_run_that_is_not_running_changes_nothing(self) -> None:
        self.client.run("github", "acme/quick", 8)
        self.wait_for(lambda: self.state("8") == "done", "the run to finish")
        self.assertEqual(self.client.call("POST", "/api/cancel", {"key": "8"})[1], {"key": "8", "state": "done"})
        self.assertEqual(self.client.call("POST", "/api/cancel", {"key": "77"})[1], {"key": "77", "state": "idle"})

    def test_a_run_that_dies_without_a_status_is_marked_failed_with_its_last_line(self) -> None:
        self.client.run("github", "acme/broken", 10)
        self.wait_for(lambda: self.state("10") == "failed", "the run to fail")
        answer = self.client.call("GET", "/api/status?key=10")[1]
        self.assertEqual(answer["error"], "claude exited with status 1: invented failure")

    def test_a_run_that_exits_cleanly_without_a_status_is_marked_done(self) -> None:
        self.client.run("github", "acme/silent", 11)
        self.wait_for(lambda: self.state("11") == "done", "the run to be settled")

    def test_a_rerun_forgets_the_earlier_failure(self) -> None:
        self.client.run("github", "acme/broken", 10)
        self.wait_for(lambda: self.state("10") == "failed", "the run to fail")
        self.client.run("github", "acme/broken", 10)
        self.wait_for(lambda: self.starts().count("10") == 2, "the second start")
        self.wait_for(lambda: self.state("10") == "failed", "the second failure")

    def test_startup_marks_runs_left_running_as_failed(self) -> None:
        run_status.begin_status(self.home, "31")
        run_status.begin_status(self.home, "fj-32", stage="write")
        run_status.write_status(self.home, "33", state="done", stage="render", finished=time.time())
        self.assertEqual(self.runner.recover(), ["31", "fj-32"])
        for key in ("31", "fj-32"):
            answer = self.client.call("GET", f"/api/status?key={key}")[1]
            self.assertEqual((answer["state"], answer["error"]), ("failed", "server restarted"))
        self.assertEqual(self.state("33"), "done")
        self.assertEqual(self.runner.recover(), [])


class ProgressTest(unittest.TestCase):
    """run.py's Progress, which writes the status the server reads."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        patch = mock.patch.object(run, "HOME", self.home)
        patch.start()
        self.addCleanup(patch.stop)

    def status(self, key: str = "7") -> dict[str, Any]:
        return run_status.read_status(self.home, key) or {}

    def test_stages_then_done(self) -> None:
        progress = run.Progress()
        progress.begin("7")
        self.assertEqual((self.status()["state"], self.status()["stage"]), ("running", "fetch"))
        started = self.status()["started"]
        for stage in ("context", "write", "render"):
            progress.stage(stage)
            self.assertEqual(self.status()["stage"], stage)
        progress.finish(0)
        self.assertEqual((self.status()["state"], self.status()["started"] == started, "finished" in self.status()), ("done", True, True))

    def test_a_status_the_server_made_keeps_its_start_time(self) -> None:
        run_status.begin_status(self.home, "7", started=1000.0)
        run.Progress().begin("7")
        self.assertEqual(self.status()["started"], 1000.0)

    def test_a_new_run_forgets_the_last_failure(self) -> None:
        run_status.write_status(self.home, "7", state="failed", error="old", finished=5.0)
        run.Progress().begin("7")
        self.assertEqual(self.status(), {**self.status(), "state": "running", "stage": "fetch"})
        self.assertNotIn("error", self.status())
        self.assertNotIn("finished", self.status())

    def test_failure_records_the_last_line_of_the_error(self) -> None:
        progress = run.Progress()
        progress.begin("7")
        progress.finish(1, "usage: run.py\n\nrun.py: error: invented problem\n")
        self.assertEqual((self.status()["state"], self.status()["error"]), ("failed", "run.py: error: invented problem"))
        progress.begin("7")
        progress.error = "claude exited with status 1: invented"
        progress.finish(1)
        self.assertEqual(self.status()["error"], "claude exited with status 1: invented")
        progress = run.Progress()
        progress.begin("7")
        progress.finish(3)
        self.assertEqual(self.status()["error"], "run exited with status 3")

    def test_a_canceled_run_is_not_overwritten(self) -> None:
        progress = run.Progress()
        progress.begin("7")
        run_status.write_status(self.home, "7", state="canceled", finished=1.0)
        progress.stage("write")
        progress.finish(0)
        self.assertEqual(self.status()["state"], "canceled")

    def test_without_begin_nothing_is_written(self) -> None:
        progress = run.Progress()
        progress.stage("write")
        progress.finish(0)
        self.assertFalse((self.home / "runs").exists())


class TokenFileTest(unittest.TestCase):
    def test_a_token_is_created_with_private_permissions_and_then_reused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sub" / "token"
            token = serve.load_token(path)
            self.assertGreaterEqual(len(token), 32)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(serve.load_token(path), token)

    def test_loose_permissions_are_tightened_and_an_empty_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "token"
            path.write_text("kept-token\n")
            path.chmod(0o644)
            self.assertEqual(serve.load_token(path), "kept-token")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            path.write_text("\n")
            with self.assertRaises(SystemExit):
                serve.load_token(path)


class ServeReposTest(unittest.TestCase):
    def test_serve_repos_shape(self) -> None:
        self.assertEqual(serve.parse_serve_repos(None), {})
        self.assertEqual(serve.parse_serve_repos({"github": ["A/b"]}), {"github": frozenset({"a/b"})})
        for bad in (["a/b"], {"gitlab": ["a/b"]}, {"github": "a/b"}, {"github": ["ab"]}, {"github": [3]}):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                serve.parse_serve_repos(bad)


if __name__ == "__main__":
    unittest.main()
