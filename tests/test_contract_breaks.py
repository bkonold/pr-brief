"""Tests for the removals and newly required fields that a contract comparison lists. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context_pack import contract_breaks, contract_lines  # noqa: E402


class ContractRemovals(unittest.TestCase):
    BASE = {"paths": {"/widgets": {"get": {}, "delete": {}}},
            "components": {"schemas": {"Widget": {"properties": {"id": {}, "size": {"enum": ["S", "L"]}}, "required": ["id"]}}}}

    def test_a_newly_required_property_is_a_contract_line_but_not_a_removal(self) -> None:
        head = {"paths": self.BASE["paths"],
                "components": {"schemas": {"Widget": {"properties": {"id": {}, "size": {"enum": ["S", "L"]}}, "required": ["id", "size"]}}}}
        self.assertEqual(contract_lines(self.BASE, head), ["Widget.size (now required)"])
        self.assertEqual(contract_lines(self.BASE, head, removals_only=True), [])

    def test_removed_operations_properties_and_enum_values_are_removals(self) -> None:
        head = {"paths": {"/widgets": {"get": {}}},
                "components": {"schemas": {"Widget": {"properties": {"size": {"enum": ["S"]}}, "required": ["id"]}}}}
        self.assertEqual(contract_lines(self.BASE, head, removals_only=True),
                         ["removed operation DELETE /widgets", "Widget.id (property removed)", "Widget.size (enum value L removed)"])


def document(properties: dict, required: list, parameters: list | None = None, shared_parameters: dict | None = None) -> dict:
    return {"paths": {"/widgets": {"get": {"parameters": parameters or []}}},
            "components": {"schemas": {"Widget": {"properties": properties, "required": required}},
                           "parameters": shared_parameters or {}}}


class NewlyRequired(unittest.TestCase):
    def test_an_optional_property_made_required(self) -> None:
        base = document({"id": {}, "size": {}}, ["id"])
        head = document({"id": {}, "size": {}}, ["id", "size"])
        self.assertEqual(contract_breaks(base, head), {"removals": [], "newly_required": ["Widget.size (now required)"]})

    def test_a_new_property_that_is_required_from_the_start(self) -> None:
        base = document({"id": {}}, ["id"])
        head = document({"id": {}, "color": {}}, ["id", "color"])
        self.assertEqual(contract_breaks(base, head)["newly_required"], ["Widget.color (now required)"])

    def test_a_new_optional_property_is_not_breaking(self) -> None:
        self.assertEqual(contract_breaks(document({"id": {}}, ["id"]), document({"id": {}, "color": {}}, ["id"])),
                         {"removals": [], "newly_required": []})

    def test_a_parameter_made_required_and_a_new_required_parameter(self) -> None:
        base = document({}, [], [{"name": "limit", "in": "query"}])
        head = document({}, [], [{"name": "limit", "in": "query", "required": True},
                                 {"$ref": "#/components/parameters/Tenant"}, {"name": "page", "in": "query"}],
                        {"Tenant": {"name": "tenant", "in": "header", "required": True}})
        self.assertEqual(contract_breaks(base, head)["newly_required"],
                         ["GET /widgets parameter limit (query, now required)", "GET /widgets parameter tenant (header, now required)"])

    def test_a_required_parameter_on_a_new_operation_is_not_breaking(self) -> None:
        base = {"paths": {}, "components": {}}
        head = document({}, [], [{"name": "limit", "in": "query", "required": True}])
        self.assertEqual(contract_breaks(base, head), {"removals": [], "newly_required": []})

    def test_an_edit_with_no_breaking_change_is_not_listed_and_does_not_raise(self) -> None:
        base = document({"id": {}, "size": {"description": "a"}}, ["id"], [{"name": "limit", "in": "query", "required": True}])
        head = document({"id": {}, "size": {"description": "b"}}, ["id"], [{"name": "limit", "in": "query", "required": True}])
        breaks = contract_breaks(base, head)
        self.assertEqual(breaks, {"removals": [], "newly_required": []})
