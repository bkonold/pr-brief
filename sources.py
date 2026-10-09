"""Where the PR's own source declares what a contract or data line is about.

The OpenAPI document is generated from the Java code, so a contract line can point at the code that caused it: a schema
is named after the simple name of its record or class, a property after the field or record component, an enum value
after the constant, and an operation's operationId is the controller method's name (springdoc adds a `_1`-style suffix
to an overload; it is dropped here). A data line can point at the entity whose `@Table(name = "...")` names its table.

`SourceFinder` looks only at the files the PR changes, never at a test file. It reads their lines from the PR's diff and, for an entity whose
`@Table` annotation the diff does not show, from the file at the head commit through `read`. A line it cannot place has no
source. A location is a `Source`: the file, the side of the diff and the line number, so a removed line links to the
old file.

Which files can hold a schema or a controller is configuration: a path that contains one of `model_dirs` is a model
file, and one that contains one of `controller_dirs` is a controller.
"""
import re
from pathlib import PurePosixPath
from typing import Callable

from context_pack import is_test_file
from contract_lines import Line, Member, Source
from diff_lines import DiffLine, file_diff_lines

MODEL_DIRS: tuple[str, ...] = ("models/frontend/",)
CONTROLLER_DIRS: tuple[str, ...] = ("controllers/",)

OVERLOAD_SUFFIX = re.compile(r"_\d+$")
MAPPING_ANNOTATION = re.compile(r"^@\w*Mapping\b")
NOT_A_DECLARATION = re.compile(r"^\s*(?:return|throw|new|else|import|package)\b|^\s*(?://|\*|/\*)")
TABLE_ANNOTATION = re.compile(r"@Table\s*\([^)]*?\bname\s*=\s*\"([^\"]+)\"", re.S)
# How many lines above a method's declaration its annotations are searched for the `@...Mapping` line.
ANNOTATION_REACH = 12

REMOVED_KINDS: frozenset[str] = frozenset({"property_removed", "schema_removed", "enum_removed", "operation_removed"})
ADDED_KINDS: frozenset[str] = frozenset({"property_added", "property_added_required", "schema_added", "enum_added", "operation_added"})


def kinds_for(change_kind: str) -> str:
    """The diff line kinds that can hold a change of this kind, in the order to try them (`+` added, `-` removed, a space
    kept): an added thing is on an added line and a removed thing on a removed one, and any other change is most likely on
    an added line, then a removed one, then a kept one (a field whose annotation changed is still declared on a kept line)."""
    if change_kind in REMOVED_KINDS:
        return "-"
    return "+" if change_kind in ADDED_KINDS else "+- "


def table_name(raw: str) -> str:
    """A table as a migration names it, lower case, without its schema or quotes: `"public"."Items"` is `items`."""
    return raw.strip().strip('"`').rsplit(".", 1)[-1].strip('"`').lower()


