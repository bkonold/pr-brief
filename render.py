#!/usr/bin/env python3
"""Render a run's answer.yaml as the PR body PR-Agent would publish, and as a standalone HTML page.

usage: render.py <run dir>      e.g. runs/42/one_path_risk_chunked_v15

Reads answer.yaml, run.json and pr.json from the run dir and the variant's [render] settings.
Writes body.md and body.html (plus review.json for a chunked variant), and records the diagram's labelled and total arrows in run.json. On broken YAML it writes error.txt and an error page and exits 1.
The body mirrors PR-Agent's _prepare_data, _prepare_pr_answer and process_pr_files_prediction
(pr_agent/tools/pr_description.py) with default settings: the PR's own title and description are
kept, the diagram direction is adaptive, and the file table is collapsible above 6 files.
"""
import html
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from config import ROOT, config_file, load_local, variant_file
from contract_block import contract_block, contract_rows, file_diff_lines, migration_rows
from hosts import get_host
from hosts.github import GitHub

sys.path.insert(0, str(ROOT / "vendor"))
from pr_agent_helpers import apply_diagram_direction, insert_br_after_x_chars, replace_code_tags, sanitize_diagram  # noqa: E402

COLLAPSIBLE_FILE_LIST_THRESHOLD = 6
DELTA = 75
DIAGRAM_THRESHOLD = 5
SAVE_CLASS_DEF = "classDef save fill:#fff4e5,stroke:#b26a00"
CONTEXT_CLASS_DEF = "classDef context stroke-dasharray:5 4,fill:#fff;"
SKIM_COLORS = ("#eef0f2", "#afb8c1")  # fill, stroke; a muted grey, solid, so it differs from the dashed white context box
SKIM_CLASS_DEF = f"classDef skim fill:{SKIM_COLORS[0]},stroke:{SKIM_COLORS[1]},color:#6e7781;"
ALSO_ID = "also"
ALSO_SUBGRAPH = f'subgraph {ALSO_ID}["Also in this PR"]'
LEVELS: list[str] = ["skim", "read", "read carefully"]
ROUTES_DIR: str = load_local().get("routes_dir", "")
MIGRATION_GLOBS: list[str] = load_local().get("migration_globs", [])
DEFAULT_TEST_GLOBS: list[str] = ["**/test/**", "**/tests/**", "**/*Test.*", "**/*Tests.*", "**/*.test.*", "**/*_test.*"]
TEST_GLOBS: list[str] = load_local().get("test_globs", DEFAULT_TEST_GLOBS)
TEST_DIRS: list[str] = load_local().get("test_dirs", [])


class AnswerError(Exception):
    pass


# ---------------------------------------------------------------- diagram

def render_diagram(raw: Any, cfg: dict[str, Any]) -> str:
    diagram: str = sanitize_diagram(raw)  # an empty diagram is dropped, as PR-Agent does
    if not diagram:
        return ""
    direction: str = {"force_td": "TD", "force_lr": "LR"}.get(cfg.get("diagram", ""), "adaptive")
    diagram = apply_diagram_direction(diagram, direction, DIAGRAM_THRESHOLD)
    lines: list[str] = diagram.split("\n")
    if cfg.get("wrapping_width"):
        init: str = '%%{init: {"flowchart": {"wrappingWidth": ' + str(cfg["wrapping_width"]) + '}}}%%'
        fence: int = next(i for i, line in enumerate(lines) if line.strip().startswith("```mermaid"))
        lines.insert(fence + 1, init)
    if ":::save" in diagram and not re.search(r"^\s*classDef\s+save\b", diagram, re.MULTILINE):
        lines.insert(len(lines) - 1, "  " + SAVE_CLASS_DEF)
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


# ---------------------------------------------------------------- PR-Agent's label-grouped walkthrough

def file_label_dict(pr_files: list[dict[str, Any]], include_summary: bool) -> dict[str, list[tuple[str, str, str]]]:
    labels: dict[str, list[tuple[str, str, str]]] = {}
    for file in pr_files:
        if not all(field_name in file for field_name in ("changes_title", "filename", "label")) or not file["changes_title"]:
            continue
        summary: str = (file.get("changes_summary") or "").strip()
        if not summary and include_summary:
            continue
        filename: str = file["filename"].replace("'", "`").replace('"', "`").strip()
        labels.setdefault(file["label"].strip().lower(), []).append((filename, file["changes_title"].strip(), summary))
    return labels


def labels_walkthrough(labels: dict[str, list[tuple[str, str, str]]], counts: dict[str, tuple[int, int]], repo: str, pr: str) -> str:
    num_files: int = sum(len(files) for files in labels.values())
    collapsible: bool = num_files > COLLAPSIBLE_FILE_LIST_THRESHOLD
    out: str = '<table><thead><tr><th></th><th align="left">Relevant files</th></tr></thead><tbody>'
    for label, files in labels.items():
        out += f"<tr><td><strong>{label.strip(chr(39)).strip(chr(34)).capitalize()}</strong></td>"
        out += f"<td><details><summary>{len(files)} files</summary><table>" if collapsible else "<td><table>"
        for filename, title, summary in files:
            published: str = filename.split("/")[-1]
            if title and title != "...":
                code: str = insert_br_after_x_chars(f"<code>{title}</code>", x=DELTA - 5).strip()
                if len(code) < DELTA - 5:
                    code += "&nbsp; " * ((DELTA - 5) - len(code))
                published = f"<strong>{published}</strong><dd>{code}</dd>"
            else:
                published = f"<strong>{published}</strong>"
            plus_minus, delta_nbsp, link = "", "", ""
            found: tuple[int, int] | None = counts.get(filename.lower().strip("/"))
            if found:
                plus_minus = f"+{found[0]}/-{found[1]}"
                if len(plus_minus) > 12 or plus_minus == "+0/-0":
                    plus_minus = "[link]"
                delta_nbsp = "&nbsp; " * max(0, 8 - len(plus_minus))
                link = diff_link(repo, pr, filename)
            description: str = insert_br_after_x_chars(summary, x=DELTA - 5)
            out += file_row(delta_nbsp, plus_minus, description, filename, published, link)
        out += "</table></details></td></tr>" if collapsible else "</table></td></tr>"
    return out + "</tr></tbody></table>"


def file_row(delta_nbsp: str, plus_minus: str, description: str, filename: str, published: str, link: str) -> str:
    if not description:
        return f'\n<tr>\n  <td>{published}</td>\n  <td><a href="{link}">{plus_minus}</a>{delta_nbsp}</td>\n\n</tr>\n'
    return (f'\n<tr>\n  <td>\n    <details>\n      <summary>{published}</summary>\n<hr>\n\n{filename}\n\n{description}\n\n\n'
            f'</details>\n\n\n  </td>\n  <td><a href="{link}">{plus_minus}</a>{delta_nbsp}</td>\n\n</tr>\n')


