#!/usr/bin/env python3
"""Render a run's answer.yaml as the PR body, and as a standalone HTML page.

usage: render.py <run dir>      e.g. runs/42/one_path_risk_chunked_v23

Reads answer.yaml, run.json and pr.json from the run dir and the variant's [render] settings.
Writes body.md and body.html, review.json and the diagram's SVG, and records the diagram's labelled and total arrows in run.json. On broken YAML it writes error.txt and an error page and exits 1.
The body is the PR's title, the model's description, the Contract and Data sections, the diagram and its legend; the
chunks, walkthrough stops and contract lines go to review.json.
"""
import html
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from config import ROOT, config_file, load_local, variant_file
import layout
from diff_lines import file_diff_lines
from contract_lines import CALLERS, CONSUMERS, CONTRACT_LEVELS, Line, contract_lines
from data_lines import DATA_LEVELS, DESTRUCTIVE, data_lines
from hosts import get_host
from hosts.github import GitHub

sys.path.insert(0, str(ROOT / "vendor"))
from pr_agent_helpers import apply_diagram_direction, sanitize_diagram  # noqa: E402

DIAGRAM_THRESHOLD = 5
SAVE_CLASS_DEF = "classDef save fill:#fff4e5,stroke:#b26a00"
CONTEXT_CLASS_DEF = "classDef context stroke-dasharray:5 4,fill:#fff;"
LEVEL_CLASS = "lv-"
CHECK_CLASS = "chk-"
ALSO_ID = "also"
ALSO_SUBGRAPH = f'subgraph {ALSO_ID}["Also in this PR"]'
LEVELS: list[str] = ["skim", "read", "verify"]
# The level words that older variants ask the model for.
CHECK_ORDER: list[str] = ["logic", "contract", "breaking", "data", "destructive", "access", "generated"]
# The labels the model sets; the renderer sets the others (`breaking`, `destructive`, `generated`).
MODEL_CHECKS: list[str] = ["logic", "contract", "data", "access"]
MAX_MODEL_CHECKS = 3
MIGRATION_GLOBS: list[str] = load_local().get("migration_globs", [])
DEFAULT_TEST_GLOBS: list[str] = ["**/test/**", "**/tests/**", "**/*Test.*", "**/*Tests.*", "**/*.test.*", "**/*_test.*"]
TEST_GLOBS: list[str] = load_local().get("test_globs", DEFAULT_TEST_GLOBS)
TEST_DIRS: list[str] = load_local().get("test_dirs", [])
TAG_FILE_TEMPLATES: list[str] = load_local().get("tag_file_templates", layout.DEFAULT_TAG_TEMPLATES)


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


def normalize_level(raw: Any) -> str | None:
    """The review level a word names: one of LEVELS; None for anything else."""
    word: str = " ".join(str(raw or "").lower().split())
    return word if word in LEVELS else None


def file_floor(floor_cfg: dict[str, Any], path: str, deletions: int,
               contract: dict[str, Any] | None = None) -> tuple[str, str] | None:
    """The highest (level, rule name) among the rules that match the file, or None."""
    best: tuple[str, str] | None = None
    for rule in floor_cfg.get("floor", []):
        if not matches(rule["globs"], path):
            continue
        word: str = rule["level_if_deleted"] if breaking_change_counts(rule, path, deletions, contract) else rule["level"]
        level: str | None = normalize_level(word)
        if level is None:
            raise AnswerError(f"review floor {rule['name']!r} has an unknown level {word!r}")
        if best is None or LEVELS.index(level) > LEVELS.index(best[0]):
            best = (level, rule["name"])
    return best


def file_tags(floor_cfg: dict[str, Any], path: str) -> list[str]:
    return [tag["name"] for tag in floor_cfg.get("tag", []) if matches(tag["globs"], path)]


# ---------------------------------------------------------------- check labels

GENERATED_TAG = "generated"

def clean_checks(raw: Any, name: str, notes: list[str]) -> list[str]:
    """The labels the model gave the chunk, in display order: only logic, contract, data and access, at most
    MAX_MODEL_CHECKS of them."""
    items: list[Any] = re.split(r"[,\s]+", raw) if isinstance(raw, str) else raw if isinstance(raw, list) else []
    given: set[str] = set()
    for item in items:
        check: str = str(item).strip().strip("`'\"").lower()
        if not check:
            continue
        if check in MODEL_CHECKS:
            given.add(check)
        else:
            notes.append(f"chunk '{name}': unknown check {check!r}, dropped")
    ordered: list[str] = [check for check in CHECK_ORDER if check in given]
    if len(ordered) > MAX_MODEL_CHECKS:
        notes.append(f"chunk '{name}': {len(ordered)} checks, kept the first {MAX_MODEL_CHECKS}")
    return ordered[:MAX_MODEL_CHECKS]


