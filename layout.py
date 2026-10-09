"""How the contract and data lines of a brief are summarised.

`section` draws one section (API or Data) of the brief: its name and a link to the
PR's files page that opens with the section's files selected, a chip for each impact level present, and a closed
`<details>` listing those files.
The lines themselves live in review.json; the body carries no per-line table. The markup is HTML and markdown, so it
survives both GitHub and the extension's brief pane; GitHub drops the `class` attributes, which leaves the top level bold
and the others plain.
"""
import html
from pathlib import PurePosixPath

from contract_lines import Line, plural

# The query parameter that makes the extension open the files page with a file set selected, and its value for each
# section: the contract section is called API.
FILE_SET_PARAM = "pr-brief"
FILE_SET_VALUES: dict[str, str] = {"contract": "api", "data": "data"}


# ---------------------------------------------------------------- drawing

def pill(level: str | None, levels: tuple[str, ...]) -> str:
    """The level as a chip; none for a line with no level. The level's rank (`p0` is the worst) sets its style."""
    if level not in levels:
        return ""
    rank: int = min(levels.index(level), 2)
    label: str = html.escape(level)
    return f'<span class="pill p{rank}">{"<strong>" + label + "</strong>" if rank == 0 else label}</span>'


def glance(lines: list[Line], levels: tuple[str, ...]) -> str:
    """A chip for each level that a line has, worst first, then one for the lines with no level (`other`)."""
    present: set[str | None] = {line.impact if line.impact in levels else None for line in lines}
    parts: list[str] = [pill(level, levels) for level in levels if level in present]
    if None in present:
        parts.append('<span class="pill">other</span>')
    return " ".join(parts)


def files_list(files: list[tuple[str, str]]) -> str:
    """A markdown list with a link to each file, `(path, url)`, labelled with its name, or its whole path when two files
    share a name."""
    names: list[str] = [PurePosixPath(path).name for path, _ in files]
    return "\n".join(f"- [{path if names.count(name) > 1 else name}]({url})" for (path, url), name in zip(files, names))


def section(kind: str, heading: str, levels: tuple[str, ...], lines: list[Line], files_url: str,
            files: list[tuple[str, str]]) -> str:
    """The section's markdown (`kind` is `contract` or `data`; the contract is shown as API), on three parts: `heading` in bold and a "View files" link
    to `files_url` with the section's `pr-brief` parameter, then after a `<br>` the chip of each level present, worst first;
    then a closed `<details>` whose summary counts the files and which lists them one to a line (`files` holds
    `(path, url)`). A section with no file has the heading and the chips only."""
    title: str = f"**{html.escape(heading)}**"
    if not files:
        return f"{title}<br>\n{glance(lines, levels)}"
    return (f"{title} · [View files]({files_url}?{FILE_SET_PARAM}={FILE_SET_VALUES[kind]})<br>\n{glance(lines, levels)}\n\n"
            f"<details>\n<summary>{plural(len(files), 'file')}</summary>\n\n{files_list(files)}\n\n</details>")