# ---------------------------------------------------------------- review floor

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


def is_test_path(path: str, globs: list[str] | None = None, dirs: list[str] | None = None) -> bool:
    """Whether the path is a test file: it matches a test glob (`test_globs` in local.toml, else the generic
    folder and name patterns) or contains one of the repository's `test_dirs` markers."""
    return matches(TEST_GLOBS if globs is None else globs, path) or any(d in path for d in (TEST_DIRS if dirs is None else dirs))


def breaking_change_counts(rule: dict[str, Any], path: str, deletions: int, contract: dict[str, Any] | None) -> bool:
    """Whether `level_if_deleted` applies to the file. By default any deleted line counts; a rule with
    `deleted_from = "contract"` counts only a breaking change (a removal or a newly required field) that the run's
    contract.json lists for the file, and falls back to the deleted-line count for a run that saved no contract.json."""
    if "level_if_deleted" not in rule:
        return False
    if rule.get("deleted_from") == "contract" and contract is not None:
        return contract.get("path") == path and bool(contract.get("removals") or contract.get("newly_required"))
    return deletions > 0


def file_floor(floor_cfg: dict[str, Any], path: str, deletions: int,
               contract: dict[str, Any] | None = None) -> tuple[str, str] | None:
    """The highest (level, rule name) among the rules that match the file, or None."""
    best: tuple[str, str] | None = None
    for rule in floor_cfg.get("floor", []):
        if not matches(rule["globs"], path):
            continue
        level: str = rule["level_if_deleted"] if breaking_change_counts(rule, path, deletions, contract) else rule["level"]
        if best is None or LEVELS.index(level) > LEVELS.index(best[0]):
            best = (level, rule["name"])
    return best


def file_tags(floor_cfg: dict[str, Any], path: str) -> list[str]:
    return [tag["name"] for tag in floor_cfg.get("tag", []) if matches(tag["globs"], path)]


# ---------------------------------------------------------------- directory labels

def route_url(folder: str) -> str:
    """Route URL of a flat-route folder: `_layout.a.$id._index` -> `/a/:id`."""
    segments: list[str] = [s for s in folder.split(".") if s and not s.startswith("_")]
    return "/" + "/".join(":" + s[1:] if s.startswith("$") else s for s in segments)


def directory_labels(paths: list[str]) -> dict[str, str]:
    """Label for each directory of the changed files: a route URL under the routes folder,
    otherwise the shortest path suffix that no other changed directory shares."""
    dirs: set[str] = {str(Path(p).parent) if "/" in p else "" for p in paths}
    labels: dict[str, str] = {}
    plain: list[str] = []
    for d in sorted(dirs):
        folder: str = d[len(ROUTES_DIR):].split("/")[0] if ROUTES_DIR and d.startswith(ROUTES_DIR) else ""
        url: str = route_url(folder) if folder else ""
        if folder and (url != "/" or folder == "_index"):
            labels[d] = url
        elif folder:
            labels[d] = folder
        else:
            plain.append(d)
    for d in plain:
        parts: list[str] = d.split("/") if d else []
        others: list[list[str]] = [o.split("/") if o else [] for o in plain if o != d]
        labels[d] = "(root)" if not parts else "/".join(parts)
        for k in range(1, len(parts) + 1):
            if not any(o[-k:] == parts[-k:] for o in others):
                labels[d] = "/".join(parts[-k:])
                break
    return labels


# ---------------------------------------------------------------- start lines

HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
DIFF_START = "The PR Git Diff:\n=====\n"
DIFF_END = "\n=====\n\nNote that lines in the diff body"

START_WHY_MAX_WORDS = 15

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


def resolve_start(raw: Any, name: str, files: list[str], diff_lines: dict[str, list[DiffLine]],
                  notes: list[str]) -> dict[str, Any] | None:
    """The chunk's start line when its quoted text matches exactly one line of the quoted file's diff."""
    if raw is None:
        return None
    path: str = clean_path(raw.get("file", "")) if isinstance(raw, dict) else ""
    text: str = str(raw.get("line_text", "")).strip() if isinstance(raw, dict) else ""
    if not path or not text:
        notes.append(f"chunk '{name}': start line not found")
        return None
    if path not in files:
        notes.append(f"chunk '{name}': start file is not one of the chunk's files: {path}")
        return None
    found: list[DiffLine] = [line for line in diff_lines.get(path, []) if line[2] == text]
    if not found:
        notes.append(f"chunk '{name}': start line not found")
        return None
    if len(found) > 1:
        notes.append(f"chunk '{name}': start line matched {len(found)} lines")
        return None
    side, number, _ = found[0]
    start: dict[str, Any] = {"path": path, "side": side, "line": number, "text": text}
    why: str | None = start_why(raw.get("why"), name, notes)
    if why:
        start["why"] = why
    return start


def start_why(raw: Any, name: str, notes: list[str]) -> str | None:
    """The reason to read the start line when it is one to START_WHY_MAX_WORDS words; None when absent or invalid."""
    if raw is None:
        return None
    why: str = " ".join(str(raw).split())
    if not why:
        notes.append(f"chunk '{name}': start reason is empty, dropped")
        return None
    if len(why.split()) > START_WHY_MAX_WORDS:
        notes.append(f"chunk '{name}': start reason is longer than {START_WHY_MAX_WORDS} words, dropped")
        return None
    return why


STEP_MAX_WORDS = 2


def clean_step(raw: Any, name: str, notes: list[str]) -> str | None:
    """The chunk's stage along the data path when it is one or two words; None when absent or invalid."""
    if raw is None:
        return None
    step: str = " ".join(str(raw).split()).strip(".:,;")
    if not step:
        notes.append(f"chunk '{name}': step is empty, dropped")
        return None
    if len(step.split()) > STEP_MAX_WORDS:
        notes.append(f"chunk '{name}': step is longer than {STEP_MAX_WORDS} words, dropped")
        return None
    return step


# ---------------------------------------------------------------- review chunks

@dataclass
class Chunk:
    name: str
    review: str
    why: str
    files: list[str]
    nodes: list[str] = field(default_factory=list)
    number: int = 0
    boxes: list[int] = field(default_factory=list)
    raised_by: list[str] = field(default_factory=list)
    start: dict[str, Any] | None = None
    step: str | None = None
    following: list[int] = field(default_factory=list)


