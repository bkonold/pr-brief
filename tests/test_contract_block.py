"""Tests for the "Contract and data" block. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import difflib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context_pack import contract_breaks, contract_changes  # noqa: E402
from contract_block import contract_block, contract_rows, file_diff_lines, migration_rows  # noqa: E402

SPEC = "api/openapi.json"
MIGRATION = "db/V9__orders.sql"


def make_diff(path: str, before: str, after: str) -> str:
    body = difflib.unified_diff(before.splitlines(), after.splitlines(), f"a/{path}", f"b/{path}", lineterm="", n=3)
    return f"diff --git a/{path} b/{path}\n" + "\n".join(body)


def operation(operation_id: str, parameters: list | None = None) -> dict:
    return {"operationId": operation_id, "parameters": parameters or [], "responses": {"200": {"description": "ok"}}}


def document(paths: dict, schemas: dict, parameters: dict | None = None) -> dict:
    return {"openapi": "3.0.1", "paths": paths, "components": {"schemas": schemas, "parameters": parameters or {}}}


def contract_of(base: dict, head: dict) -> dict:
    breaks = contract_breaks(base, head)
    return {"path": SPEC, **breaks, **contract_changes(base, head, breaks)}


def rows_for(base: dict, head: dict) -> tuple[list, list]:
    diff = make_diff(SPEC, json.dumps(base, indent=2), json.dumps(head, indent=2))
    lines = file_diff_lines(diff, SPEC)
    return contract_rows(contract_of(base, head), lines, SPEC), lines


def line_at(lines: list, loc: tuple[str, int]) -> str:
    return next(line.text.strip() for line in lines if (line.side, line.number) == loc)


def link(path: str, side: str, line: int) -> str:
    return f"{path}#{side}{line}"


def file_link(path: str) -> str:
    return path


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


class ContractRows(unittest.TestCase):
    def test_a_new_operation_links_to_its_line_in_the_diff(self) -> None:
        base = document({**FILLER}, {})
        head = document({**FILLER, "/widgets": {"get": operation("listWidgets")}}, {})
        rows, lines = rows_for(base, head)
        self.assertEqual([(r.label, [b.text for b in r.badges]) for r in rows], [("GET /widgets", ["new"])])
        self.assertEqual(line_at(lines, rows[0].loc), '"get": {')

    def test_a_removed_operation_is_a_breaking_badge(self) -> None:
        base = document({**FILLER, "/widgets": {"get": operation("listWidgets")}}, {})
        head = document({**FILLER}, {})
        rows, lines = rows_for(base, head)
        self.assertEqual([(r.label, [(b.text, b.breaking) for b in r.badges]) for r in rows],
                         [("GET /widgets", [("removed", True)])])
        self.assertEqual(rows[0].badges[0].loc[0], "L")

    def test_a_property_added_to_a_schema_lands_on_the_operation_that_returns_it(self) -> None:
        returns = {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Widget"}}}}}
        paths = {**FILLER, "/widgets": {"get": {"operationId": "listWidgets", "responses": returns}}}
        base = document(paths, {"Widget": {"type": "object", "properties": {"id": {"type": "string"}}}})
        head = document(paths, {"Widget": {"type": "object", "properties": {"id": {"type": "string"}, "size": {"type": "integer"}}}})
        rows, lines = rows_for(base, head)
        self.assertEqual([(r.label, [b.text for b in r.badges]) for r in rows], [("GET /widgets", ["size added"])])
        self.assertEqual(line_at(lines, rows[0].badges[0].loc), '"size": {')

    def test_a_field_made_required_is_breaking_and_links_to_the_required_entry(self) -> None:
        returns = {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Widget"}}}}}
        paths = {**FILLER, "/widgets": {"post": {"operationId": "makeWidget", "responses": returns}}}
        base = document(paths, {"Widget": {"type": "object", "properties": {"id": {}, "size": {}}, "required": ["id"]}})
        head = document(paths, {"Widget": {"type": "object", "properties": {"id": {}, "size": {}}, "required": ["id", "size"]}})
        rows, lines = rows_for(base, head)
        badge = rows[0].badges[0]
        self.assertEqual((rows[0].label, badge.text, badge.breaking), ("POST /widgets", "size now required", True))
        self.assertEqual(line_at(lines, badge.loc), '"size"')

    def test_a_required_parameter_added_to_an_existing_operation(self) -> None:
        base = document({**FILLER, "/widgets": {"get": operation("listWidgets")}}, {})
        head = document({**FILLER, "/widgets": {"get": operation("listWidgets", [{"name": "kind", "in": "query", "required": True}])}}, {})
        rows, lines = rows_for(base, head)
        badge = rows[0].badges[0]
        self.assertEqual((rows[0].label, badge.text, badge.breaking), ("GET /widgets", "kind now required", True))
        self.assertEqual(line_at(lines, badge.loc), '"name": "kind",')

    def test_a_schema_no_operation_uses_gets_its_own_row(self) -> None:
        base = document({**FILLER}, {"Orphan": {"properties": {"id": {}}}})
        head = document({**FILLER}, {"Orphan": {"properties": {"id": {}, "note": {}}}})
        rows, _ = rows_for(base, head)
        self.assertEqual([(r.kind, r.label, [b.text for b in r.badges]) for r in rows], [("schema", "Orphan", ["note added"])])

    def test_a_change_the_diff_does_not_show_links_to_the_file(self) -> None:
        contract = {"path": SPEC, "removals": [], "newly_required": [], "added": {"operations": [
            {"method": "GET", "path": "/gone", "operation_id": "gone"}]}, "changed": {}}
        rows = contract_rows(contract, [], SPEC)
        html = contract_block(rows, link, file_link, [])
        self.assertIn(f'<a href="{SPEC}"><code>GET /gone</code></a>', html)

    def test_no_changes_is_a_sentence(self) -> None:
        self.assertEqual(contract_block([], link, file_link, []), "No API or database changes")

    def test_an_unchecked_side_is_named(self) -> None:
        self.assertEqual(contract_block([], link, file_link, ["API"]), "No database changes. API changes not checked")
        self.assertEqual(contract_block([], link, file_link, ["API", "database"]), "API and database changes not checked")

    def test_the_block_lists_each_row_with_linked_badges(self) -> None:
        base = document({**FILLER}, {})
        head = document({**FILLER, "/widgets": {"get": operation("listWidgets")}}, {})
        rows, lines = rows_for(base, head)
        html = contract_block(rows, link, file_link, [])
        side, number = rows[0].loc
        self.assertEqual(html, '<ul class="contract">\n'
                               f'<li><a href="{SPEC}#{side}{number}"><code>GET /widgets</code></a> · <a href="{SPEC}#{side}{number}">new</a></li>\n</ul>')

    def test_a_long_list_is_cut_with_a_count(self) -> None:
        base = document({}, {})
        head = document({f"/w{i:02d}": {"get": operation(f"op{i}")} for i in range(15)}, {})
        rows, _ = rows_for(base, head)
        html = contract_block(rows, link, file_link, [])
        self.assertEqual(html.count("<li>"), 13)
        self.assertIn("<li>+3 more</li>", html)


def migration_lines(sql: str) -> list:
    return file_diff_lines(make_diff(MIGRATION, "", sql), MIGRATION)


class Migrations(unittest.TestCase):
    def rows(self, sql: str) -> list[tuple[str, list[tuple[str, bool]]]]:
        return [(r.label, [(b.text, b.breaking) for b in r.badges]) for r in migration_rows({MIGRATION: migration_lines(sql)})]

    def test_create_and_alter_statements_group_by_table(self) -> None:
        sql = ("CREATE TABLE orders (id uuid PRIMARY KEY);\n"
               "ALTER TABLE customers ADD COLUMN region text;\n"
               "ALTER TABLE customers DROP COLUMN legacy;\n"
               "CREATE INDEX idx_orders_id ON orders (id);\n")
        self.assertEqual(self.rows(sql), [
            ("orders", [("CREATE TABLE", False), ("CREATE INDEX idx_orders_id", False)]),
            ("customers", [("ADD COLUMN region", False), ("DROP COLUMN legacy", True)])])

    def test_a_multi_line_alter_table_names_each_action(self) -> None:
        sql = "ALTER TABLE customers\n  ADD COLUMN region text,\n  ALTER COLUMN name SET NOT NULL;\n"
        self.assertEqual(self.rows(sql), [("customers", [("ADD COLUMN region", False), ("ALTER COLUMN name", False)])])

    def test_data_statements_and_destructive_verbs(self) -> None:
        sql = "INSERT INTO settings (k) VALUES ('a');\nDELETE FROM audit WHERE old;\nDROP TABLE IF EXISTS scratch;\n"
        self.assertEqual(self.rows(sql), [("settings", [("INSERT", False)]), ("audit", [("DELETE", True)]),
                                          ("scratch", [("DROP TABLE", True)])])

    def test_comments_and_quoted_names_are_handled(self) -> None:
        sql = "-- ALTER TABLE ignored DROP COLUMN x;\n/* CREATE TABLE hidden (a int); */\nCREATE TABLE \"orders\" (id int);\n"
        self.assertEqual(self.rows(sql), [("orders", [("CREATE TABLE", False)])])

    def test_the_row_links_to_the_first_statement_line(self) -> None:
        rows = migration_rows({MIGRATION: migration_lines("-- header\nCREATE TABLE orders (id int);\n")})
        self.assertEqual(rows[0].loc, ("R", 2))

    def test_a_migration_with_no_statements_has_no_rows(self) -> None:
        self.assertEqual(migration_rows({MIGRATION: migration_lines("-- nothing\n")}), [])


if __name__ == "__main__":
    unittest.main()
