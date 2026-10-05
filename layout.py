"""Where the contract and data lines of a v22 brief go, and how they are drawn.

`place` gives each line (from contract_lines.py or data_lines.py) the review chunk that owns it:

1. A line goes to the chunk holding the file that its subject is named after: an operation's OpenAPI tag turned into a
   file name (`dynamic-attribute-enum-value-controller` -> `DynamicAttributeEnumValueController`, or each of the
   `tag_file_templates` in local.toml), a schema's own name, or a migration file's path.
2. A subject with no such file goes to the chunk whose hand-written code names it, found with the same probes as the
   breaking-change placement (a schema's name as a word, an operation's last literal path segment).
3. A line about several subjects goes where most of them do. A chunk that holds only generated files never owns a line.

A line that no chunk owns is "not in any chunk". `section` draws one section (Contract or Data): a glance line with
the count at each impact level, then one group per chunk, then the group of lines that no chunk owns. A group is a closed
`<details>` headed by the chunk, the worst impact and the number of changes, holding a table with a row per line; a group
of one line is that line as a plain row. The markup is HTML and GitHub-flavoured markdown tables, so it survives both
GitHub and the extension's brief pane; GitHub drops the `class` attributes, which leaves the top level bold and the others
plain.
"""
import html
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from contract_lines import Line, Member, plural, rank_of

DEFAULT_TAG_TEMPLATES: list[str] = ["{pascal}"]
LOOSE_NAME = "Not in any chunk"
CONTRACT_COLUMNS: tuple[str, ...] = ("Impact", "Side", "Change", "On", "↗")
DATA_COLUMNS: tuple[str, ...] = ("Impact", "Change", "Table", "↗")
# A schema, table or controller name longer than this is cut in its middle on screen, with the whole name as the
# element's title. An endpoint (`GET /path`) is never cut: it wraps in its cell.
NAME_LIMIT = 40
GLANCE_WORDS: dict[str, tuple[str, str]] = {
    "callers must change": ("caller must change", "callers must change"),
    "consumers may break": ("consumer may break", "consumers may break"),
    "rewrites rows": ("rewrites rows", "rewrite rows"),
}


@dataclass
class LineSet:
    """The lines of a PR's contract and data, and where they landed: each chunk keeps its own (`Chunk.contract`,
    `Chunk.data`) and the ones no chunk owns are here."""
    contract: list[Line]
    data: list[Line]
    spec: str = ""
    templates: list[str] = field(default_factory=lambda: list(DEFAULT_TAG_TEMPLATES))
    loose_contract: list[Line] = field(default_factory=list)
    loose_data: list[Line] = field(default_factory=list)


def words_of(name: str) -> list[str]:
    return [word for word in re.split(r"[^A-Za-z0-9]+", name) if word]


def tag_stems(tag: str, templates: list[str]) -> set[str]:
    """The file names (lowercase, without extension) an operation tag may stand for. A template can use `{pascal}`
    (`DynamicAttribute`), `{camel}` (`dynamicAttribute`) and `{kebab}` (`dynamic-attribute`)."""
    words: list[str] = words_of(tag)
    pascal: str = "".join(word[:1].upper() + word[1:] for word in words)
    camel: str = pascal[:1].lower() + pascal[1:]
    forms: dict[str, str] = {"pascal": pascal, "camel": camel, "kebab": "-".join(word.lower() for word in words)}
    return {template.format(**forms).lower() for template in templates}


def stem(path: str) -> str:
    """The file's name up to its first dot, lowercase: `ItemList.test.tsx` -> `itemlist`."""
    return Path(path).name.split(".")[0].lower()


def schema_probe(name: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(name)}\b")


def operation_probe(path: str) -> re.Pattern[str] | None:
    """The last literal segment of an endpoint's path between quotes or slashes, or None when it has none."""
    literal: list[str] = [part for part in path.split("/") if part and not part.startswith("{")]
    return re.compile(r'(?<=["/])' + re.escape(literal[-1]) + r'(?=["/{])') if literal else None


def probe_of(member: Member) -> re.Pattern[str] | None:
    if member.schema:
        return schema_probe(member.schema)
    if member.operation:
        found: re.Match[str] | None = re.match(r"[A-Z]+\s+(/\S*)", member.operation)
        return operation_probe(found.group(1)) if found else None
    return None