def clean_path(raw: Any) -> str:
    return str(raw).strip().strip("`'\"").removeprefix("./")


def clean_nodes(raw: Any) -> list[str]:
    items: list[Any] = re.split(r"[,\s]+", raw) if isinstance(raw, str) else raw if isinstance(raw, list) else []
    return list(dict.fromkeys(n for n in (str(item).strip().strip("`'\"") for item in items) if n))


UNCHUNKED = "Unchunked"


def order_files(files: list[str], start: dict[str, Any] | None) -> list[str]:
    """The chunk's start file first, then the other files in the model's order, test files last."""
    first: list[str] = [start["path"]] if start else []
    rest: list[str] = [path for path in files if path not in first]
    return first + [p for p in rest if not is_test_path(p)] + [p for p in rest if is_test_path(p)]


def build_chunks(raw_chunks: Any, counts: dict[str, tuple[int, int]], paths: list[str], floor_cfg: dict[str, Any],
                 notes: list[str], diff_lines: dict[str, list[DiffLine]], contract: dict[str, Any] | None = None,
                 flow_order: bool = False) -> list[Chunk]:
    chunks: list[Chunk] = []
    seen: set[str] = set()
    for item in raw_chunks if isinstance(raw_chunks, list) else []:
        if not isinstance(item, dict):
            continue
        name: str = str(item.get("name", "")).strip()
        files: list[str] = []
        for raw_path in item.get("files") or []:
            path: str = clean_path(raw_path)
            if path not in paths:
                notes.append(f"chunk '{name}': dropped a path that is not in the PR: {path}")
            elif path not in seen:
                seen.add(path)
                files.append(path)
        if not files:
            notes.append(f"chunk '{name}': dropped, it has no files")
            continue
        review: str = str(item.get("review", "")).strip().lower()
        if review not in LEVELS:
            notes.append(f"chunk '{name}': unknown review level {review!r}, using 'read'")
            review = "read"
        step: str | None = clean_step(item.get("step"), name, notes)
        if flow_order and step is None and "step" not in item:
            notes.append(f"chunk '{name}': no step")
        start: dict[str, Any] | None = resolve_start(item.get("start"), name, files, diff_lines, notes)
        chunks.append(Chunk(name, review, str(item.get("why", "")).strip(), order_files(files, start),
                            clean_nodes(item.get("nodes")), start=start, step=step))
    missing: list[str] = [p for p in paths if p not in seen]
    if missing:
        notes.append("files the model left out of every chunk: " + ", ".join(missing))
        chunks.append(Chunk(UNCHUNKED, "read", "Not assigned to a chunk by the model", order_files(missing, None)))
    for chunk in chunks:
        apply_floor(chunk, counts, floor_cfg, contract)
    if flow_order:
        # The model's order is the flow of the change; the floors raise a level but do not move a chunk.
        chunks.sort(key=lambda chunk: chunk.name == UNCHUNKED)
    else:
        # Highest level first, ties in the model's order, and the catch-all chunk last, as the extension's list has it.
        chunks.sort(key=lambda chunk: (chunk.name == UNCHUNKED, -LEVELS.index(chunk.review)))
    for number, chunk in enumerate(chunks, 1):
        chunk.number = number
    return chunks


NODE_DECLARATION = re.compile(r'(?<![\w-])(?P<id>[A-Za-z0-9_][A-Za-z0-9_-]*)(?P<open>\s*\[")(?:\d+\s*·\s*|\d+[.:)]\s+)?')


def declaration_positions(lines: list[str]) -> dict[str, int]:
    """Node id -> index of its first labelled declaration in the flowchart."""
    position: dict[str, int] = {}
    for line in lines:
        if not NON_EDGE_LINE.match(line):
            for declaration in NODE_DECLARATION.finditer(line):
                position.setdefault(declaration.group("id"), len(position))
    return position


def keep_diagram_nodes(chunks: list[Chunk], position: dict[str, int], notes: list[str]) -> dict[str, int]:
    """Drop from every chunk the node ids that are not in the diagram, noting each in `notes`.
    Returns node id -> index of the first chunk (in the model's order) that lists it."""
    owner: dict[str, int] = {}
    for index, chunk in enumerate(chunks):
        known: list[str] = [node for node in chunk.nodes if node in position]
        for node in chunk.nodes:
            if node not in position:
                notes.append(f"chunk '{chunk.name}': ignored node id that is not in the diagram: {node}")
            else:
                owner.setdefault(node, index)
        chunk.nodes = known
    return owner


def prefix_labels(lines: list[str], number_of: Callable[[str], int | None]) -> str:
    """Prefix each labelled node declaration with `<n> · `, replacing any number the model wrote.
    A node for which `number_of` returns None keeps no number."""
    def prefix(declaration: re.Match[str]) -> str:
        number: int | None = number_of(declaration.group("id"))
        label_number: str = f"{number} · " if number is not None else ""
        return f"{declaration.group('id')}{declaration.group('open')}{label_number}"

    return "\n".join(line if NON_EDGE_LINE.match(line) else NODE_DECLARATION.sub(prefix, line) for line in lines)


def number_chunks_by_path(diagram: str, chunks: list[Chunk], notes: list[str]) -> str:
    """Number the chunks by where their nodes first appear in the diagram, set each chunk's
    `number`, and prefix every node label with the number of the first chunk (in the model's
    order) that lists the node."""
    lines: list[str] = diagram.split("\n")
    position: dict[str, int] = declaration_positions(lines)
    owner: dict[str, int] = keep_diagram_nodes(chunks, position, notes)

    on_diagram: list[int] = sorted((i for i, c in enumerate(chunks) if c.nodes),
                                   key=lambda i: min(position[n] for n in chunks[i].nodes))
    for number, index in enumerate(on_diagram + [i for i, c in enumerate(chunks) if not c.nodes], 1):
        chunks[index].number = number

    return prefix_labels(lines, lambda node: chunks[owner[node]].number if node in owner else None)


def number_boxes(diagram: str, chunks: list[Chunk], notes: list[str]) -> str:
    """Number the diagram's boxes 1..N in the order they are first declared, prefix every label
    with its box number, and set each chunk's `boxes` to the sorted numbers of its nodes."""
    lines: list[str] = diagram.split("\n")
    position: dict[str, int] = declaration_positions(lines)
    keep_diagram_nodes(chunks, position, notes)
    for chunk in chunks:
        chunk.boxes = sorted(position[node] + 1 for node in chunk.nodes)
    return prefix_labels(lines, lambda node: position[node] + 1)