def generated_share(floor_cfg: dict[str, Any], files: list[str]) -> str:
    """"all" when every file carries the `generated` tag, "none" when no file does, else "mixed"."""
    tagged: int = sum(GENERATED_TAG in file_tags(floor_cfg, path) for path in files)
    return "all" if tagged == len(files) else "none" if tagged == 0 else "mixed"


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


def resolve_stops(raw: Any, files: list[str], diff_lines: dict[str, list[DiffLine]],
                  chunk_of: dict[str, int]) -> tuple[list[dict[str, Any]], list[str]]:
    """The walkthrough's stops, numbered from 1 in the model's order, and the notes about what was fixed.

    A stop quoting a line found exactly once in its file's diff points at that line; any other stop points at its file
    alone (side and line None). A stop in a file outside the diff, or at a place an earlier stop already has, is
    dropped. `chunk` is the number of the chunk that holds the stop's file, from `chunk_of`."""
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
        stops.append({"i": len(stops) + 1, "title": title, "why": why, "path": path, "side": side, "line": number,
                      "chunk": chunk_of.get(path)})
    low, high = STOPS_RANGE
    if not low <= len(stops) <= high:
        notes.append(f"{len(stops)} stops, expected {low} to {high}")
    return stops, notes


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
    raised_by: list[str] = field(default_factory=list)
    step: str | None = None
    checks: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    contract: list[Line] = field(default_factory=list)
    data: list[Line] = field(default_factory=list)


def clean_path(raw: Any) -> str:
    return str(raw).strip().strip("`'\"").removeprefix("./")


def clean_nodes(raw: Any) -> list[str]:
    items: list[Any] = re.split(r"[,\s]+", raw) if isinstance(raw, str) else raw if isinstance(raw, list) else []
    return list(dict.fromkeys(n for n in (str(item).strip().strip("`'\"") for item in items) if n))


UNCHUNKED = "Unchunked"


def order_files(files: list[str]) -> list[str]:
    """The files in the model's order, test files last."""
    return [p for p in files if not is_test_path(p)] + [p for p in files if is_test_path(p)]


def build_chunks(raw_chunks: Any, counts: dict[str, tuple[int, int]], paths: list[str], floor_cfg: dict[str, Any],
                 notes: list[str], diff_lines: dict[str, list[DiffLine]], contract: dict[str, Any] | None = None,
                 review_labels: bool = False, lineset: layout.LineSet | None = None) -> list[Chunk]:
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
        review: str | None = normalize_level(item.get("review"))
        if review is None:
            notes.append(f"chunk '{name}': unknown review level {str(item.get('review', '')).strip().lower()!r}, using 'read'")
            review = "read"
        step: str | None = clean_step(item.get("step"), name, notes)
        if step is None and "step" not in item:
            notes.append(f"chunk '{name}': no step")
        chunk: Chunk = Chunk(name, review, str(item.get("why", "")).strip(), order_files(files),
                             clean_nodes(item.get("nodes")), step=step)
        if review_labels:
            chunk.checks = clean_checks(item.get("checks"), name, notes)
        chunks.append(chunk)
    missing: list[str] = [p for p in paths if p not in seen]
    if missing:
        notes.append("files the model left out of every chunk: " + ", ".join(missing))
        chunks.append(Chunk(UNCHUNKED, "skim", "Not assigned to a chunk by the model", order_files(missing)))
    if lineset is not None:
        place_lines(chunks, lineset, floor_cfg, diff_lines)
    raising: dict[int, list[tuple[str, str]]] = {}
    if review_labels:
        raising = apply_labels(chunks, floor_cfg, notes)
    for index, chunk in enumerate(chunks):
        apply_floor(chunk, counts, floor_cfg, contract, raising.get(index, []))
    # The model's order is the flow of the change; the floors raise a level but do not move a chunk.
    chunks.sort(key=lambda chunk: chunk.name == UNCHUNKED)
    for number, chunk in enumerate(chunks, 1):
        chunk.number = number
    return chunks


