"""The "Contract and data" block of a brief: the API operations, schema fields and database tables a PR touches, one
line each, with a link to the line in the diff that shows it. Built from the run's contract.json, the migration files
in the PR and the diff the model was shown, with no model call. render.py puts it right after the description.

The links come from the caller (`link_to(path, side, line)` and `file_link(path)`), so a brief on any host links the
way its start lines do. A line that cannot be placed in the diff links to the file's diff instead.
"""
import html
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from diff_lines import (
    ENUM_REMOVED, FIELD_REMOVED, FIELD_REQUIRED, HTTP_METHODS, PARAMETER_REQUIRED, REMOVED_OPERATION, SCHEMA_REMOVED, SQL_NAME,
    DiffLine, SpecDiff, sql_name,
)

MAX_OPERATIONS_PER_SCHEMA = 3
MAX_ROWS = 12
MAX_BADGES = 6


# (path, side, line): the diff's own line addressing, as render.py's start lines use it.
Location = tuple[str, str, int]


# ---------------------------------------------------------------- rows

@dataclass
class Badge:
    text: str
    breaking: bool = False
    loc: tuple[str, int] | None = None


@dataclass
class Row:
    label: str
    kind: str
    path: str
    loc: tuple[str, int] | None = None
    badges: list[Badge] = field(default_factory=list)
    note: str = ""


