#!/usr/bin/env python3
"""Run PR-Agent's /describe prompt for one PR and one variant through `claude -p` or the GitHub Copilot CLI.

usage: run.py <pr> [--variant NAME] [--with-body] [--runner claude|copilot] [--model NAME]
              [--host github|forgejo] [--repo owner/name] [--config FILE] [--prompt-only]

--config names a TOML to read in place of local.toml, with the same keys and, if it has one, the `[reach]`
table (see config.py). --variant defaults to the config's `default_variant`, else the tool's current
variant.

--runner defaults to claude. A copilot run uses the CLI's own stored login and is written beside the Claude run, to
runs/<key>/<variant>_copilot/, with the same variant settings; --model defaults to the runner's entry in
local.toml's [model] table, else claude-opus-5-5 for claude and claude-opus-5.5 for copilot.

--host defaults to local.toml's `host`, else github. --repo is the host's `owner/name` and is required
unless local.toml sets `repo` for that host (`repo` applies to the host named by `host`, github by default).

Reads from the host only (see hosts/). Writes runs/<key>/<variant>/ under PR_BRIEF_HOME (default: the tool's
folder), where <key> is the PR number on GitHub and `fj-<number>` on Forgejo.
"""
import argparse
import hashlib
import json
import os
import re
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

from compare import write_variants_json  # noqa: E402
from config import DEFAULT_VARIANT, HOME, ROOT, load_local, variant_file  # noqa: E402
from context_pack import Pack, build, ensure_commits  # noqa: E402
from hosts import get_host, host_names, run_key  # noqa: E402
from runners import CLAUDE, COPILOT, RUNNERS, clean_answer, command_line, invocation, resolve_model, run_dir_name  # noqa: E402
from run_status import CANCELED, DONE, FAILED, RUNNING, begin_status, last_line, read_status, write_status  # noqa: E402

UPSTREAM_PROMPT_SHA = "5e9fd335372da85f9c345392337b6f31615af803"

# The schema field and the example YAML key that the variant's additions are inserted after.
# Both end with the `{%- endif %}` that closes the diagram block.
SCHEMA_ANCHOR = re.compile(r"changes_diagram: str = Field\([^\n]*\n[^\n]*\{%- endif %\}")
EXAMPLE_ANCHOR = re.compile(r"changes_diagram: \|\n  ```mermaid\n  flowchart LR\n    \.\.\.\n  ```\n\{%- endif %\}")


def insert_after(template: str, anchor: re.Pattern[str], text: str, what: str) -> str:
    """Insert `text` on its own lines right after the anchor. The template's next `{%- ... %}` tag
    strips the newline that follows, so the inserted text carries none."""
    found: list[re.Match[str]] = list(anchor.finditer(template))
    if len(found) != 1:
        raise SystemExit(f"{what}: expected exactly one anchor in the prompt, found {len(found)}")
    end: int = found[0].end()
    return template[:end] + "\n" + text.strip("\n") + template[end:]


def build_prompts(variant: dict[str, Any], pr: dict[str, Any], diff: str, with_body: bool,
                  repo_context: str = "") -> tuple[str, str]:
    prompt: dict[str, str] = tomllib.loads((ROOT / "vendor/pr_description_prompts.toml").read_text())["pr_description_prompt"]
    system_template: str = prompt["system"]
    if variant.get("schema_additions"):
        system_template = insert_after(system_template, SCHEMA_ANCHOR, variant["schema_additions"], "schema_additions")
    if variant.get("example_additions"):
        system_template = insert_after(system_template, EXAMPLE_ANCHOR, variant["example_additions"], "example_additions")

    commits: str = "\n".join(f"{i}. {c['messageHeadline']}" for i, c in enumerate(pr["commits"], 1))
    values: dict[str, Any] = {
        "title": pr["title"],
        "description": (pr["body"] or "") if with_body else "",
        "branch": pr["headRefName"],
        "commit_messages_str": commits,
        "diff": diff,
        "extra_instructions": variant.get("extra_instructions", "").strip(),
        "skills_context": "",
        "repo_context": repo_context,
        "related_tickets": [],
        "related_tickets_omitted": 0,
        "enable_custom_labels": False,
        "custom_labels_class": "",
        "enable_semantic_files_types": False,
        "enable_pr_diagram": True,
        "enable_pr_description": True,
        "duplicate_prompt_examples": False,
    }
    env = Environment()
    return env.from_string(system_template).render(**values), env.from_string(prompt["user"]).render(**values)


def now() -> datetime:
    return datetime.now(timezone.utc)


class Progress:
    """Writes runs/<key>/status.json as the run moves through its stages (see run_status.py). It does
    nothing until `begin` names the run, so a --prompt-only run leaves no status behind."""

    def __init__(self) -> None:
        self.key: str | None = None
        self.error: str | None = None

    def begin(self, key: str) -> None:
        self.key = key
        existing: dict[str, Any] | None = read_status(HOME, key)
        if existing and existing.get("state") == RUNNING:
            self.stage("fetch")
        else:
            begin_status(HOME, key)

    def _canceled(self) -> bool:
        existing: dict[str, Any] | None = read_status(HOME, self.key) if self.key else None
        return bool(existing and existing.get("state") == CANCELED)

    def stage(self, name: str) -> None:
        if self.key and not self._canceled():
            write_status(HOME, self.key, state=RUNNING, stage=name)

    def finish(self, code: int, message: str | None = None) -> None:
        if not self.key or self._canceled():
            return
        if code == 0:
            write_status(HOME, self.key, state=DONE, finished=datetime.now().timestamp())
            return
        error: str = last_line(message or self.error or "") or f"run exited with status {code}"
        write_status(HOME, self.key, state=FAILED, finished=datetime.now().timestamp(), error=error)