def build_walkthrough(raw: Any, chunks: list[Chunk], paths: list[str], diff_lines: dict[str, list[DiffLine]],
                      notes: list[str]) -> list[dict[str, Any]]:
    """The resolved stops, with a note for each `verify` chunk that no stop visits."""
    chunk_of: dict[str, int] = {path: chunk.number for chunk in chunks for path in chunk.files}
    stops, stop_notes = resolve_stops(raw, paths, diff_lines, chunk_of)
    notes.extend(stop_notes)
    visited: set[int | None] = {stop["chunk"] for stop in stops}
    notes.extend(f"chunk '{chunk.name}': a verify chunk with no walkthrough stop"
                 for chunk in chunks if chunk.review == "verify" and chunk.number not in visited)
    return stops


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


def note_box_sharing(diagram: str, chunks: list[Chunk], notes: list[str]) -> None:
    """Note each box claimed by more than one chunk and each chunk with no box or with several, for variants that
    ask for exactly one box per chunk. The diagram and the chunks are left as they are."""
    keep_diagram_nodes(chunks, declaration_positions(diagram.split("\n")), notes)
    claimed: dict[str, list[str]] = {}
    for chunk in chunks:
        for node in chunk.nodes:
            claimed.setdefault(node, []).append(chunk.name)
    for node, names in claimed.items():
        if len(names) > 1:
            notes.append(f"box {node} is claimed by {len(names)} chunks: " + ", ".join(f"'{name}'" for name in names))
    for chunk in chunks:
        if not chunk.nodes:
            notes.append(f"chunk '{chunk.name}': has no box")
        elif len(chunk.nodes) > 1:
            notes.append(f"chunk '{chunk.name}': has {len(chunk.nodes)} boxes: " + ", ".join(chunk.nodes))


def prefix_labels(lines: list[str], number_of: Callable[[str], int | None]) -> str:
    """Prefix each labelled node declaration with `<n> · `, replacing any number the model wrote.
    A node for which `number_of` returns None keeps no number."""
    def prefix(declaration: re.Match[str]) -> str:
        number: int | None = number_of(declaration.group("id"))
        label_number: str = f"{number} · " if number is not None else ""
        return f"{declaration.group('id')}{declaration.group('open')}{label_number}"

    return "\n".join(line if NON_EDGE_LINE.match(line) else NODE_DECLARATION.sub(prefix, line) for line in lines)


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


def style_levels(diagram: str, chunks: list[Chunk], notes: list[str]) -> str:
    """Give every box a chunk owns a class for its review level (`lv-<level>`, the highest level among its chunks)
    and one class per label (`chk-<label>`, in the labels' display order), before the closing fence. A box that no
    chunk owns gets none."""
    lines: list[str] = diagram.split("\n")
    positions: dict[str, int] = declaration_positions(lines)
    keep_diagram_nodes(chunks, positions, notes)
    by_level: dict[str, list[str]] = {level: [] for level in reversed(LEVELS)}
    by_label: dict[str, list[str]] = {label: [] for label in CHECK_ORDER}
    for node in positions:
        owners: list[Chunk] = [chunk for chunk in chunks if node in chunk.nodes]
        if not owners:
            continue
        by_level[max((chunk.review for chunk in owners), key=LEVELS.index)].append(node)
        for label in CHECK_ORDER:
            if any(label in chunk.labels for chunk in owners):
                by_label[label].append(node)
    statements: list[str] = [f"  class {','.join(nodes)} {LEVEL_CLASS}{level}" for level, nodes in by_level.items() if nodes]
    statements += [f"  class {','.join(nodes)} {CHECK_CLASS}{label}" for label, nodes in by_label.items() if nodes]
    lines[len(lines) - 1:len(lines) - 1] = statements
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


def add_context_style(diagram: str, context_nodes: list[str]) -> str:
    """Give the nodes that cover no changed file a dashed `context` style, before the closing fence."""
    if not context_nodes:
        return diagram
    lines: list[str] = diagram.split("\n")
    lines[len(lines) - 1:len(lines) - 1] = [f"  {CONTEXT_CLASS_DEF}", f"  class {','.join(context_nodes)} context"]
    return "\n".join(lines)


# The border of an unstyled box in Mermaid's default theme, which the legend's "unchanged context" swatch copies.
DEFAULT_STROKE = "#9370DB"
SAVE_NODE = re.compile(r'(?<![\w-])(?P<id>[A-Za-z0-9_][A-Za-z0-9_-]*)\["[^\n]*?"\]:::save')
SAVE_CLASS_LINE = re.compile(r"^\s*class\s+(?P<ids>[\w,\s-]+?)\s+save\s*$", re.MULTILINE)
SAVE_CLASS_DEF_LINE = re.compile(r"^\s*classDef\s+save\s+(?P<props>[^\n]+)$", re.MULTILINE)


