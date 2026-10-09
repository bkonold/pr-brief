"""The "Contract" lines of a brief: what a PR changes in the OpenAPI document, one line per pattern, each with an
impact level.

`collect_changes` reads a run's contract.json and the spec's diff and yields one `Change` per atomic difference, each
with the side it reaches (request or response) and its impact level from `contract_impact`. `pattern_lines` then
collapses repeated changes: the same change to the same property across several schemas, a removed and an added
operation that are one move, new operations under one base path, the same parameter change across several operations,
and added enum values. `contract_lines` runs both and returns the lines, worst impact first.

The lines are drawn by layout.py.
"""
import re
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from typing import Any

from diff_lines import (
    ENUM_REMOVED, FIELD_REMOVED, FIELD_REQUIRED, PARAMETER_REQUIRED, REMOVED_OPERATION, SCHEMA_REMOVED, DiffLine,
    SpecDiff,
)

BREAKING = "breaking"
MAY_BREAK = "may break"
ADDITIVE = "additive"
DEPRECATED = "deprecated"
CONTRACT_LEVELS: tuple[str, ...] = (BREAKING, MAY_BREAK, ADDITIVE, DEPRECATED)

REQUEST = "request"
RESPONSE = "response"

# Keys whose change tells a caller nothing: prose, examples and defaults.
COSMETIC_KEYS: frozenset[str] = frozenset({
    "description", "summary", "title", "example", "examples", "externalDocs", "default", "readOnly", "writeOnly",
    "operationId", "tags", "deprecated", "xml",
})
TYPE_KEYS: frozenset[str] = frozenset({"type", "format", "$ref", "items", "oneOf", "anyOf", "allOf", "additionalProperties"})


@dataclass(frozen=True)
class Member:
    """What a line is about: a schema, an operation and its controller tag, or a migration file. A contract member also
    carries what the change is, for finding the source that declares it: `kind` is the change's kind (see
    `contract_impact`), `name` the property (for an enum value, the property that holds the enum, when it is inline),
    `value` the enum value, and `operation_id` the operation's id."""
    schema: str | None = None
    operation: str | None = None
    tag: str | None = None
    file: str | None = None
    table: str | None = None
    kind: str | None = None
    name: str | None = None
    value: str | None = None
    operation_id: str | None = None


@dataclass(frozen=True)
class Source:
    """A line of the PR's diff that declares what a contract or data line is about: the file, `side` (`R` for a line of
    the new file, `L` for a removed line of the old file) and the line number."""
    path: str
    side: str
    line: int


@dataclass
class Change:
    kind: str
    impact: str
    sides: frozenset[str]
    subject: str
    scope: str
    member: Member
    loc: tuple[str, int] | None
    detail: str = ""
    types: tuple[str, str] | None = None


def contract_impact(kind: str, sides: frozenset[str] | set[str] = frozenset()) -> str:
    """The impact level of one contract change, worst first: `breaking`, `may break`, `additive`,
    `deprecated`. `sides` is where the change reaches, `request` (a body or a parameter), `response`, or both; a schema
    used on both sides counts as both, and the worst of them wins. Empty `sides` (a schema no operation reaches) counts
    as both.

    | Kind | Request | Response |
    |---|---|---|
    | operation_removed | breaking | breaking |
    | operation_moved | breaking | breaking |
    | operation_added | additive | additive |
    | operation_changed (request body, security) | may break | may break |
    | responses_changed | additive | additive |
    | parameter_added | additive | |
    | parameter_added_required | breaking | |
    | parameter_required (existing, made required) | breaking | |
    | parameter_no_longer_required | additive | |
    | parameter_type_changed | breaking | |
    | parameter_constraint_changed | may break | |
    | property_added | additive | additive |
    | property_added_required | breaking | additive |
    | property_required (existing, made required) | breaking | additive |
    | property_no_longer_required | additive | may break |
    | property_removed | may break | may break |
    | schema_removed | may break | may break |
    | schema_added | additive | additive |
    | property_type_changed | breaking | may break |
    | property_constraint_changed | may break | may break |
    | enum_added | additive | additive |
    | enum_removed | breaking | may break |
    | deprecated | deprecated | deprecated |
    """
    table: dict[str, tuple[str, str]] = {
        "operation_removed": (BREAKING, BREAKING), "operation_moved": (BREAKING, BREAKING),
        "operation_added": (ADDITIVE, ADDITIVE), "operation_changed": (MAY_BREAK, MAY_BREAK),
        "responses_changed": (ADDITIVE, ADDITIVE),
        "parameter_added": (ADDITIVE, ADDITIVE), "parameter_added_required": (BREAKING, BREAKING),
        "parameter_required": (BREAKING, BREAKING), "parameter_no_longer_required": (ADDITIVE, ADDITIVE),
        "parameter_type_changed": (BREAKING, BREAKING), "parameter_constraint_changed": (MAY_BREAK, MAY_BREAK),
        "property_added": (ADDITIVE, ADDITIVE), "property_added_required": (BREAKING, ADDITIVE),
        "property_required": (BREAKING, ADDITIVE), "property_no_longer_required": (ADDITIVE, MAY_BREAK),
        "property_removed": (MAY_BREAK, MAY_BREAK), "schema_removed": (MAY_BREAK, MAY_BREAK),
        "schema_added": (ADDITIVE, ADDITIVE), "property_type_changed": (BREAKING, MAY_BREAK),
        "property_constraint_changed": (MAY_BREAK, MAY_BREAK), "enum_added": (ADDITIVE, ADDITIVE),
        "enum_removed": (BREAKING, MAY_BREAK), "deprecated": (DEPRECATED, DEPRECATED),
    }
    request_level, response_level = table[kind]
    reached: set[str] = set(sides) or {REQUEST, RESPONSE}
    levels: list[str] = [level for side, level in ((REQUEST, request_level), (RESPONSE, response_level)) if side in reached]
    return min(levels, key=CONTRACT_LEVELS.index)