def number_by_flow(diagram: str, chunks: list[Chunk], notes: list[str]) -> str:
    """Prefix every node label with the flow step (the number) of the first chunk, in flow order, that lists the node."""
    lines: list[str] = diagram.split("\n")
    owner: dict[str, int] = keep_diagram_nodes(chunks, declaration_positions(lines), notes)
    return prefix_labels(lines, lambda node: chunks[owner[node]].number if node in owner else None)


def also_block(lines: list[str]) -> tuple[int, int] | None:
    """Indexes of the `subgraph also` line and of the `end` that closes it, or None when there is none."""
    start: int | None = next((i for i, line in enumerate(lines) if re.match(rf"\s*subgraph\s+{ALSO_ID}\b", line)), None)
    if start is None:
        return None
    depth: int = 0
    for index in range(start, len(lines)):
        if re.match(r"\s*subgraph\b", lines[index]):
            depth += 1
        elif re.match(r"\s*end\s*$", lines[index]):
            depth -= 1
            if depth == 0:
                return start, index
    return None


def main_file(chunk: Chunk, counts: dict[str, tuple[int, int]]) -> str:
    """The chunk's file with the most changed lines (the first one on a tie)."""
    return max(chunk.files, key=lambda path: sum(counts[path.lower()]))


def add_chunk_boxes(diagram: str, chunks: list[Chunk], node_files: dict[str, list[str]] | None,
                    counts: dict[str, tuple[int, int]], notes: list[str]) -> str:
    """Give every chunk that still lists no node on the diagram a box of its own in the `also` subgraph (the
    model's, or one appended before the closing fence). The box is `chunk<n>["<chunk name><br/><main file>"]`; it
    becomes the chunk's node and, in `node_files`, covers all the chunk's files."""
    lines: list[str] = diagram.split("\n")
    taken: set[str] = set(declaration_positions(lines))
    keep_diagram_nodes(chunks, declaration_positions(lines), notes)
    added: list[str] = []
    for chunk in chunks:
        if chunk.nodes:
            continue
        node: str = f"chunk{chunk.number}"
        while node in taken:
            node += "x"
        taken.add(node)
        label: str = f"{chunk.name.replace(chr(34), '#quot;')}<br/>{main_file(chunk, counts).split('/')[-1]}"
        added.append(f'    {node}["{label}"]')
        chunk.nodes = [node]
        if node_files is not None:
            node_files[node] = list(chunk.files)
    if not added:
        return diagram
    block: tuple[int, int] | None = also_block(lines)
    if block:
        lines[block[1]:block[1]] = added
    else:
        lines[len(lines) - 1:len(lines) - 1] = [f"  {ALSO_SUBGRAPH}", *added, "  end"]
    return "\n".join(lines)


def style_skim(diagram: str, chunks: list[Chunk], notes: list[str]) -> str:
    """Give the boxes of the `also` subgraph that only skim-level chunks own a muted `skim` style."""
    lines: list[str] = diagram.split("\n")
    block: tuple[int, int] | None = also_block(lines)
    if not block:
        return diagram
    keep_diagram_nodes(chunks, declaration_positions(lines), notes)
    inside: list[str] = list(declaration_positions(lines[block[0]:block[1] + 1]))
    skim: list[str] = [node for node in inside
                       if (owners := [c for c in chunks if node in c.nodes]) and all(c.review == "skim" for c in owners)]
    if not skim:
        return diagram
    lines[len(lines) - 1:len(lines) - 1] = [f"  {SKIM_CLASS_DEF}", f"  class {','.join(skim)} skim"]
    return "\n".join(lines)


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


MAX_FOLLOWING = 3
# A dotted link is a return to an earlier box and `~~~` only spaces boxes apart, so neither is a step forward.
NOT_A_STEP = re.compile(r"\.|^~")


def diagram_successors(diagram: str) -> dict[str, list[str]]:
    """Box id -> the boxes the diagram's arrows lead to from it, in the order the arrows are written. A connector
    without an arrowhead is read from its first box to its second; `<-->` leads both ways."""
    successors: dict[str, list[str]] = {}
    for edge in parse_diagram_edges(diagram):
        if NOT_A_STEP.search(edge.link):
            continue
        successors.setdefault(edge.source, []).append(edge.target)
        if edge.link.startswith("<"):
            successors.setdefault(edge.target, []).append(edge.source)
    return successors


def assign_following(diagram: str, chunks: list[Chunk]) -> None:
    """Set each chunk's `following`: the numbers of the (at most three) chunks to read after it, in diagram order.

    From the boxes the chunk owns the diagram's arrows are walked breadth-first. A box owned by the chunk itself or
    by no chunk (context) is walked through; a box owned by other chunks ends that branch and gives each of them.
    The chunks are ordered by where the box that reached them is first declared in the diagram, then by number.
    A chunk with a lower number than this one is never offered, since a shared box can lead back to an earlier chunk.
    A chunk with no boxes, or whose walk reaches no later chunk, is followed by the next higher number, if any."""
    successors: dict[str, list[str]] = diagram_successors(diagram)
    position: dict[str, int] = declaration_positions(diagram.split("\n"))
    owners: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        for node in chunk.nodes:
            owners.setdefault(node, []).append(chunk)
    by_number: list[Chunk] = sorted(chunks, key=lambda chunk: chunk.number)
    for chunk in chunks:
        reached: dict[int, int] = {}
        seen: set[str] = set(chunk.nodes)
        queue: deque[str] = deque(chunk.nodes)
        while queue:
            for target in successors.get(queue.popleft(), []):
                if target in seen:
                    continue
                seen.add(target)
                if target in owners:
                    for other in owners[target]:
                        reached[other.number] = min(reached.get(other.number, position[target]), position[target])
                else:
                    queue.append(target)
        later: list[int] = [number for number in reached if number > chunk.number]
        chunk.following = sorted(later, key=lambda number: (reached[number], number))[:MAX_FOLLOWING]
        if not chunk.following:
            chunk.following = [other.number for other in by_number if other.number > chunk.number][:1]


def add_context_style(diagram: str, context_nodes: list[str]) -> str:
    """Give the nodes that cover no changed file a dashed `context` style, before the closing fence."""
    if not context_nodes:
        return diagram
    lines: list[str] = diagram.split("\n")
    lines[len(lines) - 1:len(lines) - 1] = [f"  {CONTEXT_CLASS_DEF}", f"  class {','.join(context_nodes)} context"]
    return "\n".join(lines)


