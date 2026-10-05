"""Tests for the order of the review list after the floors apply. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context_pack import contract_breaks, contract_lines  # noqa: E402
from render import build_chunks, file_floor  # noqa: E402

FLOORS = {"floor": [{"name": "schema file", "level": "verify", "globs": ["**/schema.json"]}]}
PATHS = ["src/a.js", "src/b.js", "src/c.js", "src/d.js", "api/schema.json"]
COUNTS = {path.lower(): (1, 0) for path in PATHS}


def raw(name: str, review: str, path: str) -> dict:
    return {"name": name, "review": review, "why": "w", "files": [path]}


def build(chunks: list[dict], paths: list[str] = PATHS) -> list:
    return build_chunks(chunks, COUNTS, paths, FLOORS, [], {})


class ChunkOrder(unittest.TestCase):
    def test_a_chunk_the_floor_raises_moves_above_lower_levels(self) -> None:
        chunks = build([raw("A", "read", "src/a.js"), raw("B", "skim", "src/b.js"), raw("C", "read", "api/schema.json")],
                       ["src/a.js", "src/b.js", "api/schema.json"])
        self.assertEqual([(c.name, c.review) for c in chunks],
                         [("C", "verify"), ("A", "read"), ("B", "skim")])
        self.assertEqual(chunks[0].raised_by, ["schema file"])

    def test_the_models_order_holds_within_a_level(self) -> None:
        chunks = build([raw("A", "skim", "src/a.js"), raw("B", "read", "src/b.js"), raw("C", "skim", "src/c.js"),
                        raw("D", "read", "src/d.js")], PATHS[:4])
        self.assertEqual([c.name for c in chunks], ["B", "D", "A", "C"])

    def test_the_numbers_are_sequential_after_the_sort(self) -> None:
        chunks = build([raw("A", "skim", "src/a.js"), raw("B", "read", "src/b.js"), raw("C", "skim", "api/schema.json")],
                       ["src/a.js", "src/b.js", "api/schema.json"])
        self.assertEqual([(c.number, c.name) for c in chunks], [(1, "C"), (2, "B"), (3, "A")])

    def test_files_the_model_left_out_stay_last(self) -> None:
        chunks = build([raw("A", "skim", "src/a.js")], ["src/a.js", "src/b.js"])
        self.assertEqual([c.name for c in chunks], ["A", "Unchunked"])


SPEC = "api/openapi.json"
RULE = {"name": "OpenAPI spec", "level": "read", "level_if_deleted": "verify", "globs": [SPEC]}


class ContractFloor(unittest.TestCase):
    def level(self, rule: dict, contract: dict | None, deletions: int = 12) -> str:
        floor = file_floor({"floor": [rule]}, SPEC, deletions, contract)
        return floor[0] if floor else ""

    def test_an_edited_spec_with_no_removals_is_not_raised(self) -> None:
        contract = {"path": SPEC, "removals": []}
        self.assertEqual(self.level({**RULE, "deleted_from": "contract"}, contract), "read")

    def test_a_spec_with_a_listed_removal_is_raised(self) -> None:
        contract = {"path": SPEC, "removals": ["removed operation GET /widgets"]}
        self.assertEqual(self.level({**RULE, "deleted_from": "contract"}, contract), "verify")

    def test_a_rule_without_the_key_counts_deleted_lines_as_before(self) -> None:
        contract = {"path": SPEC, "removals": []}
        self.assertEqual(self.level(RULE, contract), "verify")
        self.assertEqual(self.level(RULE, contract, deletions=0), "read")

    def test_a_run_with_no_contract_json_counts_deleted_lines_as_before(self) -> None:
        self.assertEqual(self.level({**RULE, "deleted_from": "contract"}, None), "verify")
        self.assertEqual(self.level({**RULE, "deleted_from": "contract"}, None, deletions=0), "read")

    def test_a_newly_required_field_raises_the_spec(self) -> None:
        contract = {"path": SPEC, "removals": [], "newly_required": ["Widget.size (now required)"]}
        self.assertEqual(self.level({**RULE, "deleted_from": "contract"}, contract), "verify")

    def test_a_removal_listed_for_another_file_does_not_raise_this_one(self) -> None:
        contract = {"path": "other/openapi.json", "removals": ["removed operation GET /widgets"]}
        self.assertEqual(self.level({**RULE, "deleted_from": "contract"}, contract), "read")


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
        floor = file_floor({"floor": [{**RULE, "deleted_from": "contract"}]}, SPEC, 9, {"path": SPEC, **breaks})
        self.assertEqual(floor[0], "read")


if __name__ == "__main__":
    unittest.main()