def save_colors(diagram: str) -> tuple[str, str]:
    """(fill, stroke) of the diagram's `save` class: the model's own classDef, else the renderer's default."""
    found: re.Match[str] | None = SAVE_CLASS_DEF_LINE.search(diagram)
    props: dict[str, str] = dict(p.split(":", 1) for p in re.split(r"[;,]", found.group("props")) if ":" in p) if found else {}
    default: dict[str, str] = dict(p.split(":", 1) for p in SAVE_CLASS_DEF.split(" ", 2)[2].split(","))
    return props.get("fill", default["fill"]).strip(), props.get("stroke", default["stroke"]).strip()


# Box borders by review level, as the diagram's theme draws them: (stroke, width in px, dashed, fill).
LEVEL_LOOKS: dict[str, tuple[str, int, bool, str]] = {
    "verify": ("#1f2328", 2, False, "#fff"),
    "read": ("#1f2328", 1, False, "#fff"),
    "skim": ("#8c959f", 1, True, "#f6f8fa"),
}
LEVEL_CLASS_LINE = re.compile(rf"^\s*class\s+(?P<ids>[\w,\s-]+?)\s+{LEVEL_CLASS}(?P<level>\w+)\s*$", re.MULTILINE)


def swatch(fill: str, stroke: str, dashed: bool = False, width: float = 1.5) -> str:
    style: str = (f"display:inline-block;width:14px;height:9px;vertical-align:middle;border-radius:2px;"
                  f"background:{fill};border:{width}px {'dashed' if dashed else 'solid'} {stroke}")
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
    leveled: dict[str, set[str]] = {level: set() for level in reversed(LEVELS)}
    for found in LEVEL_CLASS_LINE.finditer(diagram):
        if found.group("level") in leveled:
            leveled[found.group("level")].update(re.split(r"[,\s]+", found.group("ids").strip()))
    entries: list[str] = []
    for level, members in leveled.items():
        if members & nodes:
            border, width, dashed, level_fill = LEVEL_LOOKS[level]
            entries.append(f"{swatch(level_fill, border, dashed, width)} {level}")
    if saved:
        entries.append(f"{swatch(*save_colors(diagram))} writes data")
    if context:
        entries.append(f"{swatch('#fff', DEFAULT_STROKE, dashed=True)} unchanged context")
    return "Legend: " + " · ".join(entries) if entries else ""


def apply_floor(chunk: Chunk, counts: dict[str, tuple[int, int]], floor_cfg: dict[str, Any],
                contract: dict[str, Any] | None = None, extra: list[tuple[str, str]] | None = None) -> None:
    """Raise the chunk's level to the highest floor of its files and of `extra` (level, reason) pairs, and record
    in `raised_by` the names behind the new level."""
    floors: list[tuple[str, str]] = list(extra or [])
    for path in chunk.files:
        found: tuple[str, str] | None = file_floor(floor_cfg, path, counts[path.lower()][1], contract)
        if found:
            floors.append(found)
    top: int = max([LEVELS.index(chunk.review)] + [LEVELS.index(level) for level, _ in floors])
    if top > LEVELS.index(chunk.review):
        chunk.raised_by = list(dict.fromkeys(name for level, name in floors if LEVELS.index(level) == top))
        chunk.review = LEVELS[top]


def derive_labels(checks: list[str], breaking: bool, destructive: bool, generated: bool) -> list[str]:
    """A chunk's labels in display order: the model's checks, `breaking` in place of `contract` and `destructive` in
    place of `data`, then `generated`."""
    present: set[str] = set(checks)
    if breaking:
        present.discard("contract")
        present.add("breaking")
    if destructive:
        present.discard("data")
        present.add("destructive")
    if generated:
        present.add(GENERATED_TAG)
    return [label for label in CHECK_ORDER if label in present]


def hand_written_paths(files: list[str], spec: str, floor_cfg: dict[str, Any]) -> list[str]:
    """The files that are neither the spec, generated nor tests: the code that a contract change is traced to."""
    return [p for p in files if p != spec and GENERATED_TAG not in file_tags(floor_cfg, p) and not is_test_path(p)]


def hand_written_code(files: list[str], spec: str, floor_cfg: dict[str, Any], diff_lines: dict[str, list[DiffLine]]) -> list[str]:
    """The file stems and diff lines of the hand-written files, which the probes search."""
    paths: list[str] = hand_written_paths(files, spec, floor_cfg)
    return [Path(p).stem for p in paths] + [text for p in paths for _, _, text in diff_lines.get(p, [])]


