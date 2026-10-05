"""Where the contract and data lines of a v22 brief go, and how they are drawn.

`place` gives each line (from contract_lines.py or data_lines.py) the review chunk that owns it:

1. A line goes to the chunk holding the file that its subject is named after: an operation's OpenAPI tag turned into a
   file name (`dynamic-attribute-enum-value-controller` -> `DynamicAttributeEnumValueController`, or each of the
   `tag_file_templates` in local.toml), a schema's own name, or a migration file's path.
2. A subject with no such file goes to the chunk whose hand-written code names it, found with the same probes as the
   breaking-change placement (a schema's name as a word, an operation's last literal path segment).
3. A line about several subjects goes where most of them do. A chunk that holds only generated files never owns a line.

A line that no chunk owns is "not in any chunk". `section` draws one section (Contract or Data): a glance line with
the count at each impact level, then one closed `<details>` group per chunk, then the group of lines that no chunk owns.
The markup is plain HTML so it survives both GitHub's markdown and the extension's brief pane; GitHub drops the
`class` attributes, which leaves the top level bold and the others plain.
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


def inline(text: str) -> str:
    """The text escaped, with each `backticked` span as a code element."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(text, quote=False))


def glance(title: str, lines: list[Line], levels: tuple[str, ...]) -> str:
    """`Contract: 2 callers must change · 1 additive`: the count at each level, worst first, zeros left out, and the
    lines with no level counted as `other`."""
    counts: Counter[str | None] = Counter(line.impact if line.impact in levels else None for line in lines)
    parts: list[str] = []
    for level in levels:
        if counts[level]:
            singular, many = GLANCE_WORDS.get(level, (level, level))
            parts.append(f"{counts[level]} {singular if counts[level] == 1 else many}")
    if counts[None]:
        parts.append(f"{counts[None]} other")
    return f"{title}: " + " · ".join(parts)


def sorted_lines(lines: list[Line], levels: tuple[str, ...]) -> list[Line]:
    return sorted(lines, key=lambda line: rank_of(line.impact, levels))


def item(line: Line, levels: tuple[str, ...], link_of: Callable[[Line], str]) -> str:
    chip: str = pill(line.impact, levels)
    text: str = f'<a href="{html.escape(link_of(line))}">{inline(line.text)}</a>'
    return f"<li>{chip + ' ' if chip else ''}{text}</li>"


def summary_text(lines: list[Line]) -> str:
    first: str = inline(lines[0].text)
    return first if len(lines) == 1 else f"{first} <em>+{len(lines) - 1} more</em>"


def group_html(head: str, lines: list[Line], levels: tuple[str, ...], link_of: Callable[[Line], str],
               gist: str | None = None, key_of: Callable[[Line], str] | None = None) -> str:
    """One closed `<details>`: the head, the worst level's chip and a gist (the first line unless given), and the
    lines, split under a sub-heading per `key_of` when it is given."""
    top: str | None = lines[0].impact
    chip: str = pill(top, levels)
    body: str
    if key_of is None:
        body = "\n".join(item(line, levels, link_of) for line in lines)
    else:
        keyed: dict[str, list[Line]] = {}
        for line in lines:
            keyed.setdefault(key_of(line), []).append(line)
        body = "\n".join(f"<li><code>{html.escape(key)}</code><ul>\n"
                         + "\n".join(item(line, levels, link_of) for line in group)
                         + "\n</ul></li>" for key, group in keyed.items())
    return (f"<details>\n<summary>{head}{' ' + chip if chip else ''} {gist if gist is not None else summary_text(lines)}"
            f"</summary>\n\n<ul>\n{body}\n</ul>\n\n</details>")


def section(title: str, levels: tuple[str, ...], owned: list[tuple[int, str, list[Line]]], loose: list[Line],
            link_of: Callable[[Line], str], key_of: Callable[[Line], str], noun: str) -> str:
    """The section's markdown: the glance line, a group per chunk that owns lines (`owned` holds each chunk's number,
    name and lines) sorted by worst level then chunk number, then the group of `loose` lines under their `key_of`
    sub-headings. `noun` names what the loose lines are grouped by, for the group's gist."""
    every: list[Line] = [line for _, _, lines in owned for line in lines] + loose
    ranked: list[tuple[int, int, str, list[Line]]] = []
    for number, name, lines in owned:
        if lines:
            ordered: list[Line] = sorted_lines(lines, levels)
            ranked.append((rank_of(ordered[0].impact, levels), number, name, ordered))
    out: list[str] = [glance(title, every, levels)]
    for _, number, name, ordered in sorted(ranked, key=lambda entry: entry[:2]):
        out.append(group_html(f"{number} · {inline(name)}", ordered, levels, link_of))
    if loose:
        ordered = sorted_lines(loose, levels)
        keys: int = len({key_of(line) for line in ordered})
        gist: str = f"{plural(len(ordered), 'change')} in {plural(keys, noun)}"
        out.append(group_html(LOOSE_NAME, ordered, levels, link_of, gist, key_of))
    return "\n\n".join(out)