def stems_of(member: Member, templates: list[str]) -> set[str]:
    if member.schema:
        return {member.schema.lower()}
    if member.tag:
        return tag_stems(member.tag, templates)
    return set()


def place(lines: list[Line], held: list[set[str]], stems: list[set[str]], code: dict[int, list[str]],
          preferred: set[int], templates: list[str]) -> tuple[dict[int, list[Line]], list[Line]]:
    """The lines each chunk owns, by chunk index, and the lines no chunk owns.

    `held[i]` is the paths chunk i holds, `stems[i]` the stems (see `stem`) of its hand-written non-test files, `code[i]`
    the text that it contains (file stems and added lines) for the probes, and `preferred` the chunks the model flagged
    for this kind of change, which win a tie. A chunk with no `code` entry (it holds only generated files) owns nothing."""
    eligible: list[int] = sorted(code)

    def best(hits: Counter[int]) -> int:
        return max(hits, key=lambda i: (i in preferred, hits[i], -i))

    def home(member: Member) -> int | None:
        if member.file:
            holders: list[int] = [i for i in eligible if member.file in held[i]]
            return min(holders) if holders else None
        wanted: set[str] = stems_of(member, templates)
        named: Counter[int] = Counter({i: 1 for i in eligible if wanted & stems[i]})
        if named:
            return best(named)
        probe: re.Pattern[str] | None = probe_of(member)
        if probe is None:
            return None
        hits: Counter[int] = Counter({i: sum(bool(probe.search(text)) for text in code[i]) for i in eligible})
        hits = Counter({i: count for i, count in hits.items() if count})
        return best(hits) if hits else None

    owned: dict[int, list[Line]] = {}
    loose: list[Line] = []
    for line in lines:
        votes: Counter[int] = Counter(chunk for chunk in (home(member) for member in line.members) if chunk is not None)
        if votes:
            owned.setdefault(best(votes), []).append(line)
        else:
            loose.append(line)
    return owned, loose


# ---------------------------------------------------------------- drawing

def pill(level: str | None, levels: tuple[str, ...]) -> str:
    """The level as a chip; none for a line with no level. The level's rank (`p0` is the worst) sets its style."""
    if level not in levels:
        return ""
    rank: int = min(levels.index(level), 2)
    label: str = html.escape(level)
    return f'<span class="pill p{rank}">{"<strong>" + label + "</strong>" if rank == 0 else label}</span>'


def middle(name: str) -> str:
    """`name` cut in the middle to NAME_LIMIT characters when it is longer."""
    if len(name) <= NAME_LIMIT:
        return name
    keep: int = (NAME_LIMIT - 1) // 2
    return f"{name[:keep]}…{name[-keep:]}"


def code_element(name: str) -> str:
    """A name as a code element; a name that is too long is cut in its middle and carries the whole name as its title."""
    shown: str = name if " " in name else middle(name)
    title: str = f' title="{html.escape(name)}"' if shown != name else ""
    return f"<code{title}>{html.escape(shown, quote=False)}</code>"


def inline(text: str) -> str:
    """The text escaped, with each `backticked` span as a code element."""
    parts: list[str] = re.split(r"`([^`]+)`", text)
    return "".join(code_element(part) if at % 2 else html.escape(part, quote=False) for at, part in enumerate(parts))


def cell(text: str) -> str:
    """`text` as the inside of a markdown table cell: inline markup, with `|` as an entity."""
    return inline(text).replace("|", "&#124;")


def glance(lines: list[Line], levels: tuple[str, ...]) -> str:
    """The count at each level as chips, worst first, zeros left out, and the lines with no level counted as `other`:
    `2 callers must change` `1 additive`."""
    counts: Counter[str | None] = Counter(line.impact if line.impact in levels else None for line in lines)
    parts: list[str] = []
    for level in levels:
        if counts[level]:
            singular, many = GLANCE_WORDS.get(level, (level, level))
            rank: int = min(levels.index(level), 2)
            label: str = f"{counts[level]} {singular if counts[level] == 1 else many}"
            parts.append(f'<span class="pill p{rank}">{"<strong>" + label + "</strong>" if rank == 0 else label}</span>')
    if counts[None]:
        parts.append(f'<span class="pill">{counts[None]} other</span>')
    return " ".join(parts)


def sorted_lines(lines: list[Line], levels: tuple[str, ...]) -> list[Line]:
    return sorted(lines, key=lambda line: rank_of(line.impact, levels))


