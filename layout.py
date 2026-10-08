"""How the contract and data lines of a brief are drawn.

`section` draws one section (Contract or Data) of the brief: a closed `<details>` whose summary holds the section's name
and the count at each impact level, and whose body is one table with a row per line of the whole PR. The markup is HTML
and GitHub-flavoured markdown tables, so it survives both GitHub and the extension's brief pane; GitHub drops the
`class` attributes, which leaves the top level bold and the others plain.
"""
import html
import re
from typing import Callable

from contract_lines import Line, plural, rank_of

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


def row_cells(kind: str, line: Line, levels: tuple[str, ...], link_of: Callable[[Line], str]) -> list[str]:
    """The cells of a line's table row: the contract's Impact, Side, Change, On and link, or the data's Impact, Change,
    Table and link."""
    chip: str = pill(line.impact, levels)
    link: str = f"[↗]({link_of(line)})"
    if kind == "contract":
        return [chip, line.side, cell(line.change or line.text), cell(line.on), link]
    return [chip, cell(line.change or line.text), cell(line.on), link]


def table(kind: str, levels: tuple[str, ...], lines: list[Line], link_of: Callable[[Line], str]) -> str:
    """A table of `lines`, in the order given."""
    columns: tuple[str, ...] = CONTRACT_COLUMNS if kind == "contract" else DATA_COLUMNS
    rows: list[list[str]] = [row_cells(kind, line, levels, link_of) for line in lines]
    return "\n".join([f"| {' | '.join(columns)} |", f"| {' | '.join('---' for _ in columns)} |",
                      *(f"| {' | '.join(cells)} |" for cells in rows)])


def section(kind: str, heading: str, levels: tuple[str, ...], lines: list[Line], link_of: Callable[[Line], str]) -> str:
    """The section's markdown (`kind` is `contract` or `data`): a closed `<details>` whose summary holds `heading`, the glance
    chips and the number of lines in muted text, and one table of every line in it, sorted by `sort_key` (lines of equal
    key keep their order)."""
    ordered: list[Line] = sorted(lines, key=lambda line: sort_key(kind, line, levels))
    return (f'<details class="section">\n<summary><strong>{html.escape(heading)}</strong> {glance(lines, levels)} '
            f'<span class="muted">{plural(len(lines), "change")}</span></summary>\n\n'
            f'<div class="table-wrap">\n\n{table(kind, levels, ordered, link_of)}\n\n</div>\n\n</details>')
