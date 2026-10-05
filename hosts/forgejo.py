"""Forgejo (or Gitea) through its REST API, read only. The base URL and the file holding the API token
come from local.toml (`forgejo_url`, `forgejo_token_file`). The token is sent in an `Authorization`
header and never appears in a URL, a message or a log line."""
import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PAGE_SIZE = 50
TIMEOUT_SECONDS = 60


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
        files: list[dict[str, Any]] = self._pages(f"{base}/files")
        return {
            "title": pull["title"],
            "body": pull.get("body") or "",
            "headRefName": pull["head"]["ref"],
            # The merge base is what the diff is taken against; the base branch's tip can have moved on.
            "baseRefOid": pull.get("merge_base") or pull["base"]["sha"],
            "headRefOid": pull["head"]["sha"],
            "commits": [{"oid": c["sha"], "messageHeadline": c["commit"]["message"].split("\n", 1)[0]} for c in commits],
            "files": [{"path": f["filename"], "additions": f["additions"], "deletions": f["deletions"],
                       "changeType": f["status"].upper()} for f in files],
        }

    def head_sha(self, owner: str, repo: str, n: int | str) -> str:
        """The PR's current head commit, from the pull request alone (no commits or files)."""
        return json.loads(self._get(f"/repos/{owner}/{repo}/pulls/{n}"))["head"]["sha"]

    def diff(self, owner: str, repo: str, n: int | str) -> str:
        return self._get(f"/repos/{owner}/{repo}/pulls/{n}.diff").decode("utf-8")

    # Forgejo's page ids are `diff-` plus the sha1 of the file's path, and its line anchors add the side and number.
    def diff_link(self, repo: str, pr: str, filename: str) -> str:
        return f"{self.url}/{repo}/pulls/{pr}/files#diff-{hashlib.sha1(filename.encode('utf-8')).hexdigest()}"

    def line_link(self, repo: str, pr: str, start: dict[str, Any]) -> str:
        digest: str = hashlib.sha1(start["path"].encode("utf-8")).hexdigest()
        return f"{self.url}/{repo}/pulls/{pr}/files#diff-{digest}{start['side']}{start['line']}"