# The look of an unstyled box in Mermaid's default theme, which the legend's "changed step" swatch copies.
DEFAULT_BOX = ("#ECECFF", "#9370DB")
SAVE_NODE = re.compile(r'(?<![\w-])(?P<id>[A-Za-z0-9_][A-Za-z0-9_-]*)\["[^\n]*?"\]:::save')
SAVE_CLASS_LINE = re.compile(r"^\s*class\s+(?P<ids>[\w,\s-]+?)\s+save\s*$", re.MULTILINE)
SKIM_CLASS_LINE = re.compile(r"^\s*class\s+(?P<ids>[\w,\s-]+?)\s+skim\s*$", re.MULTILINE)
SAVE_CLASS_DEF_LINE = re.compile(r"^\s*classDef\s+save\s+(?P<props>[^\n]+)$", re.MULTILINE)


def save_colors(diagram: str) -> tuple[str, str]:
    """(fill, stroke) of the diagram's `save` class: the model's own classDef, else the renderer's default."""
    found: re.Match[str] | None = SAVE_CLASS_DEF_LINE.search(diagram)
    props: dict[str, str] = dict(p.split(":", 1) for p in re.split(r"[;,]", found.group("props")) if ":" in p) if found else {}
    default: dict[str, str] = dict(p.split(":", 1) for p in SAVE_CLASS_DEF.split(" ", 2)[2].split(","))
    return props.get("fill", default["fill"]).strip(), props.get("stroke", default["stroke"]).strip()


def swatch(fill: str, stroke: str, dashed: bool = False) -> str:
    style: str = (f"display:inline-block;width:14px;height:9px;vertical-align:middle;border-radius:2px;"
                  f"background:{fill};border:1.5px {'dashed' if dashed else 'solid'} {stroke}")
    return f'<span style="{style}"></span>'


def diagram_legend(diagram: str, context_nodes: list[str]) -> str:
    """One line under the diagram naming only the box styles it uses, each with a swatch drawn like the boxes."""
    lines: list[str] = diagram.split("\n")
    nodes: set[str] = set(declaration_positions(lines))
    saved: set[str] = set(SAVE_NODE.findall(diagram))
    for found in SAVE_CLASS_LINE.finditer(diagram):
        saved.update(re.split(r"[,\s]+", found.group("ids").strip()))
    saved &= nodes
    context: set[str] = set(context_nodes) & nodes
    skim: set[str] = set()
    for found in SKIM_CLASS_LINE.finditer(diagram):
        skim.update(re.split(r"[,\s]+", found.group("ids").strip()))
    skim &= nodes
    fill, stroke = DEFAULT_BOX
    entries: list[str] = []
    if nodes - saved - context - skim:
        entries.append(f"{swatch(fill, stroke)} changed step")
    if saved:
        entries.append(f"{swatch(*save_colors(diagram))} writes data")
    if context:
        entries.append(f"{swatch('#fff', stroke, dashed=True)} unchanged context")
    if skim:
        entries.append(f"{swatch(*SKIM_COLORS)} skim, off the path")
    if any(re.match(rf"\s*subgraph\s+(?!{ALSO_ID}\b)", line) for line in lines):
        entries.append("columns are code layers")
    return "Legend: " + " · ".join(entries) if entries else ""


def format_boxes(boxes: list[int]) -> str:
    """Box numbers as comma-separated ranges, `1–3, 5`; an empty list is `—`."""
    runs: list[list[int]] = []
    for box in boxes:
        if runs and box == runs[-1][-1] + 1:
            runs[-1].append(box)
        else:
            runs.append([box])
    return ", ".join(str(run[0]) if len(run) == 1 else f"{run[0]}–{run[-1]}" for run in runs) or "—"


def apply_floor(chunk: Chunk, counts: dict[str, tuple[int, int]], floor_cfg: dict[str, Any],
                contract: dict[str, Any] | None = None) -> None:
    floors: list[tuple[str, str]] = []
    for path in chunk.files:
        found: tuple[str, str] | None = file_floor(floor_cfg, path, counts[path.lower()][1], contract)
        if found:
            floors.append(found)
    top: int = max([LEVELS.index(chunk.review)] + [LEVELS.index(level) for level, _ in floors])
    if top > LEVELS.index(chunk.review):
        chunk.raised_by = list(dict.fromkeys(name for level, name in floors if LEVELS.index(level) == top))
        chunk.review = LEVELS[top]


def inline(text: str) -> str:
    return replace_code_tags(html.escape(text, quote=False))


START_TEXT_LIMIT = 80


def start_cell(chunk: Chunk, repo: str, pr: str) -> str:
    """The chunk's start line under its name: a link to the line and a short quote of it."""
    if not chunk.start:
        return ""
    start: dict[str, Any] = chunk.start
    quote: str = start["text"] if len(start["text"]) <= START_TEXT_LIMIT else start["text"][:START_TEXT_LIMIT - 1] + "…"
    return (f'<br><sub>start <a href="{line_link(repo, pr, start)}" title="{html.escape(start["path"])}">'
            f'{html.escape(start["path"].split("/")[-1])}:{start["line"]}</a></sub><br><code>{html.escape(quote)}</code>')


def risk_rank(chunk: Chunk) -> int:
    """How high the chunk sits in the risk order: its level, with the catch-all chunk below every level."""
    return -1 if chunk.name == UNCHUNKED else LEVELS.index(chunk.review)


def chunks_walkthrough(chunks: list[Chunk], counts: dict[str, tuple[int, int]], paths: list[str],
                       floor_cfg: dict[str, Any], repo: str, pr: str, numbering: str, show_start: bool,
                       flow_order: bool = False) -> str:
    labels: dict[str, str] = directory_labels(paths)
    by_boxes: bool = numbering == "boxes"
    with_steps: bool = any(chunk.step for chunk in chunks)
    wide_first: bool = by_boxes or with_steps

    def boxes_width(width: str) -> str:
        return f' style="width: {width}"' if wide_first else ""

    out: str = ('<details open> <summary><h3> Review order</h3></summary>\n\n'
                f'<table class="review-order"><thead><tr><th{boxes_width("8%")}>{"Boxes" if by_boxes else "#"}</th>'
                '<th align="left">Chunk</th><th align="left">Review</th>'
                f'<th align="left"{boxes_width("27%")}>Why</th><th align="left">Files</th></tr></thead><tbody>')
    for chunk in chunks:
        review: str = f"<strong>{chunk.review}</strong>" if chunk.review == "read carefully" else chunk.review
        if chunk.raised_by:
            review += f"<br><sub>raised by {html.escape(', '.join(chunk.raised_by))}</sub>"
        rows: str = ""
        for path in chunk.files:
            directory: str = str(Path(path).parent) if "/" in path else ""
            plus, minus = counts[path.lower()]
            tags: str = "".join(f" <em>{html.escape(t)}</em>" for t in file_tags(floor_cfg, path))
            rows += (f'<tr><td><code title="{html.escape(directory or "(root)")}">{html.escape(labels[directory]).replace("/", "/<wbr>")}</code><br>'
                     f'<a href="{diff_link(repo, pr, path)}"><strong>{html.escape(path.split("/")[-1])}</strong></a> +{plus}/-{minus}{tags}</td></tr>')
        first_cell: str = format_boxes(chunk.boxes) if by_boxes else str(chunk.number)
        if chunk.step:
            first_cell += f"<br><sub>{html.escape(chunk.step)}</sub>"
        start: str = start_cell(chunk, repo, pr) if show_start else ""
        order_data: str = f' data-flow="{chunk.number}" data-risk="{risk_rank(chunk)}"' if flow_order and with_steps else ""
        out += (f"<tr{order_data}><td>{first_cell}</td><td><strong>{inline(chunk.name)}</strong>{start}</td><td>{review}</td>"
                f"<td>{inline(chunk.why)}</td><td><table>{rows}</table></td></tr>")
    return out + "</tbody></table>\n\n</details>\n\n"


