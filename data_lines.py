"""The "Data" lines of a v22 brief: what a PR's migration files do to the database, one line per change, each with an
impact level.

`split_statements` cuts a migration's added lines into SQL statements, ignoring comments and keeping string literals and
dollar-quoted bodies whole. `classify_statement` turns one statement into its changes with a data impact each, and
`data_lines` runs both over the PR's migration files and collapses repeats: the same statement on the same table is one
line with a count, and one column added or dropped on three or more tables is one line. A statement the classifier does
not know (a DO block, a publication, a rename) becomes `other statement in <file>`, with no impact, so a migration never
renders nothing.
"""
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from contract_block import SQL_NAME, DiffLine, sql_name
from contract_lines import SWEEP_MINIMUM, Line, Member, code, names_text, plural

DESTRUCTIVE = "destructive"
REWRITES = "rewrites rows"
ADDITIVE = "additive"
DATA_LEVELS: tuple[str, ...] = (DESTRUCTIVE, REWRITES, ADDITIVE)

DOLLAR_TAG = re.compile(r"\$[A-Za-z_]*\$")
# Types a column can be changed to without risking lost values; any other explicit size or a small fixed type may narrow.
NARROW_TYPES: frozenset[str] = frozenset({"smallint", "int2", "integer", "int", "int4", "real", "float4", "date",
                                          "boolean", "bool", "time", "smallserial", "serial"})
NO_DEFAULT_TYPES = re.compile(r"\b(?:small|big)?serial\b", re.I)


@dataclass
class Action:
    """One thing a statement does: its impact (None when it is not classified), a verb that groups like actions, the
    table, the column it concerns and the sentence that describes it."""
    level: str | None
    verb: str
    table: str
    column: str | None
    text: str


def split_statements(lines: list[DiffLine]) -> list[tuple[str, int]]:
    """The SQL statements in the added lines of a migration, each with the line it starts on. Comments are dropped;
    `;` inside a string, a quoted identifier or a `$tag$ ... $tag$` body does not end a statement."""
    statements: list[tuple[str, int]] = []
    buffer: list[str] = []
    start: int | None = None
    quote: str | None = None

    def flush() -> None:
        nonlocal start
        text: str = "".join(buffer).strip()
        if text and start is not None:
            statements.append((text, start))
        buffer.clear()
        start = None

    for diff_line in lines:
        if diff_line.kind != "+":
            continue
        text: str = diff_line.text + "\n"
        i: int = 0
        while i < len(text):
            char: str = text[i]
            if quote == "/*":
                if text.startswith("*/", i):
                    quote = None
                    i += 2
                else:
                    i += 1
                continue
            if quote in ("'", '"'):
                buffer.append(char)
                if char == quote:
                    if text[i + 1:i + 2] == quote:
                        buffer.append(quote)
                        i += 1
                    else:
                        quote = None
                i += 1
                continue
            if quote:
                if text.startswith(quote, i):
                    buffer.append(quote)
                    i += len(quote)
                    quote = None
                else:
                    buffer.append(char)
                    i += 1
                continue
            if text.startswith("--", i):
                break
            if text.startswith("/*", i):
                quote = "/*"
                i += 2
                continue
            tag: re.Match[str] | None = DOLLAR_TAG.match(text, i) if i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_") else None
            if tag:
                quote = tag.group()
                buffer.append(quote)
                i += len(quote)
                if start is None:
                    start = diff_line.number
                continue
            if char == ";":
                flush()
                i += 1
                continue
            if char in ("'", '"'):
                quote = char
            if start is None and not char.isspace():
                start = diff_line.number
            buffer.append(char)
            i += 1
    flush()
    return statements


def top_level_commas(text: str) -> list[str]:
    """`text` cut at the commas outside parentheses."""
    parts: list[str] = []
    depth: int = 0
    current: list[str] = []
    for char in text:
        depth += char == "("
        depth -= char == ")"
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    parts.append("".join(current).strip())
    return [part for part in parts if part]


def narrows(type_text: str) -> bool:
    """Whether a target type may lose values: it has an explicit size or precision (`varchar(20)`, `numeric(10,2)`) or is a
    small fixed type (`smallint`, `integer`, `real`, `date`, `boolean`)."""
    lowered: str = " ".join(type_text.lower().split())
    return "(" in lowered or lowered.split(" ")[0] in NARROW_TYPES


