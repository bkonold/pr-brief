#!/usr/bin/env python3
"""Render a run's answer.yaml as the PR body, and as a standalone HTML page.

usage: render.py <run dir> [--config FILE]      e.g. runs/42/brief

--config names a TOML to read in place of local.toml (see config.py); run.py passes its own on.

Reads answer.yaml, run.json and pr.json from the run dir.
Writes body.md and body.html, review.json and the diagram's SVG, and records the diagram's labelled and total arrows in run.json. On broken YAML it writes error.txt and an error page and exits 1.
The body is the PR's title, the model's description, the Contract and Data sections, the diagram and a caption about its dashed boxes; the
diagram's boxes, the walkthrough stops and the contract and data lines go to review.json.
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

import config

# Before MIGRATION_GLOBS and the other settings below are read.
config.use_config_flag(sys.argv)

from config import ROOT, load_local  # noqa: E402
import layout  # noqa: E402
from diff_lines import file_diff_lines  # noqa: E402
from context_pack import BlobReader, has_commit  # noqa: E402
from contract_lines import CONTRACT_LEVELS, Line, Source, contract_lines  # noqa: E402
from data_lines import DATA_LEVELS, data_lines  # noqa: E402
from hosts import get_host  # noqa: E402
from hosts.github import GitHub  # noqa: E402
from sources import CONTROLLER_DIRS, MODEL_DIRS, SourceFinder  # noqa: E402

sys.path.insert(0, str(ROOT / "vendor"))
from pr_agent_helpers import apply_diagram_direction, sanitize_diagram  # noqa: E402

DIAGRAM_THRESHOLD = 5
# The diagram's text size (Mermaid's default) and the width its labels wrap at, in diagram units. The theme sets the
# label size explicitly (see DIAGRAM_STYLE), so a page whose CSS styles `.label` cannot change what the boxes were laid out for.
DIAGRAM_FONT_SIZE = 16
DIAGRAM_WRAPPING_WIDTH = 280
CONTEXT_CLASS_DEF = "classDef context stroke-dasharray:5 4,fill:#fff;"
CONTEXT_CAPTION = "Dashed boxes are unchanged context"
# Section headings whose name is not the key's own word.
HEADINGS: dict[str, str] = {"type": "PR Type", "contract": "API"}
MIGRATION_GLOBS: list[str] = load_local().get("migration_globs", [])
MODEL_DIR_MARKERS: tuple[str, ...] = tuple(load_local().get("model_dirs", MODEL_DIRS))
CONTROLLER_DIR_MARKERS: tuple[str, ...] = tuple(load_local().get("controller_dirs", CONTROLLER_DIRS))


class AnswerError(Exception):
    pass


# ---------------------------------------------------------------- diagram

def render_diagram(raw: Any) -> str:
    """The diagram top-down, in DIAGRAM_FONT_SIZE text with its labels wrapped at DIAGRAM_WRAPPING_WIDTH."""
    diagram: str = sanitize_diagram(raw)  # an empty diagram is dropped, as PR-Agent does
    if not diagram:
        return ""
    diagram = apply_diagram_direction(diagram, "TD", DIAGRAM_THRESHOLD)
    lines: list[str] = diagram.split("\n")
    init: str = ('%%{init: {"themeVariables": {"fontSize": "' + str(DIAGRAM_FONT_SIZE) + 'px"}, "flowchart": {"wrappingWidth": '
                 + str(DIAGRAM_WRAPPING_WIDTH) + '}}}%%')
    fence: int = next(i for i, line in enumerate(lines) if line.strip().startswith("```mermaid"))
    lines.insert(fence + 1, init)
    return "\n".join(lines)


LINK_TOKEN = re.compile(r'"[^"]*"|\|[^|]*\||(?P<link><?[-=.~]{2,}[->ox]?)|(?P<id>[A-Za-z0-9_]+)|&')
NODE_SHAPE = re.compile(r'(?<=\w)(?:\[+[^\]]*\]+|\(+[^)]*\)+|\{+[^}]*\}+)')
NON_EDGE_LINE = re.compile(r"\s*(?:%%|classDef\b|class\b|style\b|linkStyle\b|subgraph\b|click\b|direction\b)")
# A two-character connector opens a label written between two connectors: `A -- text --> B`.
LABEL_OPENERS = ("--", "==", "-.")


@dataclass(frozen=True)
class DiagramEdge:
    source: str
    target: str
    labelled: bool
    link: str  # the connector as written (the opening one of a `A -- text --> B` label): `-->`, `-.->`, `<-->`, `~~~`


def parse_diagram_edges(diagram: str) -> list[DiagramEdge]:
    """Every arrow of a mermaid flowchart, one per source and target pair: chained links (`a --> b --> c`) give one
    edge per link and `A & B --> C` one per pair. A label is `-- x -->`, `-->|x|`, `-. x .->` or `== x ==>`."""
    edges: list[DiagramEdge] = []
    for raw_line in diagram.split("\n"):
        if NON_EDGE_LINE.match(raw_line):
            continue
        line: str = re.sub(r":::\w+", "", NODE_SHAPE.sub("", re.sub(r"(?<=\w)\s*[\[({]+\"(?:[^\"\\]|\\.)*\"[\])}]+", "", raw_line)))
        groups: list[list[str]] = []
        link_labelled: list[bool] = []
        links: list[str] = []
        current: list[str] = []
        in_label: bool = False
        for token in LINK_TOKEN.finditer(line):
            text: str = token.group(0)
            if token.group("link"):
                if in_label:
                    in_label = False
                    continue
                groups.append(current)
                current = []
                in_label = text in LABEL_OPENERS
                link_labelled.append(in_label)
                links.append(text)
            elif text.startswith('"') or text.startswith("|"):
                if link_labelled and not current and len(groups) == len(link_labelled):
                    link_labelled[-1] = True
            elif token.group("id") and not in_label:
                current.append(text)
        groups.append(current)
        for index, is_labelled in enumerate(link_labelled):
            if index + 1 < len(groups):
                edges.extend(DiagramEdge(source, target, is_labelled, links[index])
                             for source in groups[index] for target in groups[index + 1])
    return edges


def count_diagram_edges(diagram: str) -> tuple[int, int]:
    """(labelled, total) arrows of a mermaid flowchart."""
    edges: list[DiagramEdge] = parse_diagram_edges(diagram)
    return sum(edge.labelled for edge in edges), len(edges)


# ---------------------------------------------------------------- file links

# The host that built the run (hosts/); main() sets it from run.json, and GitHub is the default.
LINK_HOST = GitHub()


def diff_link(repo: str, pr: str, filename: str) -> str:
    return LINK_HOST.diff_link(repo, pr, filename)


def line_link(repo: str, pr: str, start: dict[str, Any]) -> str:
    return LINK_HOST.line_link(repo, pr, start)


# ---------------------------------------------------------------- globs

def glob_to_regex(glob: str) -> re.Pattern[str]:
    out: str = ""
    i: int = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif glob.startswith("**", i):
            out += ".*"
            i += 2
        elif glob[i] == "*":
            out += "[^/]*"
            i += 1
        elif glob[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(glob[i])
            i += 1
    return re.compile(out + r"\Z")


def matches(globs: list[str], path: str) -> bool:
    return any(glob_to_regex(g).match(path) for g in globs)


# ---------------------------------------------------------------- diff lines and walkthrough stops

HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
DIFF_START = "The PR Git Diff:\n=====\n"
DIFF_END = "\n=====\n\nNote that lines in the diff body"

# (side, line number, stripped text): "L" is a removed line numbered in the old file; "R" is an
# added or context line numbered in the new file.
DiffLine = tuple[str, int, str]


def diff_from_prompt(prompt: str) -> str:
    """The `gh pr diff` text the model was shown, which prompt.txt embeds."""
    start: int = prompt.find(DIFF_START)
    end: int = prompt.rfind(DIFF_END)
    return prompt[start + len(DIFF_START):end] if start != -1 and end > start else ""


def diff_lines_by_path(diff: str) -> dict[str, list[DiffLine]]:
    lines_by_path: dict[str, list[DiffLine]] = {}
    current: list[DiffLine] | None = None
    old: int = 0
    new: int = 0
    in_hunk: bool = False
    for line in diff.split("\n"):
        header: re.Match[str] | None = re.match(r"diff --git a/(.*) b/(.*)$", line)
        if header:
            current = lines_by_path.setdefault(header.group(2), [])
            in_hunk = False
            continue
        hunk: re.Match[str] | None = HUNK_HEADER.match(line)
        if hunk:
            old, new, in_hunk = int(hunk.group(1)), int(hunk.group(2)), True
        elif current is None or not in_hunk or line.startswith("\\"):
            continue
        elif line.startswith("+"):
            current.append(("R", new, line[1:].strip()))
            new += 1
        elif line.startswith("-"):
            current.append(("L", old, line[1:].strip()))
            old += 1
        else:
            current.append(("R", new, line[1:].strip()))
            old += 1
            new += 1
    return lines_by_path


def match_diff_line(diff_lines: dict[str, list[DiffLine]], path: str, text: str) -> tuple[DiffLine | None, str]:
    """The one line of the file's diff whose stripped text is `text`; None, with what went wrong, when no line or
    several lines match."""
    found: list[DiffLine] = [line for line in diff_lines.get(path, []) if line[2] == text]
    if len(found) == 1:
        return found[0], ""
    return None, "not found" if not found else f"matched {len(found)} lines"


STOP_TITLE_MAX_WORDS = 6
STOP_WHY_MAX_WORDS = 20
STOPS_RANGE = (3, 10)


def clean_path(raw: Any) -> str:
    return str(raw).strip().strip("`'\"").removeprefix("./")


def stop_node(raw: Any, path: str, node_files: dict[str, list[str]], label: str, notes: list[str]) -> str | None:
    """The diagram box a stop belongs to: the box the answer names when the diagram has it and it covers files, else the
    first box, in diagram order, whose files include the stop's file, else None. Each fallback is noted."""
    named: str = str(raw or "").strip().strip("`'\"")
    if node_files.get(named):
        return named
    found: str | None = next((node for node, files in node_files.items() if path in files), None)
    problem: str = ("no node" if not named else f"node {named!r} covers no files" if named in node_files
                    else f"node {named!r} is not a box in the diagram")
    if found is None:
        notes.append(f"{label}: {problem}, and no box holds {path}")
    else:
        notes.append(f"{label}: {problem}, using {found}")
    return found


