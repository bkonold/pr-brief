#!/usr/bin/env python3
"""Run PR-Agent's /describe prompt for one PR and one variant through `claude -p`.

usage: run.py <pr> --variant NAME [--with-body] [--model opus]
              [--repo owner/name] [--prompt-only]

--repo is required unless local.toml sets `repo`.

Reads from GitHub only (`gh pr view`, `gh pr diff`). Writes runs/<pr>/<variant>/ under PR_DESCRIBE_HOME (default: the tool's folder).
A variant with `render_from = "<other variant>"` makes no model call and no GitHub call: it
copies the other variant's prompt, answer and PR data from runs/<pr>/ and renders them with its own settings.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment

from config import HOME, ROOT, load_local, variant_file
from context_pack import Pack, build, ensure_commits

UPSTREAM_PROMPT_SHA = "5e9fd335372da85f9c345392337b6f31615af803"
COLLAPSIBLE_FILE_LIST_THRESHOLD = 6

# The schema field and the example YAML key that the variant's additions are inserted after.
# Both end with the `{%- endif %}` that closes the diagram block.
SCHEMA_ANCHOR = re.compile(r"changes_diagram: str = Field\([^\n]*\n[^\n]*\{%- endif %\}")
EXAMPLE_ANCHOR = re.compile(r"changes_diagram: \|\n  ```mermaid\n  flowchart LR\n    \.\.\.\n  ```\n\{%- endif %\}")


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


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
        "enable_semantic_files_types": True,
        "include_file_summary_changes": len(pr["files"]) <= COLLAPSIBLE_FILE_LIST_THRESHOLD,
        "enable_pr_diagram": True,
        "enable_pr_description": True,
        "duplicate_prompt_examples": False,
    }
    env = Environment()
    return env.from_string(system_template).render(**values), env.from_string(prompt["user"]).render(**values)


def now() -> datetime:
    return datetime.now(timezone.utc)


def render_only(pr: str, name: str, variant_path: Path, source_name: str) -> int:
    """Copy the source variant's run into this variant's folder and render it with this variant's settings."""
    source_dir: Path = HOME / "runs" / pr / source_name
    copied: tuple[str, ...] = ("prompt.txt", "answer.yaml", "pr.json", "run.json")
    optional: tuple[str, ...] = ("context.md",)
    absent: list[str] = [f for f in copied if not (source_dir / f).exists()]
    if absent:
        raise SystemExit(f"{name} renders from {source_name}, but {source_dir} has no {', '.join(absent)}. "
                         f"Run `run.py {pr} --variant {source_name}` first.")
    source: dict[str, Any] = json.loads((source_dir / "run.json").read_text())
    run_dir: Path = HOME / "runs" / pr / name
    run_dir.mkdir(parents=True, exist_ok=True)
    for stale in ("error.txt", "body.md", "body.html", *optional):
        (run_dir / stale).unlink(missing_ok=True)
    for f in (*copied[:3], *(o for o in optional if (source_dir / o).exists())):
        shutil.copyfile(source_dir / f, run_dir / f)
    (run_dir / "run.json").write_text(json.dumps({
        **source,
        "variant": name,
        "variant_sha256": hashlib.sha256(variant_path.read_bytes()).hexdigest(),
        "render_from": source_name,
    }, indent=2) + "\n")
    return subprocess.run([sys.executable, str(ROOT / "render.py"), str(run_dir)]).returncode


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("pr")
    p.add_argument("--variant", required=True)
    p.add_argument("--with-body", action="store_true", help="show the model the PR's existing description")
    p.add_argument("--model", default="opus")
    p.add_argument("--repo", default=load_local().get("repo"), help="GitHub repository as owner/name (default: local.toml's `repo`)")
    p.add_argument("--prompt-only", action="store_true", help="print the rendered prompt and stop")
    a = p.parse_args()

    variant_path: Path | None = variant_file(a.variant)
    if variant_path is None:
        raise SystemExit(f"no variant {a.variant!r} in {HOME / 'variants'} or {ROOT / 'variants'}")
    variant: dict[str, Any] = tomllib.loads(variant_path.read_text())

    if "render_from" in variant:
        if a.prompt_only:
            raise SystemExit(f"{a.variant} renders from {variant['render_from']} and has no prompt of its own")
        return render_only(a.pr, a.variant, variant_path, variant["render_from"])
    if not a.repo:
        p.error("--repo owner/name is required when local.toml sets no `repo`")

    pr: dict[str, Any] = json.loads(gh("pr", "view", a.pr, "--repo", a.repo,
                                       "--json", "title,body,headRefName,baseRefOid,headRefOid,commits,files"))
    diff: str = gh("pr", "diff", a.pr, "--repo", a.repo)
    pack: Pack | None = None
    if variant.get("context"):
        ensure_commits([pr["baseRefOid"], pr["headRefOid"]])
        pack = build(pr, diff, variant["context"], options=variant.get("context_options"))
    context_md: str = pack.markdown() if pack else ""
    system, user = build_prompts(variant, pr, diff, a.with_body, context_md)
    prompt_text: str = f"{system}\n\n=====USER=====\n\n{user}"

    if a.prompt_only:
        print(prompt_text)
        if pack:
            print(f"repo context: {len(context_md)} chars, ~{pack.stats()['estimated_tokens']} tokens", file=sys.stderr)
        return 0

    run_dir: Path = HOME / "runs" / a.pr / a.variant
    run_dir.mkdir(parents=True, exist_ok=True)
    for stale in ("error.txt", "body.md", "body.html", "context.md"):
        (run_dir / stale).unlink(missing_ok=True)
    (run_dir / "prompt.txt").write_text(prompt_text)
    if pack:
        (run_dir / "context.md").write_text(context_md + "\n")
    (run_dir / "pr.json").write_text(json.dumps(pr, indent=2) + "\n")

    started: datetime = now()
    out = subprocess.run(
        ["claude", "-p", "--system-prompt", system, "--tools", "", "--model", a.model],
        input=user, capture_output=True, text=True,
    )
    finished: datetime = now()
    (run_dir / "answer.yaml").write_text(out.stdout)
    if out.returncode != 0:
        (run_dir / "error.txt").write_text(f"claude exited with status {out.returncode}\n{out.stderr}")

    (run_dir / "run.json").write_text(json.dumps({
        "variant": a.variant,
        "variant_sha256": hashlib.sha256(variant_path.read_bytes()).hexdigest(),
        **({"context": pack.stats()} if pack else {}),
        "pr": int(a.pr),
        "repo": a.repo,
        "pr_head_sha": pr["headRefOid"],
        "model": a.model,
        "with_body": a.with_body,
        "started": started.isoformat(timespec="seconds"),
        "finished": finished.isoformat(timespec="seconds"),
        "duration_seconds": round((finished - started).total_seconds()),
        "upstream_prompt_sha": UPSTREAM_PROMPT_SHA,
        "exit_status": out.returncode,
    }, indent=2) + "\n")

    if out.returncode != 0:
        sys.stderr.write(out.stderr)
    rendered: subprocess.CompletedProcess[bytes] = subprocess.run([sys.executable, str(ROOT / "render.py"), str(run_dir)])
    return out.returncode or rendered.returncode


if __name__ == "__main__":
    raise SystemExit(main())