# ---------------------------------------------------------------- contract and data block

def contract_section(run: dict[str, Any], pr: dict[str, Any], contract: dict[str, Any] | None, diff_text: str) -> str:
    """The "Contract and data" block: the run's API contract changes and the tables its migration files touch."""
    repo: str = run["repo"]
    number: str = str(run["pr"])
    context: dict[str, Any] = run.get("context") or {}
    api_checked: bool = "contract" in (context.get("sections") or {}) and "contract" not in (context.get("dropped") or {})
    unchecked: list[str] = []
    rows: list[Any] = []
    if contract is not None:
        rows += contract_rows(contract, file_diff_lines(diff_text, contract["path"]), contract["path"])
    elif not api_checked:
        unchecked.append("API")
    if MIGRATION_GLOBS:
        migrations: list[str] = [f["path"] for f in pr["files"]
                                 if matches(MIGRATION_GLOBS, f["path"]) and f.get("changeType") != "DELETED"]
        rows += migration_rows({path: file_diff_lines(diff_text, path) for path in migrations})
    else:
        unchecked.append("database")
    return contract_block(rows,
                          lambda path, side, line: line_link(repo, number, {"path": path, "side": side, "line": line}),
                          lambda path: diff_link(repo, number, path), unchecked)


# ---------------------------------------------------------------- body

def build_body(run: dict[str, Any], pr: dict[str, Any], data: dict[str, Any], cfg: dict[str, Any],
               floor_cfg: dict[str, Any], diff_lines: dict[str, list[DiffLine]],
               notes: list[str], contract: dict[str, Any] | None = None,
               diff_text: str = "") -> tuple[str, tuple[int, int], list[Chunk], list[dict[str, Any]] | None]:
    pr_number: str = str(run["pr"])
    counts: dict[str, tuple[int, int]] = {f["path"].lower(): (f["additions"], f["deletions"]) for f in pr["files"]}
    paths: list[str] = [f["path"] for f in pr["files"]]

    ordered: dict[str, Any] = {}
    if run["with_body"] and (pr["body"] or "").strip():
        ordered["User Description"] = pr["body"].strip()
    for key in ("type", "description"):
        if key in data:
            ordered[key] = data[key]
    if cfg.get("contract_block"):
        ordered["contract_and_data"] = contract_section(run, pr, contract, diff_text)
    flow_order: bool = cfg.get("chunk_order") == "flow"
    if cfg.get("chunk_order", "risk") not in ("risk", "flow"):
        raise AnswerError(f"unknown render chunk_order {cfg['chunk_order']!r}, expected 'risk' or 'flow'")
    chunks: list[Chunk] = []
    if cfg.get("files") == "chunks":
        chunks = build_chunks(data.get("chunks"), counts, paths, floor_cfg, notes, diff_lines, contract, flow_order)
    diagram: str = render_diagram(data.get("changes_diagram"), cfg)
    numbering: str = cfg.get("numbering", "chunks")
    if numbering not in ("chunks", "boxes", "flow"):
        raise AnswerError(f"unknown render numbering {numbering!r}, expected 'chunks', 'boxes' or 'flow'")
    node_files: dict[str, list[str]] | None = None
    if diagram and "node_files" in data:
        node_files = clean_node_files(data["node_files"], declaration_positions(diagram.split("\n")), paths, notes)
        diagram = add_context_style(diagram, [node for node, files in node_files.items() if not files])
    if diagram and chunks and cfg.get("chunk_box_fallback"):
        diagram = add_chunk_boxes(diagram, chunks, node_files, counts, notes)
    if diagram:
        diagram = style_skim(diagram, chunks, notes)
    if diagram and numbering == "boxes":
        diagram = number_boxes(diagram, chunks, notes)
    elif diagram and numbering == "flow":
        diagram = number_by_flow(diagram, chunks, notes)
    elif diagram and any(isinstance(item, dict) and "nodes" in item for item in data.get("chunks") or []):
        diagram = number_chunks_by_path(diagram, chunks, notes)
    assign_following(diagram, chunks)
    edges: tuple[int, int] = count_diagram_edges(diagram)
    legend: str = ""
    if diagram and cfg.get("files") == "chunks":
        context_nodes: list[str] = [node for node, files in (node_files or {}).items() if not files]
        legend = diagram_legend(diagram, context_nodes)
    if diagram:
        ordered["changes_diagram"] = diagram
    if cfg.get("files") == "chunks":
        ordered["pr_files"] = True
    elif data.get("pr_files"):
        ordered["pr_files"] = data["pr_files"]

    body: str = ""
    walkthrough: str = ""
    for idx, (key, value) in enumerate(ordered.items()):
        if key == "changes_diagram":
            body += f"### Diagram Walkthrough\n\n{value}\n\n{legend + chr(10) * 2 if legend else ''}"
            continue
        if key == "pr_files":
            if cfg.get("files") == "chunks":
                walkthrough = chunks_walkthrough(chunks, counts, paths, floor_cfg, run["repo"], pr_number, numbering,
                                                bool(cfg.get("start_line")), flow_order)
            else:
                include_summary: bool = len(pr["files"]) <= COLLAPSIBLE_FILE_LIST_THRESHOLD
                labels = file_label_dict(value, include_summary)
                walkthrough = ("<details> <summary><h3> File Walkthrough</h3></summary>\n\n"
                               f"{labels_walkthrough(labels, counts, run['repo'], pr_number)}\n\n</details>\n\n")
        else:
            body += f"### **{'PR Type' if key == 'type' else key.replace('_', ' ').capitalize()}**\n"
            if isinstance(value, list):
                value = ", ".join(str(v).rstrip() for v in value)
            if key == "description":
                value = value.replace("\n-", "\n\n-").strip()
            body += f"{value}\n"
        if idx < len(ordered) - 1:
            body += "\n\n___\n\n"
    body += "\n\n" + walkthrough + "___\n\n"
    nodes: list[dict[str, Any]] | None = None
    if node_files is not None:
        nodes = [{"id": node, "number": index + 1 if numbering == "boxes" else None, "files": files}
                 for index, (node, files) in enumerate(node_files.items())]
    return f"# {pr['title']}\n\n<!-- pr-agent-generated -->\n{body}", edges, chunks, nodes