def resolve_stops(raw: Any, files: list[str], diff_lines: dict[str, list[DiffLine]],
                  node_files: dict[str, list[str]]) -> tuple[list[dict[str, Any]], list[str]]:
    """The walkthrough's stops, numbered from 1 in the model's order, and the notes about what was fixed.

    A stop quoting a line found exactly once in its file's diff points at that line; any other stop points at its file
    alone (side and line None). A stop in a file outside the diff, or at a place an earlier stop already has, is
    dropped. `node` is the diagram box the stop belongs to (see `stop_node`); `node_files` maps each box on the diagram,
    in diagram order, to its files, and is empty when there is no diagram, which leaves every stop's node None."""
    notes: list[str] = []
    if not isinstance(raw, list):
        return [], ["no walkthrough"]
    stops: list[dict[str, Any]] = []
    taken: set[tuple[str, int | None]] = set()
    for position, item in enumerate(raw, 1):
        label: str = f"stop {position}"
        path: str = clean_path(item.get("file", "")) if isinstance(item, dict) else ""
        if path not in files:
            notes.append(f"{label}: dropped, its file is not in the PR: {path or '(none)'}")
            continue
        text: str = str(item.get("line_text", "")).strip()
        side: str | None = None
        number: int | None = None
        if text:
            match, problem = match_diff_line(diff_lines, path, text)
            if match is None:
                notes.append(f"{label}: line {problem}, pointing at the file")
            else:
                side, number, _ = match
        if (path, number) in taken:
            notes.append(f"{label}: dropped, an earlier stop is already at {path}" + ("" if number is None else f":{number}"))
            continue
        taken.add((path, number))
        title: str = " ".join(str(item.get("title", "")).split())
        if not title:
            notes.append(f"{label}: no title, using the file's name")
            title = path.split("/")[-1]
        elif len(title.split()) > STOP_TITLE_MAX_WORDS:
            notes.append(f"{label}: title is longer than {STOP_TITLE_MAX_WORDS} words")
        why: str = " ".join(str(item.get("why", "")).split())
        if not why:
            notes.append(f"{label}: no reason")
        elif len(why.split()) > STOP_WHY_MAX_WORDS:
            notes.append(f"{label}: reason is longer than {STOP_WHY_MAX_WORDS} words")
        node: str | None = stop_node(item.get("node"), path, node_files, label, notes) if node_files else None
        stops.append({"i": len(stops) + 1, "title": title, "why": why, "path": path, "side": side, "line": number, "node": node})
    low, high = STOPS_RANGE
    if not low <= len(stops) <= high:
        notes.append(f"{len(stops)} stops, expected {low} to {high}")
    return stops, notes