class SourceFinder:
    """Finds contract and data lines' sources among the changed `paths`, whose diffs come from `diff`."""

    def __init__(self, diff: str, paths: list[str], model_dirs: tuple[str, ...] = MODEL_DIRS,
                 controller_dirs: tuple[str, ...] = CONTROLLER_DIRS,
                 read: Callable[[str], str | None] = lambda path: None) -> None:
        self.diff: str = diff
        self.paths: list[str] = sorted(paths)
        self.model_dirs: tuple[str, ...] = model_dirs
        self.controller_dirs: tuple[str, ...] = controller_dirs
        self.read: Callable[[str], str | None] = read
        self._lines: dict[str, list[DiffLine]] = {}

    def lines(self, path: str) -> list[DiffLine]:
        if path not in self._lines:
            self._lines[path] = file_diff_lines(self.diff, path)
        return self._lines[path]

    def java_files(self) -> list[str]:
        return [p for p in self.paths if p.endswith(".java") and not is_test_file(p)]

    def java_in(self, dirs: tuple[str, ...]) -> list[str]:
        return [p for p in self.java_files() if any(d in p for d in dirs)]

    def model_file(self, schema: str) -> str | None:
        """The model file that declares the schema's type: the one named for it, else the only one that declares it as a
        nested record or class, in its diff or at the head commit."""
        models: list[str] = self.java_in(self.model_dirs)
        named: list[str] = [p for p in models if PurePosixPath(p).stem == schema]
        if named:
            return named[0]
        declaration: re.Pattern[str] = re.compile(rf"\b(?:record|class|interface|enum)\s+{re.escape(schema)}\b")
        nesting: list[str] = [p for p in models if any(declaration.search(line.text) for line in self.lines(p))
                              or declaration.search(self.read(p) or "")]
        return nesting[0] if len(nesting) == 1 else None

    # ------------------------------------------------------------ contract

    def contract(self, line: Line) -> list[Source]:
        """The sources of a contract line's members, in order and without repeats."""
        found: list[Source] = []
        for member in line.members:
            source: Source | None = self.member(member)
            if source is not None and source not in found:
                found.append(source)
        return found

    def member(self, member: Member) -> Source | None:
        kind: str = member.kind or ""
        if member.operation:
            return self.operation(member.operation_id, kind)
        if member.schema is None:
            return None
        if kind.startswith("enum_"):
            return self.enum_value(member.schema, member.name, member.value or "", kind == "enum_removed")
        if kind in ("schema_added", "schema_removed"):
            return self.schema(member.schema, kind == "schema_removed")
        if member.name:
            return self.property(member.schema, member.name, kind)
        return None

    def at(self, path: str, index: int) -> Source:
        line: DiffLine = self.lines(path)[index]
        return Source(path, line.side, line.number)

    def first(self, path: str, kinds: str, matches: Callable[[DiffLine], bool]) -> int | None:
        """The index in the file's diff of the first line that `matches`, trying each kind of line in `kinds` in turn."""
        lines: list[DiffLine] = self.lines(path)
        for kind in kinds:
            for index, line in enumerate(lines):
                if line.kind == kind and matches(line):
                    return index
        return None

    def schema(self, schema: str, removed: bool) -> Source | None:
        path: str | None = self.model_file(schema)
        if path is None:
            return None
        pattern: re.Pattern[str] = re.compile(rf"\b(?:record|class|interface|enum)\s+{re.escape(schema)}\b")
        index: int | None = self.first(path, "-" if removed else "+", lambda line: bool(pattern.search(line.text)))
        return None if index is None else self.at(path, index)

    def property(self, schema: str, name: str, change_kind: str) -> Source | None:
        """The line declaring the property as a record component or a field of the schema's model file."""
        path: str | None = self.model_file(schema)
        if path is None:
            return None
        pattern: re.Pattern[str] = re.compile(rf"[\w>\]?]\s+{re.escape(name)}\s*(?:[,;=)]|$)")
        index: int | None = self.first(path, kinds_for(change_kind),
                                       lambda line: not NOT_A_DECLARATION.match(line.text) and bool(pattern.search(line.text)))
        return None if index is None else self.at(path, index)

    def enum_value(self, schema: str, prop: str | None, value: str, removed: bool) -> Source | None:
        """The line of the enum constant. The enum is in the schema's own file, in a file named for the property that
        holds it (`Status` for `status`), or else the only model file that declares the constant."""
        pattern: re.Pattern[str] = re.compile(rf"^{re.escape(value)}\s*(?:\(.*)?[,;]?$")
        kinds: str = "-" if removed else "+"
        models: list[str] = self.java_in(self.model_dirs)
        own: list[str] = [p for p in models if PurePosixPath(p).stem == schema]
        named: list[str] = [p for p in models if prop and PurePosixPath(p).stem.lower().endswith(prop.lower()) and p not in own]
        elsewhere: list[str] = [p for p in models if p not in own and p not in named]
        for group in (own, named, elsewhere):
            hits: list[tuple[str, int]] = []
            for path in group:
                index: int | None = self.first(path, kinds, lambda line: bool(pattern.match(line.text.strip())))
                if index is not None:
                    hits.append((path, index))
            if group is elsewhere and len(hits) != 1:
                return None
            if hits:
                return self.at(*hits[0])
        return None

    def operation(self, operation_id: str | None, change_kind: str) -> Source | None:
        """The controller method's declaration, or the `@...Mapping` annotation above it when the diff shows that."""
        if not operation_id:
            return None
        name: str = OVERLOAD_SUFFIX.sub("", operation_id)
        pattern: re.Pattern[str] = re.compile(
            rf"^\s*(?:(?:public|protected|private|static|final|default|abstract|synchronized)\s+)*[\w<>\[\],.?][\w<>\[\],.? ]*\s+{re.escape(name)}\s*\(")
        kinds: str = kinds_for(change_kind)
        for path in self.java_in(self.controller_dirs):
            index: int | None = self.first(path, kinds, lambda line: not NOT_A_DECLARATION.match(line.text) and bool(pattern.match(line.text)))
            if index is not None:
                return self.at(path, self.mapping_above(path, index) or index)
        return None

    def mapping_above(self, path: str, index: int) -> int | None:
        """The index of the `@...Mapping` line that begins the annotations just above the declaration at `index`, when it is
        in the same hunk of the diff; lines of the other side of the change (removed lines above an added declaration) are skipped."""
        lines: list[DiffLine] = self.lines(path)
        declaration: DiffLine = lines[index]
        for above in range(index - 1, max(index - ANNOTATION_REACH, 0) - 1, -1):
            line: DiffLine = lines[above]
            text: str = line.text.strip()
            if {line.kind, declaration.kind} == {"+", "-"}:
                continue
            if line.hunk != declaration.hunk or not text or text.endswith(("}", ";", "{")):
                return None
            if MAPPING_ANNOTATION.match(text):
                return above
        return None

    # ------------------------------------------------------------ data

    def data(self, line: Line) -> list[Source]:
        """The entity source of each table a data line names, in order and without repeats."""
        found: list[Source] = []
        for member in line.members:
            source: Source | None = self.entity(member.table) if member.table else None
            if source is not None and source not in found:
                found.append(source)
        return found

    def entity(self, table: str) -> Source | None:
        """The `@Table(name = ...)` line in the changed Java file that names `table`: in the diff when the diff holds it,
        else in the file at the head commit. The line's own side is used for a diff line, `R` for the file."""
        wanted: str = table_name(table)
        javas: list[str] = self.java_files()
        for kind in "+ -":
            for path in javas:
                for line in self.lines(path):
                    found: re.Match[str] | None = TABLE_ANNOTATION.search(line.text)
                    if found and line.kind == kind and table_name(found.group(1)) == wanted:
                        return Source(path, line.side, line.number)
        for path in javas:
            text: str = self.read(path) or ""
            for annotation in TABLE_ANNOTATION.finditer(text):
                if table_name(annotation.group(1)) == wanted:
                    return Source(path, "R", text.count("\n", 0, annotation.start()) + 1)
        return None