# ---------------------------------------------------------------- review.json

def review_json(run: dict[str, Any], pr: dict[str, Any], chunks: list[Chunk], has_diagram: bool,
                nodes: list[dict[str, Any]] | None) -> dict[str, Any]:
    """The chunks in review order, for the browser extension that groups the Files changed page by chunk."""
    counts: dict[str, tuple[int, int]] = {f["path"].lower(): (f["additions"], f["deletions"]) for f in pr["files"]}
    return {
        "schema": 2,
        "repo": run["repo"],
        "pr": run["pr"],
        "head_sha": run["pr_head_sha"],
        "variant": run["variant"],
        **({"diagram": DIAGRAM_SVG} if has_diagram else {}),
        **({"nodes": nodes} if nodes is not None else {}),
        "chunks": [{"n": c.number, "name": c.name, "review": c.review, "raised_by": c.raised_by, "why": c.why,
                    "nodes": c.nodes,
                    "files": [{"path": path, "additions": counts[path.lower()][0], "deletions": counts[path.lower()][1]}
                              for path in c.files],
                    "next": c.following,
                    **({"step": c.step} if c.step else {}),
                    **({"start": c.start} if c.start else {})} for c in chunks],
    }


# ---------------------------------------------------------------- diagram svg

DIAGRAM_SVG = "diagram.svg"
SVG_ID = "pr-diagram"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_TIMEOUT_SECONDS = 90
MERMAID_FENCE = re.compile(r"```mermaid\n(.*?)\n```", re.DOTALL)
SVG_OUT = re.compile(r'<pre id="svg-out">(.*?)</pre>', re.DOTALL)

DIAGRAM_STYLE = r"""
const DIAGRAM_CONFIG = {
  themeVariables: { fontFamily: '-apple-system, "Segoe UI", sans-serif' },
  themeCSS: `
    .node rect.label-container { rx: 14px; ry: 14px; fill: none; stroke: #9370db; stroke-width: 1px; }
    .node.save rect.label-container { fill: #fff4e5; stroke: #b26a00; }
    .node.context rect.label-container { fill: none; stroke: #b4b2a9; stroke-dasharray: 4 4; }
    .node.skim rect.label-container { fill: #eef0f2; stroke: #afb8c1; }
    .node .nodeLabel, .node .label div { color: #26215c; text-align: center; }
    .node .nodeLabel p { margin: 0; }
    .nodeLabel .n { color: #9370db; }
    .nodeLabel .t { font-weight: 600; }
    .nodeLabel .s { color: #5f5e5a; font-weight: 400; }
    .save .nodeLabel, .save .label div { color: #633806; }
    .save .nodeLabel .n { color: #b26a00; }
    .save .nodeLabel .s { color: #854f0b; }
    .context .nodeLabel, .context .label div { color: #5f5e5a; }
    .context .nodeLabel .n { color: #b4b2a9; }
    .skim .nodeLabel, .skim .label div { color: #6e7781; }
    .skim .nodeLabel .n { color: #afb8c1; }
    .skim .nodeLabel .s { color: #8c959f; }
    path.flowchart-link { stroke: #9370db; stroke-width: 1px; fill: none; }
    .marker, .arrowMarkerPath { fill: none !important; stroke: #9370db !important; stroke-width: 1px; }
    .edgeLabel rect { fill: transparent !important; opacity: 0; }
    .edgeLabel, .edgeLabel p, .edgeLabel span, .labelBkg { background-color: transparent !important; color: #7f77dd !important; font-weight: 400; text-shadow: 0 0 3px #fff, 0 0 3px #fff, 0 0 3px #fff; }
    .cluster rect { fill: none; stroke: #e5e3f0; stroke-width: 1px; rx: 8px; ry: 8px; }
    .cluster-label .nodeLabel, .cluster-label span, .cluster-label p { color: #8a8a99; font-size: 12px; font-weight: 400; }
  `,
};

// The leading box number, the title and the second line of a node label each get a class the theme styles.
// Node declarations only: subgraph titles and edge labels stay as written. The save, context and skim classDefs are
// dropped because the theme styles those classes.
function styleDiagramText(text) {
  const skip = /^\s*(%%|classDef\b|class\b|style\b|linkStyle\b|subgraph\b|click\b|direction\b)/;
  const themed = /^\s*classDef\s+(save|context|skim)\b/;
  return text.split('\n').filter((line) => !themed.test(line)).map((line) => skip.test(line) ? line : line.replace(
    /(^|[^\w-])([A-Za-z0-9_][\w-]*)\["([^"]*)"\]/g,
    (match, before, id, label) => {
      const [first, ...rest] = label.split(/<br\s*\/?>/);
      const number = /^(\d+)\s*·\s*/.exec(first);
      const title = number ? first.slice(number[0].length) : first;
      const lead = number ? "<span class='n'>" + number[1] + " ·</span> " : '';
      const second = rest.length ? "<br/><span class='s'>" + rest.join('<br/>') + '</span>' : '';
      return before + id + '["' + lead + "<span class='t'>" + title + '</span>' + second + '"]';
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

// body.md's legend swatches are drawn in the old box colours; this redraws them in the current look.
function restyleLegend(root) {
  const looks = [
    [/^changed/, 'none', '#9370db', 'solid'],
    [/^writes/, '#fff4e5', '#b26a00', 'solid'],
    [/^unchanged/, 'none', '#b4b2a9', 'dashed'],
    [/^skim/, '#eef0f2', '#afb8c1', 'solid'],
  ];
  for (const paragraph of root.querySelectorAll('p')) {
    if (!paragraph.textContent.startsWith('Legend:')) continue;
    for (const swatch of paragraph.querySelectorAll('span[style]')) {
      const word = (swatch.nextSibling?.textContent ?? '').trim();
      const look = looks.find(([pattern]) => pattern.test(word));
      if (!look) continue;
      swatch.style.cssText = 'display:inline-block;width:14px;height:9px;vertical-align:middle;border-radius:7px;' +
        'background:' + look[1] + ';border:1px ' + look[3] + ' ' + look[2];
    }
  }
}
"""