def contract_rows(contract: dict[str, Any], lines: list[DiffLine], spec_path: str) -> list[Row]:
    """One row per operation the contract touches, with a badge per change; changes to a schema land on the
    operations that use it, or on a row for the schema when it has none to name or more than
    MAX_OPERATIONS_PER_SCHEMA."""
    spec: SpecDiff = SpecDiff(lines)
    rows: dict[tuple[str, str], Row] = {}
    new_operations: set[str] = {f"{o['method']} {o['path']}" for o in contract.get("added", {}).get("operations", [])}
    schema_operations: dict[str, list[str]] = contract.get("schema_operations", {})

    def where(index: int | None) -> tuple[str, int] | None:
        return None if index is None else (lines[index].side, lines[index].number)

    def row_for(kind: str, label: str) -> Row:
        return rows.setdefault((kind, label), Row(label, kind, spec_path))

    def on_operation(operation: str, badge: Badge, own: bool = False) -> None:
        row: Row = row_for("operation", operation)
        if badge.text not in [b.text for b in row.badges]:
            row.badges.append(badge)
        if badge.loc and (own or row.loc is None):
            row.loc = badge.loc

    def on_schema(schema: str, badge: Badge) -> None:
        operations: list[str] = schema_operations.get(schema, [])
        if not operations or len(operations) > MAX_OPERATIONS_PER_SCHEMA:
            row: Row = row_for("schema", schema)
            row.note = f"used by {len(operations)} operations" if operations else ""
            if badge.text not in [b.text for b in row.badges]:
                row.badges.append(badge)
            row.loc = row.loc or badge.loc
            return
        for operation in operations:
            if operation not in new_operations:
                on_operation(operation, badge)

    def rank_of(group: list[str], key: str) -> tuple[int, int]:
        return group.index(key), len(group)

    required_fields: list[tuple[str, str]] = []
    required_parameters: list[tuple[str, str, str]] = []
    for entry in contract.get("newly_required", []):
        if found := FIELD_REQUIRED.match(entry):
            required_fields.append((found.group(1), found.group(2)))
        elif found := PARAMETER_REQUIRED.match(entry):
            required_parameters.append((f"{found.group(1)} {found.group(2)}", found.group(3), found.group(4)))
    operation_ids: dict[str, str | None] = {f"{o['method']} {o['path']}": o.get("operation_id")
                                              for kind in ("added", "changed") for o in contract.get(kind, {}).get("operations", [])}
    for kind in ("added", "changed"):
        for p in contract.get(kind, {}).get("parameters", []):
            operation_ids.setdefault(f"{p['method']} {p['path']}", p.get("operation_id"))

    added: dict[str, list[Any]] = contract.get("added", {})
    changed: dict[str, list[Any]] = contract.get("changed", {})
    removed_ops: list[tuple[str, str]] = []
    for entry in contract.get("removals", []):
        if found := REMOVED_OPERATION.match(entry):
            removed_ops.append((found.group(1), found.group(2)))
    added_fields: dict[str, list[str]] = {}
    for item in added.get("properties", []):
        added_fields.setdefault(item["name"], []).append(item["schema"])
    required_names: dict[str, list[str]] = {}
    for schema, name in required_fields:
        required_names.setdefault(name, []).append(schema)
    removed_fields: list[str] = [e for e in contract.get("removals", []) if FIELD_REMOVED.match(e)]

    for method, path in removed_ops:
        index: int | None = spec.operation(method, path, None, "-")
        on_operation(f"{method} {path}", Badge("removed", True, where(index)), own=True)

    for operation in added.get("operations", []):
        index = spec.operation(operation["method"], operation["path"], operation.get("operation_id"), "+")
        on_operation(f"{operation['method']} {operation['path']}", Badge("new", False, where(index)), own=True)

    for operation in changed.get("operations", []):
        label = f"{operation['method']} {operation['path']}"
        index = spec.operation(operation["method"], operation["path"], operation.get("operation_id"), "+- ")
        index = spec.first_change(index) if index is not None else None
        on_operation(label, Badge(f"{', '.join(operation['what'])} changed", False, where(index)), own=True)

    for kind, group, kinds in (("added", added.get("parameters", []), "+"), ("changed", changed.get("parameters", []), "+- ")):
        names: dict[str, list[str]] = {}
        for item in group:
            names.setdefault(item["name"], []).append(f"{item['method']} {item['path']}")
        for item in group:
            label = f"{item['method']} {item['path']}"
            if label in new_operations:
                continue
            required: bool = (label, item["name"], item["in"]) in required_parameters
            if kind == "added" and required:
                continue
            rank, total = rank_of(names[item["name"]], label)
            index = spec.parameter(item.get("operation_id"), item["name"], kinds, rank, total)
            text: str = f"{item['name']} parameter {'added' if kind == 'added' else 'changed'}"
            on_operation(label, Badge(text, False, where(index)))
    for operation, name, location in required_parameters:
        if operation in new_operations:
            continue
        rank, total = rank_of([o for o, n, _ in required_parameters if n == name], operation)
        index = spec.parameter(operation_ids.get(operation), name, "+- ", rank, total)
        on_operation(operation, Badge(f"{name} now required", True, where(index)))

    for schema, name in required_fields:
        rank, total = rank_of(required_names[name], schema)
        required_index: int | None = spec.required_entry(schema, name, rank, total)
        on_schema(schema, Badge(f"{name} now required", True, where(required_index)))

    for item in added.get("properties", []):
        if (item["schema"], item["name"]) in required_fields:
            continue
        rank, total = rank_of(added_fields[item["name"]], item["schema"])
        added_index: int | None = spec.schema_field(item["schema"], item["name"], "+", rank, total)
        on_schema(item["schema"], Badge(f"{item['name']} added", False, where(added_index)))

    for item in changed.get("properties", []):
        index = spec.schema_field(item["schema"], item["name"], "+- ", 0, 0)
        detail: str = item["what"][0] if item.get("what") == ["no longer required"] else "changed"
        on_schema(item["schema"], Badge(f"{item['name']} {detail}", False, where(index)))

    for entry in removed_fields:
        found = FIELD_REMOVED.match(entry)
        index = spec.schema_field(found.group(1), found.group(2), "-", 0, 0)
        on_schema(found.group(1), Badge(f"{found.group(2)} removed", True, where(index)))

    for entry in contract.get("removals", []):
        if found := SCHEMA_REMOVED.match(entry):
            starts: list[int] = spec.keyed(found.group(1), "-", opens=True)
            on_schema(found.group(1), Badge("schema removed", True, where(starts[0] if starts else None)))
        elif (found := ENUM_REMOVED.match(entry)):
            what: str = found.group(2) or found.group(1)
            on_schema(found.group(1), Badge(f"{what} enum value {found.group(3)} removed", True, where(spec.enum_entry(found.group(3)))))

    for schema in added.get("schemas", []):
        starts = spec.keyed(schema, "+", opens=True)
        on_schema(schema, Badge("schema added", False, where(starts[0] if starts else None)))

    return sorted(rows.values(), key=sort_key)


def sort_key(row: Row) -> tuple[int, str, str]:
    if row.kind == "operation":
        method, _, path = row.label.partition(" ")
        return 0, path, method
    return 1, row.label, ""


# ---------------------------------------------------------------- migrations

