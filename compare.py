#!/usr/bin/env python3
"""Build runs/<pr>/index.html, one iframe column per variant, and runs/index.html listing every PR.

usage: compare.py <key> [--variants a,b,...] [--all]

<key> is the run folder: a GitHub PR number, or `fj-<number>` for a Forgejo PR.

Also writes runs/<pr>/variants.json for the browser extension: the variants of compare.toml that
have a run with a review.json, as [{variant, label, description}], in compare.toml's order.

The columns default to the variants in compare.toml, in that order. `--variants` overrides them
and `--all` shows every variant that has a run for the PR.
"""
import argparse
import html
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

from config import HOME, config_file, variant_file
from hosts import run_label, run_order

RUNS = HOME / "runs"
ARCHETYPES: Path | None = config_file("archetypes")
UNCLASSIFIED = "Unclassified"

# The labels the browser extension's dropdown shows; a variant without one is listed under its name.
VARIANT_LABELS: dict[str, str] = {
    "one_path_risk_chunked_v10": "V10 (original)",
    "one_path_risk_chunked_v11b": "B",
    "one_path_risk_chunked_v12": "12: rule + fallback",
    "one_path_risk_chunked_v13": "13: rule only",
    "one_path_risk_chunked_v14": "14: fallback only",
    "one_path_risk_chunked_v15": "15: line reason",
    "one_path_risk_chunked_v15_nocontext": "15: no context pack",
    "one_path_risk_chunked_v16": "16: flow order + contract block",
    "one_path_risk_chunked_v17": "17: conceptual start line",
    "one_path_risk_chunked_v18": "18: 10-box diagram path",
    "one_path_risk_chunked_v19": "19: one box per chunk",
    "one_path_risk_chunked_v20": "20: file or line start",
    "one_path_risk_chunked_v21": "21: effort levels + check labels",
    "one_path_risk_chunked_v22": "22: contract and data by chunk",
    "one_path_risk_chunked_v23": "23: walkthrough stops",
}

STYLE = """
 :root { color-scheme: light; }
 body { margin: 0; font: 14px/1.4 system-ui, sans-serif; background: #f6f8fa; color: #1f2328; }
 h1 { font-size: 16px; margin: 0; padding: 10px 16px; border-bottom: 1px solid #d0d7de; background: #fff; }
 .cols { display: grid; grid-template-rows: auto 1fr; column-gap: 8px; padding: 8px; }
 .col { min-width: 0; display: grid; grid-row: span 2; grid-template-rows: subgrid; background: #fff; border: 1px solid #d0d7de; border-radius: 6px; }
 .head { padding: 8px 12px; border-bottom: 1px solid #d0d7de; }
 .head strong { font-size: 15px; }
 .head div { color: #57606a; font-size: 12px; }
 .failed { color: #cf222e; font-weight: 600; }
 iframe { width: 100%; height: calc(100vh - 150px); min-height: 700px; border: 0; }
 ul { padding: 16px 32px; } li { margin: 6px 0; }
 table { border-collapse: collapse; margin: 16px 32px; background: #fff; }
 th, td { text-align: left; padding: 6px 14px; border: 1px solid #d0d7de; }
 th { background: #f6f8fa; }
"""


def variant_order(name: str) -> tuple[int, str]:
    return (0 if name == "control" else 1, name)


def variant_description(name: str) -> str:
    path: Path | None = variant_file(name)
    return tomllib.loads(path.read_text()).get("description", "") if path else ""


def variants_json(pr_dir: Path, extra: str | None = None) -> list[dict[str, str]]:
    """The variants of compare.toml (when it exists) that have a run with a review.json, in its order, then
    `extra` when it has one too and compare.toml does not list it."""
    path: Path = HOME / "compare.toml"
    names: list[str] = tomllib.loads(path.read_text())["variants"] if path.exists() else []
    if extra and extra not in names:
        names = [*names, extra]
    return [{"variant": name, "label": VARIANT_LABELS.get(name, name), "description": variant_description(name)}
            for name in names if (pr_dir / name / "review.json").exists()]


def write_variants_json(pr_dir: Path, extra: str | None = None) -> None:
    """Writes runs/<key>/variants.json, which is how the browser extension finds the variants a PR has."""
    (pr_dir / "variants.json").write_text(json.dumps(variants_json(pr_dir, extra), indent=2) + "\n")