def execute(progress: Progress) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("pr")
    local: dict[str, Any] = load_local()
    p.add_argument("--variant", default=local.get("default_variant", DEFAULT_VARIANT),
                   help="the variant to run (default: the config's `default_variant`, else the tool's current variant)")
    p.add_argument("--config", help="a TOML to read in place of local.toml (see config.py)")
    p.add_argument("--with-body", action="store_true", help="show the model the PR's existing description")
    p.add_argument("--runner", choices=RUNNERS, default=CLAUDE, help="the program that runs the model (default: claude)")
    p.add_argument("--model", help="the runner's model id (default: local.toml's [model] entry for the runner, else claude-opus-5-5 for claude and claude-opus-5.5 for copilot)")
    p.add_argument("--host", choices=host_names(), default=local.get("host", "github"),
                   help="where the PR lives (default: local.toml's `host`, else github)")
    p.add_argument("--repo", help="the host's repository as owner/name (default: local.toml's `repo`, for the host local.toml names)")
    p.add_argument("--prompt-only", action="store_true", help="print the rendered prompt and stop")
    a = p.parse_args()
    try:
        a.model = resolve_model(a.runner, a.model, local)
    except ValueError as e:
        raise SystemExit(str(e)) from None
    if a.repo is None and a.host == local.get("host", "github"):
        a.repo = local.get("repo")
    key: str = run_key(a.host, a.pr)
    if not a.prompt_only:
        progress.begin(key)

    variant_path: Path | None = variant_file(a.variant)
    if variant_path is None:
        raise SystemExit(f"no variant {a.variant!r} in {HOME / 'variants'} or {ROOT / 'variants'}")
    variant: dict[str, Any] = tomllib.loads(variant_path.read_text())

    if not a.repo:
        p.error(f"--repo owner/name is required: the config sets no `repo` for the {a.host} host")
    owner, _, name = a.repo.partition("/")
    if not owner or not name:
        p.error("--repo must be owner/name")

    host = get_host(a.host, local)
    pr: dict[str, Any] = host.pr(owner, name, a.pr)
    diff: str = host.diff(owner, name, a.pr)
    if not pr["files"]:
        raise SystemExit(f"{a.host} lists no files for PR {a.pr}, in its file list or its diff, so there is nothing to describe")
    pack: Pack | None = None
    if variant.get("context"):
        progress.stage("context")
        ensure_commits([pr["baseRefOid"], pr["headRefOid"]], a.host)
        pack = build(pr, diff, variant["context"], options=variant.get("context_options"))
    context_md: str = pack.markdown() if pack else ""
    system, user = build_prompts(variant, pr, diff, a.with_body, context_md)
    prompt_text: str = f"{system}\n\n=====USER=====\n\n{user}"

    if a.prompt_only:
        print(prompt_text)
        if pack:
            print(f"repo context: {len(context_md)} chars, ~{pack.stats()['estimated_tokens']} tokens", file=sys.stderr)
        return 0

    run_dir: Path = HOME / "runs" / key / run_dir_name(a.variant, a.runner)
    run_dir.mkdir(parents=True, exist_ok=True)
    for stale in ("error.txt", "body.md", "body.html", "context.md", "contract.json", "answer.raw.txt"):
        (run_dir / stale).unlink(missing_ok=True)
    (run_dir / "prompt.txt").write_text(prompt_text)
    if pack:
        (run_dir / "context.md").write_text(context_md + "\n")
        if pack.contract is not None:
            (run_dir / "contract.json").write_text(json.dumps(pack.contract, indent=2) + "\n")
    (run_dir / "pr.json").write_text(json.dumps(pr, indent=2) + "\n")

    progress.stage("write")
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
        progress.error = f"{a.runner} exited with status {out.returncode}: {last_line(out.stderr)}"

    (run_dir / "run.json").write_text(json.dumps({
        "variant": a.variant,
        "variant_sha256": hashlib.sha256(variant_path.read_bytes()).hexdigest(),
        **({"context": pack.stats()} if pack else {}),
        "pr": int(a.pr),
        "host": a.host,
        "repo": a.repo,
        "pr_head_sha": pr["headRefOid"],
        "runner": a.runner,
        "model": a.model,
        **({"answer_cleanup": cleanup} if cleanup else {}),
        "with_body": a.with_body,
        "started": started.isoformat(timespec="seconds"),
        "finished": finished.isoformat(timespec="seconds"),
        "duration_seconds": round((finished - started).total_seconds()),
        "upstream_prompt_sha": UPSTREAM_PROMPT_SHA,
        "exit_status": out.returncode,
    }, indent=2) + "\n")

    if out.returncode != 0:
        sys.stderr.write(out.stderr)
    progress.stage("render")
    rendered: subprocess.CompletedProcess[bytes] = subprocess.run([sys.executable, str(ROOT / "render.py"), str(run_dir)])
    if rendered.returncode != 0 and progress.error is None:
        error_file: Path = run_dir / "error.txt"
        progress.error = last_line(error_file.read_text()) if error_file.exists() else f"render exited with status {rendered.returncode}"
    code: int = out.returncode or rendered.returncode
    if code == 0:
        write_variants_json(run_dir.parent, a.variant)
    return code


def main() -> int:
    progress = Progress()
    try:
        code: int = execute(progress)
    except SystemExit as stop:
        progress.finish(1 if isinstance(stop.code, str) else int(stop.code or 0), stop.code if isinstance(stop.code, str) else None)
        raise
    except Exception as error:
        progress.finish(1, f"{type(error).__name__}: {error}")
        raise
    progress.finish(code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