CREATE_TABLE = re.compile(rf"\bCREATE\s+(?:(?:GLOBAL\s+|LOCAL\s+)?(?:TEMP|TEMPORARY|UNLOGGED)\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?({SQL_NAME})", re.I)
DROP_TABLE = re.compile(rf"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?({SQL_NAME})", re.I)
ALTER_TABLE = re.compile(rf"\bALTER\s+TABLE\s+(?:ONLY\s+|IF\s+EXISTS\s+)*({SQL_NAME})", re.I)
CREATE_INDEX = re.compile(rf"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(?:({SQL_NAME})\s+)?ON\s+(?:ONLY\s+)?({SQL_NAME})", re.I)
WHOLE_TABLE_STATEMENTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("INSERT", re.compile(rf"\bINSERT\s+INTO\s+({SQL_NAME})", re.I)),
    ("UPDATE", re.compile(rf"(?<!\bON\s)\bUPDATE\s+(?!CASCADE\b|RESTRICT\b|SET\b|NO\b)({SQL_NAME})", re.I)),
    ("DELETE", re.compile(rf"\bDELETE\s+FROM\s+({SQL_NAME})", re.I)),
    ("TRUNCATE", re.compile(rf"\bTRUNCATE\s+(?:TABLE\s+)?(?:ONLY\s+)?({SQL_NAME})", re.I)),
)
ALTER_ACTIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ADD COLUMN", re.compile(rf"\bADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?({SQL_NAME})", re.I)),
    ("DROP COLUMN", re.compile(rf"\bDROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?({SQL_NAME})", re.I)),
    ("ALTER COLUMN", re.compile(rf"\bALTER\s+COLUMN\s+({SQL_NAME})", re.I)),
    ("ADD CONSTRAINT", re.compile(rf"\bADD\s+CONSTRAINT\s+({SQL_NAME})", re.I)),
    ("DROP CONSTRAINT", re.compile(rf"\bDROP\s+CONSTRAINT\s+(?:IF\s+EXISTS\s+)?({SQL_NAME})", re.I)),
    ("RENAME", re.compile(rf"\bRENAME\s+(?:COLUMN\s+)?({SQL_NAME}\s+TO\s+{SQL_NAME}|TO\s+{SQL_NAME})", re.I)),
    ("ADD COLUMN", re.compile(rf"\bADD\s+(?!COLUMN\b|CONSTRAINT\b|PRIMARY\b|FOREIGN\b|UNIQUE\b|CHECK\b)({SQL_NAME})\s+\w", re.I)),
)
UNNAMED_CONSTRAINT = re.compile(r"\bADD\s+(PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK)\b", re.I)
BREAKING_VERBS: frozenset[str] = frozenset({"DROP", "DELETE", "TRUNCATE"})


@dataclass
class Statement:
    table: str
    verb: str
    line: int


def parse_migration(lines: list[DiffLine]) -> list[Statement]:
    """The tables a migration touches and what it does to each, from its added lines."""
    statements: list[Statement] = []
    table: str = ""
    in_comment: bool = False
    for diff_line in lines:
        if diff_line.kind != "+":
            continue
        sql: str = diff_line.text
        if in_comment:
            if "*/" not in sql:
                continue
            sql, in_comment = sql.split("*/", 1)[1], False
        sql = re.sub(r"/\*.*?\*/", " ", sql)
        if "/*" in sql:
            sql, in_comment = sql.split("/*", 1)[0], True
        sql = sql.split("--", 1)[0]
        segments: list[str] = sql.split(";")
        for position, segment in enumerate(segments):
            table = scan_statement(segment, table, diff_line.number, statements)
            if position < len(segments) - 1:
                table = ""
    return statements


