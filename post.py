#!/usr/bin/env python3
"""Post a run's brief as one comment on its pull request, or update the comment that an earlier run left.

usage: post.py <run dir> [--repo owner/name] [--pr N] [--dry-run]
       post.py --find-only --repo owner/name --pr N

<run dir> is a run folder (it has review.json and body.md), or the PR's `runs/<n>` folder, whose newest run is used.
--repo and --pr default to the run's own. --dry-run prints the comment and posts nothing; without it the program calls
`gh api`, which reads GH_TOKEN from the environment.

The comment is one collapsed "PR Brief" details element, whose summary line names the variant and the head commit. It holds the
brief's markdown with the diagram as a ```mermaid fence, which GitHub draws itself, a walkthrough whose stops link to their
lines in the diff, any notes and a collapsed "Brief data" block; a hidden `<!-- pr-brief:v1 -->` marker follows it. The block is a code fence holding the base64 of the gzip of review.json plus the run's `diagram.svg` and
`body.html` (as the keys `diagram_svg` and `body_html`, null when the run has no such file); the browser extension reads
the brief from it, so a reader needs no server. The comment that gets updated is the earliest one by the token's user that
holds the marker. A comment over GitHub's size limit loses the data block first, then walkthrough stops, then the tail of
the brief; it is always posted.

--find-only posts nothing and needs no run: it looks for that comment and exits 0 when there is one (printing its id),
3 when there is none. Any other failure, such as a refused token, exits with the error.
"""
import argparse
import base64
import gzip
import hashlib
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
BODY_FILE = "body.html"
DATA_BLOCK = re.compile(rf"<details><summary>{DATA_SUMMARY}</summary>\s*```\n(?P<data>[A-Za-z0-9+/=\s]*?)\n```\s*</details>")
PAYLOAD_DROPPED = "<sub>The data the browser extension reads was left out: the comment was over GitHub's size limit.</sub>"
TRIMMED = "<sub>The brief is cut short: it was over GitHub's size limit.</sub>"

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


def diff_anchor(repo: str, pr: int | str, path: str, side: str | None = None, line: int | None = None) -> str:
    """The link to a file in the PR's diff, and to a line of it (`R12` for line 12 of the new side, `L12` of the old)."""
    digest: str = hashlib.sha256(path.encode("utf-8")).hexdigest()
    place: str = f"{side}{line}" if side and line else ""
    return f"https://github.com/{repo}/pull/{pr}/files#diff-{digest}{place}"


def stop_markdown(stop: dict[str, Any], repo: str, pr: int | str) -> str:
    link: str = diff_anchor(repo, pr, stop["path"], stop.get("side"), stop.get("line"))
    where: str = f"{stop['path']}:{stop['line']}" if stop.get("line") else stop["path"]
    return f"{stop['i']}. [{stop['title']}]({link}) — {stop['why']}  \n   <sub>`{where}`</sub>"


def walkthrough_markdown(stops: list[dict[str, Any]], repo: str, pr: int | str, shown: int | None = None) -> str:
    """The walkthrough as a numbered list, its first `shown` stops (all by default); empty for no stop."""
    chosen: list[dict[str, Any]] = stops if shown is None else stops[:shown]
    return "### Walkthrough\n\n" + "\n".join(stop_markdown(s, repo, pr) for s in chosen) + "\n" if chosen else ""


def payload(review: dict[str, Any], diagram_svg: str | None = None, body_html: str | None = None) -> str:
    """review.json plus the run's diagram and body page as the base64 of their gzip, with no timestamp so that the same
    inputs always give the same text."""
    data: dict[str, Any] = {**review, "diagram_svg": diagram_svg, "body_html": body_html}
    text: bytes = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.b64encode(gzip.compress(text, mtime=0)).decode("ascii")


def data_block(encoded: str) -> str:
    """The collapsed block that holds a payload: GitHub and Forgejo render it as a closed details element."""
    return f"<details><summary>{DATA_SUMMARY}</summary>\n\n```\n{encoded}\n```\n\n</details>"


def unpack(comment: str) -> dict[str, Any] | None:
    """The payload (review.json plus `diagram_svg` and `body_html`) that a comment holds; None when it holds none. It is
    read from the "Brief data" block, or from the base64 inside the marker comment where a comment has its payload there."""
    block: re.Match[str] | None = DATA_BLOCK.search(comment)
    encoded: str = "".join(block["data"].split()) if block else ""
    if not encoded:
        start: int = comment.find(MARKER)
        encoded = comment[start + len(MARKER):].split("-->", 1)[0].strip() if start >= 0 else ""
    return json.loads(gzip.decompress(base64.b64decode(encoded))) if encoded else None


def run_text(run_dir: Path, name: str) -> str | None:
    """The text of a file of the run; None when it has none."""
    file: Path = run_dir / name
    return file.read_text(encoding="utf-8") if file.is_file() else None


def brief_markdown(body: str) -> str:
    """The run's body.md without its title (the PR has one) and its tool marker, and without the rule that closes it."""
    lines: list[str] = body.strip().split("\n")
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    kept: str = "\n".join(line for line in lines if line.strip() != "<!-- pr-agent-generated -->").strip()
    return kept.removesuffix("___").strip()


def close_fences(text: str) -> str:
    """`text` with a code fence it leaves open closed."""
    return text + "\n```" if text.count("```") % 2 else text


def build_comment(run_dir: Path, repo: str | None = None, pr: int | str | None = None, limit: int = COMMENT_LIMIT) -> str:
    """The comment for a run, within `limit` characters."""
    review: dict[str, Any] = json.loads((run_dir / "review.json").read_text())
    repo = repo or review["repo"]
    pr = pr or review["pr"]
    brief: str = brief_markdown((run_dir / "body.md").read_text())
    stops: list[dict[str, Any]] = review["walkthrough"]
    summary: str = f"<details>\n<summary><b>PR Brief</b> · {review['variant']} · {review['head_sha'][:7]}</summary>"

    def assemble(shown: int, notes: list[str], data: str, brief_text: str = brief) -> str:
        parts: list[str] = [summary, brief_text, walkthrough_markdown(stops, repo, pr, shown).strip(), *notes, data, "</details>", f"{MARKER} -->"]
        return "\n\n".join(part for part in parts if part) + "\n"

    encoded: str = payload(review, run_text(run_dir, DIAGRAM_FILE), run_text(run_dir, BODY_FILE))
    full: str = assemble(len(stops), [], data_block(encoded))
    if len(full) <= limit:
        return full
    for shown in range(len(stops), -1, -1):
        notes: list[str] = [PAYLOAD_DROPPED]
        if shown < len(stops):
            notes.append(f"<sub>The walkthrough shows the first {shown} of {len(stops)} stops: the comment was over GitHub's size limit.</sub>")
        candidate: str = assemble(shown, notes, "")
        if len(candidate) <= limit:
            return candidate
    notes = [PAYLOAD_DROPPED, TRIMMED]
    overhead: int = len(assemble(0, notes, "", "")) + 10
    cut: str = brief[: max(limit - overhead, 0)].rsplit("\n", 1)[0] if limit > overhead else ""
    return assemble(0, notes, "", close_fences(cut).strip())[:limit]


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
    body: str = build_comment(run_dir, repo, pr)
    if a.dry_run:
        print(body)
        print(f"{len(body)} characters of {COMMENT_LIMIT}", file=sys.stderr)
        return 0
    print(f"{upsert(repo, pr, body, gh)} the brief comment on {repo}#{pr} ({len(body)} characters)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
