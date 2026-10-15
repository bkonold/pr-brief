#!/usr/bin/env python3
"""Post a run's brief as one comment on its pull request, or update the comment that an earlier run left.

usage: post.py <run dir> [--repo owner/name] [--pr N] [--dry-run]
       post.py --find-only --repo owner/name --pr N

<run dir> is a run folder (it has review.json), or the PR's `runs/<n>` folder, whose newest run is used.
--repo and --pr default to the run's own. --dry-run prints the comment and posts nothing; without it the program calls
`gh api`, which reads GH_TOKEN from the environment.

The comment is one collapsed "PR Brief · AI-generated" details element, whose summary line names the variant and the head commit. It holds the
diagram as a ```mermaid fence (the run's diagram.md), which GitHub draws itself, any notes and a collapsed "Brief data" block; a hidden
`<!-- pr-brief:v1 -->` marker follows it. The block is a code fence holding the base64 of the gzip of review.json plus the run's
`diagram.svg` (as the key `diagram_svg`, null when the run has none); the browser extension reads the brief from it, which is
where the walkthrough and the layers are. The comment that gets updated is the earliest one by the token's user that holds the
marker. A comment over GitHub's size limit loses the data block first, then the diagram; it is always posted.

--find-only posts nothing and needs no run: it looks for that comment and exits 0 when there is one (printing its id),
3 when there is none. Any other failure, such as a refused token, exits with the error.
"""
import argparse
import base64
import gzip
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

MARKER = "<!-- pr-brief:v1"
COMMENT_LIMIT = 65536
# `gh api user` is refused for the token a workflow gets, whose comments are authored by this account.
ACTIONS_LOGIN = "github-actions[bot]"
NOT_FOUND_EXIT = 3
DATA_SUMMARY = "Brief data"
DIAGRAM_FILE = "diagram.svg"
DIAGRAM_MD = "diagram.md"
DATA_BLOCK = re.compile(rf"<details><summary>{DATA_SUMMARY}</summary>\s*```\n(?P<data>[A-Za-z0-9+/=\s]*?)\n```\s*</details>")
PAYLOAD_DROPPED = "<sub>The data the browser extension reads was left out: the comment was over GitHub's size limit.</sub>"
DIAGRAM_DROPPED = "<sub>The diagram was left out: the comment was over GitHub's size limit.</sub>"

# Runs `gh` with these arguments and this stdin text, and returns what it printed. Raises CalledProcessError on failure.
Gh = Callable[[list[str], str | None], str]


def run_gh(args: list[str], stdin: str | None = None) -> str:
    return subprocess.run(["gh", *args], input=stdin, check=True, capture_output=True, text=True).stdout


def find_run(path: Path) -> Path:
    """`path` when it is a run folder; else its newest subfolder that is one, as in `runs/<pr>/`, which holds one folder per variant."""
    if (path / "review.json").is_file():
        return path
    runs: list[Path] = sorted((d for d in path.iterdir() if (d / "review.json").is_file()),
                              key=lambda d: (d / "review.json").stat().st_mtime) if path.is_dir() else []
    if not runs:
        raise SystemExit(f"{path} is not a run folder and holds none (no review.json)")
    return runs[-1]


def payload(review: dict[str, Any], diagram_svg: str | None = None) -> str:
    """review.json plus the run's diagram as the base64 of their gzip, with no timestamp so that the same inputs always
    give the same text."""
    data: dict[str, Any] = {**review, "diagram_svg": diagram_svg}
    text: bytes = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.b64encode(gzip.compress(text, mtime=0)).decode("ascii")


def data_block(encoded: str) -> str:
    """The collapsed block that holds a payload: GitHub renders it as a closed details element."""
    return f"<details><summary>{DATA_SUMMARY}</summary>\n\n```\n{encoded}\n```\n\n</details>"


def run_text(run_dir: Path, name: str) -> str | None:
    """The text of a file of the run; None when it has none."""
    file: Path = run_dir / name
    return file.read_text(encoding="utf-8") if file.is_file() else None