def alter_actions(table: str, rest: str) -> list[Action]:
    actions: list[Action] = []
    for part in top_level_commas(rest):
        found: re.Match[str] | None
        if re.match(r"ADD\s+(?:CONSTRAINT|PRIMARY|FOREIGN|UNIQUE|CHECK|EXCLUDE)\b", part, re.I):
            named: re.Match[str] | None = re.match(rf"ADD\s+CONSTRAINT\s+({SQL_NAME})", part, re.I)
            kind: re.Match[str] | None = re.search(r"\b(PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK|EXCLUDE)\b", part, re.I)
            label: str = f"{code(sql_name(named.group(1)))} on {code(table)}" if named else \
                f"{' '.join(kind.group(1).upper().split()) if kind else 'constraint'} on {code(table)}"
            actions.append(Action(REWRITES, "add constraint", table, None, f"add constraint {label}"))
        elif found := re.match(rf"ADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?({SQL_NAME})\s+(.*)$", part, re.I):
            column: str = sql_name(found.group(1))
            definition: str = found.group(2)
            bare: bool = bool(re.search(r"\bNOT\s+NULL\b", definition, re.I)) and not re.search(
                r"\b(?:DEFAULT|GENERATED)\b", definition, re.I) and not NO_DEFAULT_TYPES.search(definition)
            subject: str = code(f"{table}.{column}")
            if bare:
                actions.append(Action(REWRITES, "add column", table, column, f"add column {subject} NOT NULL without a default"))
            else:
                actions.append(Action(ADDITIVE, "add column", table, column, f"add column {subject}"))
        elif found := re.match(rf"DROP\s+(?:COLUMN\s+)?(?:IF\s+EXISTS\s+)?(?!CONSTRAINT\b)({SQL_NAME})", part, re.I):
            column = sql_name(found.group(1))
            actions.append(Action(DESTRUCTIVE, "drop column", table, column, f"drop column {code(f'{table}.{column}')}"))
        elif found := re.match(rf"ALTER\s+(?:COLUMN\s+)?({SQL_NAME})\s+(?:SET\s+DATA\s+)?TYPE\s+(.*?)(?:\s+USING\b.*)?$", part, re.I):
            column = sql_name(found.group(1))
            target: str = found.group(2).strip()
            subject = code(f"{table}.{column}")
            if narrows(target):
                actions.append(Action(DESTRUCTIVE, "narrow column", table, column, f"narrow {subject} to {code(target)}"))
            else:
                actions.append(Action(REWRITES, "change column type", table, column, f"change type of {subject} to {code(target)}"))
        elif found := re.match(rf"ALTER\s+(?:COLUMN\s+)?({SQL_NAME})\s+SET\s+NOT\s+NULL\b", part, re.I):
            column = sql_name(found.group(1))
            actions.append(Action(REWRITES, "set not null", table, column, f"set {code(f'{table}.{column}')} NOT NULL"))
        else:
            actions.append(Action(None, "other", table, None, ""))
    return actions


def classify_statement(statement: str) -> list[Action]:
    """The changes one SQL statement makes, each with its data impact; a statement or an `ALTER TABLE` action that is not
    in the table has level None.

    | Statement | Impact |
    |---|---|
    | DROP TABLE, DROP COLUMN, TRUNCATE, DELETE | destructive |
    | ALTER COLUMN ... TYPE to a size-limited or small fixed type (it may narrow) | destructive |
    | UPDATE (a backfill) | rewrites rows |
    | ALTER COLUMN ... SET NOT NULL | rewrites rows |
    | ALTER COLUMN ... TYPE to any other type | rewrites rows |
    | ADD CONSTRAINT (CHECK, UNIQUE, PRIMARY KEY, FOREIGN KEY) | rewrites rows |
    | ADD COLUMN ... NOT NULL without a DEFAULT | rewrites rows |
    | CREATE TABLE, CREATE INDEX, CREATE VIEW | additive |
    | ADD COLUMN that is nullable or has a DEFAULT | additive |
    | INSERT (seed data) | additive |
    | anything else: DO blocks, publications, renames, DROP INDEX or CONSTRAINT, SET DEFAULT, ... | none |
    """
    text: str = " ".join(statement.split())
    found: re.Match[str] | None
    if found := re.match(rf"CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?({SQL_NAME})", text, re.I):
        name: str = sql_name(found.group(1))
        return [Action(ADDITIVE, "create view", name, None, f"create view {code(name)}")]
    if found := re.match(rf"CREATE\s+(?:(?:GLOBAL\s+|LOCAL\s+)?(?:TEMP|TEMPORARY)\s+|UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?({SQL_NAME})", text, re.I):
        name = sql_name(found.group(1))
        return [Action(ADDITIVE, "create table", name, None, f"create table {code(name)}")]
    if found := re.match(rf"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(?:({SQL_NAME})\s+)?ON\s+(?:ONLY\s+)?({SQL_NAME})", text, re.I):
        table: str = sql_name(found.group(2))
        index: str = f"{code(sql_name(found.group(1)))} " if found.group(1) else ""
        return [Action(ADDITIVE, "create index", table, None, f"create index {index}on {code(table)}")]
    if found := re.match(rf"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(.*?)(?:\s+(?:CASCADE|RESTRICT))?$", text, re.I):
        return [Action(DESTRUCTIVE, "drop table", sql_name(n), None, f"drop table {code(sql_name(n))}")
                for n in re.findall(SQL_NAME, found.group(1))]
    if found := re.match(r"TRUNCATE\s+(?:TABLE\s+)?(?:ONLY\s+)?(.*?)(?:\s+(?:RESTART|CONTINUE)\s+IDENTITY)?(?:\s+(?:CASCADE|RESTRICT))?$", text, re.I):
        return [Action(DESTRUCTIVE, "truncate", sql_name(n), None, f"truncate {code(sql_name(n))}")
                for n in re.findall(SQL_NAME, found.group(1))]
    cte: str = "WITH" if re.match(r"WITH\b", text, re.I) else ""
    verbs: tuple[tuple[str, str, str, str], ...] = (
        (r"INSERT\s+INTO\s+", ADDITIVE, "insert", "insert rows into"),
        (r"UPDATE\s+(?:ONLY\s+)?", REWRITES, "update", "update rows in"),
        (r"DELETE\s+FROM\s+(?:ONLY\s+)?", DESTRUCTIVE, "delete", "delete rows from"),
    )
    for pattern, level, verb, words in verbs:
        found = re.search(rf"{'' if cte else '^'}{pattern}({SQL_NAME})", text, re.I)
        if found and (cte or found.start() == 0):
            name = sql_name(found.group(1))
            return [Action(level, verb, name, None, f"{words} {code(name)}")]
    if found := re.match(rf"ALTER\s+TABLE\s+(?:ONLY\s+|IF\s+EXISTS\s+)*({SQL_NAME})\s+(.*)$", text, re.I):
        return alter_actions(sql_name(found.group(1)), found.group(2))
    return [Action(None, "other", "", None, "")]


