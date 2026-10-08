"""The diff's lines as the contract and data lines read them: one `DiffLine` per added, removed or kept line with its side
and number, the lookup that finds where an OpenAPI document's diff shows an operation, a schema field or a parameter, the
patterns of contract.json's change descriptions, and the SQL name pattern.
"""
import re
from dataclasses import dataclass
from typing import Callable

HTTP_METHODS: frozenset[str] = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})

DIFF_HEADER = re.compile(r"diff --git a/(.*) b/(.*)$")
HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
KEY_LINE = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*:\s*(.*?)\s*$')


@dataclass
class DiffLine:
    side: str
    number: int
    kind: str
    text: str
    hunk: int
    indent: int = 0
    key: str | None = None
    value: str = ""

    def __post_init__(self) -> None:
        self.indent = len(self.text) - len(self.text.lstrip(" "))
        found: re.Match[str] | None = KEY_LINE.match(self.text)
        if found:
            self.key, self.value = found.group(1), found.group(2)


def file_diff_lines(diff: str, path: str) -> list[DiffLine]:
    """The lines of one file's diff, in order, each with its side and number, whether it was added, removed or
    kept, its indentation and the hunk it is in."""
    lines: list[DiffLine] = []
    active: bool = False
    in_hunk: bool = False
    old: int = 0
    new: int = 0
    hunk: int = -1
    for line in diff.split("\n"):
        header: re.Match[str] | None = DIFF_HEADER.match(line)
        if header:
            active, in_hunk = header.group(2) == path, False
            continue
        if not active:
            continue
        start: re.Match[str] | None = HUNK_HEADER.match(line)
        if start:
            old, new, in_hunk, hunk = int(start.group(1)), int(start.group(2)), True, hunk + 1
        elif not in_hunk or line.startswith("\\"):
            continue
        elif line.startswith("+"):
            lines.append(DiffLine("R", new, "+", line[1:].rstrip(), hunk))
            new += 1
        elif line.startswith("-"):
            lines.append(DiffLine("L", old, "-", line[1:].rstrip(), hunk))
            old += 1
        else:
            lines.append(DiffLine("R", new, " ", line[1:].rstrip(), hunk))
            old += 1
            new += 1
    return lines


# ---------------------------------------------------------------- finding a contract item in the diff

