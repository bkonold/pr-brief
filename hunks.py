"""The diff's hunks as objects: where each one is, what it changes and its lines, the tags that name them in a prompt, and the
hunks a contract or data line is declared in.

`parse_hunks` is the one reader of hunk headers; `diff_lines.file_diff_lines` and `render.diff_lines_by_path` take their lines
from it. A hunk is named `h01`, `h02`, and so on, in the order the diff shows them, across all of its files. `tag_headers` writes
those names at the end of each hunk header so a model can refer to a hunk by name, and `parse_hunks` reads a tagged diff and an
untagged one alike. A chunk groups hunks (see render.py's `resolve_chunks`); `pins` finds the hunks that the deterministic
analysis says belong in the same chunk.
"""
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # contract_lines reads diff_lines, which reads this module
    from contract_lines import Line

DIFF_HEADER = re.compile(r"diff --git a/(.*) b/(.*)$")
HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
HUNK_TAG = re.compile(r" \[h\d+\]$")
HUNK_ID = re.compile(r"h(\d+)$")

PINS_HEADING = "### Hunks that belong together"
PINS_INTRO = "These hunks declare the same API or database change, so they must be in the same chunk."


@dataclass
class Hunk:
    """One `@@` block of a file's diff. `path` is the file's new path, or its old path for a deleted file. `header` is the `@@`
    line without its tag, `old_*` and `new_*` the ranges it states (a count it omits is 1), `lines` the lines of the body as
    the diff has them, `\\ No newline at end of file` markers included, and `change` how the file changed: `added`, `deleted`,
    `renamed` or `modified`."""
    id: str
    path: str
    header: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str]
    change: str = "modified"


@dataclass
class ReadDiff:
    """Every hunk of a diff, in order, and the new path of every file in it, in order, including files with no hunk (a pure
    rename, a binary file)."""
    hunks: list[Hunk]
    paths: list[str]


def hunk_id(number: int) -> str:
    return f"h{number:02d}"


def scan(diff: str) -> tuple[ReadDiff, list[int]]:
    """The hunks and paths of `diff`, and the index in `diff.split("\\n")` of each hunk's header line."""
    lines: list[str] = diff.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    hunks: list[Hunk] = []
    header_at: list[int] = []
    paths: list[str] = []
    old_path: str = ""
    new_path: str = ""
    change: str = "modified"
    current: Hunk | None = None
    in_file: bool = False
    for index, line in enumerate(lines):
        file_header: re.Match[str] | None = DIFF_HEADER.match(line)
        if file_header:
            old_path, new_path = file_header.group(1), file_header.group(2)
            change, current, in_file = "modified", None, True
            paths.append(new_path)
            continue
        if not in_file:
            continue
        start: re.Match[str] | None = HUNK_HEADER.match(line)
        if start:
            old_count, new_count = start.group(2), start.group(4)
            current = Hunk(hunk_id(len(hunks) + 1), old_path if change == "deleted" else new_path, HUNK_TAG.sub("", line),
                           int(start.group(1)), 1 if old_count is None else int(old_count),
                           int(start.group(3)), 1 if new_count is None else int(new_count), [], change)
            hunks.append(current)
            header_at.append(index)
        elif current is not None:
            current.lines.append(line)
        elif line.startswith("new file mode") or line.startswith("--- /dev/null"):
            change = "added" if change == "modified" else change
        elif line.startswith("deleted file mode") or line.startswith("+++ /dev/null"):
            change = "deleted" if change == "modified" else change
        elif line.startswith("rename from "):
            change = "renamed" if change == "modified" else change
    return ReadDiff(hunks, paths), header_at


def read_diff(diff: str) -> ReadDiff:
    return scan(diff)[0]


def parse_hunks(diff: str) -> list[Hunk]:
    """The hunks of `diff` in order, numbered from `h01`. A tag on a header line is read past, not kept."""
    return scan(diff)[0].hunks


def tag_headers(diff: str) -> str:
    """`diff` with ` [hNN]` at the end of each hunk header line, `NN` being the hunk's number in `parse_hunks`."""
    lines: list[str] = diff.split("\n")
    found, header_at = scan(diff)
    for hunk, at in zip(found.hunks, header_at):
        lines[at] = f"{HUNK_TAG.sub('', lines[at])} [{hunk.id}]"
    return "\n".join(lines)


def hunk_at(hunks: list[Hunk], path: str, side: str, line: int) -> Hunk | None:
    """The hunk of `path` whose old range (`side` `L`) or new range (`side` `R`) holds `line`."""
    for hunk in hunks:
        start, count = (hunk.old_start, hunk.old_count) if side == "L" else (hunk.new_start, hunk.new_count)
        if hunk.path == path and start <= line < start + count:
            return hunk
    return None


def hunk_json(hunk: Hunk) -> dict[str, Any]:
    """A hunk for review.json: its id, file, how the file changed and its old and new ranges as `[start, count]`."""
    return {"id": hunk.id, "path": hunk.path, "change": hunk.change,
            "old": [hunk.old_start, hunk.old_count], "new": [hunk.new_start, hunk.new_count]}


def hunk_number(name: str) -> int:
    """The number in a hunk's id (`h07` is 7); 0 for anything that is not an id."""
    found: re.Match[str] | None = HUNK_ID.match(name)
    return int(found.group(1)) if found else 0


def pins(api: "list[Line]", data: "list[Line]", hunks: list[Hunk]) -> list[list[str]]:
    """The groups of hunks that hold one contract or data line: the hunk of its place in the spec or migration and the hunks of
    its sources. A line with two or more distinct hunks makes a group; groups that share a hunk are merged. Hunks are sorted
    within a group and groups by their first hunk, in diff order."""
    groups: list[set[str]] = []
    for line in [*api, *data]:
        found: list[Hunk | None] = [hunk_at(hunks, line.path, *line.loc)] if line.loc else []
        found += [hunk_at(hunks, source.path, source.side, source.line) for source in line.sources]
        ids: set[str] = {hunk.id for hunk in found if hunk}
        if len(ids) >= 2:
            groups.append(ids)
    merged: list[set[str]] = []
    for ids in groups:
        for existing in [group for group in merged if group & ids]:
            merged.remove(existing)
            ids = ids | existing
        merged.append(ids)
    ordered: list[list[str]] = [sorted(group, key=hunk_number) for group in merged]
    return sorted(ordered, key=lambda group: hunk_number(group[0]))


def pins_markdown(groups: list[list[str]]) -> str:
    """The prompt section that lists each group on a line; empty for no group."""
    if not groups:
        return ""
    return "\n".join([PINS_HEADING, PINS_INTRO, "", *(f"- {', '.join(group)}" for group in groups)])