def scan_statement(segment: str, table: str, line: int, statements: list[Statement]) -> str:
    """Adds the statements in `segment` and returns the table an ALTER TABLE still applies to."""
    found: re.Match[str] | None
    if found := CREATE_TABLE.search(segment):
        statements.append(Statement(sql_name(found.group(1)), "CREATE TABLE", line))
    if found := DROP_TABLE.search(segment):
        statements.append(Statement(sql_name(found.group(1)), "DROP TABLE", line))
    if found := CREATE_INDEX.search(segment):
        name: str = f" {sql_name(found.group(1))}" if found.group(1) else ""
        statements.append(Statement(sql_name(found.group(2)), f"CREATE INDEX{name}", line))
    for verb, pattern in WHOLE_TABLE_STATEMENTS:
        if found := pattern.search(segment):
            statements.append(Statement(sql_name(found.group(1)), verb, line))
    if found := ALTER_TABLE.search(segment):
        table = sql_name(found.group(1))
        rest: str = segment[found.end():]
        statements.append(Statement(table, "ALTER TABLE", line))
    else:
        rest = segment
    if table:
        actions: list[Statement] = []
        for verb, pattern in ALTER_ACTIONS:
            actions.extend(Statement(table, f"{verb} {sql_name(m.group(1))}", line) for m in pattern.finditer(rest))
        actions.extend(Statement(table, f"ADD CONSTRAINT ({' '.join(m.group(1).upper().split())})", line)
                       for m in UNNAMED_CONSTRAINT.finditer(rest) if not re.search(r"\bADD\s+CONSTRAINT\b", rest, re.I))
        if actions:
            statements[:] = [s for s in statements if not (s.table == table and s.verb == "ALTER TABLE" and s.line == line)]
        statements.extend(actions)
    return table


def migration_rows(files: dict[str, list[DiffLine]]) -> list[Row]:
    """One row per table the PR's migration files touch, in the order they first appear. A bare ALTER TABLE shows only
    when nothing more specific was found for the table."""
    tables: dict[str, Row] = {}
    for path, lines in files.items():
        for statement in parse_migration(lines):
            row: Row = tables.setdefault(statement.table, Row(statement.table, "table", path, ("R", statement.line)))
            if statement.verb not in [b.text for b in row.badges]:
                row.badges.append(Badge(statement.verb, statement.verb.split(" ")[0] in BREAKING_VERBS, ("R", statement.line)))
    for row in tables.values():
        if len(row.badges) > 1:
            row.badges = [b for b in row.badges if b.text != "ALTER TABLE"]
    return list(tables.values())


# ---------------------------------------------------------------- the block

def badge_html(badge: Badge, path: str, link_to: Callable[[str, str, int], str]) -> str:
    text: str = html.escape(badge.text)
    text = f"<strong>{text}</strong>" if badge.breaking else text
    return f'<a href="{html.escape(link_to(path, *badge.loc))}">{text}</a>' if badge.loc else text


def row_html(row: Row, link_to: Callable[[str, str, int], str], file_link: Callable[[str], str]) -> str:
    target: str = link_to(row.path, *row.loc) if row.loc else file_link(row.path)
    label: str = f'<a href="{html.escape(target)}"><code>{html.escape(row.label)}</code></a>'
    kind: str = " <sub>table</sub>" if row.kind == "table" else " <sub>schema</sub>" if row.kind == "schema" else ""
    shown: list[Badge] = row.badges[:MAX_BADGES]
    badges: list[str] = [badge_html(badge, row.path, link_to) for badge in shown]
    if len(row.badges) > len(shown):
        badges.append(f"+{len(row.badges) - len(shown)} more")
    note: str = f" <sub>({html.escape(row.note)})</sub>" if row.note else ""
    return f"<li>{label}{kind}{note} · {' · '.join(badges)}</li>" if badges else f"<li>{label}{kind}{note}</li>"


def contract_block(rows: list[Row], link_to: Callable[[str, str, int], str], file_link: Callable[[str], str],
                   unchecked: list[str]) -> str:
    """The block's markdown body (the heading comes from render.py): an HTML list with one line per row, or a sentence
    when there are none. `unchecked` names what could not be checked (`API contract`, `database`)."""
    if not rows:
        checked: list[str] = [name for name in ("API", "database") if name not in unchecked]
        if len(checked) == 2:
            return "No API or database changes"
        not_checked: str = " and ".join(unchecked) + " changes not checked"
        return f"No {checked[0]} changes. {not_checked[0].upper()}{not_checked[1:]}" if checked else not_checked[0].upper() + not_checked[1:]
    shown: list[Row] = rows[:MAX_ROWS]
    items: list[str] = [row_html(row, link_to, file_link) for row in shown]
    if len(rows) > len(shown):
        items.append(f"<li>+{len(rows) - len(shown)} more</li>")
    block: str = '<ul class="contract">\n' + "\n".join(items) + "\n</ul>"
    if unchecked:
        block += f"\n\n<sub>{' and '.join(unchecked)} changes not checked</sub>"
    return block