def build_comment(run_dir: Path, limit: int = COMMENT_LIMIT) -> str:
    """The comment for a run, within `limit` characters."""
    review: dict[str, Any] = json.loads((run_dir / "review.json").read_text())
    diagram: str = (run_text(run_dir, DIAGRAM_MD) or "").strip()
    summary: str = f"<details>\n<summary><b>PR Brief · AI-generated</b> · {review['variant']} · {review['head_sha'][:7]}</summary>"

    def assemble(shown: str, notes: list[str], data: str) -> str:
        parts: list[str] = [summary, shown, *notes, data, "</details>", f"{MARKER} -->"]
        return "\n\n".join(part for part in parts if part) + "\n"

    full: str = assemble(diagram, [], data_block(payload(review, run_text(run_dir, DIAGRAM_FILE))))
    if len(full) <= limit:
        return full
    candidate: str = assemble(diagram, [PAYLOAD_DROPPED], "")
    if len(candidate) <= limit:
        return candidate
    return assemble("", [PAYLOAD_DROPPED, DIAGRAM_DROPPED], "")[:limit]


def token_login(gh: Gh) -> str:
    try:
        return gh(["api", "user", "--jq", ".login"], None).strip()
    except subprocess.CalledProcessError:
        return ACTIONS_LOGIN


def existing_comment(repo: str, pr: int | str, gh: Gh) -> int | None:
    """The id of the earliest comment on the PR by the token's user that holds the marker; None when there is none."""
    login: str = token_login(gh)
    listing: str = gh(["api", "--paginate", f"repos/{repo}/issues/{pr}/comments",
                       "--jq", f'.[] | select(.body | contains("{MARKER}")) | "\\(.id)\\t\\(.user.login)"'], None)
    ids: list[int] = [int(row.split("\t")[0]) for row in listing.splitlines() if row.count("\t") == 1 and row.split("\t")[1] == login]
    return min(ids) if ids else None


def upsert(repo: str, pr: int | str, body: str, gh: Gh = run_gh) -> str:
    """Updates the PR's brief comment, or adds one; returns `updated` or `created`."""
    found: int | None = existing_comment(repo, pr, gh)
    request: str = json.dumps({"body": body})
    if found is None:
        gh(["api", f"repos/{repo}/issues/{pr}/comments", "--input", "-"], request)
        return "created"
    gh(["api", "-X", "PATCH", f"repos/{repo}/issues/comments/{found}", "--input", "-"], request)
    return "updated"


def main(argv: list[str] | None = None, gh: Gh = run_gh) -> int:
    p = argparse.ArgumentParser(description="Post a run's brief as a comment on its pull request.")
    p.add_argument("run_dir", type=Path, nargs="?")
    p.add_argument("--repo", help="owner/name (default: the run's)")
    p.add_argument("--pr", help="the PR number (default: the run's)")
    p.add_argument("--dry-run", action="store_true", help="print the comment and post nothing")
    p.add_argument("--find-only", action="store_true",
                   help=f"look for the PR's brief comment: exit 0 and print its id when there is one, {NOT_FOUND_EXIT} when there is none")
    a = p.parse_args(argv)
    if a.find_only:
        if not (a.repo and a.pr):
            p.error("--find-only needs --repo and --pr")
        found: int | None = existing_comment(a.repo, a.pr, gh)
        if found is None:
            return NOT_FOUND_EXIT
        print(found)
        return 0
    if a.run_dir is None:
        p.error("a run folder is required")
    run_dir: Path = find_run(a.run_dir)
    review: dict[str, Any] = json.loads((run_dir / "review.json").read_text())
    repo: str = a.repo or review["repo"]
    pr: str = a.pr or str(review["pr"])
    body: str = build_comment(run_dir)
    if a.dry_run:
        print(body)
        print(f"{len(body)} characters of {COMMENT_LIMIT}", file=sys.stderr)
        return 0
    print(f"{upsert(repo, pr, body, gh)} the brief comment on {repo}#{pr} ({len(body)} characters)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