def side_word(sides: frozenset[str]) -> str:
    """`request`, `response` or `request and response`; empty when the sides are not known."""
    return "request and response" if len(sides) == 2 else next(iter(sides), "")


def side_cell(sides: frozenset[str] | set[str]) -> str:
    """`request`, `response` or `both`; empty when the sides are not known."""
    return "both" if len(sides) == 2 else next(iter(sides), "")


def several(count: int, noun: str, names: list[str], many: str | None = None) -> str:
    """`9 schemas: A, B, C +6`: the count, then the first names as code."""
    return f"{plural(count, noun, many)}: {names_text(names)}"


def side_phrase(sides: frozenset[str]) -> str:
    """`request only`, `response only` or `request and response`; empty when the sides are not known."""
    if not sides:
        return ""
    return "request and response" if len(sides) == 2 else f"{next(iter(sides))} only"


# ---------------------------------------------------------------- finding changes in the spec's diff

class Locator:
    """Where the spec's diff shows each kind of change, as `(side, line)` or None when the diff does not settle it."""

    def __init__(self, lines: list[DiffLine]) -> None:
        self.lines = lines
        self.spec = SpecDiff(lines)

    def where(self, index: int | None) -> tuple[str, int] | None:
        return None if index is None else (self.lines[index].side, self.lines[index].number)

    def operation(self, method: str, path: str, operation_id: str | None, kinds: str, first_change: bool = False) -> tuple[str, int] | None:
        index: int | None = self.spec.operation(method, path, operation_id, kinds)
        return self.where(self.spec.first_change(index) if first_change and index is not None else index)

    def schema_field(self, schema: str, name: str, kinds: str, rank: int = 0, total: int = 0) -> tuple[str, int] | None:
        return self.where(self.spec.schema_field(schema, name, kinds, rank, total))

    def required_entry(self, schema: str, name: str, rank: int, total: int) -> tuple[str, int] | None:
        return self.where(self.spec.required_entry(schema, name, rank, total))

    def parameter(self, operation_id: str | None, name: str, kinds: str, rank: int, total: int) -> tuple[str, int] | None:
        return self.where(self.spec.parameter(operation_id, name, kinds, rank, total))

    def schema(self, name: str, kinds: str) -> tuple[str, int] | None:
        starts: list[int] = self.spec.keyed(name, kinds, opens=True)
        return self.where(starts[0] if starts else None)

    def enum_entry(self, schema: str, value: Any, removed: bool) -> tuple[str, int] | None:
        wanted: set[str] = {f'"{value}"', f'"{value}",'}
        kind: str = "-" if removed else "+"
        found: list[int] = [i for i, line in enumerate(self.lines)
                            if line.kind == kind and line.key is None and line.text.strip() in wanted]
        if len(found) > 1:
            for start in self.spec.keyed(schema, "+- ", opens=True):
                inside: set[int] = set(self.spec.block(start))
                found = [i for i in found if i in inside] or found
                break
        return self.where(found[0] if len(found) == 1 else None)


# ---------------------------------------------------------------- the atomic changes

def operation_parts(label: str) -> tuple[str, str]:
    method, _, path = label.partition(" ")
    return method, path


def shape(path: str) -> list[str]:
    return ["{}" if part.startswith("{") else part for part in path.split("/")]


def find_moves(removed: list[tuple[str, str, str | None]],
               added: list[tuple[str, str, str | None]]) -> list[tuple[tuple[str, str, str | None], tuple[str, str, str | None]]]:
    """Pairs of a removed and an added operation with the same verb that are one operation at a new path: the same
    operationId, or the same number of path segments with the parameters in the same places and a similar path."""
    moves: list[tuple[tuple[str, str, str | None], tuple[str, str, str | None]]] = []
    used: set[tuple[str, str, str | None]] = set()
    for old in removed:
        best: tuple[str, str, str | None] | None = None
        best_ratio: float = 0.0
        for new in added:
            if new in used or new[0] != old[0]:
                continue
            if old[2] and old[2] == new[2]:
                best, best_ratio = new, 2.0
                break
            old_shape: list[str] = shape(old[1])
            new_shape: list[str] = shape(new[1])
            if len(old_shape) != len(new_shape) or [p == "{}" for p in old_shape] != [p == "{}" for p in new_shape]:
                continue
            ratio: float = SequenceMatcher(None, "/".join(old_shape), "/".join(new_shape)).ratio()
            if ratio >= 0.7 and ratio > best_ratio:
                best, best_ratio = new, ratio
        if best is not None:
            used.add(best)
            moves.append((old, best))
    return moves