NODE_DECLARATION = re.compile(r'(?<![\w-])(?P<id>[A-Za-z0-9_][A-Za-z0-9_-]*)(?P<open>\s*\[")(?:\d+\s*·\s*|\d+[.:)]\s+)?')


def declaration_positions(lines: list[str]) -> dict[str, int]:
    """Node id -> index of its first labelled declaration in the flowchart."""
    position: dict[str, int] = {}
    for line in lines:
        if not NON_EDGE_LINE.match(line):
            for declaration in NODE_DECLARATION.finditer(line):
                position.setdefault(declaration.group("id"), len(position))
    return position


def stop_badges(diagram: str, stops_on: dict[str, list[int]]) -> str:
    """Prefix the label of every box that stops land on with their numbers, `2 · 5 · `, replacing any number the model
    wrote; a box with no stops keeps no number."""
    def prefix(declaration: re.Match[str]) -> str:
        numbers: list[int] = stops_on.get(declaration.group("id"), [])
        badge: str = "".join(f"{number} · " for number in numbers)
        return f"{declaration.group('id')}{declaration.group('open')}{badge}"

    return "\n".join(line if NON_EDGE_LINE.match(line) else NODE_DECLARATION.sub(prefix, line) for line in diagram.split("\n"))


BOX_LABEL = re.compile(r'(?<![\w-])(?P<id>[A-Za-z0-9_][A-Za-z0-9_-]*)\["(?P<label>[^"\n]*)"\]')
LABEL_TAG = re.compile(r"<[^>]*>")


def node_titles(diagram: str) -> dict[str, str]:
    """Box id -> the first line of its label (the step's title), as plain text, from the box's first declaration."""
    titles: dict[str, str] = {}
    for line in diagram.split("\n"):
        if NON_EDGE_LINE.match(line):
            continue
        for box in BOX_LABEL.finditer(line):
            first: str = re.split(r"<br\s*/?>", box.group("label"))[0]
            title: str = " ".join(LABEL_TAG.sub("", first).replace("#quot;", '"').split())
            titles.setdefault(box.group("id"), re.sub(r"^(?:\d+\s*·\s*)+", "", title))
    return titles


def clean_node_files(raw: Any, position: dict[str, int], paths: list[str], notes: list[str]) -> dict[str, list[str]]:
    """Node id -> the changed files that box covers, for every node on the diagram in declaration order.
    A node the model left out, or whose files were all dropped, gets an empty list: unchanged context."""
    files: dict[str, list[str]] = {node: [] for node in position}
    if not isinstance(raw, dict):
        notes.append("node_files is not a mapping")
        return files
    for raw_node, raw_paths in raw.items():
        node: str = str(raw_node).strip().strip("`'\"")
        if node not in position:
            notes.append(f"node_files: ignored node id that is not in the diagram: {node}")
            continue
        for raw_path in raw_paths if isinstance(raw_paths, list) else [raw_paths]:
            path: str = clean_path(raw_path)
            if path not in paths:
                notes.append(f"node_files '{node}': dropped a path that is not in the PR: {path}")
            elif path not in files[node]:
                files[node].append(path)
    return files