def place_lines(chunks: list[Chunk], lineset: layout.LineSet, floor_cfg: dict[str, Any],
                diff_lines: dict[str, list[DiffLine]]) -> None:
    """Give each chunk the contract and data lines it owns (`Chunk.contract`, `Chunk.data`) and keep the rest in
    `lineset`. A chunk of only generated files owns none."""
    eligible: list[int] = [i for i, chunk in enumerate(chunks) if generated_share(floor_cfg, chunk.files) != "all"]
    held: list[set[str]] = [set(chunk.files) for chunk in chunks]
    stems: list[set[str]] = [{layout.stem(p) for p in hand_written_paths(chunk.files, lineset.spec, floor_cfg)} for chunk in chunks]
    code: dict[int, list[str]] = {i: hand_written_code(chunks[i].files, lineset.spec, floor_cfg, diff_lines) for i in eligible}
    for kind, lines in (("contract", lineset.contract), ("data", lineset.data)):
        preferred: set[int] = {i for i in eligible if kind in chunks[i].checks}
        owned, loose = layout.place(lines, held, stems, code, preferred, lineset.templates)
        for index, found in owned.items():
            setattr(chunks[index], kind, found)
        setattr(lineset, f"loose_{kind}", loose)


def apply_labels(chunks: list[Chunk], floor_cfg: dict[str, Any], notes: list[str]) -> dict[int, list[tuple[str, str]]]:
    """Set every chunk's `labels` and return, by chunk index, the (level, reason) pairs that raise a chunk to `verify`:
    a breaking API change or a destructive migration. A chunk is breaking when it owns a contract line at the top two
    levels and destructive when it owns a destructive data line."""
    raising: dict[int, list[tuple[str, str]]] = {}
    for index, chunk in enumerate(chunks):
        breaking: bool = any(line.impact in (CALLERS, CONSUMERS) for line in chunk.contract)
        destructive: bool = any(line.impact == DESTRUCTIVE for line in chunk.data)
        share: str = generated_share(floor_cfg, chunk.files)
        if share == "mixed":
            notes.append(f"chunk '{chunk.name}': mixes generated and hand-written files")
        chunk.labels = derive_labels(chunk.checks, breaking, destructive, share == "all")
        reasons: list[tuple[str, str]] = [("verify", reason) for reason, applies in
                                          (("breaking change", breaking), ("destructive migration", destructive))
                                          if applies]
        if reasons:
            raising[index] = reasons
    return raising


# ---------------------------------------------------------------- contract and data block

def unchecked_sides(run: dict[str, Any], contract: dict[str, Any] | None) -> list[str]:
    """`API` when the run has no contract and did not look for one, and `database` when no migration globs are set."""
    context: dict[str, Any] = run.get("context") or {}
    api_checked: bool = "contract" in (context.get("sections") or {}) and "contract" not in (context.get("dropped") or {})
    return (["API"] if contract is None and not api_checked else []) + ([] if MIGRATION_GLOBS else ["database"])


def migration_paths(pr: dict[str, Any]) -> list[str]:
    return [f["path"] for f in pr["files"] if matches(MIGRATION_GLOBS, f["path"]) and f.get("changeType") != "DELETED"]


def build_lineset(run: dict[str, Any], pr: dict[str, Any], contract: dict[str, Any] | None, diff_text: str) -> layout.LineSet:
    """The run's contract and data lines, before any chunk owns them."""
    api: list[Line] = contract_lines(contract, file_diff_lines(diff_text, contract["path"]), contract["path"]) if contract else []
    data: list[Line] = data_lines({path: file_diff_lines(diff_text, path) for path in migration_paths(pr)}) if MIGRATION_GLOBS else []
    return layout.LineSet(api, data, contract["path"] if contract else "", TAG_FILE_TEMPLATES)


def chunked_sections(run: dict[str, Any], lineset: layout.LineSet, unchecked: list[str]) -> tuple[str, str]:
    """The Contract and Data sections of a v22 body, each one closed block with a table of all its lines. A section with
    no lines says so, and says when its side could not be checked."""
    repo: str = run["repo"]
    number: str = str(run["pr"])

    def link_of(line: Line) -> str:
        if line.loc:
            return line_link(repo, number, {"path": line.path, "side": line.loc[0], "line": line.loc[1]})
        return diff_link(repo, number, line.path)

    def draw(side: str, none: str, levels: tuple[str, ...], kind: str, lines: list[Line]) -> str:
        if not lines:
            return f"{side[0].upper()}{side[1:]} changes not checked" if side in unchecked else none
        return layout.section(kind, kind.capitalize(), levels, lines, link_of)

    return (draw("API", "No API changes", CONTRACT_LEVELS, "contract", lineset.contract),
            draw("database", "No database changes", DATA_LEVELS, "data", lineset.data))


