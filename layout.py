"""How the contract and data lines of a brief are drawn.

`section` draws one section (Contract or Data) of the brief: a closed `<details>` whose summary holds the section's name
and the count at each impact level, and whose body is one table with a row per line of the whole PR. The markup is HTML
and GitHub-flavoured markdown tables, so it survives both GitHub and the extension's brief pane; GitHub drops the
`class` attributes, which leaves the top level bold and the others plain. The section's name is an `<h3>` inside the
summary, the same heading size as the brief's other sections.

`chunks_section` draws the Layers section: one `<details>` per layer, in review order, with a link to each of its hunks.
"""
import html
import re
from typing import Any, Callable

from pathlib import PurePosixPath

from contract_lines import Line, Source, plural, rank_of
from hunks import Hunk

CONTRACT_COLUMNS: tuple[str, ...] = ("Impact", "Side", "Change", "On", "↗")
DATA_COLUMNS: tuple[str, ...] = ("Impact", "Change", "Table", "↗")
# A schema, table or controller name longer than this is cut in its middle on screen, with the whole name as the
# element's title. An endpoint (`GET /path`) is never cut: it wraps in its cell.
NAME_LIMIT = 40
SIDE_ORDER: tuple[str, ...] = ("request", "response", "both")


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
    """A chip for each level that a line has, worst first, then one for the lines with no level (`other`)."""
    present: set[str | None] = {line.impact if line.impact in levels else None for line in lines}
    parts: list[str] = [pill(level, levels) for level in levels if level in present]
    if None in present:
        parts.append('<span class="pill">other</span>')
    return " ".join(parts)


def sort_key(kind: str, line: Line, levels: tuple[str, ...]) -> tuple[int, int, str]:
    """Worst level first; for the contract then request before response, then where it is; for data then the table."""
    where: str = line.on.replace("`", "").casefold()
    if kind == "contract":
        return rank_of(line.impact, levels), SIDE_ORDER.index(line.side) if line.side in SIDE_ORDER else len(SIDE_ORDER), where
    return rank_of(line.impact, levels), 0, where


def source_label(source: Source) -> str:
    return f"{PurePosixPath(source.path).name}:{source.line}"


def row_cells(kind: str, line: Line, levels: tuple[str, ...], link_of: Callable[[Line], str],
              source_link_of: Callable[[Source], str] | None = None) -> list[str]:
    """The cells of a line's table row: the contract's Impact, Side, Change, On and link, or the data's Impact, Change,
    Table and link. The link of a contract line that has a source goes to the source, with the spec as a second link."""
    chip: str = pill(line.impact, levels)
    link: str = f"[↗]({link_of(line)})"
    if kind == "contract":
        if line.sources and source_link_of:
            source: Source = line.sources[0]
            link = f"[{source_label(source)}]({source_link_of(source)}) · [spec]({link_of(line)})"
        return [chip, line.side, cell(line.change or line.text), cell(line.on), link]
    return [chip, cell(line.change or line.text), cell(line.on), link]


def table(kind: str, levels: tuple[str, ...], lines: list[Line], link_of: Callable[[Line], str],
          source_link_of: Callable[[Source], str] | None = None) -> str:
    """A table of `lines`, in the order given."""
    columns: tuple[str, ...] = CONTRACT_COLUMNS if kind == "contract" else DATA_COLUMNS
    rows: list[list[str]] = [row_cells(kind, line, levels, link_of, source_link_of) for line in lines]
    return "\n".join([f"| {' | '.join(columns)} |", f"| {' | '.join('---' for _ in columns)} |",
                      *(f"| {' | '.join(cells)} |" for cells in rows)])


def files_list(heading: str, files: list[tuple[str, str]]) -> str:
    """`**Contract files**`, a blank line, then one `- [name](url)` item per file, `(path, url)`, in the order given; the label
    is the file's name, or its whole path when two files share a name. Empty for no file."""
    names: list[str] = [PurePosixPath(path).name for path, _ in files]
    items: list[str] = [f"- [{path if names.count(name) > 1 else name}]({url})" for (path, url), name in zip(files, names)]
    return f"**{heading}**\n\n" + "\n".join(items) if files else ""


