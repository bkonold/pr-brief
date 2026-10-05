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


class FakeForgejo(BaseHTTPRequestHandler):
    seen_auth: list[str | None] = []

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        FakeForgejo.seen_auth.append(self.headers.get("Authorization"))
        url = urlparse(self.path)
        query = parse_qs(url.query)
        prefix = "/api/v1/repos/acme/widgets/pulls/7"
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
        self.assertEqual(host.line_link("acme/widgets", "7", {"path": "src/Widget.java", "side": "L", "line": 12}), f"{link}L12")

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
