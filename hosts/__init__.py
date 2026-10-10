"""Where a pull request is read from. One class per host, each with the same two methods:

    pr(owner, repo, n)        title, body, head branch, base and head SHA, commits and files, in the
                              shape `gh pr view --json` gives (the shape pr.json, render.py and
                              context_pack.py read)
    diff(owner, repo, n)      the unified diff
    head_sha(owner, repo, n)  the PR's current head commit, and nothing else

A host also names its runs (`runs/<run_key>/`), builds the links render.py puts in the body, and says
where a commit missing from the local mirror is fetched from. Both hosts only read.
"""
import re
from typing import Any

FORGEJO_PREFIX = "fj-"
FORGEJO_KEY = re.compile(rf"^{FORGEJO_PREFIX}(\d+)$")


def host_names() -> tuple[str, ...]:
    return ("github", "forgejo")


def get_host(name: str, settings: dict[str, Any]):
    """The host called `name`; `settings` is local.toml's contents (the Forgejo host reads `forgejo_url` and
    `forgejo_token_file` from it)."""
    if name == "github":
        from hosts.github import GitHub
        return GitHub()
    if name == "forgejo":
        from hosts.forgejo import Forgejo
        return Forgejo(settings.get("forgejo_url"), settings.get("forgejo_token_file"))
    raise SystemExit(f"unknown host {name!r}; expected one of {', '.join(host_names())}")


def run_key(host: str, number: int | str) -> str:
    """The folder name of a PR's runs: the bare number on GitHub, `fj-<n>` on Forgejo, so numbers of
    the two hosts cannot collide."""
    return f"{FORGEJO_PREFIX}{number}" if host == "forgejo" else str(number)


def parse_run_key(key: str) -> tuple[str, int] | None:
    """(host, number) for a run folder name, or None when it is neither a number nor `fj-<n>`."""
    forgejo = FORGEJO_KEY.match(key)
    if forgejo:
        return "forgejo", int(forgejo.group(1))
    return ("github", int(key)) if key.isdigit() else None