def add_context_style(diagram: str, context_nodes: list[str]) -> str:
    """Give the nodes that cover no changed file a dashed `context` style, before the closing fence."""
    if not context_nodes:
        return diagram
    lines: list[str] = diagram.split("\n")
    lines[len(lines) - 1:len(lines) - 1] = [f"  {CONTEXT_CLASS_DEF}", f"  class {','.join(context_nodes)} context"]
    return "\n".join(lines)


# ---------------------------------------------------------------- contract and data block

def unchecked_sides(run: dict[str, Any], contract: dict[str, Any] | None) -> list[str]:
    """`API` when the run has no contract and did not look for one, and `database` when no migration globs are set."""
    context: dict[str, Any] = run.get("context") or {}
    api_checked: bool = "contract" in (context.get("sections") or {}) and "contract" not in (context.get("dropped") or {})
    return (["API"] if contract is None and not api_checked else []) + ([] if MIGRATION_GLOBS else ["database"])


def migration_paths(pr: dict[str, Any]) -> list[str]:
    return [f["path"] for f in pr["files"] if matches(MIGRATION_GLOBS, f["path"]) and f.get("changeType") != "DELETED"]


def build_lines(pr: dict[str, Any], contract: dict[str, Any] | None, diff_text: str) -> tuple[list[Line], list[Line]]:
    """The run's contract lines and data lines."""
    api: list[Line] = contract_lines(contract, file_diff_lines(diff_text, contract["path"]), contract["path"]) if contract else []
    data: list[Line] = data_lines({path: file_diff_lines(diff_text, path) for path in migration_paths(pr)}) if MIGRATION_GLOBS else []
    return api, data


def head_reader(sha: str, pr: dict[str, Any]) -> Callable[[str], str | None]:
    """Reads a changed Java file at the PR's head commit from the mirror, all of them in one call on the first read; None
    for every file when the mirror does not hold the commit."""
    if not has_commit(sha):
        return lambda path: None
    reader: BlobReader = BlobReader(sha)
    reader.load([f["path"] for f in pr["files"] if f["path"].endswith(".java") and f.get("changeType") != "DELETED"])
    return lambda path: reader.raw(path) or None


def locate_sources(pr: dict[str, Any], api: list[Line], data: list[Line], diff_text: str,
                   read_file: Callable[[str], str | None] | None = None) -> None:
    """Gives each contract and data line the sources in the PR that declare what it is about (see sources.py);
    `read_file` reads a changed file at the head commit, for what the diff does not show."""
    finder: SourceFinder = SourceFinder(diff_text, [f["path"] for f in pr["files"]], MODEL_DIR_MARKERS, CONTROLLER_DIR_MARKERS,
                                        read_file or (lambda path: None))
    for line in api:
        line.sources = finder.contract(line)
    for line in data:
        line.sources = finder.data(line)


def file_sets(pr: dict[str, Any], contract: dict[str, Any] | None, api: list[Line], data: list[Line]) -> dict[str, list[str]]:
    """The files that make up the PR's contract change and its data change, each sorted without repeats. The contract
    is the spec when the PR changes it, the source of every contract line and every changed file under a model
    directory; the data is the migration files and the source of every data line."""
    paths: list[str] = [f["path"] for f in pr["files"]]
    spec: str | None = (contract or {}).get("path") or load_local().get("openapi_path")
    models: set[str] = {p for p in paths if any(marker in p for marker in MODEL_DIR_MARKERS)}
    migrations: set[str] = {p for p in paths if matches(MIGRATION_GLOBS, p)}
    return {"contract": sorted(models | {s.path for line in api for s in line.sources} | ({spec} if spec in paths else set())),
            "data": sorted(migrations | {s.path for line in data for s in line.sources})}


def sections(run: dict[str, Any], api: list[Line], data: list[Line], unchecked: list[str],
             files: dict[str, list[str]] | None = None) -> tuple[str, str]:
    """The Contract and Data sections of a body, each one closed block with a table of all its lines and a list of its
    files. A section with no lines says so, and says when its side could not be checked."""
    repo: str = run["repo"]
    number: str = str(run["pr"])
    file_lists: dict[str, list[str]] = files or {}

    def source_link(source: Source) -> str:
        return line_link(repo, number, {"path": source.path, "side": source.side, "line": source.line})

    def link_of(line: Line) -> str:
        if line.loc:
            return line_link(repo, number, {"path": line.path, "side": line.loc[0], "line": line.loc[1]})
        return diff_link(repo, number, line.path)

    def draw(side: str, none: str, levels: tuple[str, ...], kind: str, lines: list[Line]) -> str:
        if not lines:
            return f"{side[0].upper()}{side[1:]} changes not checked" if side in unchecked else none
        return layout.section(kind, HEADINGS.get(kind) or kind.capitalize(), levels, lines, link_of, source_link,
                              [(path, diff_link(repo, number, path)) for path in file_lists.get(kind, [])])

    return (draw("API", "No API changes", CONTRACT_LEVELS, "contract", api),
            draw("database", "No database changes", DATA_LEVELS, "data", data))


# ---------------------------------------------------------------- body

@dataclass
class Brief:
    """What a run's answer renders to: the body, the diagram's arrow counts, its boxes by id (`title`, `files` and the
    numbers of the `stops` that land on it, in diagram order), the walkthrough's stops, and the contract and data lines."""
    body: str
    edges: tuple[int, int]
    nodes: dict[str, dict[str, Any]]
    stops: list[dict[str, Any]]
    contract: list[Line]
    data: list[Line]
    file_sets: dict[str, list[str]] = field(default_factory=lambda: {"contract": [], "data": []})