def collect_changes(contract: dict[str, Any], lines: list[DiffLine]) -> tuple[list[Change], dict[str, Any]]:
    """One `Change` per atomic difference in `contract` (a run's contract.json), and the extras the patterns need: the
    moved operations and the operations that are removed, added or deprecated, with their tags and locations."""
    locator: Locator = Locator(lines)
    tags: dict[str, str] = contract.get("operation_tags", {})
    schema_sides: dict[str, dict[str, list[str]]] = contract.get("schema_sides", {})
    schema_operations: dict[str, list[str]] = contract.get("schema_operations", {})
    added: dict[str, list[Any]] = contract.get("added", {})
    changed: dict[str, list[Any]] = contract.get("changed", {})
    deprecated: dict[str, list[Any]] = contract.get("deprecated", {})
    changes: list[Change] = []

    def sides_of(schema: str) -> frozenset[str]:
        return frozenset(side for found in schema_sides.get(schema, {}).values() for side in found)

    def tag_of_schema(schema: str) -> str | None:
        found: list[str] = [tags[o] for o in schema_operations.get(schema, []) if o in tags]
        return max(sorted(set(found)), key=found.count) if found else None

    def schema_member(schema: str) -> Member:
        return Member(schema=schema, tag=tag_of_schema(schema))

    def add(kind: str, sides: frozenset[str], subject: str, scope: str, member: Member, loc: tuple[str, int] | None,
            detail: str = "", types: tuple[str, str] | None = None) -> None:
        if kind.startswith("enum_"):
            member = replace(member, kind=kind, name=subject.partition(".")[2] or None, value=detail)
        elif member.operation is None and kind not in ("schema_added", "schema_removed"):
            member = replace(member, kind=kind, name=subject)
        else:
            member = replace(member, kind=kind)
        changes.append(Change(kind, contract_impact(kind, sides), sides, subject, scope, member, loc, detail, types))

    removed_ids: dict[str, str | None] = {f"{o['method']} {o['path']}": o.get("operation_id") for o in contract.get("removed_operations", [])}
    removed: list[tuple[str, str, str | None]] = []
    for entry in contract.get("removals", []):
        if found := REMOVED_OPERATION.match(entry):
            removed.append((found.group(1), found.group(2), removed_ids.get(f"{found.group(1)} {found.group(2)}")))
    new_operations: list[tuple[str, str, str | None]] = [(o["method"], o["path"], o.get("operation_id")) for o in added.get("operations", [])]
    moves = find_moves(removed, new_operations)
    moved_old: set[tuple[str, str, str | None]] = {old for old, _ in moves}
    moved_new: set[tuple[str, str, str | None]] = {new for _, new in moves}
    new_labels: set[str] = {f"{m} {p}" for m, p, _ in new_operations}

    extras: dict[str, Any] = {"moves": [], "removed": [], "added": [], "deprecated": []}
    for old, new in moves:
        loc = locator.operation(new[0], new[1], new[2], "+")
        extras["moves"].append({"method": old[0], "from": old[1], "to": new[1], "loc": loc, "operation_id": new[2],
                                "tag": tags.get(f"{new[0]} {new[1]}") or tags.get(f"{old[0]} {old[1]}")})
    for method, path, operation_id in removed:
        if (method, path, operation_id) in moved_old:
            continue
        extras["removed"].append({"method": method, "path": path, "tag": tags.get(f"{method} {path}"), "operation_id": operation_id,
                                  "loc": locator.operation(method, path, None, "-")})
    for method, path, operation_id in new_operations:
        if (method, path, operation_id) in moved_new:
            continue
        extras["added"].append({"method": method, "path": path, "tag": tags.get(f"{method} {path}"), "operation_id": operation_id,
                                "loc": locator.operation(method, path, operation_id, "+")})
    for item in deprecated.get("operations", []):
        label = f"{item['method']} {item['path']}"
        extras["deprecated"].append({"method": item["method"], "path": item["path"], "tag": tags.get(label),
                                     "operation_id": item.get("operation_id"), "loc": locator.operation(item["method"], item["path"], None, "+- ", first_change=True)})

    for item in changed.get("operations", []):
        label = f"{item['method']} {item['path']}"
        member: Member = Member(operation=label, tag=tags.get(label), operation_id=item.get("operation_id"))
        loc = locator.operation(item["method"], item["path"], item.get("operation_id"), "+- ", first_change=True)
        for key in item["what"]:
            if key in COSMETIC_KEYS or key.startswith("x-"):
                continue
            if key == "responses":
                add("responses_changed", frozenset(), label, label, member, loc, "responses")
            else:
                add("operation_changed", frozenset(), label, label, member, loc, "request body" if key == "requestBody" else key)

    parameter_groups: dict[str, list[dict[str, Any]]] = {}
    for kind, group in (("added", added.get("parameters", [])), ("changed", changed.get("parameters", []))):
        for item in group:
            parameter_groups.setdefault(f"{kind}:{item['name']}", []).append(item)
    required_parameters: set[tuple[str, str]] = set()
    for entry in contract.get("newly_required", []):
        if found := PARAMETER_REQUIRED.match(entry):
            required_parameters.add((f"{found.group(1)} {found.group(2)}", found.group(3)))
    operation_ids: dict[str, str | None] = {}
    for group in (*added.values(), *changed.values()):
        for item in group:
            if isinstance(item, dict) and "method" in item and "path" in item:
                operation_ids.setdefault(f"{item['method']} {item['path']}", item.get("operation_id"))

    for kind_word in ("added", "changed"):
        for name_key, group in parameter_groups.items():
            if not name_key.startswith(f"{kind_word}:"):
                continue
            for rank, item in enumerate(group):
                label = f"{item['method']} {item['path']}"
                if label in new_labels:
                    continue
                member = Member(operation=label, tag=tags.get(label), operation_id=item.get("operation_id"))
                kinds_text: str = "+" if kind_word == "added" else "+- "
                loc = locator.parameter(item.get("operation_id"), item["name"], kinds_text, rank, len(group))
                if kind_word == "added":
                    add("parameter_added_required" if item.get("required") else "parameter_added", frozenset({REQUEST}),
                        item["name"], label, member, loc)
                    continue
                what: list[str] = [k for k in item.get("what", []) if k not in COSMETIC_KEYS]
                if "required" in what:
                    if not item.get("required"):
                        add("parameter_no_longer_required", frozenset({REQUEST}), item["name"], label, member, loc)
                    what.remove("required")
                if "schema" in what:
                    inner: list[str] = [k for k in item.get("schema_what", ["type"]) if k not in COSMETIC_KEYS and not k.startswith("x-")]
                    if set(inner) & TYPE_KEYS:
                        add("parameter_type_changed", frozenset({REQUEST}), item["name"], label, member, loc)
                    elif inner:
                        add("parameter_constraint_changed", frozenset({REQUEST}), item["name"], label, member, loc)
    ranks: dict[str, list[str]] = {}
    for entry in contract.get("newly_required", []):
        if found := PARAMETER_REQUIRED.match(entry):
            ranks.setdefault(found.group(3), []).append(f"{found.group(1)} {found.group(2)}")
    brand_new: set[tuple[str, str]] = {(f"{item['method']} {item['path']}", item["name"]) for item in added.get("parameters", [])}
    for operation, name in sorted(required_parameters):
        if operation in new_labels or (operation, name) in brand_new:
            continue
        group_ops: list[str] = ranks[name]
        method, path = operation_parts(operation)
        loc = locator.parameter(operation_ids.get(operation), name, "+- ", group_ops.index(operation), len(group_ops))
        add("parameter_required", frozenset({REQUEST}), name, operation,
            Member(operation=operation, tag=tags.get(operation), operation_id=operation_ids.get(operation)), loc)

    introduced: set[str] = set(contract.get("added_required", []))
    required_fields: list[tuple[str, str]] = []
    for entry in contract.get("newly_required", []):
        if found := FIELD_REQUIRED.match(entry):
            required_fields.append((found.group(1), found.group(2)))
    added_properties: dict[str, list[str]] = {}
    for item in added.get("properties", []):
        added_properties.setdefault(item["name"], []).append(item["schema"])
    required_names: dict[str, list[str]] = {}
    for schema, name in required_fields:
        required_names.setdefault(name, []).append(schema)
    new_schemas: set[str] = set(added.get("schemas", []))

    for schema, name in required_fields:
        if schema in new_schemas:
            continue
        group = required_names[name]
        loc = locator.required_entry(schema, name, group.index(schema), len(group))
        is_new: bool = schema in added_properties.get(name, []) or f"{schema}.{name}" in introduced
        add("property_added_required" if is_new else "property_required", sides_of(schema), name, schema, schema_member(schema), loc)
    for item in added.get("properties", []):
        if (item["schema"], item["name"]) in required_fields:
            continue
        group = added_properties[item["name"]]
        loc = locator.schema_field(item["schema"], item["name"], "+", group.index(item["schema"]), len(group))
        add("property_added", sides_of(item["schema"]), item["name"], item["schema"], schema_member(item["schema"]), loc)
    for item in changed.get("properties", []):
        schema, name = item["schema"], item["name"]
        loc = locator.schema_field(schema, name, "+- ")
        what = item.get("what", [])
        if what == ["no longer required"]:
            add("property_no_longer_required", sides_of(schema), name, schema, schema_member(schema), loc)
            continue
        if set(what) & TYPE_KEYS:
            add("property_type_changed", sides_of(schema), name, schema, schema_member(schema), loc,
                types=(item["from"], item["to"]) if "from" in item and "to" in item else None)
        elif [k for k in what if k not in COSMETIC_KEYS and k != "enum" and not k.startswith("x-")]:
            add("property_constraint_changed", sides_of(schema), name, schema, schema_member(schema), loc)
    for entry in contract.get("removals", []):
        if found := FIELD_REMOVED.match(entry):
            schema, name = found.group(1), found.group(2)
            add("property_removed", sides_of(schema), name, schema, schema_member(schema),
                locator.schema_field(schema, name, "-"))
        elif found := SCHEMA_REMOVED.match(entry):
            add("schema_removed", sides_of(found.group(1)), found.group(1), found.group(1), schema_member(found.group(1)),
                locator.schema(found.group(1), "-"))
        elif found := ENUM_REMOVED.match(entry):
            schema, prop, value = found.group(1), found.group(2), found.group(3)
            add("enum_removed", sides_of(schema), f"{schema}.{prop}" if prop else schema, schema, schema_member(schema),
                locator.enum_entry(schema, value, removed=True), value)
    for item in contract.get("enums_added", []):
        schema = item["schema"]
        subject: str = f"{schema}.{item['property']}" if item.get("property") else schema
        add("enum_added", sides_of(schema), subject, schema, schema_member(schema),
            locator.enum_entry(schema, item["value"], removed=False), str(item["value"]))
    for item in deprecated.get("properties", []):
        schema = item["schema"]
        add("deprecated", sides_of(schema), item["name"], schema, schema_member(schema),
            locator.schema_field(schema, item["name"], "+- "))
    for schema in added.get("schemas", []):
        add("schema_added", sides_of(schema), schema, schema, schema_member(schema), locator.schema(schema, "+"))
    return changes, extras


