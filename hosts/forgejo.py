"""Forgejo (or Gitea) through its REST API, read only. The base URL and the file holding the API token
come from local.toml (`forgejo_url`, `forgejo_token_file`). The token is sent in an `Authorization`
header and never appears in a URL, a message or a log line."""
import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PAGE_SIZE = 50
TIMEOUT_SECONDS = 60
DIFF_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")


def files_from_diff(diff: str) -> list[dict[str, Any]]:
    """The file list of a unified diff, in the shape `pr` returns: path (the new path of a rename), additions, deletions
    and changeType (ADDED, DELETED, RENAMED or CHANGED)."""
    files: list[dict[str, Any]] = []
    for line in diff.splitlines():
        header: re.Match[str] | None = DIFF_HEADER.match(line)
        if header:
            files.append({"path": header.group(2), "additions": 0, "deletions": 0, "changeType": "CHANGED"})
        elif not files:
            continue
        elif line.startswith("new file mode"):
            files[-1]["changeType"] = "ADDED"
        elif line.startswith("deleted file mode"):
            files[-1]["changeType"] = "DELETED"
        elif line.startswith("rename to "):
            files[-1].update(path=line.removeprefix("rename to "), changeType="RENAMED")
        elif line.startswith("+") and not line.startswith("+++ "):
            files[-1]["additions"] += 1
        elif line.startswith("-") and not line.startswith("--- "):
            files[-1]["deletions"] += 1
    return files


class Forgejo:
    name = "forgejo"

    def __init__(self, url: str | None, token_file: str | None) -> None:
        if not url:
            raise SystemExit("local.toml sets no forgejo_url")
        self.url: str = url.rstrip("/")
        self.token_file: Path | None = Path(token_file).expanduser() if token_file else None

    def _token(self) -> str | None:
        if self.token_file is None:
            return None
        try:
            return self.token_file.read_text().strip()
        except OSError as e:
            raise SystemExit(f"cannot read forgejo_token_file {self.token_file}: {e.strerror}") from None

    def _get(self, path: str) -> bytes:
        headers: dict[str, str] = {}
        token: str | None = self._token()
        if token:
            headers["Authorization"] = f"token {token}"
        request = urllib.request.Request(f"{self.url}/api/v1{path}", headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            raise SystemExit(f"Forgejo answered {e.code} for GET {path}") from None
        except urllib.error.URLError as e:
            raise SystemExit(f"cannot reach Forgejo at {self.url}: {e.reason}") from None

    def _pages(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page: int = 1
        while True:
            batch: list[dict[str, Any]] = json.loads(self._get(f"{path}?page={page}&limit={PAGE_SIZE}"))
            items.extend(batch)
            if len(batch) < PAGE_SIZE:
                return items
            page += 1

    def pr(self, owner: str, repo: str, n: int | str) -> dict[str, Any]:
        base: str = f"/repos/{owner}/{repo}/pulls/{n}"
        pull: dict[str, Any] = json.loads(self._get(base))
        commits: list[dict[str, Any]] = self._pages(f"{base}/commits")
        listed: list[dict[str, Any]] = [
            {"path": f["filename"], "additions": f["additions"], "deletions": f["deletions"], "changeType": f["status"].upper()}
            for f in self._pages(f"{base}/files")]
        # A closed pull request whose head has moved can list no files here while its diff still has them.
        files: list[dict[str, Any]] = listed or files_from_diff(self.diff(owner, repo, n))
        return {
            "title": pull["title"],
            "body": pull.get("body") or "",
            "headRefName": pull["head"]["ref"],
            # The merge base is what the diff is taken against; the base branch's tip can have moved on.
            "baseRefOid": pull.get("merge_base") or pull["base"]["sha"],
            "headRefOid": pull["head"]["sha"],
            "commits": [{"oid": c["sha"], "messageHeadline": c["commit"]["message"].split("\n", 1)[0]} for c in commits],
            "files": files,
        }

    def head_sha(self, owner: str, repo: str, n: int | str) -> str:
        """The PR's current head commit, from the pull request alone (no commits or files)."""
        return json.loads(self._get(f"/repos/{owner}/{repo}/pulls/{n}"))["head"]["sha"]

    def diff(self, owner: str, repo: str, n: int | str) -> str:
        return self._get(f"/repos/{owner}/{repo}/pulls/{n}.diff").decode("utf-8")

    def files_link(self, repo: str, pr: str) -> str:
        return f"{self.url}/{repo}/pulls/{pr}/files"

    # Forgejo's page ids are `diff-` plus the sha1 of the file's path.
    def diff_link(self, repo: str, pr: str, filename: str) -> str:
        return f"{self.url}/{repo}/pulls/{pr}/files#diff-{hashlib.sha1(filename.encode('utf-8')).hexdigest()}"