# ---------------------------------------------------------------- body

def build_body(run: dict[str, Any], pr: dict[str, Any], data: dict[str, Any], cfg: dict[str, Any],
               floor_cfg: dict[str, Any], diff_lines: dict[str, list[DiffLine]],
               notes: list[str], contract: dict[str, Any] | None = None,
               diff_text: str = "") -> tuple[str, tuple[int, int], list[Chunk], list[dict[str, Any]] | None,
                                            layout.LineSet | None]:
    counts: dict[str, tuple[int, int]] = {f["path"].lower(): (f["additions"], f["deletions"]) for f in pr["files"]}
    paths: list[str] = [f["path"] for f in pr["files"]]

    ordered: dict[str, Any] = {}
    if run["with_body"] and (pr["body"] or "").strip():
        ordered["User Description"] = pr["body"].strip()
    for key in ("type", "description"):
        if key in data:
            ordered[key] = data[key]
    layout_mode: str | None = cfg.get("contract_layout")
    if layout_mode not in (None, "by_chunk"):
        raise AnswerError(f"unknown render contract_layout {layout_mode!r}, expected 'by_chunk'")
    if layout_mode and not (cfg.get("contract_block") and cfg.get("files") == "chunks"):
        raise AnswerError("render contract_layout 'by_chunk' needs contract_block and files = 'chunks'")
    lineset: layout.LineSet | None = build_lineset(run, pr, contract, diff_text) if layout_mode else None
    if lineset is not None:
        ordered["contract"] = ordered["data"] = ""
    chunks: list[Chunk] = build_chunks(data.get("chunks"), counts, paths, floor_cfg, notes, diff_lines, contract,
                                       bool(cfg.get("review_labels")), lineset)
    if lineset is not None:
        ordered["contract"], ordered["data"] = chunked_sections(run, lineset, unchecked_sides(run, contract))
    diagram: str = render_diagram(data.get("changes_diagram"), cfg)
    node_files: dict[str, list[str]] | None = None
    if diagram and "node_files" in data:
        node_files = clean_node_files(data["node_files"], declaration_positions(diagram.split("\n")), paths, notes)
        diagram = add_context_style(diagram, [node for node, files in node_files.items() if not files])
    if diagram and chunks and cfg.get("one_box_per_chunk"):
        note_box_sharing(diagram, chunks, notes)
    if diagram and chunks and cfg.get("chunk_box_fallback"):
        diagram = add_chunk_boxes(diagram, chunks, node_files, counts, notes)
    if diagram and cfg.get("review_labels"):
        diagram = style_levels(diagram, chunks, notes)
    if diagram:
        diagram = number_by_flow(diagram, chunks, notes)
    edges: tuple[int, int] = count_diagram_edges(diagram)
    legend: str = ""
    if diagram:
        context_nodes: list[str] = [node for node, files in (node_files or {}).items() if not files]
        legend = diagram_legend(diagram, context_nodes)
        ordered["changes_diagram"] = diagram

    body: str = ""
    for idx, (key, value) in enumerate(ordered.items()):
        if key == "changes_diagram":
            body += f"### Diagram Walkthrough\n\n{value}\n\n{legend + chr(10) * 2 if legend else ''}"
            continue
        if lineset is not None and key in ("contract", "data") and value.startswith("<details"):
            body += f"{value}\n"
        else:
            body += f"### **{'PR Type' if key == 'type' else key.replace('_', ' ').capitalize()}**\n"
            if isinstance(value, list):
                value = ", ".join(str(v).rstrip() for v in value)
            if key == "description":
                value = value.replace("\n-", "\n\n-").strip()
            body += f"{value}\n"
        if idx < len(ordered) - 1:
            joined: bool = bool(cfg.get("walkthrough")) and key in ("contract", "data")
            body += "\n\n" if joined else "\n\n___\n\n"
    body += "\n\n___\n\n"
    nodes: list[dict[str, Any]] | None = None
    if node_files is not None:
        nodes = [{"id": node, "files": files} for node, files in node_files.items()]
    return f"# {pr['title']}\n\n<!-- pr-agent-generated -->\n{body}", edges, chunks, nodes, lineset


# ---------------------------------------------------------------- review.json