def row_cells(kind: str, line: Line, levels: tuple[str, ...], link_of: Callable[[Line], str]) -> list[str]:
    """The cells of a line's table row: the contract's Impact, Side, Change, On and link, or the data's Impact, Change,
    Table and link."""
    chip: str = pill(line.impact, levels)
    link: str = f"[↗]({link_of(line)})"
    if kind == "contract":
        return [chip, line.side, cell(line.change or line.text), cell(line.on), link]
    return [chip, cell(line.change or line.text), cell(line.on), link]


def table(kind: str, levels: tuple[str, ...], lines: list[Line], link_of: Callable[[Line], str],
          key_of: Callable[[Line], str] | None = None) -> str:
    """A table of `lines`, in the order given. With `key_of`, a row under each key's name precedes that key's lines; it
    has the name in its first cell and nothing after it, which the brief card draws across the whole row."""
    columns: tuple[str, ...] = CONTRACT_COLUMNS if kind == "contract" else DATA_COLUMNS
    rows: list[str] = []
    if key_of is None:
        rows = [row_cells(kind, line, levels, link_of) for line in lines]
    else:
        keyed: dict[str, list[Line]] = {}
        for line in lines:
            keyed.setdefault(key_of(line), []).append(line)
        for key, group in keyed.items():
            rows.append([f"<strong>{cell('`' + key + '`')}</strong>", *[""] * (len(columns) - 1)])
            rows.extend(row_cells(kind, line, levels, link_of) for line in group)
    return "\n".join([f"| {' | '.join(columns)} |", f"| {' | '.join('---' for _ in columns)} |",
                      *(f"| {' | '.join(cells)} |" for cells in rows)])


def plain_row(kind: str, head: str, line: Line, levels: tuple[str, ...], link_of: Callable[[Line], str]) -> str:
    """A group of one line: the head, the line's chip, its change and where, and its link, in one paragraph."""
    chip: str = pill(line.impact, levels)
    side: str = f' <span class="muted">{html.escape(line.side)}</span>' if kind == "contract" and line.side else ""
    return (f'<p class="group-row">{head}{" " + chip if chip else ""} {inline(line.change or line.text)} · {inline(line.on)}{side} '
            f'<a href="{html.escape(link_of(line))}">↗</a></p>')


def group_html(kind: str, head: str, lines: list[Line], levels: tuple[str, ...], link_of: Callable[[Line], str],
               key_of: Callable[[Line], str] | None = None) -> str:
    """One group of lines (worst first): a single row for one line, otherwise a closed `<details>` headed by `head`, the
    worst level's chip and the number of changes, holding the table, split under a row per `key_of` when it is given."""
    if len(lines) == 1:
        return plain_row(kind, head, lines[0], levels, link_of)
    chip: str = pill(lines[0].impact, levels)
    return (f'<details>\n<summary>{head}{" " + chip if chip else ""} <span class="muted">{plural(len(lines), "change")}</span>'
            f'</summary>\n\n<div class="table-wrap">\n\n{table(kind, levels, lines, link_of, key_of)}\n\n</div>\n\n</details>')


def section(kind: str, levels: tuple[str, ...], owned: list[tuple[int, str, list[Line]]], loose: list[Line],
            link_of: Callable[[Line], str], key_of: Callable[[Line], str]) -> str:
    """The section's markdown: the glance line, a group per chunk that owns lines (`owned` holds each chunk's number,
    name and lines; `kind` is `contract` or `data`) sorted by worst level then chunk number, then the group of `loose`
    lines under a row per `key_of`."""
    every: list[Line] = [line for _, _, lines in owned for line in lines] + loose
    ranked: list[tuple[int, int, str, list[Line]]] = []
    for number, name, lines in owned:
        if lines:
            ordered: list[Line] = sorted_lines(lines, levels)
            ranked.append((rank_of(ordered[0].impact, levels), number, name, ordered))
    out: list[str] = [glance(every, levels)]
    for _, number, name, ordered in sorted(ranked, key=lambda entry: entry[:2]):
        out.append(group_html(kind, f"{number} · {inline(name)}", ordered, levels, link_of))
    if loose:
        out.append(group_html(kind, LOOSE_NAME, sorted_lines(loose, levels), levels, link_of, key_of))
    return "\n\n".join(out)