def build_body(run: dict[str, Any], pr: dict[str, Any], data: dict[str, Any], diff_lines: dict[str, list[DiffLine]],
               notes: list[str], contract: dict[str, Any] | None = None, diff_text: str = "",
               read_file: Callable[[str], str | None] | None = None) -> Brief:
    paths: list[str] = [f["path"] for f in pr["files"]]
    if not paths:
        raise AnswerError("The pull request has no files, so no stop can point at one.")

    ordered: dict[str, Any] = {}
    if run["with_body"] and (pr["body"] or "").strip():
        ordered["User Description"] = pr["body"].strip()
    for key in ("type", "description"):
        if key in data:
            ordered[key] = data[key]
    api, rows = build_lines(pr, contract, diff_text)
    locate_sources(pr, api, rows, diff_text, read_file)
    sets: dict[str, list[str]] = file_sets(pr, contract, api, rows)
    ordered["contract"], ordered["data"] = sections(run, api, rows, unchecked_sides(run, contract), sets)
    diagram: str = render_diagram(data.get("changes_diagram"))
    node_files: dict[str, list[str]] = {}
    titles: dict[str, str] = {}
    if diagram:
        node_files = clean_node_files(data.get("node_files"), declaration_positions(diagram.split("\n")), paths, notes)
        titles = node_titles(diagram)
    else:
        notes.append("no changes_diagram")
    stops, stop_notes = resolve_stops(data.get("walkthrough"), paths, diff_lines, node_files)
    notes.extend(stop_notes)
    if not stops:
        raise AnswerError("The walkthrough has no stop left, so there is nothing to guide a reviewer through:\n"
                          + "\n".join(f"- {note}" for note in stop_notes))
    stops_on: dict[str, list[int]] = {node: [stop["i"] for stop in stops if stop["node"] == node] for node in node_files}
    nodes: dict[str, dict[str, Any]] = {node: {"title": titles.get(node, node), "files": files, "stops": stops_on[node]}
                                        for node, files in node_files.items()}
    caption: str = ""
    if diagram:
        context_nodes: list[str] = [node for node, files in node_files.items() if not files]
        diagram = stop_badges(add_context_style(diagram, context_nodes), stops_on)
        caption = CONTEXT_CAPTION if context_nodes else ""
        ordered["changes_diagram"] = diagram

    body: str = ""
    for idx, (key, value) in enumerate(ordered.items()):
        if key == "changes_diagram":
            body += f"### Diagram Walkthrough\n\n{value}\n\n{caption + chr(10) * 2 if caption else ''}"
            continue
        if key in ("contract", "data") and value.startswith("<details"):
            body += f"{value}\n"
        else:
            body += f"### **{HEADINGS.get(key) or key.replace('_', ' ').capitalize()}**\n"
            if isinstance(value, list):
                value = ", ".join(str(v).rstrip() for v in value)
            if key == "description":
                value = value.replace("\n-", "\n\n-").strip()
            body += f"{value}\n"
        if idx < len(ordered) - 1:
            body += "\n\n" if key in ("contract", "data") else "\n\n___\n\n"
    body += "\n\n___\n\n"
    return Brief(f"# {pr['title']}\n\n<!-- pr-agent-generated -->\n{body}", count_diagram_edges(diagram), nodes, stops, api, rows, sets)


# ---------------------------------------------------------------- review.json

def line_json(line: Line) -> dict[str, Any]:
    """A contract or data line for review.json: its level (null when it has none), text, the parts of that text (what
    changed, on what, and for a contract line the side it reaches), where its diff line is in the spec or migration, and
    `source`, where the PR's own code declares it (null when the PR has none)."""
    side, number = line.loc if line.loc else (None, None)
    source: Source | None = line.sources[0] if line.sources else None
    return {"impact": line.impact, "text": line.text, "change": line.change, "on": line.on, "reaches": line.side,
            "path": line.path, "side": side, "line": number,
            "source": {"path": source.path, "side": source.side, "line": source.line} if source else None}


def review_json(run: dict[str, Any], brief: Brief, has_diagram: bool) -> dict[str, Any]:
    """What the browser extension reads: the diagram's boxes with the stops that land on each, the walkthrough's stops
    in reading order, and the contract and data lines of the tables."""
    return {
        "schema": 4,
        "repo": run["repo"],
        "pr": run["pr"],
        "head_sha": run["pr_head_sha"],
        "variant": run["variant"],
        **({"diagram": DIAGRAM_SVG} if has_diagram else {}),
        "nodes": brief.nodes,
        "walkthrough": brief.stops,
        "contract": [line_json(line) for line in brief.contract],
        "data": [line_json(line) for line in brief.data],
        "file_sets": brief.file_sets,
    }


# ---------------------------------------------------------------- diagram svg

DIAGRAM_SVG = "diagram.svg"
SVG_ID = "pr-diagram"
CHROME_TIMEOUT_SECONDS = 90
CHROME_ENV = "PR_BRIEF_CHROME"
CHROME_PATH_NAMES: tuple[str, ...] = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
CHROME_MACOS = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MERMAID_PACKAGE = ROOT / "node_modules" / "mermaid" / "package.json"
MERMAID_JS = ROOT / "node_modules" / "mermaid" / "dist" / "mermaid.min.js"
MERMAID_FENCE = re.compile(r"```mermaid\n(.*?)\n```", re.DOTALL)
SVG_OUT = re.compile(r'<pre id="svg-out">(.*?)</pre>', re.DOTALL)

