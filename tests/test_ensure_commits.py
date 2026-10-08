"""ensure_commits: where a commit missing from the mirror is fetched from, per host. Uses throwaway git
repositories with invented content. context_pack reads its settings when imported, so each check runs in a
subprocess with its own PR_BRIEF_HOME. Run with `python3 -m unittest discover -s tests`."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent
CHECK = """
import sys
sys.path.insert(0, {tool!r})
import context_pack as c
c.ensure_commits([{sha!r}], {host!r})
print(c.has_commit({sha!r}))
"""


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env).stdout.strip()


class EnsureCommitsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.checkout = root / "checkout"
        self.home = root / "home"
        self.home.mkdir()
        subprocess.run(["git", "init", "-q", str(self.checkout)], check=True)
        (self.checkout / "a.txt").write_text("one\n")
        git(self.checkout, "add", "a.txt")
        git(self.checkout, "commit", "-q", "-m", "first")
        (self.home / "local.toml").write_text(
            f'source_checkout = "{self.checkout}"\n'
            'github_url = "http://127.0.0.1:9/never-reached.git"\n')
        self.check("0" * 40, "forgejo")  # clones the mirror while it still lacks the next commit
        (self.checkout / "a.txt").write_text("two\n")
        git(self.checkout, "commit", "-q", "-am", "second")
        self.sha = git(self.checkout, "rev-parse", "HEAD")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def check(self, sha: str, host: str) -> bool:
        code = CHECK.format(tool=str(TOOL), sha=sha, host=host)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             env={**os.environ, "PR_BRIEF_HOME": str(self.home)})
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip() == "True"

    def test_forgejo_fetches_a_missing_commit_from_the_checkout(self) -> None:
        self.assertTrue(self.check(self.sha, "forgejo"))

    def test_github_asks_only_github_so_the_checkout_is_not_used(self) -> None:
        self.assertFalse(self.check(self.sha, "github"))

    def test_an_unknown_commit_stays_missing(self) -> None:
        self.assertFalse(self.check("1" * 40, "forgejo"))


if __name__ == "__main__":
    unittest.main()