# Renders the diagram the way the comparison page does (same mermaid build and theme) and leaves the
# serialized SVG in #svg-out, since HTML serialization of the SVG would not be well-formed XML.
SVG_PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<pre class="mermaid" id="diagram"></pre><pre id="svg-out"></pre>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
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


def render_svg(diagram_text: str) -> str:
    """The diagram as an SVG document, rendered by headless Chrome. Raises AnswerError when it can't be."""
    if not Path(CHROME).exists():
        raise AnswerError("Chrome is not installed")
    with tempfile.TemporaryDirectory() as tmp:
        page: Path = Path(tmp) / "diagram.html"
        page.write_text(SVG_PAGE.replace("__DIAGRAM_STYLE__", DIAGRAM_STYLE).replace("__TEXT__", json.dumps(diagram_text).replace("</", "<\\/")))
        try:
            out: subprocess.CompletedProcess[str] = subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", f"--user-data-dir={tmp}/profile", "--virtual-time-budget=15000",
                 "--dump-dom", page.as_uri()],
                capture_output=True, text=True, timeout=CHROME_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as e:
            raise AnswerError("Chrome timed out") from e
    found: re.Match[str] | None = SVG_OUT.search(out.stdout)
    svg: str = html.unescape(found.group(1)).strip() if found else ""
    root: re.Match[str] | None = re.match(r'<svg id="([^"]+)"', svg)
    if not root:
        raise AnswerError(f"Chrome did not produce an SVG: {svg[:200] or 'no output'}")
    return svg.replace(root.group(1), SVG_ID)  # mermaid derives its id from the clock; a fixed one keeps the file stable


def write_diagram_svg(md: str, run_dir: Path, notes: list[str]) -> bool:
    """Writes diagram.svg for the diagram in `md`; a failure is noted and skipped, never fatal."""
    fence: re.Match[str] | None = MERMAID_FENCE.search(md)
    if not fence:
        return False
    try:
        (run_dir / DIAGRAM_SVG).write_text(render_svg(fence.group(1)) + "\n")
    except (AnswerError, OSError) as e:
        notes.append(f"{DIAGRAM_SVG} skipped: {e}")
        return False
    return True


# ---------------------------------------------------------------- pages

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/github-markdown-css@5/github-markdown-light.css">
<style>
 body { background: #fff; margin: 0; }
 .markdown-body { box-sizing: border-box; max-width: 980px; margin: 0 auto; padding: 32px 16px; }
 pre.mermaid { background: #fff; text-align: center; }
 table.review-order { display: table; table-layout: fixed; width: 100%; }
 table.review-order > thead > tr > th:nth-child(1) { width: 4%; }
 table.review-order > thead > tr > th:nth-child(2) { width: 16%; }
 table.review-order > thead > tr > th:nth-child(3) { width: 11%; }
 table.review-order > thead > tr > th:nth-child(4) { width: 31%; }
 table.review-order > thead > tr > th:nth-child(5) { width: 38%; }
 table.review-order td, table.review-order th { padding: 6px 8px; overflow-wrap: break-word; }
 table.review-order table { display: table; table-layout: fixed; width: 100%; }
 table.review-order table td { padding: 2px 0; border: 0; background: none; overflow-wrap: anywhere; }
 table.review-order table tr, table.review-order table tr:nth-child(2n) { border: 0; background: none; }
</style></head><body><article class="markdown-body" id="out"></article>
<script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>
__DIAGRAM_STYLE__
 const md = __MD__;
 document.getElementById('out').innerHTML = marked.parse(md, { gfm: true });
 restyleLegend(document.getElementById('out'));
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
    run_dir: Path = Path(sys.argv[1]).resolve()
    run: dict[str, Any] = json.loads((run_dir / "run.json").read_text())
    LINK_HOST = get_host(run.get("host", "github"), load_local())
    pr: dict[str, Any] = json.loads((run_dir / "pr.json").read_text())
    variant_path: Path | None = variant_file(run["variant"])
    if variant_path is None:
        raise SystemExit(f"no variant {run['variant']!r} in $PR_DESCRIBE_HOME/variants or the tool's variants")
    cfg: dict[str, Any] = tomllib.loads(variant_path.read_text()).get("render", {})
    floor_file: Path | None = config_file("review_floor", fall_back_to_example=True)
    floor_cfg: dict[str, Any] = tomllib.loads(floor_file.read_text()) if floor_file else {}
    raw: str = (run_dir / "answer.yaml").read_text()
    contract_file: Path = run_dir / "contract.json"
    contract: dict[str, Any] | None = json.loads(contract_file.read_text()) if contract_file.exists() else None
    notes: list[str] = []
    for stale in ("body.md", "body.html", "review.json", DIAGRAM_SVG, "error.txt"):
        (run_dir / stale).unlink(missing_ok=True)

    try:
        if run["exit_status"] != 0:
            raise AnswerError(f"claude exited with status {run['exit_status']}")
        data: dict[str, Any] = parse_answer(raw)
        prompt_file: Path = run_dir / "prompt.txt"
        diff_text: str = diff_from_prompt(prompt_file.read_text()) if prompt_file.exists() else ""
        diff_lines: dict[str, list[DiffLine]] = diff_lines_by_path(diff_text)
        md, (labelled, total), chunks, nodes = build_body(run, pr, data, cfg, floor_cfg, diff_lines, notes, contract, diff_text)
    except AnswerError as e:
        (run_dir / "error.txt").write_text(f"{e}\n")
        (run_dir / "body.html").write_text(ERROR_PAGE.replace("__ERROR__", html.escape(str(e))).replace("__RAW__", html.escape(raw)))
        print(f"{run_dir}: {e}", file=sys.stderr)
        return 1

    run["diagram_edges"] = {"labelled": labelled, "total": total}
    (run_dir / "run.json").write_text(json.dumps(run, indent=2) + "\n")
    (run_dir / "body.md").write_text(md)
    (run_dir / "body.html").write_text(markdown_page(md))
    has_diagram: bool = write_diagram_svg(md, run_dir, notes)
    if cfg.get("files") == "chunks":
        (run_dir / "review.json").write_text(json.dumps(review_json(run, pr, chunks, has_diagram, nodes), indent=2) + "\n")
    if notes:
        (run_dir / "error.txt").write_text("Rendered with these fixes:\n" + "\n".join(f"- {n}" for n in notes) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