DIAGRAM_STYLE = r"""
const DIAGRAM_CONFIG = {
  themeVariables: { fontFamily: '-apple-system, "Segoe UI", sans-serif' },
  themeCSS: `
    .node rect.label-container { rx: 14px; ry: 14px; fill: none; stroke: #9370db; stroke-width: 1px; }
    .node.context rect.label-container { fill: none; stroke: #b4b2a9; stroke-dasharray: 4 4; }
    .label { padding: 0; font: inherit; white-space: normal; border: 0; border-radius: 0; }
    .nodeLabel, .edgeLabel, .edgeLabel p { font-size: __FONT_SIZE__px; line-height: 1.5; }
    .node .nodeLabel, .node .label div { color: #26215c; text-align: center; }
    .node .nodeLabel p { margin: 0; }
    .nodeLabel .badge { display: inline-block; margin-right: .25em; padding: 0 .5em; font-size: .75em; line-height: 1.4; font-weight: 600; letter-spacing: normal; white-space: nowrap; color: #fff; background: #7f77dd; border-radius: 1em; }
    .nodeLabel .t { font-weight: 600; }
    .nodeLabel .s { color: #5f5e5a; font-weight: 400; }
    .context .nodeLabel, .context .label div { color: #5f5e5a; }
    path.flowchart-link { stroke: #9370db; stroke-width: 1px; fill: none; }
    .marker, .arrowMarkerPath { fill: none !important; stroke: #9370db !important; stroke-width: 1px; }
    .edgeLabel rect { fill: transparent !important; opacity: 0; }
    .edgeLabel, .edgeLabel p, .edgeLabel span, .labelBkg { background-color: transparent !important; color: #7f77dd !important; font-weight: 400; text-shadow: 0 0 3px #fff, 0 0 3px #fff, 0 0 3px #fff; }
    .cluster rect { fill: none; stroke: #e5e3f0; stroke-width: 1px; rx: 8px; ry: 8px; }
    .cluster-label .nodeLabel, .cluster-label span, .cluster-label p { color: #8a8a99; font-size: __CLUSTER_FONT_SIZE__px; font-weight: 400; }
  `,
};

// Marks where a long identifier may wrap: between a lower-case letter or digit and an upper-case one (camelCase and
// PascalCase), inside an acronym before a capitalised word, and after `.` or `_`.
function breakable(text) {
  return text.replace(/([a-z0-9])(?=[A-Z])|([A-Z])(?=[A-Z][a-z])|([._])(?=[A-Za-z0-9])/g, '$&<wbr>');
}

// The stop numbers that lead a node label (`2 · 5 · Title`) become one badge, and the title and the second line each
// get a class the theme styles. Node declarations only: subgraph titles and edge labels stay as written. The context
// classDef is dropped because the theme styles that class.
function styleDiagramText(text) {
  const skip = /^\s*(%%|classDef\b|class\b|style\b|linkStyle\b|subgraph\b|click\b|direction\b)/;
  const themed = /^\s*classDef\s+context\b/;
  return text.split('\n').filter((line) => !themed.test(line)).map((line) => skip.test(line) ? line : line.replace(
    /(^|[^\w-])([A-Za-z0-9_][\w-]*)\["([^"]*)"\]/g,
    (match, before, id, label) => {
      const [first, ...rest] = label.split(/<br\s*\/?>/);
      const numbers = /^(?:\d+\s*·\s*)+/.exec(first);
      const title = numbers ? first.slice(numbers[0].length) : first;
      const badge = numbers ? "<span class='badge'>" + numbers[0].split('·').map((n) => n.trim()).filter(Boolean).join(' · ') + '</span>' : '';
      const second = rest.length ? "<br/><span class='s'>" + breakable(rest.join('<br/>')) + '</span>' : '';
      return before + id + '["' + badge + "<span class='t'>" + title + '</span>' + second + '"]';
    })).join('\n');
}

// Drops the inline !important declarations that classDefs write, so the theme decides, and draws arrowheads as
// open chevrons.
function restyleDiagramSvg(svg) {
  for (const element of svg.querySelectorAll('[style]')) {
    const kept = element.getAttribute('style').split(';').filter((d) => d.trim() && !d.includes('!important')).join(';');
    if (kept) element.setAttribute('style', kept); else element.removeAttribute('style');
  }
  for (const path of svg.querySelectorAll('marker path')) {
    path.setAttribute('d', 'M 1 1 L 9 5 L 1 9');
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', '#9370db');
    path.parentElement.setAttribute('markerWidth', '11');
    path.parentElement.setAttribute('markerHeight', '11');
  }
}
"""

DIAGRAM_STYLE = (DIAGRAM_STYLE.replace("__FONT_SIZE__", str(DIAGRAM_FONT_SIZE))
                 .replace("__CLUSTER_FONT_SIZE__", str(round(DIAGRAM_FONT_SIZE * 0.75))))