# ---------------------------------------------------------------- collapsing into pattern lines

# The same change to the same property, parameter or kind of endpoint on this many schemas or operations is one line.
SWEEP_MINIMUM = 3
LISTED_NAMES = 3
PAGINATION_PARAMETERS: frozenset[str] = frozenset({"page", "size", "sort", "pageable", "limit", "offset", "cursor"})
METHOD_ORDER: tuple[str, ...] = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE")
@dataclass
class Line:
    """One contract or data line. `text` is the whole line as a sentence. `change`, `on` and `side` are its parts for a
    table row: what changed (`+ name` required), what it changed on (an endpoint, schemas, a table) and the side it reaches
    (`request`, `response`, `both`, or empty when it has none); each may hold `code` spans."""
    impact: str | None
    text: str
    path: str
    loc: tuple[str, int] | None
    members: list[Member] = field(default_factory=list)
    group: str = ""
    change: str = ""
    on: str = ""
    side: str = ""
    sources: list[Source] = field(default_factory=list)


def rank_of(impact: str | None, levels: tuple[str, ...] = CONTRACT_LEVELS) -> int:
    return levels.index(impact) if impact in levels else len(levels)


def code(name: str) -> str:
    return f"`{name}`"


def names_text(names: list[str]) -> str:
    """The first LISTED_NAMES names as code, then `+N` for the rest."""
    shown: str = ", ".join(code(n) for n in names[:LISTED_NAMES])
    return f"{shown} +{len(names) - LISTED_NAMES}" if len(names) > LISTED_NAMES else shown