class SpecDiff:
    """Finds where the OpenAPI document's diff shows an operation, a schema field or a parameter. The document is
    pretty-printed JSON, so a key's indentation says what encloses it; only the lines of the diff are visible, so
    every lookup returns None when the diff does not settle it."""

    def __init__(self, lines: list[DiffLine]) -> None:
        self.lines = lines

    def keyed(self, key: str, kinds: str, opens: bool = False) -> list[int]:
        return [i for i, line in enumerate(self.lines)
                if line.key == key and line.kind in kinds and (not opens or line.value.startswith("{"))]

    def block(self, index: int) -> list[int]:
        """The lines after `index`, in its hunk, that are indented deeper than it."""
        start: DiffLine = self.lines[index]
        found: list[int] = []
        for i in range(index + 1, len(self.lines)):
            line: DiffLine = self.lines[i]
            if line.hunk != start.hunk or (line.text.strip() and line.indent <= start.indent):
                break
            found.append(i)
        return found

    def before(self, index: int, accept: Callable[[DiffLine], bool]) -> int | None:
        """The nearest earlier line in the hunk that is indented less than `index` and that `accept` takes."""
        here: DiffLine = self.lines[index]
        for i in range(index - 1, -1, -1):
            line: DiffLine = self.lines[i]
            if line.hunk != here.hunk:
                return None
            if line.key is not None and line.indent < here.indent and accept(line):
                return i
        return None

    def operation(self, method: str, path: str, operation_id: str | None, kinds: str) -> int | None:
        """The line of the operation: its method key when the diff shows it, else the nearest line that settles it."""
        if operation_id:
            for i in self.keyed("operationId", kinds):
                if self.lines[i].value.strip('",') == operation_id:
                    found: int | None = self.before(i, lambda line: line.key in HTTP_METHODS and line.value.startswith("{"))
                    return found if found is not None else i
        for p in self.keyed(path, "+- ", opens=True):
            for i in self.block(p):
                if self.lines[i].key == method.lower() and self.lines[i].kind in kinds and self.lines[i].value.startswith("{"):
                    return i
        if kinds != "+- ":
            alone: list[int] = self.keyed(method.lower(), kinds, opens=True)
            return alone[0] if len(alone) == 1 else None
        return None

    def first_change(self, index: int) -> int:
        """The first added or removed line inside the block at `index`, else `index` itself."""
        return next((i for i in self.block(index) if self.lines[i].kind != " "), index)

    def pick(self, candidates: list[int], rank: int, total: int) -> int | None:
        """The one candidate when there is one; otherwise the `rank`th of them when there are as many candidates as
        there are items of this kind to place (both follow the document's order)."""
        if len(candidates) == 1:
            return candidates[0]
        return candidates[rank] if candidates and total == len(candidates) and 0 <= rank < total else None

    def schema_field(self, schema: str, name: str, kinds: str, rank: int, total: int) -> int | None:
        candidates: list[int] = self.keyed(name, kinds, opens=True)
        for s in self.keyed(schema, "+- ", opens=True):
            inside: set[int] = set(self.block(s))
            within: list[int] = [i for i in candidates if i in inside]
            if within:
                return within[0]
        return self.pick(candidates, rank, total)

    def required_entry(self, schema: str, name: str, rank: int, total: int) -> int | None:
        """The added `"name"` element of a `required` array, else the field's own definition."""
        def in_required(i: int) -> bool:
            parent: int | None = self.before(i, lambda line: True)
            return parent is None or self.lines[parent].key == "required"

        candidates: list[int] = [i for i, line in enumerate(self.lines)
                                 if line.kind == "+" and line.key is None and line.text.strip() in (f'"{name}"', f'"{name}",')
                                 and in_required(i)]
        found: int | None = self.pick(candidates, rank, total)
        return found if found is not None else self.schema_field(schema, name, "+- ", 0, 0)

    def parameter(self, operation_id: str | None, name: str, kinds: str, rank: int, total: int) -> int | None:
        candidates: list[int] = [i for i in self.keyed("name", kinds) if self.lines[i].value.strip('",') == name]
        owner: dict[int, str | None] = {}
        for i in candidates:
            nearest: int | None = self.nearest_operation_id(i)
            owner[i] = self.lines[nearest].value.strip('",') if nearest is not None else None
        if operation_id:
            confirmed: list[int] = [i for i in candidates if owner[i] == operation_id]
            if confirmed:
                return confirmed[0]
            candidates = [i for i in candidates if owner[i] is None]
        return self.pick(candidates, rank, total)

    def nearest_operation_id(self, index: int) -> int | None:
        here: DiffLine = self.lines[index]
        for i in range(index - 1, -1, -1):
            line: DiffLine = self.lines[i]
            if line.hunk != here.hunk:
                return None
            if line.key == "operationId":
                return i
        return None

    def enum_entry(self, value: str) -> int | None:
        found: list[int] = [i for i, line in enumerate(self.lines)
                            if line.kind == "-" and line.key is None and line.text.strip() in (f'"{value}"', f'"{value}",')]
        return found[0] if len(found) == 1 else None


# ---------------------------------------------------------------- contract.json change descriptions

REMOVED_OPERATION = re.compile(r"removed operation ([A-Z]+) (\S+)$")
SCHEMA_REMOVED = re.compile(r"(\S+) \(schema removed\)$")
FIELD_REMOVED = re.compile(r"(\S+?)\.(\S+) \(property removed\)$")
ENUM_REMOVED = re.compile(r"(\S+?)(?:\.(\S+))? \(enum value (.*) removed\)$")
FIELD_REQUIRED = re.compile(r"(\S+?)\.(\S+) \(now required\)$")
PARAMETER_REQUIRED = re.compile(r"([A-Z]+) (\S+) parameter (\S+) \((\w+), now required\)$")


# ---------------------------------------------------------------- SQL names

SQL_NAME = r'[\w."]+'


def sql_name(raw: str) -> str:
    return raw.replace('"', "").rstrip(",;")