# Renders the diagram the way the comparison page does (same mermaid build and theme) and leaves the
# serialized SVG in #svg-out, since HTML serialization of the SVG would not be well-formed XML.
SVG_PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<pre class="mermaid" id="diagram"></pre><pre id="svg-out"></pre>
<script src="__MERMAID_SRC__"></script>
<script>
__DIAGRAM_STYLE__
 const out = document.getElementById('svg-out');
 const pre = document.getElementById('diagram');
 pre.textContent = styleDiagramText(__TEXT__);
 mermaid.initialize({ startOnLoad: false, theme: 'default', ...DIAGRAM_CONFIG });
 mermaid.run({ nodes: [pre] })
   .then(() => {
     restyleDiagramSvg(pre.querySelector('svg'));
     out.textContent = new XMLSerializer().serializeToString(pre.querySelector('svg'));
   })
   .catch((e) => { out.textContent = 'ERROR ' + e; });
</script></body></html>"""


def chrome_order() -> str:
    """The places `find_chrome` looks, in order, as a sentence for an error message."""
    return (f"the {CHROME_ENV} environment variable, then the `chrome` key in local.toml, then "
            f"{', '.join(CHROME_PATH_NAMES)} on PATH, then {CHROME_MACOS}")


def find_chrome(environ: Mapping[str, str], local: Mapping[str, Any], macos: str = CHROME_MACOS) -> str:
    """The Chrome to render with: the first of the environment variable, local.toml's `chrome`, a Chrome-like program on
    PATH and the macOS install. A path that is set but is not an executable file is an error rather than a reason to
    try the next place, so a pinned Chrome is never swapped for another. Raises AnswerError when there is none."""
    for source, configured in ((CHROME_ENV, environ.get(CHROME_ENV)), ("`chrome` in local.toml", local.get("chrome"))):
        if configured:
            path: Path = Path(str(configured)).expanduser()
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
            raise AnswerError(f"{source} names {configured}, which is not an executable file. Chrome is looked for in this order: {chrome_order()}.")
    for name in CHROME_PATH_NAMES:
        found: str | None = shutil.which(name, path=environ.get("PATH", ""))
        if found:
            return found
    if Path(macos).is_file():
        return macos
    raise AnswerError(f"No Chrome was found, so diagram.svg cannot be drawn. Chrome is looked for in this order: {chrome_order()}. "
                      f"Install Chrome or Chromium, or set {CHROME_ENV}.")


def mermaid_version() -> str:
    """The version of the Mermaid build that draws diagrams, from the lockfile-installed package. Raises AnswerError when
    it is not installed."""
    if not MERMAID_JS.is_file() or not MERMAID_PACKAGE.is_file():
        raise AnswerError(f"Mermaid is not installed ({MERMAID_JS} is missing): run `npm ci` in {ROOT}.")
    return str(json.loads(MERMAID_PACKAGE.read_text())["version"])


def svg_page(diagram_text: str) -> str:
    """The page headless Chrome draws the diagram in. It loads Mermaid from the installed package and nothing else."""
    return (SVG_PAGE.replace("__MERMAID_SRC__", MERMAID_JS.as_uri()).replace("__DIAGRAM_STYLE__", DIAGRAM_STYLE)
            .replace("__TEXT__", json.dumps(diagram_text).replace("</", "<\\/")))


def render_svg(diagram_text: str) -> str:
    """The diagram as an SVG document, rendered by headless Chrome. Raises AnswerError when it can't be."""
    mermaid_version()
    chrome: str = find_chrome(os.environ, load_local(), CHROME_MACOS)
    with tempfile.TemporaryDirectory() as tmp:
        page: Path = Path(tmp) / "diagram.html"
        page.write_text(svg_page(diagram_text))
        try:
            out: subprocess.CompletedProcess[str] = subprocess.run(
                [chrome, "--headless=new", "--disable-gpu", "--disable-background-networking", "--no-first-run",
                 f"--user-data-dir={tmp}/profile", "--virtual-time-budget=15000", "--dump-dom", page.as_uri()],
                capture_output=True, text=True, timeout=CHROME_TIMEOUT_SECONDS)
        except (subprocess.TimeoutExpired, OSError) as e:
            raise AnswerError(f"Chrome ({chrome}) could not render diagram.svg: {e}") from e
    found: re.Match[str] | None = SVG_OUT.search(out.stdout)
    svg: str = html.unescape(found.group(1)).strip() if found else ""
    root: re.Match[str] | None = re.match(r'<svg id="([^"]+)"', svg)
    if not root:
        raise AnswerError(f"Chrome ({chrome}) did not produce diagram.svg: {svg[:200] or 'no output'}")
    return svg.replace(root.group(1), SVG_ID)  # mermaid derives its id from the clock; a fixed one keeps the file stable


def write_diagram_svg(md: str, run_dir: Path) -> str | None:
    """Writes diagram.svg for the diagram in `md` and returns the Mermaid version that drew it; None when `md` has no
    diagram. Raises AnswerError when it can't be drawn: a brief is never kept without its diagram."""
    fence: re.Match[str] | None = MERMAID_FENCE.search(md)
    if not fence:
        return None
    svg: str = render_svg(fence.group(1))
    (run_dir / DIAGRAM_SVG).write_text(svg + "\n")
    return mermaid_version()


