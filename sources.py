"""Where the PR's own source declares what a contract or data line is about.

The OpenAPI document is generated from the Java code, so a contract line can point at the code that caused it: a schema
is named after the simple name of its record, class or enum, a property after the field or record component, an enum
value after the constant, and an operation's operationId is the controller method's name (springdoc adds a `_1`-style
suffix to an overload; it is dropped here). A data line can point at the entity whose `@Table(name = "...")` names its
table. The generated TypeScript client declares the same things, so a contract line also points at the line that
declares it in a changed file under `sdk_dir`.

`SourceFinder` looks only at the files the PR changes, never at a test file. It searches every changed Java file for a
schema, a property or an enum value, and the changed Java files that are controllers (a `@RestController` or
`@Controller` annotation, in the file at the head commit or else in its diff) for an operation. It reads their lines
from the PR's diff and, for what the diff does not show (a controller's annotation, an entity's `@Table` annotation, a
declaration in the generated client), from the file at the head commit through `read`. A line it cannot place has no
source. A location is a `Source`: the file, the side of the diff and the line number, so a removed line links to the
old file.

In the generated client a schema is an `export interface`, `export type` or `export const` of its name, a property is a
`name:` row of its interface, an enum value is a `VALUE: "VALUE"` row of the `export const` object of the enum, and an
operation is the `operationId: (` member of the client's operations. `contract` lists a line's Java sources first, then
its client sources.
"""
import re
from itertools import groupby
from pathlib import PurePosixPath
from typing import Callable

from context_pack import is_test_file
from contract_lines import Line, Member, Source
from diff_lines import DiffLine, file_diff_lines

OVERLOAD_SUFFIX = re.compile(r"_\d+$")
MAPPING_ANNOTATION = re.compile(r"^@\w*Mapping\b")
NOT_A_DECLARATION = re.compile(r"^\s*(?:return|throw|new|else|import|package)\b|^\s*(?://|\*|/\*)")
CONTROLLER_ANNOTATION = re.compile(r"@(?:Rest)?Controller\b")
# A line at column 0 that ends the generated client's declaration above it: the next `export` or a closing brace.
SDK_CLOSE = re.compile(r"^(?:export\s|\})")
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


def rows_inside(texts: list[str], opens: re.Pattern[str] | None, target: re.Pattern[str]) -> list[int]:
    """The indexes of the `texts` that match `target`. With `opens`, only those after a line that matches it and before the
    next line that ends a declaration (`SDK_CLOSE`)."""
    hits: list[int] = []
    inside: bool = opens is None
    for index, text in enumerate(texts):
        if opens is not None:
            if opens.match(text):
                inside = True
                continue
            if SDK_CLOSE.match(text):
                inside = False
        if inside and target.match(text):
            hits.append(index)
    return hits


def table_name(raw: str) -> str:
    """A table as a migration names it, lower case, without its schema or quotes: `"public"."Items"` is `items`."""
    return raw.strip().strip('"`').rsplit(".", 1)[-1].strip('"`').lower()


