"""Tests for hosts/: run keys, the Forgejo reader against a local fake of its API, and the links.
Run with `python3 -m unittest discover -s tests` from the tool's folder. All data here is invented."""
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hosts import get_host, parse_run_key, run_key, run_label, run_order  # noqa: E402
from hosts.forgejo import PAGE_SIZE, Forgejo  # noqa: E402

TOKEN = "invented-token"
BASE_SHA = "b" * 40
HEAD_SHA = "c" * 40
MERGE_BASE = "a" * 40
DIFF = "diff --git a/src/Widget.java b/src/Widget.java\n--- a/src/Widget.java\n+++ b/src/Widget.java\n@@ -1 +1 @@\n-old\n+new\n"
FILE_COUNT = PAGE_SIZE + 3
MOVED_DIFF = (
    "diff --git a/src/Changed.java b/src/Changed.java\n--- a/src/Changed.java\n+++ b/src/Changed.java\n@@ -1,2 +1,3 @@\n"
    "-old\n+new\n+newer\n context\n"
    "diff --git a/src/Added.java b/src/Added.java\nnew file mode 100644\n--- /dev/null\n+++ b/src/Added.java\n@@ -0,0 +1 @@\n+first\n"
    "diff --git a/src/Gone.java b/src/Gone.java\ndeleted file mode 100644\n--- a/src/Gone.java\n+++ /dev/null\n@@ -1 +0,0 @@\n-bye\n"
    "diff --git a/src/Before.java b/src/After.java\nsimilarity index 90%\nrename from src/Before.java\nrename to src/After.java\n"
    "--- a/src/Before.java\n+++ b/src/After.java\n@@ -1 +1 @@\n-a\n+b\n")