def column(run_dir: Path) -> str:
    run: dict[str, Any] = json.loads((run_dir / "run.json").read_text())
    description: str = variant_description(run["variant"])
    failed: str = '' if (run_dir / "body.md").exists() else ' <span class="failed">failed</span>'
    edges: dict[str, int] | None = run.get("diagram_edges")
    arrows: str = f" · arrows labelled {edges['labelled']}/{edges['total']}" if edges else ""
    started: str = run["started"][:16].replace("T", " ") + " UTC"
    render_only: str = f" · render-only from {html.escape(run['render_from'])}" if run.get("render_from") else ""
    return (f'<div class="col"><div class="head"><strong>{html.escape(run["variant"])}</strong>{failed}'
            f'<div>{html.escape(description)}</div>'
            f'<div>run {started} · with_body: {str(run["with_body"]).lower()}{arrows}{render_only}</div></div>'
            f'<iframe src="{html.escape(run_dir.name)}/body.html" title="{html.escape(run["variant"])}"></iframe></div>')


def pr_title(pr_dir: Path) -> str:
    for pr_json in sorted(pr_dir.glob("*/pr.json")):
        return json.loads(pr_json.read_text())["title"]
    return ""


def pr_author(pr_dir: Path) -> str:
    for pr_json in sorted(pr_dir.glob("*/pr.json")):
        login: str | None = (json.loads(pr_json.read_text()).get("author") or {}).get("login")
        if login:
            return login
    return ""


def archetype_table(prs: list[Path]) -> str:
    config: dict[str, Any] = tomllib.loads(ARCHETYPES.read_text())
    assigned: dict[str, str] = config["prs"]
    groups: list[str] = [*config["order"], UNCLASSIFIED]
    rows: list[str] = []
    for group in groups:
        members: list[Path] = sorted((d for d in prs if archetype_of(d.name, assigned, config["order"]) == group), key=lambda d: run_order(d.name), reverse=True)
        for i, d in enumerate(members):
            label: str = html.escape(group) if i == 0 else ""
            rows.append(f'<tr><td>{label}</td><td><a href="{d.name}/index.html">{run_label(d.name)}</a> {html.escape(pr_title(d))}</td>'
                        f'<td>{html.escape(pr_author(d))}</td></tr>')
    return f"<table><tr><th>Archetype</th><th>PR</th><th>Author</th></tr>{''.join(rows)}</table>"


def archetype_of(pr: str, assigned: dict[str, str], order: list[str]) -> str:
    name: str | None = assigned.get(pr)
    return name if name in order else UNCLASSIFIED


def page(title: str, body: str) -> str:
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{html.escape(title)}</title><style>{STYLE}</style></head><body>{body}</body></html>")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pr")
    parser.add_argument("--variants", help="comma-separated variant names, in column order")
    parser.add_argument("--all", action="store_true", help="every variant on disk for the PR")
    args = parser.parse_args()
    pr: str = args.pr
    pr_dir: Path = RUNS / pr
    on_disk: list[Path] = [d for d in pr_dir.iterdir() if (d / "run.json").exists()]
    if args.all:
        run_dirs: list[Path] = sorted(on_disk, key=lambda d: variant_order(d.name))
    else:
        names: list[str] = args.variants.split(",") if args.variants else tomllib.loads((HOME / "compare.toml").read_text())["variants"]
        by_name: dict[str, Path] = {d.name: d for d in on_disk}
        missing: list[str] = [n for n in names if n not in by_name]
        if missing:
            print(f"{run_label(pr)}: no run for {', '.join(missing)}", file=sys.stderr)
        run_dirs = [by_name[n] for n in names if n in by_name]
    write_variants_json(pr_dir)
    title: str = f"{run_label(pr)}: {pr_title(pr_dir)}"
    (pr_dir / "index.html").write_text(page(title, f"<h1>{html.escape(title)}</h1><div class=\"cols\" style=\"grid-template-columns: repeat({len(run_dirs)}, minmax(0, 1fr))\">{''.join(column(d) for d in run_dirs)}</div>"))

    prs: list[Path] = sorted((d for d in RUNS.iterdir() if (d / "index.html").exists()), key=lambda d: run_order(d.name))
    if ARCHETYPES:
        listing: str = archetype_table(prs)
    else:
        items: str = "".join(f'<li><a href="{d.name}/index.html">{run_label(d.name)}</a> {html.escape(pr_title(d))}</li>' for d in prs)
        listing = f"<ul>{items}</ul>"
    (RUNS / "index.html").write_text(page("PR description comparisons", f"<h1>PR description comparisons</h1>{listing}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