def collapse(actions: list[tuple[Action, str, int]]) -> list[Line]:
    """One line per change. The same statement on the same table is one line with its count; the same column change on
    three or more tables is one line; actions with no level are one `other statement` line per file."""
    lines: list[Line] = []
    other: dict[str, tuple[int, int]] = {}
    grouped: dict[tuple[str, str, str, str | None], list[tuple[Action, str, int]]] = {}
    for action, path, number in actions:
        if action.level is None:
            count, first = other.get(path, (0, number))
            other[path] = (count + 1, first)
            continue
        grouped.setdefault((action.level, action.verb, action.table, action.column), []).append((action, path, number))
    swept: dict[tuple[str, str, str], list[tuple[Action, str, int]]] = {}
    for (level, verb, table, column), group in grouped.items():
        if column is not None:
            swept.setdefault((level, verb, column), []).append(group[0])
    done: set[tuple[str, str, str, str | None]] = set()
    for (level, verb, column), members in swept.items():
        tables: list[str] = [action.table for action, _, _ in members]
        if len(set(tables)) >= SWEEP_MINIMUM:
            action, path, number = members[0]
            sentence: str = {"add column": "add", "drop column": "drop", "set not null": "set NOT NULL on",
                             "narrow column": "narrow", "change column type": "change type of"}[verb]
            text: str = f"{sentence} column {code(column)} on {len(set(tables))} tables · {names_text(list(dict.fromkeys(tables)))}"
            lines.append(Line(level, text, path, ("R", number), [Member(file=p, table=a.table) for a, p, _ in members],
                              group=tables[0]))
            done.update(key for key in grouped if key[:2] == (level, verb) and key[3] == column)
    for key, group in grouped.items():
        if key in done:
            continue
        action, path, number = group[0]
        text = action.text if len(group) == 1 else f"{action.text} ({plural(len(group), 'statement')})"
        lines.append(Line(action.level, text, path, ("R", number), [Member(file=path, table=action.table)], group=action.table))
    for path, (count, number) in other.items():
        name: str = PurePosixPath(path).name
        text = f"other statement in {name}" if count == 1 else f"{count} other statements in {name}"
        lines.append(Line(None, text, path, ("R", number), [Member(file=path)]))
    return sorted(lines, key=lambda line: DATA_LEVELS.index(line.impact) if line.impact in DATA_LEVELS else len(DATA_LEVELS))


def data_lines(files: dict[str, list[DiffLine]]) -> list[Line]:
    """The lines for the PR's migration files (`files` maps each path to its diff lines), worst impact first."""
    actions: list[tuple[Action, str, int]] = []
    for path, lines in files.items():
        for statement, number in split_statements(lines):
            actions.extend((action, path, number) for action in classify_statement(statement))
    return collapse(actions)
