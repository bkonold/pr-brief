"""Tests for the contract changes `context_pack` lists. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context_pack import contract_breaks, contract_changes  # noqa: E402
from contract_fixtures import document, operation  # noqa: E402

FILLER = {f"/pad{i}": {"get": operation(f"pad{i}")} for i in range(6)}


class ContractChanges(unittest.TestCase):
    def test_a_new_operation_and_a_new_property_are_listed(self) -> None:
        base = document({**FILLER}, {"Widget": {"type": "object", "properties": {"id": {"type": "string"}}}})
        head = document({**FILLER, "/widgets": {"get": operation("listWidgets")}},
                        {"Widget": {"type": "object", "properties": {"id": {"type": "string"}, "size": {"type": "integer"}}}})
        changes = contract_changes(base, head, contract_breaks(base, head))
        self.assertEqual(changes["added"]["operations"], [{"method": "GET", "path": "/widgets", "operation_id": "listWidgets"}])
        self.assertEqual(changes["added"]["properties"], [{"schema": "Widget", "name": "size"}])

    def test_a_schema_change_names_the_operations_that_reach_it(self) -> None:
        base = document({"/widgets": {"get": {**operation("listWidgets"), "responses": {"200": {"content": {"application/json": {
            "schema": {"$ref": "#/components/schemas/Widget"}}}}}}}},
                        {"Widget": {"properties": {"id": {}}}})
        head = document(base["paths"], {"Widget": {"properties": {"id": {}, "size": {}}}})
        changes = contract_changes(base, head, contract_breaks(base, head))
        self.assertEqual(changes["schema_operations"], {"Widget": ["GET /widgets"]})

    def test_the_breaking_lists_are_unchanged(self) -> None:
        base = document({"/widgets": {"get": operation("a")}}, {"Widget": {"properties": {"id": {}}, "required": []}})
        head = document({}, {"Widget": {"properties": {"id": {}}, "required": ["id"]}})
        self.assertEqual(contract_breaks(base, head),
                         {"removals": ["removed operation GET /widgets"], "newly_required": ["Widget.id (now required)"]})


if __name__ == "__main__":
    unittest.main()