# ---------------------------------------------------------------- pages

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/github-markdown-css@5/github-markdown-light.css">
<style>
 body { background: #fff; margin: 0; }
 .markdown-body { box-sizing: border-box; max-width: 980px; margin: 0 auto; padding: 32px 16px; }
 pre.mermaid { background: #fff; text-align: center; }
 .pill { display: inline-block; font-size: 11px; line-height: 16px; padding: 0 7px; border: 1px solid #8c959f; border-radius: 999px; white-space: nowrap; vertical-align: 1px; }
 .pill.p0 { background: #1f2328; border-color: #1f2328; color: #fff; font-weight: 600; }
 .pill.p1 { border-color: #1f2328; font-weight: 600; }
 details > summary .pill { margin: 0 4px; }
 .muted { color: #59636e; font-size: 12px; }
 .table-wrap { overflow-x: auto; margin: 4px 0 8px; }
 .table-wrap table { display: table; margin: 0; }
 .table-wrap td:first-child, .table-wrap th:first-child, .table-wrap td:last-child, .table-wrap th:last-child { white-space: nowrap; }
 .table-wrap td:last-child, .table-wrap th:last-child { width: 1%; }
 .table-wrap td:nth-child(2), .table-wrap th:nth-child(2) { min-width: 9ch; }
</style></head><body><article class="markdown-body" id="out"></article>
<script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>
__DIAGRAM_STYLE__
 const md = __MD__;
 document.getElementById('out').innerHTML = marked.parse(md, { gfm: true });
 document.querySelectorAll('code.language-mermaid').forEach(c => {
   const pre = document.createElement('pre'); pre.className = 'mermaid'; pre.textContent = styleDiagramText(c.textContent);
   c.parentElement.replaceWith(pre);
 });
 mermaid.initialize({ startOnLoad: false, theme: 'default', ...DIAGRAM_CONFIG });
 mermaid.run().then(() => document.querySelectorAll('pre.mermaid svg').forEach(restyleDiagramSvg));
</script></body></html>"""

ERROR_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Error</title>
<style>body{font:14px/1.5 system-ui,sans-serif;margin:0;padding:24px;background:#fff;color:#1f2328}
pre{white-space:pre-wrap;background:#f6f8fa;padding:12px;border-radius:6px}h2{color:#cf222e}</style></head><body>
<h2>Run failed</h2><pre>__ERROR__</pre><h3>Raw answer</h3><pre>__RAW__</pre></body></html>"""


def markdown_page(md: str) -> str:
    title: str = html.escape(md.splitlines()[0].lstrip("# ").strip())
    return PAGE.replace("__DIAGRAM_STYLE__", DIAGRAM_STYLE).replace("__TITLE__", title).replace("__MD__", json.dumps(md).replace("</", "<\\/"))


def parse_answer(raw: str) -> dict[str, Any]:
    text: str = re.sub(r"^```(?:yaml)?\n|\n```$", "", raw.strip())
    try:
        data: Any = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise AnswerError(f"The answer is not valid YAML:\n{e}") from e
    if not isinstance(data, dict):
        raise AnswerError("The answer is not a YAML mapping.")
    return data


def main() -> int:
    global LINK_HOST
    parser = argparse.ArgumentParser(description="Render a run's answer.yaml as its brief.")
    parser.add_argument("run_dir")
    parser.add_argument("--config", help="a TOML to read in place of local.toml (see config.py)")
    run_dir: Path = Path(parser.parse_args().run_dir).resolve()
    run: dict[str, Any] = json.loads((run_dir / "run.json").read_text())
    LINK_HOST = get_host(run.get("host", "github"), load_local())
    pr: dict[str, Any] = json.loads((run_dir / "pr.json").read_text())
    raw: str = (run_dir / "answer.yaml").read_text()
    contract_file: Path = run_dir / "contract.json"
    contract: dict[str, Any] | None = json.loads(contract_file.read_text()) if contract_file.exists() else None
    notes: list[str] = []
    for stale in ("body.md", "body.html", "review.json", DIAGRAM_SVG, "error.txt"):
        (run_dir / stale).unlink(missing_ok=True)

    try:
        if run["exit_status"] != 0:
            raise AnswerError(f"{run.get('runner', 'claude')} exited with status {run['exit_status']}")
        data: dict[str, Any] = parse_answer(raw)
        prompt_file: Path = run_dir / "prompt.txt"
        diff_text: str = diff_from_prompt(prompt_file.read_text()) if prompt_file.exists() else ""
        diff_lines: dict[str, list[DiffLine]] = diff_lines_by_path(diff_text)
        brief: Brief = build_body(run, pr, data, diff_lines, notes, contract, diff_text, head_reader(run["pr_head_sha"], pr))
        mermaid: str | None = write_diagram_svg(brief.body, run_dir)
    except AnswerError as e:
        (run_dir / DIAGRAM_SVG).unlink(missing_ok=True)
        (run_dir / "error.txt").write_text(f"{e}\n")
        (run_dir / "body.html").write_text(ERROR_PAGE.replace("__ERROR__", html.escape(str(e))).replace("__RAW__", html.escape(raw)))
        print(f"{run_dir}: {e}", file=sys.stderr)
        return 1

    labelled, total = brief.edges
    run["diagram_edges"] = {"labelled": labelled, "total": total}
    if mermaid is not None:
        run["mermaid"] = mermaid
    (run_dir / "run.json").write_text(json.dumps(run, indent=2) + "\n")
    (run_dir / "body.md").write_text(brief.body)
    (run_dir / "body.html").write_text(markdown_page(brief.body))
    has_diagram: bool = mermaid is not None
    (run_dir / "review.json").write_text(json.dumps(review_json(run, brief, has_diagram), indent=2) + "\n")
    if notes:
        (run_dir / "error.txt").write_text("Rendered with these fixes:\n" + "\n".join(f"- {n}" for n in notes) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