def line_json(line: Line) -> dict[str, Any]:
    """A contract or data line for review.json: its level (null when it has none), text, the parts of that text (what
    changed, on what, and for a contract line the side it reaches) and where its diff line is."""
    side, number = line.loc if line.loc else (None, None)
    return {"impact": line.impact, "text": line.text, "change": line.change, "on": line.on, "reaches": line.side,
            "path": line.path, "side": side, "line": number}


def review_json(run: dict[str, Any], pr: dict[str, Any], chunks: list[Chunk], has_diagram: bool,
                nodes: list[dict[str, Any]] | None, review_labels: bool = False,
                lineset: layout.LineSet | None = None, walkthrough: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The chunks in review order, for the browser extension that groups the Files changed page by chunk. With a
    `lineset`, each chunk lists the contract and data lines it owns and `unchunked` the ones no chunk owns. With a
    `walkthrough`, the stops are listed in reading order beside the chunks."""
    counts: dict[str, tuple[int, int]] = {f["path"].lower(): (f["additions"], f["deletions"]) for f in pr["files"]}
    return {
        "schema": 3,
        "repo": run["repo"],
        "pr": run["pr"],
        "head_sha": run["pr_head_sha"],
        "variant": run["variant"],
        **({"diagram": DIAGRAM_SVG} if has_diagram else {}),
        **({"nodes": nodes} if nodes is not None else {}),
        **({"unchunked": {"contract": [line_json(line) for line in lineset.loose_contract],
                          "data": [line_json(line) for line in lineset.loose_data]}} if lineset is not None else {}),
        **({"walkthrough": walkthrough} if walkthrough is not None else {}),
        "chunks": [{"n": c.number, "name": c.name, "review": c.review, "raised_by": c.raised_by, "why": c.why,
                    "nodes": c.nodes,
                    **({"labels": c.labels} if review_labels else {}),
                    **({"contract": [line_json(line) for line in c.contract], "data": [line_json(line) for line in c.data]}
                       if lineset is not None else {}),
                    "files": [{"path": path, "additions": counts[path.lower()][0], "deletions": counts[path.lower()][1]}
                              for path in c.files],
                    **({"step": c.step} if c.step else {})} for c in chunks],
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
    .node.lv-verify rect.label-container { stroke: #1f2328; stroke-width: 2px; stroke-dasharray: none; }
    .node.lv-read rect.label-container { stroke: #1f2328; stroke-width: 1px; stroke-dasharray: none; }
    .node.lv-skim rect.label-container { fill: #f6f8fa; stroke: #8c959f; stroke-width: 1px; stroke-dasharray: 4 3; }
    .node.lv-skim .nodeLabel, .node.lv-skim .label div { color: #6e7781; }
    .node.lv-skim .nodeLabel .t { font-weight: 600; }
    .node.lv-skim .nodeLabel .eh .n, .node.lv-skim .nodeLabel .s { color: #8c959f; }
    .nodeLabel .eh { display: flex; justify-content: space-between; align-items: baseline; gap: 14px; text-align: left; }
    .nodeLabel .es { display: block; margin-top: 2px; text-align: left; }
    .nodeLabel .ec { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
    .node .nodeLabel .lv { flex: none; font-size: 11px; font-weight: 400; color: #57606a; }
    .node .nodeLabel .eh .n { color: #57606a; }
    .node .nodeLabel .chip { display: inline-block; padding: 0 8px; font-size: 12px; line-height: 16px; font-weight: 400; color: #57606a; border: 1px solid #8c959f; border-radius: 9px; }
    .node .nodeLabel .chip-breaking, .node .nodeLabel .chip-destructive { color: #fff; background: #1f2328; border-color: #1f2328; font-weight: 600; }
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
    path.flowchart-link { stroke: #9370db; stroke-width: 1px; fill: none; }
    .marker, .arrowMarkerPath { fill: none !important; stroke: #9370db !important; stroke-width: 1px; }
    .edgeLabel rect { fill: transparent !important; opacity: 0; }
    .edgeLabel, .edgeLabel p, .edgeLabel span, .labelBkg { background-color: transparent !important; color: #7f77dd !important; font-weight: 400; text-shadow: 0 0 3px #fff, 0 0 3px #fff, 0 0 3px #fff; }
    .cluster rect { fill: none; stroke: #e5e3f0; stroke-width: 1px; rx: 8px; ry: 8px; }
    .cluster-label .nodeLabel, .cluster-label span, .cluster-label p { color: #8a8a99; font-size: 12px; font-weight: 400; }
  `,
};

// The leading box number, the title and the second line of a node label each get a class the theme styles. A box
// with a `lv-<level>` class statement is laid out as a header (number and title left, level word right), the second
// line, and a row of chips, one per `chk-<label>` class statement, in the order the statements are written.
// Node declarations only: subgraph titles and edge labels stay as written. The save, context and skim classDefs are
// dropped because the theme styles those classes.
function boxTraits(text) {
  const traits = new Map();
  for (const line of text.split('\n')) {
    const found = /^\s*class\s+([\w,\s-]+?)\s+(lv|chk)-(\w+)\s*;?\s*$/.exec(line);
    if (!found) continue;
    for (const id of found[1].split(/[,\s]+/).filter(Boolean)) {
      const entry = traits.get(id) ?? { level: null, checks: [] };
      if (found[2] === 'lv') entry.level = found[3]; else entry.checks.push(found[3]);
      traits.set(id, entry);
    }
  }
  return traits;
}

function styleDiagramText(text) {
  const skip = /^\s*(%%|classDef\b|class\b|style\b|linkStyle\b|subgraph\b|click\b|direction\b)/;
  const themed = /^\s*classDef\s+(save|context|skim)\b/;
  const traits = boxTraits(text);
  return text.split('\n').filter((line) => !themed.test(line)).map((line) => skip.test(line) ? line : line.replace(
    /(^|[^\w-])([A-Za-z0-9_][\w-]*)\["([^"]*)"\]/g,
    (match, before, id, label) => {
      const [first, ...rest] = label.split(/<br\s*\/?>/);
      const number = /^(\d+)\s*·\s*/.exec(first);
      const title = number ? first.slice(number[0].length) : first;
      const lead = number ? "<span class='n'>" + number[1] + " ·</span> " : '';
      const box = traits.get(id);
      if (box?.level) {
        const second = rest.length ? "<span class='es s'>" + rest.join('<br/>') + '</span>' : '';
        const chips = box.checks.length
          ? "<span class='ec'>" + box.checks.map((check) => "<span class='chip chip-" + check + "'>" + check + '</span>').join('') + '</span>'
          : '';
        return before + id + '["' + "<span class='eh'><span>" + lead + "<span class='t'>" + title + "</span></span><span class='lv'>" + box.level +
          '</span></span>' + second + chips + '"]';
      }
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
    [/^writes/, '#fff4e5', '#b26a00', 'solid'],
    [/^unchanged/, 'none', '#b4b2a9', 'dashed'],
    [/^verify/, '#fff', '#1f2328', 'solid', 2],
    [/^read/, '#fff', '#1f2328', 'solid', 1],
    [/^skim/, '#f6f8fa', '#8c959f', 'dashed', 1],
  ];
  for (const paragraph of root.querySelectorAll('p')) {
    if (!paragraph.textContent.startsWith('Legend:')) continue;
    for (const swatch of paragraph.querySelectorAll('span[style]')) {
      const word = (swatch.nextSibling?.textContent ?? '').trim();
      const look = looks.find(([pattern]) => pattern.test(word));
      if (!look) continue;
      swatch.style.cssText = 'display:inline-block;width:14px;height:9px;vertical-align:middle;border-radius:7px;' +
        'background:' + look[1] + ';border:' + (look[4] ?? 1) + 'px ' + look[3] + ' ' + look[2];
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
            raise AnswerError(f"{run.get('runner', 'claude')} exited with status {run['exit_status']}")
        data: dict[str, Any] = parse_answer(raw)
        prompt_file: Path = run_dir / "prompt.txt"
        diff_text: str = diff_from_prompt(prompt_file.read_text()) if prompt_file.exists() else ""
        diff_lines: dict[str, list[DiffLine]] = diff_lines_by_path(diff_text)
        md, (labelled, total), chunks, nodes, lineset = build_body(run, pr, data, cfg, floor_cfg, diff_lines, notes, contract, diff_text)
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
    walkthrough: list[dict[str, Any]] | None = (
        build_walkthrough(data.get("walkthrough"), chunks, [f["path"] for f in pr["files"]], diff_lines, notes)
        if cfg.get("walkthrough") else None)
    (run_dir / "review.json").write_text(
        json.dumps(review_json(run, pr, chunks, has_diagram, nodes, bool(cfg.get("review_labels")), lineset, walkthrough), indent=2) + "\n")
    if notes:
        (run_dir / "error.txt").write_text("Rendered with these fixes:\n" + "\n".join(f"- {n}" for n in notes) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
