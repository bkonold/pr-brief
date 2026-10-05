"""The "Contract" changes of a v22 brief: what a PR changes in the OpenAPI document, each with the side it reaches
(request or response) and an impact level.

`collect_changes` reads a run's contract.json and the spec's diff and yields one `Change` per atomic difference, with
its impact level from `contract_impact`, plus the operations that were removed, added, deprecated or moved. Older
variants build their rows with contract_block.py instead.
"""
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from contract_block import (
    ENUM_REMOVED, FIELD_REMOVED, FIELD_REQUIRED, PARAMETER_REQUIRED, REMOVED_OPERATION, SCHEMA_REMOVED, DiffLine,
    SpecDiff,
)

CALLERS = "callers must change"
CONSUMERS = "consumers may break"
ADDITIVE = "additive"
DEPRECATED = "deprecated"
CONTRACT_LEVELS: tuple[str, ...] = (CALLERS, CONSUMERS, ADDITIVE, DEPRECATED)

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
    """What a line is about, which is how it finds its chunk: a schema, an operation and its controller tag, or a
    migration file."""
    schema: str | None = None
    operation: str | None = None
    tag: str | None = None
    file: str | None = None
    table: str | None = None


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


def contract_impact(kind: str, sides: frozenset[str] | set[str] = frozenset()) -> str:
    """The impact level of one contract change, worst first: `callers must change`, `consumers may break`, `additive`,
    `deprecated`. `sides` is where the change reaches, `request` (a body or a parameter), `response`, or both; a schema
    used on both sides counts as both, and the worst of them wins. Empty `sides` (a schema no operation reaches) counts
    as both.

    | Kind | Request | Response |
    |---|---|---|
    | operation_removed | callers must change | callers must change |
    | operation_moved | callers must change | callers must change |
    | operation_added | additive | additive |
    | operation_changed (request body, security) | consumers may break | consumers may break |
    | responses_changed | additive | additive |
    | parameter_added | additive | |
    | parameter_added_required | callers must change | |
    | parameter_required (existing, made required) | callers must change | |
    | parameter_no_longer_required | additive | |
    | parameter_type_changed | callers must change | |
    | parameter_constraint_changed | consumers may break | |
    | property_added | additive | additive |
    | property_added_required | callers must change | additive |
    | property_required (existing, made required) | callers must change | additive |
    | property_no_longer_required | additive | consumers may break |
    | property_removed | consumers may break | consumers may break |
    | schema_removed | consumers may break | consumers may break |
    | schema_added | additive | additive |
    | property_type_changed | callers must change | consumers may break |
    | property_constraint_changed | consumers may break | consumers may break |
    | enum_added | additive | additive |
    | enum_removed | callers must change | consumers may break |
    | deprecated | deprecated | deprecated |
    """
    table: dict[str, tuple[str, str]] = {
        "operation_removed": (CALLERS, CALLERS), "operation_moved": (CALLERS, CALLERS),
        "operation_added": (ADDITIVE, ADDITIVE), "operation_changed": (CONSUMERS, CONSUMERS),
        "responses_changed": (ADDITIVE, ADDITIVE),
        "parameter_added": (ADDITIVE, ADDITIVE), "parameter_added_required": (CALLERS, CALLERS),
        "parameter_required": (CALLERS, CALLERS), "parameter_no_longer_required": (ADDITIVE, ADDITIVE),
        "parameter_type_changed": (CALLERS, CALLERS), "parameter_constraint_changed": (CONSUMERS, CONSUMERS),
        "property_added": (ADDITIVE, ADDITIVE), "property_added_required": (CALLERS, ADDITIVE),
        "property_required": (CALLERS, ADDITIVE), "property_no_longer_required": (ADDITIVE, CONSUMERS),
        "property_removed": (CONSUMERS, CONSUMERS), "schema_removed": (CONSUMERS, CONSUMERS),
        "schema_added": (ADDITIVE, ADDITIVE), "property_type_changed": (CALLERS, CONSUMERS),
        "property_constraint_changed": (CONSUMERS, CONSUMERS), "enum_added": (ADDITIVE, ADDITIVE),
        "enum_removed": (CALLERS, CONSUMERS), "deprecated": (DEPRECATED, DEPRECATED),
    }
    request_level, response_level = table[kind]
    reached: set[str] = set(sides) or {REQUEST, RESPONSE}
    levels: list[str] = [level for side, level in ((REQUEST, request_level), (RESPONSE, response_level)) if side in reached]
    return min(levels, key=CONTRACT_LEVELS.index)


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
            detail: str = "") -> None:
        changes.append(Change(kind, contract_impact(kind, sides), sides, subject, scope, member, loc, detail))

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
        extras["moves"].append({"method": old[0], "from": old[1], "to": new[1], "loc": loc,
                                "tag": tags.get(f"{new[0]} {new[1]}") or tags.get(f"{old[0]} {old[1]}")})
    for method, path, operation_id in removed:
        if (method, path, operation_id) in moved_old:
            continue
        extras["removed"].append({"method": method, "path": path, "tag": tags.get(f"{method} {path}"),
                                  "loc": locator.operation(method, path, None, "-")})
    for method, path, operation_id in new_operations:
        if (method, path, operation_id) in moved_new:
            continue
        extras["added"].append({"method": method, "path": path, "tag": tags.get(f"{method} {path}"),
                                "loc": locator.operation(method, path, operation_id, "+")})
    for item in deprecated.get("operations", []):
        label = f"{item['method']} {item['path']}"
        extras["deprecated"].append({"method": item["method"], "path": item["path"], "tag": tags.get(label),
                                     "loc": locator.operation(item["method"], item["path"], None, "+- ", first_change=True)})

    for item in changed.get("operations", []):
        label = f"{item['method']} {item['path']}"
        member: Member = Member(operation=label, tag=tags.get(label))
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
                member = Member(operation=label, tag=tags.get(label))
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
        add("parameter_required", frozenset({REQUEST}), name, operation, Member(operation=operation, tag=tags.get(operation)), loc)

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
        is_new: bool = schema in added_properties.get(name, [])
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
            add("property_type_changed", sides_of(schema), name, schema, schema_member(schema), loc)
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
            add("enum_removed", sides_of(schema), prop or schema, schema, schema_member(schema),
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
