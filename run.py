#!/usr/bin/env python3
"""Run the brief's prompt (prompt.toml) for one PR and one variant through `claude -p` or the GitHub Copilot CLI.

usage: run.py <pr> [--variant NAME] [--with-body] [--runner claude|copilot] [--model NAME]
              [--repo owner/name] [--config FILE] [--prompt-only]

--config names a TOML to read in place of local.toml, with the same keys and, if it has one, the `[reach]`
table (see config.py). --variant defaults to the config's `default_variant`, else the tool's current
variant.

--runner defaults to claude. A copilot run uses the CLI's own stored login; either runner writes
runs/<key>/<variant>/, and run.json records the runner and model. --model defaults to the runner's entry in
local.toml's [model] table, else claude-opus-5-5 for claude and claude-opus-5.5 for copilot.

--repo is the GitHub repository as `owner/name` and is required unless local.toml sets `repo`.

Reads from GitHub only (see hosts/). Writes runs/<pr>/<variant>/ under PR_BRIEF_HOME (default: the tool's folder).
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment

import config

# Before the modules that read the settings when they are imported.
config.use_config_flag(sys.argv)

from config import DEFAULT_VARIANT, HOME, ROOT, load_local, variant_file  # noqa: E402
from context_pack import Pack, build, ensure_commits  # noqa: E402
from hosts.github import GitHub  # noqa: E402
from hunks import parse_hunks, pins, pins_markdown, tag_headers  # noqa: E402
from render import build_lines, head_reader, locate_sources  # noqa: E402
from runners import CLAUDE, COPILOT, RUNNERS, clean_answer, command_line, invocation, resolve_model  # noqa: E402

PROMPT_FILE = ROOT / "prompt.toml"


def build_prompts(variant: dict[str, Any], pr: dict[str, Any], diff: str, with_body: bool,
                  repo_context: str = "") -> tuple[str, str]:
    prompt: dict[str, str] = tomllib.loads(PROMPT_FILE.read_text())
    commits: str = "\n".join(f"{i}. {c['messageHeadline']}" for i, c in enumerate(pr["commits"], 1))
    values: dict[str, Any] = {
        "title": pr["title"],
        "description": (pr["body"] or "") if with_body else "",
        "branch": pr["headRefName"],
        "commit_messages_str": commits,
        "diff": diff,
        "extra_instructions": variant.get("extra_instructions", "").strip(),
        "schema_additions": variant.get("schema_additions", "").strip("\n"),
        "example_additions": variant.get("example_additions", "").strip("\n"),
        "repo_context": repo_context,
        "enable_pr_diagram": variant.get("diagram", True),
    }
    env = Environment()
    return env.from_string(prompt["system"]).render(**values), env.from_string(prompt["user"]).render(**values)


def pin_groups(pr: dict[str, Any], pack: Pack | None, diff: str) -> list[list[str]]:
    """The groups of hunks of `diff` that hold one contract or data line (see hunks.py), from the PR's contract change and its
    migrations; there are none without a pack, which is where the contract comes from."""
    contract: dict[str, Any] | None = pack.contract if pack else None
    api, data = build_lines(pr, contract, diff)
    locate_sources(pr, api, data, diff, head_reader(pr["headRefOid"], pr))
    return pins(api, data, parse_hunks(diff))


def now() -> datetime:
    return datetime.now(timezone.utc)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("pr")
    local: dict[str, Any] = load_local()
    p.add_argument("--variant", default=local.get("default_variant", DEFAULT_VARIANT),
                   help="the variant to run (default: the config's `default_variant`, else the tool's current variant)")
    p.add_argument("--config", help="a TOML to read in place of local.toml (see config.py)")
    p.add_argument("--with-body", action="store_true", help="show the model the PR's existing description")
    p.add_argument("--runner", choices=RUNNERS, default=CLAUDE, help="the program that runs the model (default: claude)")
    p.add_argument("--model", help="the runner's model id (default: local.toml's [model] entry for the runner, else claude-opus-5-5 for claude and claude-opus-5.5 for copilot)")
    p.add_argument("--repo", help="the GitHub repository as owner/name (default: local.toml's `repo`)")
    p.add_argument("--prompt-only", action="store_true", help="print the rendered prompt and stop")
    a = p.parse_args()
    try:
        a.model = resolve_model(a.runner, a.model, local)
    except ValueError as e:
        raise SystemExit(str(e)) from None
    a.repo = a.repo or local.get("repo")

    variant_path: Path | None = variant_file(a.variant)
    if variant_path is None:
        raise SystemExit(f"no variant {a.variant!r} in {HOME / 'variants'} or {ROOT / 'variants'}")
    variant: dict[str, Any] = tomllib.loads(variant_path.read_text())

    if not a.repo:
        p.error("--repo owner/name is required: the config sets no `repo`")
    owner, _, name = a.repo.partition("/")
    if not owner or not name:
        p.error("--repo must be owner/name")

    host = GitHub()
    pr: dict[str, Any] = host.pr(owner, name, a.pr)
    diff: str = host.diff(owner, name, a.pr)
    if not pr["files"]:
        raise SystemExit(f"GitHub lists no files for PR {a.pr}, so there is nothing to brief")
    pack: Pack | None = None
    if variant.get("context"):
        ensure_commits([pr["baseRefOid"], pr["headRefOid"]])
        pack = build(pr, diff, variant["context"], options=variant.get("context_options"))
    context_md: str = pack.markdown() if pack else ""
    shown_diff: str = diff
    if variant.get("hunk_ids"):
        shown_diff = tag_headers(diff)
        pinned: str = pins_markdown(pin_groups(pr, pack, diff))
        context_md = "\n\n".join(part for part in (context_md, pinned) if part)
    system, user = build_prompts(variant, pr, shown_diff, a.with_body, context_md)
    prompt_text: str = f"{system}\n\n=====USER=====\n\n{user}"

    if a.prompt_only:
        print(prompt_text)
        if pack:
            print(f"repo context: {len(context_md)} chars, ~{pack.stats()['estimated_tokens']} tokens", file=sys.stderr)
        return 0

    run_dir: Path = HOME / "runs" / str(a.pr) / a.variant
    run_dir.mkdir(parents=True, exist_ok=True)
    for stale in ("error.txt", "context.md", "contract.json", "answer.raw.txt"):
        (run_dir / stale).unlink(missing_ok=True)
    (run_dir / "prompt.txt").write_text(prompt_text)
    if pack:
        (run_dir / "context.md").write_text(context_md + "\n")
        if pack.contract is not None:
            (run_dir / "contract.json").write_text(json.dumps(pack.contract, indent=2) + "\n")
    (run_dir / "pr.json").write_text(json.dumps(pr, indent=2) + "\n")

    started: datetime = now()
    command = invocation(a.runner, system, user, a.model, os.environ)
    if a.runner == COPILOT:
        print(f"running: {command_line(command)} ({len(command.input)} characters on stdin)", file=sys.stderr, flush=True)
    try:
        out = subprocess.run(command.argv, input=command.input, env=command.env, capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit(f"{command.argv[0]} is not installed or not on PATH") from None
    finished: datetime = now()
    answer, cleanup = clean_answer(a.runner, out.stdout)
    if cleanup:
        (run_dir / "answer.raw.txt").write_text(out.stdout)
    (run_dir / "answer.yaml").write_text(answer)
    if out.returncode != 0:
        (run_dir / "error.txt").write_text(f"{a.runner} exited with status {out.returncode}\n{out.stderr}")

    (run_dir / "run.json").write_text(json.dumps({
        "variant": a.variant,
        "variant_sha256": hashlib.sha256(variant_path.read_bytes()).hexdigest(),
        **({"context": pack.stats()} if pack else {}),
        "pr": int(a.pr),
        "repo": a.repo,
        "pr_head_sha": pr["headRefOid"],
        "runner": a.runner,
        "model": a.model,
        **({"answer_cleanup": cleanup} if cleanup else {}),
        "with_body": a.with_body,
        "started": started.isoformat(timespec="seconds"),
        "finished": finished.isoformat(timespec="seconds"),
        "duration_seconds": round((finished - started).total_seconds()),
        "prompt_sha256": hashlib.sha256(PROMPT_FILE.read_bytes()).hexdigest(),
        "exit_status": out.returncode,
    }, indent=2) + "\n")

    if out.returncode != 0:
        sys.stderr.write(out.stderr)
    rendered: subprocess.CompletedProcess[bytes] = subprocess.run([sys.executable, str(ROOT / "render.py"), str(run_dir)])
    return out.returncode or rendered.returncode


if __name__ == "__main__":
    raise SystemExit(main())