class FakeForgejo(BaseHTTPRequestHandler):
    seen_auth: list[str | None] = []

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        FakeForgejo.seen_auth.append(self.headers.get("Authorization"))
        url = urlparse(self.path)
        query = parse_qs(url.query)
        prefix = "/api/v1/repos/acme/widgets/pulls/7"
        if url.path.startswith("/api/v1/repos/acme/widgets/pulls/8"):
            self.answer_moved_pr(url.path.removeprefix("/api/v1/repos/acme/widgets/pulls/8"))
            return
        if url.path == prefix:
            body = {"title": "Add widget", "body": None, "head": {"ref": "feature/widget", "sha": HEAD_SHA},
                    "base": {"ref": "main", "sha": BASE_SHA}, "merge_base": MERGE_BASE}
        elif url.path == f"{prefix}/commits":
            body = [{"sha": "d" * 40, "commit": {"message": "feat: add widget\n\nlong body"}}]
        elif url.path == f"{prefix}/files":
            page, limit = int(query["page"][0]), int(query["limit"][0])
            everything = [{"filename": f"src/File{i}.java", "status": "added" if i == 0 else "changed", "additions": i, "deletions": 0}
                          for i in range(FILE_COUNT)]
            body = everything[(page - 1) * limit:page * limit]
        elif url.path == f"{prefix}.diff":
            payload = DIFF.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        else:
            self.send_error(404)
            return
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


    def answer_moved_pr(self, rest: str) -> None:
        """A closed pull request whose head moved: its files list is empty but its diff is not."""
        if rest == ".diff":
            payload, kind = MOVED_DIFF.encode(), "text/plain; charset=utf-8"
        elif rest in ("", "/commits", "/files"):
            body = {"title": "Moved", "body": None, "head": {"ref": "feature/moved", "sha": HEAD_SHA},
                    "base": {"ref": "main", "sha": BASE_SHA}, "merge_base": MERGE_BASE} if rest == "" else []
            payload, kind = json.dumps(body).encode(), "application/json"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class ForgejoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeForgejo)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.tmp = tempfile.TemporaryDirectory()
        cls.token_file = Path(cls.tmp.name) / "token"
        cls.token_file.write_text(TOKEN + "\n")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.tmp.cleanup()

    def host(self) -> Forgejo:
        return Forgejo(self.url, str(self.token_file))

    def test_pr_has_the_shape_the_renderer_reads(self) -> None:
        pr = self.host().pr("acme", "widgets", 7)
        self.assertEqual(pr["title"], "Add widget")
        self.assertEqual(pr["body"], "")
        self.assertEqual(pr["headRefName"], "feature/widget")
        self.assertEqual(pr["baseRefOid"], MERGE_BASE)
        self.assertEqual(pr["headRefOid"], HEAD_SHA)
        self.assertEqual([c["messageHeadline"] for c in pr["commits"]], ["feat: add widget"])

    def test_files_are_paginated_and_mapped(self) -> None:
        files = self.host().pr("acme", "widgets", 7)["files"]
        self.assertEqual(len(files), FILE_COUNT)
        self.assertEqual(files[0], {"path": "src/File0.java", "additions": 0, "deletions": 0, "changeType": "ADDED"})
        self.assertEqual(files[-1]["path"], f"src/File{FILE_COUNT - 1}.java")
        self.assertEqual(files[1]["changeType"], "CHANGED")

    def test_an_empty_files_list_falls_back_to_the_files_of_the_diff(self) -> None:
        files = self.host().pr("acme", "widgets", 8)["files"]
        self.assertEqual(files, [
            {"path": "src/Changed.java", "additions": 2, "deletions": 1, "changeType": "CHANGED"},
            {"path": "src/Added.java", "additions": 1, "deletions": 0, "changeType": "ADDED"},
            {"path": "src/Gone.java", "additions": 0, "deletions": 1, "changeType": "DELETED"},
            {"path": "src/After.java", "additions": 1, "deletions": 1, "changeType": "RENAMED"},
        ])

    def test_a_files_list_that_has_entries_is_used_as_it_is(self) -> None:
        self.assertEqual(self.host().pr("acme", "widgets", 7)["files"][0]["path"], "src/File0.java")

    def test_diff_is_the_unified_diff(self) -> None:
        self.assertEqual(self.host().diff("acme", "widgets", 7), DIFF)

    def test_token_goes_only_in_the_authorization_header(self) -> None:
        FakeForgejo.seen_auth.clear()
        self.host().diff("acme", "widgets", 7)
        self.assertEqual(FakeForgejo.seen_auth, [f"token {TOKEN}"])

    def test_missing_pr_is_a_clear_error(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            self.host().pr("acme", "widgets", 999)
        self.assertIn("404", str(raised.exception))

    def test_links_use_the_sha1_of_the_path(self) -> None:
        host = Forgejo("http://forge.invalid/", None)
        link = host.diff_link("acme/widgets", "7", "src/Widget.java")
        self.assertTrue(link.startswith("http://forge.invalid/acme/widgets/pulls/7/files#diff-"))
        digest = link.rsplit("diff-", 1)[1]
        self.assertEqual(len(digest), 40)
        self.assertEqual(host.files_link("acme/widgets", "7"), "http://forge.invalid/acme/widgets/pulls/7/files")

    def test_forgejo_needs_a_url(self) -> None:
        with self.assertRaises(SystemExit):
            get_host("forgejo", {})


class RunKeyTest(unittest.TestCase):
    def test_keys(self) -> None:
        self.assertEqual(run_key("github", 42), "42")
        self.assertEqual(run_key("forgejo", "42"), "fj-42")
        self.assertEqual(parse_run_key("42"), ("github", 42))
        self.assertEqual(parse_run_key("fj-42"), ("forgejo", 42))
        self.assertIsNone(parse_run_key("index.html"))

    def test_github_numbers_sort_before_forgejo_ones_and_numerically(self) -> None:
        names = ["fj-3", "100", "9", "fj-12"]
        self.assertEqual(sorted(names, key=run_order), ["9", "100", "fj-3", "fj-12"])

    def test_labels(self) -> None:
        self.assertEqual(run_label("42"), "PR 42")
        self.assertEqual(run_label("fj-42"), "Forgejo PR 42")


if __name__ == "__main__":
    unittest.main()