class SourceFinder:
    """Finds contract and data lines' sources among the changed `paths`, whose diffs come from `diff`."""

    def __init__(self, diff: str, paths: list[str], read: Callable[[str], str | None] = lambda path: None,
                 sdk_dir: str | None = None) -> None:
        self.diff: str = diff
        self.paths: list[str] = sorted(paths)
        self.read: Callable[[str], str | None] = read
        self.sdk_dir: str | None = sdk_dir
        self._lines: dict[str, list[DiffLine]] = {}
        self._controllers: dict[str, bool] = {}
        self._head: dict[str, list[str]] = {}

    def lines(self, path: str) -> list[DiffLine]:
        if path not in self._lines:
            self._lines[path] = file_diff_lines(self.diff, path)
        return self._lines[path]

    def java_files(self) -> list[str]:
        return [p for p in self.paths if p.endswith(".java") and not is_test_file(p)]

    def sdk_files(self) -> list[str]:
        """The changed TypeScript files of the generated client, other than tests."""
        if not self.sdk_dir:
            return []
        return [p for p in self.paths if p.startswith(self.sdk_dir) and p.endswith(".ts") and not p.endswith(".test.ts")
                and not is_test_file(p)]

    def is_controller(self, path: str) -> bool:
        """Whether the Java file carries `@RestController` or `@Controller`, in the file at the head commit or else in its diff."""
        if path not in self._controllers:
            head: str | None = self.read(path)
            self._controllers[path] = bool(CONTROLLER_ANNOTATION.search(head)) if head else any(
                CONTROLLER_ANNOTATION.search(line.text) for line in self.lines(path))
        return self._controllers[path]

    def model_file(self, schema: str) -> str | None:
        """The changed Java file that declares the schema's type: the one named for it, else the only one that declares it
        as a record, class, interface or enum, in its diff or at the head commit."""
        models: list[str] = self.java_files()
        named: list[str] = [p for p in models if PurePosixPath(p).stem == schema]
        if named:
            return named[0]
        declaration: re.Pattern[str] = re.compile(rf"\b(?:record|class|interface|enum)\s+{re.escape(schema)}\b")
        nesting: list[str] = [p for p in models if any(declaration.search(line.text) for line in self.lines(p))
                              or declaration.search(self.read(p) or "")]
        return nesting[0] if len(nesting) == 1 else None

    # ------------------------------------------------------------ contract

    def contract(self, line: Line) -> list[Source]:
        """The sources of a contract line's members, in order and without repeats: those in Java, then those in the
        generated client."""
        found: list[Source] = []
        for finder in (self.member, self.sdk_member):
            for member in line.members:
                source: Source | None = finder(member)
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
        holds it (`Status` for `status`), or else the only changed Java file that declares the constant."""
        pattern: re.Pattern[str] = re.compile(rf"^{re.escape(value)}\s*(?:\(.*)?[,;]?$")
        kinds: str = "-" if removed else "+"
        models: list[str] = self.java_files()
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
        """The declaration of the method of a changed controller, or the `@...Mapping` annotation above it when the diff shows that."""
        if not operation_id:
            return None
        name: str = OVERLOAD_SUFFIX.sub("", operation_id)
        pattern: re.Pattern[str] = re.compile(
            rf"^\s*(?:(?:public|protected|private|static|final|default|abstract|synchronized)\s+)*[\w<>\[\],.?][\w<>\[\],.? ]*\s+{re.escape(name)}\s*\(")
        kinds: str = kinds_for(change_kind)
        for path in [p for p in self.java_files() if self.is_controller(p)]:
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

    # ------------------------------------------------------------ generated client

    def sdk_member(self, member: Member) -> Source | None:
        """The line of a changed file of the generated client that declares what the member is about: found in the diff
        first, then in the file at the head commit."""
        pattern: tuple[re.Pattern[str] | None, re.Pattern[str]] | None = self.sdk_pattern(member)
        if pattern is None:
            return None
        opens, target = pattern
        change_kind: str = member.kind or ""
        for path in self.sdk_files():
            lines: list[DiffLine] = self.lines(path)
            hits: list[int] = []
            for _, group in groupby(enumerate(lines), key=lambda pair: pair[1].hunk):
                numbered: list[tuple[int, DiffLine]] = list(group)
                hits += [numbered[at][0] for at in rows_inside([line.text for _, line in numbered], opens, target)]
            for kind in kinds_for(change_kind):
                for index in hits:
                    if lines[index].kind == kind:
                        return self.at(path, index)
        if change_kind in REMOVED_KINDS:
            return None
        for path in self.sdk_files():
            if path not in self._head:
                self._head[path] = (self.read(path) or "").split("\n")
            hits = rows_inside(self._head[path], opens, target)
            if hits:
                return Source(path, "R", hits[0] + 1)
        return None

    def sdk_pattern(self, member: Member) -> tuple[re.Pattern[str] | None, re.Pattern[str]] | None:
        """The pattern of the line that declares the member in the generated client, and the pattern of the line that opens
        the declaration it must be inside (None when it need not be inside one)."""
        kind: str = member.kind or ""
        if member.operation:
            if not member.operation_id:
                return None
            return None, re.compile(rf"^\s*{re.escape(OVERLOAD_SUFFIX.sub('', member.operation_id))}:\s*\(")
        if member.schema is None:
            return None
        schema: str = re.escape(member.schema)
        if kind.startswith("enum_"):
            if not member.value:
                return None
            value: str = re.escape(member.value)
            return re.compile(rf"^export const {schema} = \{{"), re.compile(rf'^\s*{value}:\s*"{value}",?$')
        if member.name and kind not in ("schema_added", "schema_removed"):
            return re.compile(rf"^export (?:interface|type) {schema}\b"), re.compile(rf"^\s*{re.escape(member.name)}\??:")
        return None, re.compile(rf"^export (?:interface|type|const) {schema}\b")

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
