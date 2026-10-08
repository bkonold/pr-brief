"""Tests for the side and impact of contract changes. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from diff_lines import file_diff_lines  # noqa: E402
from contract_lines import (  # noqa: E402
    ADDITIVE, CALLERS, CONSUMERS, CONTRACT_LEVELS, DEPRECATED, REQUEST, RESPONSE, collect_changes, contract_impact,
    side_phrase,
)
from test_contract_block import SPEC, contract_of, document, make_diff  # noqa: E402


def ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def body(name: str) -> dict:
    return {"content": {"application/json": {"schema": ref(name)}}}


def operation(operation_id: str, tag: str | None = None, request: str | None = None, response: str | None = None,
              **more: object) -> dict:
    return {"operationId": operation_id, **({"tags": [tag]} if tag else {}),
            **({"requestBody": body(request)} if request else {}),
            "responses": {"200": body(response) if response else {"description": "ok"}}, **more}


def changes_for(base: dict, head: dict) -> list:
    diff = make_diff(SPEC, json.dumps(base, indent=2), json.dumps(head, indent=2))
    found, _ = collect_changes(contract_of(base, head), file_diff_lines(diff, SPEC))
    return found


def impacts(base: dict, head: dict) -> dict[tuple[str, str], str]:
    return {(c.kind, c.subject): c.impact for c in changes_for(base, head)}


def props(*names: str, required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": {name: {"type": "string"} for name in names}, "required": list(required)}


class ImpactTable(unittest.TestCase):
    def test_the_levels_run_from_callers_to_deprecated(self) -> None:
        self.assertEqual(CONTRACT_LEVELS, (CALLERS, CONSUMERS, ADDITIVE, DEPRECATED))

    def test_a_removed_endpoint_and_a_new_required_request_property_make_callers_change(self) -> None:
        self.assertEqual(contract_impact("operation_removed", frozenset({RESPONSE})), CALLERS)
        self.assertEqual(contract_impact("property_added_required", frozenset({REQUEST})), CALLERS)
        self.assertEqual(contract_impact("property_required", frozenset({REQUEST})), CALLERS)
        self.assertEqual(contract_impact("parameter_added_required", frozenset({REQUEST})), CALLERS)
        self.assertEqual(contract_impact("enum_removed", frozenset({REQUEST})), CALLERS)
        self.assertEqual(contract_impact("property_type_changed", frozenset({REQUEST})), CALLERS)

    def test_a_required_property_on_a_response_is_additive(self) -> None:
        self.assertEqual(contract_impact("property_added_required", frozenset({RESPONSE})), ADDITIVE)
        self.assertEqual(contract_impact("property_required", frozenset({RESPONSE})), ADDITIVE)

    def test_response_removals_and_type_changes_may_break_consumers(self) -> None:
        self.assertEqual(contract_impact("property_removed", frozenset({RESPONSE})), CONSUMERS)
        self.assertEqual(contract_impact("schema_removed", frozenset({RESPONSE})), CONSUMERS)
        self.assertEqual(contract_impact("property_type_changed", frozenset({RESPONSE})), CONSUMERS)

    def test_additions_are_additive_and_deprecation_is_its_own_level(self) -> None:
        for kind in ("operation_added", "parameter_added", "property_added", "enum_added"):
            self.assertEqual(contract_impact(kind, frozenset({REQUEST})), ADDITIVE, kind)
        self.assertEqual(contract_impact("deprecated", frozenset({REQUEST})), DEPRECATED)

    def test_a_schema_on_both_sides_takes_the_worse_impact_and_unknown_sides_count_as_both(self) -> None:
        both = frozenset({REQUEST, RESPONSE})
        self.assertEqual(contract_impact("property_added_required", both), CALLERS)
        self.assertEqual(contract_impact("property_added_required", frozenset()), CALLERS)
        self.assertEqual(contract_impact("property_no_longer_required", both), CONSUMERS)

    def test_the_docstring_table_names_every_kind(self) -> None:
        table = contract_impact.__doc__
        for kind in ("operation_removed", "property_added_required", "enum_added", "deprecated", "parameter_added_required"):
            self.assertIn(f"| {kind}", table)

    def test_the_side_phrase(self) -> None:
        self.assertEqual(side_phrase(frozenset({RESPONSE})), "response only")
        self.assertEqual(side_phrase(frozenset({REQUEST, RESPONSE})), "request and response")
        self.assertEqual(side_phrase(frozenset()), "")


class RecordedSides(unittest.TestCase):
    def test_a_schema_records_the_sides_of_each_operation_that_reaches_it(self) -> None:
        paths = {"/items": {"post": operation("makeItem", "item-controller", request="ItemRequest", response="Item")}}
        base = document(paths, {"ItemRequest": props("a"), "Item": props("a")})
        head = document(paths, {"ItemRequest": props("a", "b"), "Item": props("a", "b")})
        sides = contract_of(base, head)["schema_sides"]
        self.assertEqual(sides, {"Item": {"POST /items": ["response"]}, "ItemRequest": {"POST /items": ["request"]}})

    def test_a_schema_used_on_both_sides_has_both(self) -> None:
        paths = {"/items": {"put": operation("putItem", request="Item", response="Item")}}
        base = document(paths, {"Item": props("a")})
        head = document(paths, {"Item": props("a", "b")})
        self.assertEqual(contract_of(base, head)["schema_sides"], {"Item": {"PUT /items": ["request", "response"]}})

    def test_a_schema_nested_in_a_request_schema_counts_as_request(self) -> None:
        paths = {"/items": {"post": operation("makeItem", request="Outer")}}
        outer = {"type": "object", "properties": {"inner": ref("Inner")}}
        base = document(paths, {"Outer": outer, "Inner": props("a")})
        head = document(paths, {"Outer": outer, "Inner": props("a", "b")})
        self.assertEqual(contract_of(base, head)["schema_sides"], {"Inner": {"POST /items": ["request"]}})

    def test_the_contract_lists_tags_deprecations_enum_values_and_removed_operations(self) -> None:
        base = document({"/old": {"get": operation("old", "old-controller")}, "/keep": {"get": operation("keep", "keep-controller")}},
                        {"Kind": {"type": "string", "enum": ["A"]}, "Item": {"properties": {"x": {"type": "string"}}}})
        head = document({"/keep": {"get": operation("keep", "keep-controller", deprecated=True)}},
                        {"Kind": {"type": "string", "enum": ["A", "B"]},
                         "Item": {"properties": {"x": {"type": "string", "deprecated": True}}}})
        contract = contract_of(base, head)
        self.assertEqual(contract["removed_operations"], [{"method": "GET", "path": "/old", "operation_id": "old"}])
        self.assertEqual(contract["operation_tags"], {"GET /keep": "keep-controller", "GET /old": "old-controller"})
        self.assertEqual(contract["deprecated"], {"operations": [{"method": "GET", "path": "/keep"}],
                                                  "properties": [{"schema": "Item", "name": "x"}]})
        self.assertEqual(contract["enums_added"], [{"schema": "Kind", "property": None, "value": "B"}])

    def test_a_changed_parameter_records_which_schema_keys_differ(self) -> None:
        param = {"name": "size", "in": "query", "schema": {"type": "integer", "default": 10}}
        base = document({"/items": {"get": operation("list", parameters=[param])}}, {})
        head = document({"/items": {"get": operation("list", parameters=[{**param, "schema": {"type": "integer", "default": 20}}])}}, {})
        self.assertEqual(contract_of(base, head)["changed"]["parameters"][0]["schema_what"], ["default"])


class CollectedChanges(unittest.TestCase):
    def test_a_new_required_property_is_additive_on_a_response_and_breaking_on_a_request(self) -> None:
        paths = {"/items": {"post": operation("makeItem", request="ItemRequest", response="Item")}}
        base = document(paths, {"ItemRequest": props("a"), "Item": props("a")})
        head = document(paths, {"ItemRequest": props("a", "b", required=("b",)), "Item": props("a", "b", required=("b",))})
        found = {c.scope: (c.kind, c.impact) for c in changes_for(base, head)}
        self.assertEqual(found, {"ItemRequest": ("property_added_required", CALLERS), "Item": ("property_added_required", ADDITIVE)})

    def test_an_existing_property_made_required_on_a_response_is_additive(self) -> None:
        paths = {"/items": {"get": operation("list", response="Item")}}
        base = document(paths, {"Item": props("a", "b", required=("a",))})
        head = document(paths, {"Item": props("a", "b", required=("a", "b"))})
        self.assertEqual([(c.kind, c.impact) for c in changes_for(base, head)], [("property_required", ADDITIVE)])

    def test_a_removed_response_property_may_break_consumers(self) -> None:
        paths = {"/items": {"get": operation("list", response="Item")}}
        base = document(paths, {"Item": props("a", "b")})
        head = document(paths, {"Item": props("a")})
        self.assertEqual([(c.kind, c.impact, c.sides) for c in changes_for(base, head)],
                         [("property_removed", CONSUMERS, frozenset({RESPONSE}))])

    def test_a_property_type_change_depends_on_the_side(self) -> None:
        paths = {"/items": {"post": operation("makeItem", request="In", response="Out")}}
        base = document(paths, {"In": props("a"), "Out": props("a")})
        changed = {"type": "object", "properties": {"a": {"type": "integer"}}}
        head = document(paths, {"In": changed, "Out": changed})
        found = {c.scope: c.impact for c in changes_for(base, head)}
        self.assertEqual(found, {"In": CALLERS, "Out": CONSUMERS})

    def test_a_removed_operation_and_a_new_required_parameter_make_callers_change(self) -> None:
        base = document({"/gone": {"get": operation("gone", "gone-controller")}, "/kept": {"get": operation("kept")}}, {})
        head = document({"/kept": {"get": operation("kept", parameters=[{"name": "kind", "in": "query", "required": True}])}}, {})
        found = {(c.kind, c.subject): c.impact for c in changes_for(base, head)}
        self.assertEqual(found, {("parameter_added_required", "kind"): CALLERS})

    def test_enum_values_added_and_removed_and_deprecation(self) -> None:
        base = document({}, {"Kind": {"type": "string", "enum": ["A", "B"]}, "Item": {"properties": {"x": {"type": "string"}}}})
        head = document({}, {"Kind": {"type": "string", "enum": ["B", "C"]},
                             "Item": {"properties": {"x": {"type": "string", "deprecated": True}}}})
        found = {(c.kind, c.detail or c.subject): c.impact for c in changes_for(base, head)}
        self.assertEqual(found, {("enum_added", "C"): ADDITIVE, ("enum_removed", "A"): CALLERS, ("deprecated", "x"): DEPRECATED})

    def test_a_schema_no_operation_reaches_counts_as_both_sides(self) -> None:
        base = document({}, {"Orphan": props("a")})
        head = document({}, {"Orphan": props("a", "b", required=("b",))})
        self.assertEqual([(c.impact, c.sides) for c in changes_for(base, head)], [(CALLERS, frozenset())])

    def test_cosmetic_changes_make_no_change(self) -> None:
        paths = {"/items": {"get": operation("list", summary="old")}}
        base = document(paths, {"Item": {"properties": {"a": {"type": "string", "description": "x"}}}})
        head = document({"/items": {"get": operation("list", summary="new")}},
                        {"Item": {"properties": {"a": {"type": "string", "description": "y"}}}})
        self.assertEqual(changes_for(base, head), [])


if __name__ == "__main__":
    unittest.main()