def plural(count: int, noun: str, many: str | None = None) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {many or noun + 's'}"



def literal_prefix(path: str) -> str:
    """The path up to its first `{parameter}` segment."""
    kept: list[str] = []
    for part in path.split("/"):
        if part.startswith("{"):
            break
        kept.append(part)
    return "/".join(kept) or "/"


def operation_families(operations: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """The operations grouped by controller tag and, inside a tag, by the shortest literal path prefix that the others
    in the tag start with: `(base path, operations)` in the order the first of each appears."""
    families: list[tuple[str | None, list[str], list[dict[str, Any]]]] = []
    for operation in sorted(operations, key=lambda o: len(literal_prefix(o["path"]).split("/"))):
        segments: list[str] = literal_prefix(operation["path"]).split("/")
        for tag, root, members in families:
            if tag == operation.get("tag") and segments[:len(root)] == root and len(root) > 1:
                members.append(operation)
                break
        else:
            families.append((operation.get("tag"), segments, [operation]))
    order: dict[int, int] = {id(o): i for i, o in enumerate(operations)}
    ordered = sorted(families, key=lambda family: min(order[id(o)] for o in family[2]))
    return [("/".join(root) or "/", sorted(members, key=lambda o: order[id(o)])) for _, root, members in ordered]


def methods_text(operations: list[dict[str, Any]]) -> str:
    found: set[str] = {o["method"] for o in operations}
    return " ".join(m for m in METHOD_ORDER if m in found)


def operation_pattern_lines(extras: dict[str, Any], contract: dict[str, Any], spec_path: str) -> list[Line]:
    """The lines for removed, added, deprecated and moved operations: a family of two or more under one base path is one
    line, as is a sweep of three or more moves that only change a path prefix."""
    lines: list[Line] = []
    schema_operations: dict[str, list[str]] = contract.get("schema_operations", {})

    def member_of(operation: dict[str, Any], kind: str) -> Member:
        return Member(operation=f"{operation['method']} {operation['path']}", tag=operation.get("tag"), kind=kind,
                      operation_id=operation.get("operation_id"))

    prefix_moves: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for move in extras["moves"]:
        old, new = move["from"].split("/"), move["to"].split("/")
        common: int = 0
        while common < min(len(old), len(new)) - 1 and old[-1 - common] == new[-1 - common]:
            common += 1
        key = ("/".join(old[:len(old) - common]), "/".join(new[:len(new) - common]))
        prefix_moves.setdefault(key, []).append(move)
    for (old_prefix, new_prefix), moves in prefix_moves.items():
        impact: str = contract_impact("operation_moved")
        if len(moves) >= SWEEP_MINIMUM:
            text: str = f"{code(old_prefix + '/*')} → {code(new_prefix + '/*')}, {len(moves)} endpoints"
            lines.append(Line(impact, text, spec_path, moves[0]["loc"],
                              [member_of({"method": m["method"], "path": m["to"], "tag": m["tag"], "operation_id": m.get("operation_id")}, "operation_moved")
                               for m in moves],
                              change=f"moved, {len(moves)} endpoints", on=f"{code(old_prefix + '/*')} → {code(new_prefix + '/*')}"))
        else:
            for move in moves:
                lines.append(Line(impact, f"{code(move['from'])} → {code(move['to'])}", spec_path, move["loc"],
                                  [member_of({"method": move["method"], "path": move["to"], "tag": move["tag"], "operation_id": move.get("operation_id")},
                                             "operation_moved")],
                                  change="moved", on=f"{code(move['from'])} → {code(move['to'])}"))

    for key, verb, kind in (("removed", "removed", "operation_removed"), ("added", "new", "operation_added"),
                            ("deprecated", "deprecated", "deprecated")):
        impact = contract_impact(kind)
        for base, members in operation_families(extras[key]):
            first: dict[str, Any] = members[0]
            if len(members) == 1:
                label: str = code(f"{first['method']} {first['path']}")
                text = f"new {label}" if verb == "new" else f"{label} {verb}"
                change, on = verb, label
            else:
                text = f"{verb} {code(base)} {methods_text(members)}"
                change, on = f"{verb} {methods_text(members)}", code(base)
                if verb == "new":
                    labels: set[str] = {f"{o['method']} {o['path']}" for o in members}
                    schemas: int = sum(1 for schema in contract.get("added", {}).get("schemas", [])
                                       if labels & set(schema_operations.get(schema, [])))
                    text += f" · {plural(schemas, 'new schema')}" if schemas else ""
                    change += f", +{plural(schemas, 'schema')}" if schemas else ""
            lines.append(Line(impact, text, spec_path, first["loc"], [member_of(o, kind) for o in members], change=change, on=on))
    return lines


PROPERTY_PHRASE: dict[str, str] = {
    "property_added": "added", "property_added_required": "added (required)", "property_required": "now required",
    "property_no_longer_required": "no longer required", "property_removed": "removed",
    "property_type_changed": "type changed", "property_constraint_changed": "constraint changed",
    "deprecated": "deprecated", "schema_removed": "removed",
}
PARAMETER_CHANGE: dict[str, str] = {
    "parameter_added": "{plus} param", "parameter_added_required": "{plus} required param",
    "parameter_required": "{name} param now required", "parameter_no_longer_required": "{name} param no longer required",
    "parameter_type_changed": "{name} param type changed", "parameter_constraint_changed": "{name} param constraint changed",
}
PARAMETER_PHRASE: dict[str, str] = {
    "parameter_added": "added", "parameter_added_required": "added (required)", "parameter_required": "now required",
    "parameter_no_longer_required": "no longer required", "parameter_type_changed": "type changed",
    "parameter_constraint_changed": "constraint changed",
}


def property_change(kind: str, name: str, types: tuple[str, str] | None = None) -> str:
    """The Change cell for a property: `+ name` optional, `+ name` required, `− name`, `name` number → string, ..."""
    return {
        "property_added": f"{code('+ ' + name)} optional", "property_added_required": f"{code('+ ' + name)} required",
        "property_required": f"{code(name)} now required", "property_no_longer_required": f"{code(name)} no longer required",
        "property_removed": code("− " + name), "property_constraint_changed": f"{code(name)} constraint changed",
        "property_type_changed": f"{code(name)} {types[0]} → {types[1]}" if types else f"{code(name)} type changed",
        "deprecated": f"{code(name)} deprecated", "schema_removed": "removed",
    }[kind]


def property_lines(changes: list[Change], spec_path: str) -> list[Line]:
    """One line per property change, or one line per property and kind of change when three or more schemas get the same
    change on the same sides. Removed schemas share a line when there are three or more."""
    lines: list[Line] = []
    groups: dict[tuple[str, str, frozenset[str]], list[Change]] = {}
    for change in changes:
        name: str = "" if change.kind == "schema_removed" else change.subject
        groups.setdefault((change.kind, name, change.sides), []).append(change)
    for (kind, name, sides), group in groups.items():
        phrase: str = PROPERTY_PHRASE[kind]
        side: str = side_phrase(sides)
        if len(group) >= SWEEP_MINIMUM:
            if kind == "schema_removed":
                text: str = f"{len(group)} schemas removed · {names_text([c.subject for c in group])}"
            else:
                text = f"{code(name)} {phrase} on {len(group)} schemas" + (f", {side}" if side else "")
                text += f" · {names_text([c.scope for c in group])}"
            scopes: list[str] = list(dict.fromkeys(c.scope for c in group))
            same: set[tuple[str, str] | None] = {c.types for c in group}
            lines.append(Line(group[0].impact, text, spec_path, group[0].loc, [c.member for c in group],
                              change=property_change(kind, name, same.pop() if len(same) == 1 else None),
                              on=several(len(scopes), "schema", scopes), side=side_cell(sides)))
            continue
        for change in group:
            if kind == "schema_removed":
                lines.append(Line(change.impact, f"{code(change.subject)} schema removed", spec_path, change.loc, [change.member],
                                  change="removed", on=code(change.subject), side=side_cell(sides)))
            else:
                text = f"{code(name)} {phrase} on {code(change.scope)}"
                lines.append(Line(change.impact, f"{side_word(sides)}: {text}" if sides else text, spec_path, change.loc, [change.member],
                                  change=property_change(kind, name, change.types), on=code(change.scope), side=side_cell(sides)))
    return lines


def type_sweep_lines(changes: list[Change], spec_path: str) -> tuple[list[Line], list[Change]]:
    """The same type change (old type to new type) on three or more properties, on the same sides, is one line:
    `number` → `string` on 23 properties in 9 schemas, then the first property names. Returns those lines and the
    type changes that no sweep took."""
    groups: dict[tuple[tuple[str, str], frozenset[str]], list[Change]] = {}
    for change in changes:
        if change.types:
            groups.setdefault((change.types, change.sides), []).append(change)
    lines: list[Line] = []
    swept: set[int] = set()
    for ((old, new), sides), group in groups.items():
        if len(group) < SWEEP_MINIMUM:
            continue
        side: str = side_phrase(sides)
        schemas: int = len({c.scope for c in group})
        text: str = f"{code(old)} → {code(new)} on {plural(len(group), 'property', 'properties')} in {plural(schemas, 'schema')}"
        properties: list[str] = list(dict.fromkeys(c.subject for c in group))
        text += (f", {side}" if side else "") + f" · {names_text(properties)}"
        scopes: list[str] = list(dict.fromkeys(c.scope for c in group))
        lines.append(Line(group[0].impact, text, spec_path, group[0].loc, [c.member for c in group],
                          change=f"{code(old)} → {code(new)}, {several(len(properties), 'property', properties, 'properties')}",
                          on=several(len(scopes), "schema", scopes), side=side_cell(sides)))
        swept.update(id(c) for c in group)
    return lines, [c for c in changes if id(c) not in swept]


def schema_added_lines(changes: list[Change], covered: set[str], spec_path: str) -> list[Line]:
    """One line for the new schemas that no new operation family already counted."""
    fresh: list[Change] = [c for c in changes if c.kind == "schema_added" and c.scope not in covered]
    if not fresh:
        return []
    names: list[str] = [c.scope for c in fresh]
    text: str = f"{code(names[0])} schema added" if len(names) == 1 else f"{len(names)} schemas added · {names_text(names)}"
    sides: frozenset[str] = frozenset().union(*(c.sides for c in fresh))
    return [Line(fresh[0].impact, text, spec_path, fresh[0].loc, [c.member for c in fresh],
                 change="new schema" if len(names) == 1 else "new schemas",
                 on=code(names[0]) if len(names) == 1 else several(len(names), "schema", names), side=side_cell(sides))]


def parameter_change(kind: str, name: str) -> str:
    """The Change cell for a parameter: `+ name` required param, `name` param type changed, ..."""
    return PARAMETER_CHANGE[kind].format(plus=code("+ " + name), name=code(name))


def parameter_lines(changes: list[Change], spec_path: str) -> list[Line]:
    """One line per parameter change; a pagination parameter added to three or more operations is
    `pagination added to N endpoints`, and any other parameter change on three or more operations is one line."""
    lines: list[Line] = []
    pagination: dict[str, list[Change]] = {}
    for change in changes:
        if change.kind in ("parameter_added", "parameter_added_required") and change.subject in PAGINATION_PARAMETERS:
            pagination.setdefault(change.scope, []).append(change)
    swept: set[int] = set()
    if len(pagination) >= SWEEP_MINIMUM:
        first: Change = next(iter(pagination.values()))[0]
        every: list[Change] = [c for group in pagination.values() for c in group]
        worst: str = min((c.impact for c in every), key=CONTRACT_LEVELS.index)
        lines.append(Line(worst, f"pagination added to {len(pagination)} endpoints", spec_path, first.loc,
                          [c.member for group in pagination.values() for c in group[:1]],
                          change="pagination added", on=several(len(pagination), "endpoint", list(pagination)), side=REQUEST))
        swept.update(id(c) for c in every)
    groups: dict[tuple[str, str], list[Change]] = {}
    for change in changes:
        if id(change) not in swept:
            groups.setdefault((change.kind, change.subject), []).append(change)
    for (kind, name), group in groups.items():
        phrase: str = PARAMETER_PHRASE[kind]
        if len(group) >= SWEEP_MINIMUM:
            preposition: str = "to" if kind in ("parameter_added", "parameter_added_required") else "on"
            scopes: list[str] = list(dict.fromkeys(c.scope for c in group))
            lines.append(Line(group[0].impact, f"{code(name)} parameter {phrase} {preposition} {len(group)} endpoints", spec_path,
                              group[0].loc, [c.member for c in group], change=parameter_change(kind, name),
                              on=several(len(scopes), "endpoint", scopes), side=REQUEST))
            continue
        for change in group:
            preposition = "to" if kind in ("parameter_added", "parameter_added_required") else "on"
            lines.append(Line(change.impact, f"{code(name)} parameter {phrase} {preposition} {code(change.scope)}", spec_path,
                              change.loc, [change.member], change=parameter_change(kind, name), on=code(change.scope),
                              side=REQUEST))
    return lines


def enum_lines(changes: list[Change], spec_path: str) -> list[Line]:
    """`Enum` + `VALUE` for an added value (values of one enum share a line) and `Enum` value `VALUE` removed."""
    lines: list[Line] = []
    added: dict[str, list[Change]] = {}
    for change in changes:
        if change.kind == "enum_added":
            added.setdefault(change.subject, []).append(change)
        else:
            lines.append(Line(change.impact, f"{code(change.subject)} value {code(change.detail)} removed", spec_path,
                              change.loc, [change.member], change=code("− " + change.detail), on=code(change.subject),
                              side=side_cell(change.sides)))
    for subject, group in added.items():
        lines.append(Line(group[0].impact, f"{code(subject)} + {', '.join(code(c.detail) for c in group)}", spec_path,
                          group[0].loc, [c.member for c in group],
                          change=", ".join(code("+ " + c.detail) for c in group), on=code(subject),
                          side=side_cell(frozenset().union(*(c.sides for c in group)))))
    return lines


def operation_change_lines(changes: list[Change], spec_path: str) -> list[Line]:
    lines: list[Line] = []
    for change in changes:
        words: str = {"responses": "responses changed"}.get(change.detail, f"{change.detail} changed")
        lines.append(Line(change.impact, f"{code(change.subject)} {words}", spec_path, change.loc, [change.member],
                          change=words, on=code(change.subject)))
    return lines


def pattern_lines(changes: list[Change], extras: dict[str, Any], contract: dict[str, Any], spec_path: str) -> list[Line]:
    """The collapsed lines for `changes` and `extras` (from `collect_changes`), worst impact first and otherwise in the
    order the document shows them: operations, parameters, schema properties, enums."""
    def kinds(*names: str) -> list[Change]:
        return [c for c in changes if c.kind in names]

    operations: list[Line] = operation_pattern_lines(extras, contract, spec_path)
    added_labels: set[str] = {f"{o['method']} {o['path']}" for o in extras["added"]}
    counted: set[str] = {schema for schema in contract.get("added", {}).get("schemas", [])
                         if added_labels & set(contract.get("schema_operations", {}).get(schema, []))}
    type_lines, type_leftovers = type_sweep_lines(kinds("property_type_changed"), spec_path)
    lines: list[Line] = [
        *operations,
        *operation_change_lines(kinds("operation_changed", "responses_changed"), spec_path),
        *parameter_lines(kinds(*PARAMETER_PHRASE), spec_path),
        *type_lines,
        *property_lines([c for c in kinds(*(k for k in PROPERTY_PHRASE if k != "schema_removed")) if c.kind != "property_type_changed"]
                        + type_leftovers, spec_path),
        *property_lines(kinds("schema_removed"), spec_path),
        *schema_added_lines(changes, counted, spec_path),
        *enum_lines(kinds("enum_added", "enum_removed"), spec_path),
    ]
    return sorted(lines, key=lambda line: rank_of(line.impact))


def contract_lines(contract: dict[str, Any], lines: list[DiffLine], spec_path: str) -> list[Line]:
    """The pattern lines of a run's contract.json (`lines` is the spec file's diff), worst impact first."""
    changes, extras = collect_changes(contract, lines)
    return pattern_lines(changes, extras, contract, spec_path)
