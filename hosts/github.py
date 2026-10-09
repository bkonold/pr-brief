"""GitHub through the `gh` CLI, which must be signed in."""
import hashlib
import json
import subprocess
from typing import Any

PR_FIELDS = "title,body,headRefName,baseRefOid,headRefOid,commits,files"


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


class GitHub:
    name = "github"

    def pr(self, owner: str, repo: str, n: int | str) -> dict[str, Any]:
        return json.loads(gh("pr", "view", str(n), "--repo", f"{owner}/{repo}", "--json", PR_FIELDS))

    def head_sha(self, owner: str, repo: str, n: int | str) -> str:
        """The PR's current head commit; one small read, without the commits and files `pr` fetches."""
        return json.loads(gh("pr", "view", str(n), "--repo", f"{owner}/{repo}", "--json", "headRefOid"))["headRefOid"]

    def diff(self, owner: str, repo: str, n: int | str) -> str:
        return gh("pr", "diff", str(n), "--repo", f"{owner}/{repo}")

    def files_link(self, repo: str, pr: str) -> str:
        return f"https://github.com/{repo}/pull/{pr}/files"

    def diff_link(self, repo: str, pr: str, filename: str) -> str:
        return f"https://github.com/{repo}/pull/{pr}/files#diff-{hashlib.sha256(filename.encode('utf-8')).hexdigest()}"