def section(kind: str, heading: str, levels: tuple[str, ...], lines: list[Line], link_of: Callable[[Line], str],
            source_link_of: Callable[[Source], str] | None = None, files: list[tuple[str, str]] | None = None) -> str:
    """The section's markdown (`kind` is `contract` or `data`): a closed `<details>` whose two-line summary holds `heading`
    alone on the first line and, after a `<br>`, the glance chips and the number of lines in muted text, so a collapsed
    section shows both; inside it, one table of every line, sorted by `sort_key` (lines of equal key keep their order), and
    under it the section's files as a bulleted list of links (`files` holds `(path, url)`)."""
    ordered: list[Line] = sorted(lines, key=lambda line: sort_key(kind, line, levels))
    listed: str = files_list(f"{heading} files", files or [])
    return (f'<details class="section">\n<summary><h3>{html.escape(heading)}</h3><br>\n{glance(lines, levels)} '
            f'<span class="muted">{plural(len(lines), "change")}</span></summary>\n\n'
            f'<div class="table-wrap">\n\n{table(kind, levels, ordered, link_of, source_link_of)}\n\n</div>\n\n'
            f'{listed + chr(10) * 2 if listed else ""}</details>')


# ---------------------------------------------------------------- chunks

def hunk_target(hunk: Hunk) -> tuple[str, int, int]:
    """The side, first line and last line a hunk is shown at: its new lines, or its old lines for a hunk of a deleted file."""
    if hunk.change == "deleted":
        return "L", hunk.old_start, hunk.old_start + max(hunk.old_count, 1) - 1
    return "R", hunk.new_start, hunk.new_start + max(hunk.new_count, 1) - 1


def chunk_summary(chunk: dict[str, Any]) -> str:
    """A layer's `<summary>`: its number and title in bold, its risk and, when it has one, the reason in italics."""
    reason: str = f" · <i>{html.escape(chunk['risk_reason'], quote=False)}</i>" if chunk["risk_reason"] else ""
    return f"<summary><b>{chunk['i']}. {html.escape(chunk['title'], quote=False)}</b> · {chunk['risk']}{reason}</summary>"


def chunks_section(chunks: list[dict[str, Any]], hunks: dict[str, Hunk], link_of: Callable[[Hunk], str],
                   unplaced: list[tuple[str, str]] | None = None) -> str:
    """The `### Layers` section: a line with the number of layers, then one closed `<details>` per layer, in order. A layer's
    summary holds its number, title, risk and risk reason; inside it are its summary sentence and one bullet per hunk, a link
    to the hunk's lines (`path:first–last`) and its id. `hunks` maps ids to hunks, and `link_of` gives the URL of a hunk's first
    line. `unplaced` is `(path, url)` for each file of the PR with no hunk, listed after the layers. Empty for no layer."""
    if not chunks:
        return ""
    blocks: list[str] = []
    for chunk in chunks:
        bullets: list[str] = []
        for name in chunk["hunks"]:
            _, first, last = hunk_target(hunks[name])
            bullets.append(f"- [`{hunks[name].path}:{first}–{last}`]({link_of(hunks[name])}) ({name})")
        sentence: str = f"{html.escape(chunk['summary'], quote=False)}\n\n" if chunk["summary"] else ""
        blocks.append(f"<details>\n{chunk_summary(chunk)}\n\n{sentence}" + "\n".join(bullets) + "\n\n</details>")
    out: str = f"### Layers\n\n{plural(len(chunks), 'layer')}, in review order.\n\n" + "\n\n".join(blocks)
    if unplaced:
        out += "\n\nAlso in this PR, with no hunks to assign:\n\n" + "\n".join(f"- [{path}]({url})" for path, url in unplaced)
    return out
