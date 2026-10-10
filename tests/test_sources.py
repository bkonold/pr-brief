"""Tests for finding the source of contract and data lines, and the file sets built from them. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import render  # noqa: E402
from contract_lines import Line, Member, Source, contract_lines  # noqa: E402
from diff_lines import file_diff_lines  # noqa: E402
from sources import SourceFinder, table_name  # noqa: E402
from contract_fixtures import SPEC, contract_of, document, make_diff  # noqa: E402
from test_contract_impact import operation, props  # noqa: E402

CUSTOMER = "app/models/frontend/Customer.java"
STATUS = "app/models/frontend/CustomerStatus.java"
CONTROLLER = "app/controllers/CustomerController.java"
ENTITY = "app/models/backend/CustomerBE.java"
MIGRATION = "db/V9__customers.sql"

RECORD_BEFORE = "package x;\n\npublic record Customer(\n    String name,\n    String email) {\n}\n"
RECORD_AFTER = "package x;\n\npublic record Customer(\n    String name,\n    String nickname,\n    String email) {\n}\n"
CONTROLLER_BEFORE = """@RestController class CustomerController {
  @GetMapping("/customers")
  List<Customer> list() {
    return service.list();
  }
}
"""
CONTROLLER_AFTER = """@RestController class CustomerController {
  @GetMapping("/customers")
  List<Customer> list() {
    return service.list();
  }

  @PostMapping("/customers")
  Customer makeCustomer(CustomerRequest request) {
    return service.makeCustomer(request);
  }
}
"""


def finder(files: dict[str, tuple[str, str]], **more) -> SourceFinder:
    diff = "\n".join(make_diff(path, before, after) for path, (before, after) in files.items())
    return SourceFinder(diff, list(files), **more)


def headed(files: dict[str, tuple[str, str]], **more) -> SourceFinder:
    return finder(files, read=lambda path: files[path][1] if path in files else None, **more)


def member(**fields) -> Member:
    return Member(**fields)


class Properties(unittest.TestCase):
    def test_an_added_property_is_the_added_component_line(self) -> None:
        found = finder({CUSTOMER: (RECORD_BEFORE, RECORD_AFTER)}).member(member(schema="Customer", kind="property_added", name="nickname"))
        self.assertEqual(found, Source(CUSTOMER, "R", 5))

    def test_a_removed_property_is_the_removed_line_of_the_old_file(self) -> None:
        found = finder({CUSTOMER: (RECORD_AFTER, RECORD_BEFORE)}).member(member(schema="Customer", kind="property_removed", name="nickname"))
        self.assertEqual(found, Source(CUSTOMER, "L", 5))

    def test_a_field_with_annotations_and_an_initializer_is_found(self) -> None:
        before = "class Customer {\n  private String name;\n}\n"
        after = "class Customer {\n  private String name;\n  @Size(max = 9) private Integer visits = 0;\n}\n"
        found = finder({CUSTOMER: (before, after)}).member(member(schema="Customer", kind="property_added", name="visits"))
        self.assertEqual(found, Source(CUSTOMER, "R", 3))

    def test_a_changed_property_falls_back_to_the_unchanged_declaration(self) -> None:
        before = "record Customer(\n    @Size(max = 5)\n    String name) {\n}\n"
        after = "record Customer(\n    @Size(max = 9)\n    String name) {\n}\n"
        found = finder({CUSTOMER: (before, after)}).member(member(schema="Customer", kind="property_constraint_changed", name="name"))
        self.assertEqual(found, Source(CUSTOMER, "R", 3))

    def test_a_call_that_names_the_property_is_not_its_declaration(self) -> None:
        after = "class Customer {\n  void f() {\n    return nickname;\n    use(nickname);\n  }\n}\n"
        self.assertIsNone(finder({CUSTOMER: ("class Customer {\n}\n", after)}).member(
            member(schema="Customer", kind="property_added", name="nickname")))

    def test_a_schema_that_no_changed_file_declares_has_no_source(self) -> None:
        self.assertIsNone(finder({CUSTOMER: (RECORD_BEFORE, RECORD_AFTER)}).member(
            member(schema="Order", kind="property_added", name="nickname")))

    def test_a_schema_that_two_changed_files_declare_is_not_guessed(self) -> None:
        files = {"app/models/frontend/Holder.java": ("record Holder(\n    String a) {}\n", RECORD_AFTER),
                 "app/dto/Other.java": (RECORD_BEFORE, RECORD_AFTER)}
        self.assertIsNone(finder(files).member(member(schema="Customer", kind="property_added", name="nickname")))

    def test_a_record_nested_in_another_model_file_is_found_there(self) -> None:
        holder = "app/models/frontend/CustomerRows.java"
        before = "record CustomerRows(\n    List<Row> rows) {\n  record Row(\n      String name) {}\n}\n"
        after = before.replace("      String name)", "      String name,\n      Optional<String> nickname)")
        found = finder({holder: (before, after)}).member(member(schema="Row", kind="property_added", name="nickname"))
        self.assertEqual(found, Source(holder, "R", 5))

    def test_a_nested_record_that_two_files_declare_is_not_guessed(self) -> None:
        before = "record Outer(\n    String a) {\n  record Row(\n      String name) {}\n}\n"
        after = before.replace("      String name)", "      String name,\n      String nickname)")
        files = {"app/models/frontend/One.java": (before, after), "app/models/frontend/Two.java": (before, after)}
        self.assertIsNone(finder(files).member(member(schema="Row", kind="property_added", name="nickname")))

    def test_a_test_file_is_never_a_source(self) -> None:
        test = "app/models/frontend/CustomerTest.java"
        self.assertIsNone(finder({test: (RECORD_BEFORE.replace("Customer", "CustomerTest"), RECORD_AFTER.replace("Customer", "CustomerTest"))}).member(
            member(schema="CustomerTest", kind="property_added", name="nickname")))

    def test_a_model_is_found_in_any_directory(self) -> None:
        elsewhere = "app/dto/Customer.java"
        found = finder({elsewhere: (RECORD_BEFORE, RECORD_AFTER)}).member(
            member(schema="Customer", kind="property_added", name="nickname"))
        self.assertEqual(found, Source(elsewhere, "R", 5))


class Schemas(unittest.TestCase):
    def test_an_added_schema_is_its_record_line(self) -> None:
        found = finder({CUSTOMER: ("", RECORD_AFTER)}).member(member(schema="Customer", kind="schema_added"))
        self.assertEqual(found, Source(CUSTOMER, "R", 3))

    def test_a_removed_schema_is_its_removed_record_line(self) -> None:
        found = finder({CUSTOMER: (RECORD_BEFORE, "")}).member(member(schema="Customer", kind="schema_removed"))
        self.assertEqual(found, Source(CUSTOMER, "L", 3))

    def test_a_class_declaration_counts_as_well(self) -> None:
        found = finder({CUSTOMER: ("", "public class Customer {\n}\n")}).member(member(schema="Customer", kind="schema_added"))
        self.assertEqual(found, Source(CUSTOMER, "R", 1))


class EnumValues(unittest.TestCase):
    ENUM_BEFORE = "enum CustomerStatus {\n  ACTIVE,\n  CLOSED\n}\n"
    ENUM_AFTER = "enum CustomerStatus {\n  ACTIVE,\n  PAUSED,\n  CLOSED\n}\n"

    def test_the_constant_is_found_in_the_file_named_for_the_property(self) -> None:
        found = finder({STATUS: (self.ENUM_BEFORE, self.ENUM_AFTER)}).member(
            member(schema="Customer", kind="enum_added", name="status", value="PAUSED"))
        self.assertEqual(found, Source(STATUS, "R", 3))

    def test_a_removed_constant_is_the_removed_line(self) -> None:
        found = finder({STATUS: (self.ENUM_AFTER, self.ENUM_BEFORE)}).member(
            member(schema="Customer", kind="enum_removed", name="status", value="PAUSED"))
        self.assertEqual(found, Source(STATUS, "L", 3))

    def test_a_constant_with_arguments_and_a_semicolon_is_found(self) -> None:
        before = "enum Kind {\n  A(1);\n}\n"
        after = "enum Kind {\n  A(1),\n  B(2);\n}\n"
        found = finder({"app/models/frontend/Kind.java": (before, after)}).member(
            member(schema="Kind", kind="enum_added", value="B"))
        self.assertEqual(found, Source("app/models/frontend/Kind.java", "R", 3))

    def test_a_constant_that_two_unrelated_files_declare_is_not_guessed(self) -> None:
        before, after = "enum E {\n  A\n}\n", "enum E {\n  A,\n  NEW\n}\n"
        found = finder({"app/models/frontend/One.java": (before, after), "app/models/frontend/Two.java": (before, after)}).member(
            member(schema="Customer", kind="enum_added", name="mood", value="NEW"))
        self.assertIsNone(found)

    def test_a_removed_constant_is_found_in_an_enum_outside_the_model_directory(self) -> None:
        path = "app/models/shared/enums/Kind.java"
        found = finder({path: ("enum Kind {\n  ENUM,\n  DECIMAL\n}\n", "enum Kind {\n  ENUM\n}\n")}).member(
            member(schema="Kind", kind="enum_removed", value="DECIMAL"))
        self.assertEqual(found, Source(path, "L", 3))

    def test_the_schemas_own_file_wins_over_other_files(self) -> None:
        both = {CUSTOMER: ("enum Customer {\n  A\n}\n", "enum Customer {\n  A,\n  NEW\n}\n"),
                STATUS: ("enum S {\n  A\n}\n", "enum S {\n  A,\n  NEW\n}\n")}
        self.assertEqual(finder(both).member(member(schema="Customer", kind="enum_added", value="NEW")), Source(CUSTOMER, "R", 3))


class Operations(unittest.TestCase):
    def test_an_added_operation_is_its_mapping_line_when_the_diff_shows_it(self) -> None:
        found = headed({CONTROLLER: (CONTROLLER_BEFORE, CONTROLLER_AFTER)}).member(
            member(operation="POST /customers", kind="operation_added", operation_id="makeCustomer"))
        self.assertEqual(found, Source(CONTROLLER, "R", 7))

    def test_the_declaration_is_used_when_no_mapping_sits_above_it(self) -> None:
        before = "@RestController class C {\n  void keep() {\n  }\n}\n"
        after = "@RestController class C {\n  void keep() {\n  }\n\n  Customer makeCustomer(Req r) {\n  }\n}\n"
        found = headed({CONTROLLER: (before, after)}).member(
            member(operation="POST /x", kind="operation_added", operation_id="makeCustomer"))
        self.assertEqual(found, Source(CONTROLLER, "R", 5))

    def test_removed_lines_between_the_mapping_and_an_added_declaration_are_skipped(self) -> None:
        before = '@RestController class C {\n  @GetMapping("/rows")\n  @Permission(X)\n  Rows rows() {\n    return a();\n  }\n}\n'
        after = '@RestController class C {\n  @GetMapping("/rows")\n  @Permission(X)\n  Rows rows(\n      @RequestParam Kind kind) {\n    return a(kind);\n  }\n}\n'
        found = headed({CONTROLLER: (before, after)}).member(member(operation="GET /rows", kind="operation_changed", operation_id="rows"))
        self.assertEqual(found, Source(CONTROLLER, "R", 2))

    def test_an_overload_suffix_is_dropped_from_the_operation_id(self) -> None:
        found = headed({CONTROLLER: (CONTROLLER_BEFORE, CONTROLLER_AFTER)}).member(
            member(operation="POST /customers", kind="operation_added", operation_id="makeCustomer_1"))
        self.assertEqual(found, Source(CONTROLLER, "R", 7))

    def test_a_removed_operation_is_the_removed_mapping_line(self) -> None:
        found = headed({CONTROLLER: (CONTROLLER_AFTER, CONTROLLER_BEFORE)}).member(
            member(operation="POST /customers", kind="operation_removed", operation_id="makeCustomer"))
        self.assertEqual(found, Source(CONTROLLER, "L", 7))

    def test_a_changed_operation_is_found_on_a_kept_declaration_with_a_changed_mapping(self) -> None:
        before = CONTROLLER_BEFORE
        after = CONTROLLER_BEFORE.replace('@GetMapping("/customers")', '@GetMapping("/clients")')
        found = headed({CONTROLLER: (before, after)}).member(
            member(operation="GET /clients", kind="operation_changed", operation_id="list"))
        self.assertEqual(found, Source(CONTROLLER, "R", 2))

    def test_a_call_to_the_method_is_not_its_declaration(self) -> None:
        before = "@RestController class C {\n  void keep() {\n  }\n}\n"
        after = "@RestController class C {\n  void keep() {\n    audit(x);\n    return audit(x);\n    var y = audit(x);\n  }\n}\n"
        found = headed({CONTROLLER: (before, after)}).member(
            member(operation="GET /x", kind="operation_added", operation_id="audit"))
        self.assertIsNone(found)

    def test_an_operation_without_an_id_has_no_source(self) -> None:
        self.assertIsNone(headed({CONTROLLER: (CONTROLLER_BEFORE, CONTROLLER_AFTER)}).member(
            member(operation="POST /customers", kind="operation_added")))

    def test_a_method_in_a_class_that_is_not_a_controller_is_not_a_source(self) -> None:
        service = "app/services/CustomerService.java"
        plain = CONTROLLER_BEFORE.replace("@RestController ", ""), CONTROLLER_AFTER.replace("@RestController ", "")
        self.assertIsNone(headed({service: plain}).member(
            member(operation="POST /customers", kind="operation_added", operation_id="makeCustomer")))

    def test_a_controller_is_recognised_by_the_file_at_the_head_commit_when_the_diff_lacks_the_annotation(self) -> None:
        before = "class C {\n  void keep() {\n  }\n}\n"
        after = "class C {\n  void keep() {\n  }\n\n  Customer makeCustomer(Req r) {\n  }\n}\n"
        head = "@RestController\n" + after
        found = finder({CONTROLLER: (before, after)}, read=lambda path: head).member(
            member(operation="POST /x", kind="operation_added", operation_id="makeCustomer"))
        self.assertEqual(found, Source(CONTROLLER, "R", 5))

    def test_a_controller_advice_is_not_a_controller(self) -> None:
        advice = CONTROLLER_AFTER.replace("@RestController", "@ControllerAdvice")
        self.assertIsNone(headed({CONTROLLER: (CONTROLLER_BEFORE.replace("@RestController", "@ControllerAdvice"), advice)}).member(
            member(operation="POST /customers", kind="operation_added", operation_id="makeCustomer")))

    def test_a_controller_test_under_the_controller_path_is_not_a_source(self) -> None:
        test = "app/controllers/CustomerControllerTest.java"
        self.assertIsNone(finder({test: (CONTROLLER_BEFORE, CONTROLLER_AFTER)}).member(
            member(operation="POST /customers", kind="operation_added", operation_id="makeCustomer")))

    def test_a_controller_is_found_in_any_directory(self) -> None:
        elsewhere = "app/web/CustomerController.java"
        found = headed({elsewhere: (CONTROLLER_BEFORE, CONTROLLER_AFTER)}).member(
            member(operation="POST /customers", kind="operation_added", operation_id="makeCustomer"))
        self.assertEqual(found, Source(elsewhere, "R", 7))


ENTITY_BEFORE = '@Entity\n@Table(name = "customers")\nclass CustomerBE {\n  String name;\n}\n'
ENTITY_AFTER = ENTITY_BEFORE + "  String nickname;\n"


class Entities(unittest.TestCase):
    def data_line(self, table: str) -> Line:
        return Line("additive", "t", MIGRATION, ("R", 1), [Member(file=MIGRATION, table=table)])

    def test_the_table_annotation_in_the_diff_is_the_entity_source(self) -> None:
        after = ENTITY_BEFORE.replace("class", "// c\nclass")
        found = finder({ENTITY: (ENTITY_BEFORE, after)}).data(self.data_line("customers"))
        self.assertEqual(found, [Source(ENTITY, "R", 2)])

    def test_an_annotation_the_diff_does_not_show_is_read_from_the_head_file(self) -> None:
        padding = "".join(f"  String f{i};\n" for i in range(10))
        before = ENTITY_BEFORE.replace("  String name;\n", "  String name;\n" + padding)
        after = before.replace("  String f9;\n", "  String f9;\n  String nickname;\n")
        found = finder({ENTITY: (before, after)}, read=lambda path: after if path == ENTITY else None).data(self.data_line("customers"))
        self.assertEqual(found, [Source(ENTITY, "R", 2)])
        self.assertEqual(finder({ENTITY: (before, after)}).data(self.data_line("customers")), [])

    def test_a_table_no_changed_entity_names_has_no_source(self) -> None:
        self.assertEqual(finder({ENTITY: (ENTITY_BEFORE, ENTITY_BEFORE + "// x\n")}).data(self.data_line("orders")), [])

    def test_the_table_is_compared_without_its_schema_quotes_or_case(self) -> None:
        self.assertEqual(table_name('"public"."Customers"'), "customers")
        quoted = ENTITY_BEFORE.replace('"customers"', '"Customers"')
        found = finder({ENTITY: (quoted, quoted + "// x\n")}, read=lambda path: quoted).data(self.data_line("public.customers"))
        self.assertEqual(found, [Source(ENTITY, "R", 2)])

    def test_a_deleted_entity_is_found_on_its_removed_line(self) -> None:
        self.assertEqual(finder({ENTITY: (ENTITY_BEFORE, "")}).data(self.data_line("customers")), [Source(ENTITY, "L", 2)])

    def test_a_line_with_no_table_has_no_source(self) -> None:
        self.assertEqual(finder({ENTITY: (ENTITY_BEFORE, ENTITY_BEFORE + "// x\n")}).data(
            Line(None, "DO block", MIGRATION, ("R", 1), [Member(file=MIGRATION)])), [])


SDK = "web/sdk/generated.ts"
SDK_BEFORE = """export const DynamicAttributeDataType = {
  ENUM: "ENUM",
  INTEGER: "INTEGER",
  DECIMAL: "DECIMAL",
} as const;
export type DynamicAttributeDataType =
  (typeof DynamicAttributeDataType)[keyof typeof DynamicAttributeDataType];

export interface DynamicAttributeDefinition {
  name: string;
  dataType: DynamicAttributeDataType;
  dynamicAttributes: Record<string, DynamicAttributeDefinition[]>;
}

export interface Other {
  dataType: string;
}

export const operations = {
  inventory: {
    getProductInventoryForecast: (
      query: {
        id: string;
      },
    ) => request(),
  },
};
"""
SDK_AFTER = SDK_BEFORE.replace('  DECIMAL: "DECIMAL",\n', "").replace("  name: string;\n", "  name: string;\n  label: string;\n")
SDK_FILES = {SDK: (SDK_BEFORE, SDK_AFTER)}


class GeneratedClient(unittest.TestCase):
    def sdk(self, files=None, **member_fields) -> Source | None:
        return finder(files or SDK_FILES, sdk_dir="web/sdk/").sdk_member(member(**member_fields))

    def test_a_removed_enum_value_is_the_removed_row_of_the_old_file(self) -> None:
        self.assertEqual(self.sdk(schema="DynamicAttributeDataType", kind="enum_removed", value="DECIMAL"), Source(SDK, "L", 4))

    def test_a_schema_is_its_export_line(self) -> None:
        found = self.sdk({SDK: ("", SDK_BEFORE)}, schema="DynamicAttributeDefinition", kind="schema_added")
        self.assertEqual(found, Source(SDK, "R", 9))

    def test_a_removed_schema_is_the_removed_export_line(self) -> None:
        found = self.sdk({SDK: (SDK_BEFORE, "")}, schema="Other", kind="schema_removed")
        self.assertEqual(found, Source(SDK, "L", 15))

    def test_a_property_is_its_row_inside_the_interface_of_the_schema(self) -> None:
        found = self.sdk({SDK: ("", SDK_BEFORE)}, schema="DynamicAttributeDefinition", kind="property_added", name="dataType")
        self.assertEqual(found, Source(SDK, "R", 11))

    def test_a_property_of_another_interface_is_not_matched(self) -> None:
        found = self.sdk({SDK: ("", SDK_BEFORE)}, schema="Other", kind="property_added", name="dynamicAttributes")
        self.assertIsNone(found)

    def test_an_added_property_is_found_in_the_diff(self) -> None:
        found = self.sdk(schema="DynamicAttributeDefinition", kind="property_added", name="label")
        self.assertEqual(found, Source(SDK, "R", 10))

    def test_a_property_the_diff_does_not_show_is_read_from_the_head_file(self) -> None:
        files = {SDK: ("// a\n" * 20 + SDK_BEFORE, "// a\n" * 20 + SDK_BEFORE + "// z\n")}
        found = finder(files, sdk_dir="web/sdk/", read=lambda path: files[path][1]).sdk_member(
            member(schema="DynamicAttributeDefinition", kind="property_added", name="dataType"))
        self.assertEqual(found, Source(SDK, "R", 31))
        self.assertIsNone(finder(files, sdk_dir="web/sdk/").sdk_member(
            member(schema="DynamicAttributeDefinition", kind="property_added", name="dataType")))

    def test_an_operation_is_its_member_line(self) -> None:
        found = self.sdk({SDK: ("", SDK_BEFORE)}, operation="GET /inventory", kind="operation_added", operation_id="getProductInventoryForecast")
        self.assertEqual(found, Source(SDK, "R", 21))

    def test_an_overload_suffix_is_dropped_from_the_operation_id(self) -> None:
        found = self.sdk({SDK: ("", SDK_BEFORE)}, operation="GET /inventory", kind="operation_added", operation_id="getProductInventoryForecast_1")
        self.assertEqual(found, Source(SDK, "R", 21))

    def test_a_test_file_of_the_client_is_ignored(self) -> None:
        path = "web/sdk/generated.test.ts"
        self.assertIsNone(self.sdk({path: (SDK_BEFORE, SDK_AFTER)}, schema="DynamicAttributeDataType", kind="enum_removed", value="DECIMAL"))

    def test_a_file_outside_the_client_directory_is_ignored(self) -> None:
        path = "web/app/generated.ts"
        self.assertIsNone(self.sdk({path: (SDK_BEFORE, SDK_AFTER)}, schema="DynamicAttributeDataType", kind="enum_removed", value="DECIMAL"))

    def test_without_a_client_directory_there_is_no_client_source(self) -> None:
        self.assertIsNone(finder(SDK_FILES).sdk_member(member(schema="DynamicAttributeDataType", kind="enum_removed", value="DECIMAL")))

    def test_a_contract_line_lists_the_java_source_before_the_client_source(self) -> None:
        java = "app/models/shared/enums/DynamicAttributeDataType.java"
        files = {java: ("enum DynamicAttributeDataType {\n  ENUM,\n  DECIMAL\n}\n", "enum DynamicAttributeDataType {\n  ENUM\n}\n"), **SDK_FILES}
        line = Line("consumers may break", "t", SPEC, ("L", 1),
                    [member(schema="DynamicAttributeDataType", kind="enum_removed", value="DECIMAL")])
        self.assertEqual(finder(files, sdk_dir="web/sdk/").contract(line), [Source(java, "L", 3), Source(SDK, "L", 4)])


class ContractLines(unittest.TestCase):
    """The members of the lines that contract_lines builds carry what the finder needs."""

    def lines_for(self, base: dict, head: dict, java: dict[str, tuple[str, str]]) -> list[Line]:
        contract = contract_of(base, head)
        spec = make_diff(SPEC, json.dumps(base, indent=2), json.dumps(head, indent=2))
        found = headed(java)
        lines = contract_lines(contract, file_diff_lines(spec, SPEC), SPEC)
        for line in lines:
            line.sources = found.contract(line)
        return lines

    def test_an_added_property_line_gets_its_source(self) -> None:
        base = document({}, {"Customer": props("name", "email")})
        head = document({}, {"Customer": props("name", "nickname", "email")})
        (line,) = self.lines_for(base, head, {CUSTOMER: (RECORD_BEFORE, RECORD_AFTER)})
        self.assertEqual(line.sources, [Source(CUSTOMER, "R", 5)])

    def test_a_new_operation_line_gets_the_controller_source(self) -> None:
        base = document({}, {})
        head = document({"/customers": {"post": operation("makeCustomer")}}, {})
        (line,) = self.lines_for(base, head, {CONTROLLER: (CONTROLLER_BEFORE, CONTROLLER_AFTER)})
        self.assertEqual(line.sources, [Source(CONTROLLER, "R", 7)])

    def test_a_removed_operation_line_gets_the_controller_source(self) -> None:
        base = document({"/customers": {"post": operation("makeCustomer")}}, {})
        head = document({}, {})
        (line,) = self.lines_for(base, head, {CONTROLLER: (CONTROLLER_AFTER, CONTROLLER_BEFORE)})
        self.assertEqual(line.sources, [Source(CONTROLLER, "L", 7)])

    def test_a_property_swept_over_three_schemas_lists_every_schema_file(self) -> None:
        names = ("Aa", "Bb", "Cc")
        base = document({}, {n: props("id") for n in names})
        head = document({}, {n: props("id", "nickname") for n in names})
        java = {f"app/models/frontend/{n}.java": (f"record {n}(\n    String id) {{\n}}\n", f"record {n}(\n    String id,\n    String nickname) {{\n}}\n")
                for n in names}
        (line,) = self.lines_for(base, head, java)
        self.assertEqual([s.path for s in line.sources], sorted(java))


PR_PATHS = [SPEC, CUSTOMER, STATUS, CONTROLLER, ENTITY, MIGRATION, "web/Page.tsx", "app/models/frontend/Untouched.java"]
RUN = {"repo": "acme/shop", "pr": 7, "with_body": False, "variant": "brief", "pr_head_sha": "abc",
       "context": {"sections": {"contract": 0}, "dropped": {}}}
PR = {"title": "T", "body": "", "files": [{"path": p, "additions": 2, "deletions": 1, "changeType": "MODIFIED"} for p in PR_PATHS]}
DIAGRAM = "```mermaid\nflowchart LR\n  A[\"1 · Customers\"] --> B[\"Table\"]\n```"
ANSWER = {"type": "Enhancement", "description": "d", "changes_diagram": DIAGRAM, "node_files": {"A": [CUSTOMER], "B": [MIGRATION]},
          "walkthrough": [{"file": CUSTOMER, "title": "Model", "why": "w", "node": "A"},
                          {"file": MIGRATION, "title": "Table", "why": "w", "node": "A"},
                          {"file": CONTROLLER, "title": "Endpoint", "why": "w", "node": "A"}]}
BASE = document({}, {"Customer": props("name", "email")})
HEAD = document({"/customers": {"post": operation("makeCustomer")}}, {"Customer": props("name", "nickname", "email")})


class FileSets(unittest.TestCase):
    def setUp(self) -> None:
        patch = mock.patch.object(render, "MIGRATION_GLOBS", ["db/*.sql"])
        patch.start()
        self.addCleanup(patch.stop)

    def diff(self) -> str:
        return "\n".join([
            make_diff(SPEC, json.dumps(BASE, indent=2), json.dumps(HEAD, indent=2)),
            make_diff(CUSTOMER, RECORD_BEFORE, RECORD_AFTER),
            make_diff(CONTROLLER, CONTROLLER_BEFORE, CONTROLLER_AFTER),
            make_diff(ENTITY, ENTITY_BEFORE, ENTITY_AFTER),
            make_diff(MIGRATION, "", "ALTER TABLE customers ADD COLUMN nickname text;\n"),
            make_diff("app/models/frontend/Untouched.java", "a\n", "b\n"),
        ])

    def brief(self, paths=None, read=lambda path: {ENTITY: ENTITY_AFTER, CONTROLLER: CONTROLLER_AFTER}.get(path)):
        pr = PR if paths is None else {**PR, "files": [{"path": p, "additions": 1, "deletions": 0, "changeType": "MODIFIED"} for p in paths]}
        return render.build_body(RUN, pr, ANSWER, {CUSTOMER: [("R", 5, "String nickname,")]}, [], contract_of(BASE, HEAD), self.diff(), read)

    def test_the_contract_set_is_the_spec_and_the_line_sources(self) -> None:
        self.assertEqual(self.brief().file_sets["contract"], sorted([SPEC, CUSTOMER, CONTROLLER]))

    def test_a_changed_model_file_no_line_traces_to_is_not_in_the_contract_set(self) -> None:
        contract = self.brief().file_sets["contract"]
        self.assertNotIn("app/models/frontend/Untouched.java", contract)
        self.assertNotIn(STATUS, contract)

    def test_the_data_set_is_the_migrations_and_the_entity_sources(self) -> None:
        self.assertEqual(self.brief().file_sets["data"], sorted([MIGRATION, ENTITY]))

    def test_each_set_is_sorted_and_has_no_repeats(self) -> None:
        for paths in self.brief().file_sets.values():
            self.assertEqual(paths, sorted(set(paths)))

    def test_a_pr_with_no_such_files_has_two_empty_sets(self) -> None:
        brief = render.build_body(RUN, {**PR, "files": [PR["files"][6]]}, {**ANSWER, "node_files": {}, "walkthrough": [
            {"file": "web/Page.tsx", "title": "t", "why": "w"}]}, {}, [], None, "")
        self.assertEqual(brief.file_sets, {"contract": [], "data": []})

    def test_the_spec_is_in_the_set_only_when_the_pr_changes_it(self) -> None:
        brief = self.brief(paths=[CUSTOMER, MIGRATION, ENTITY, CONTROLLER])
        self.assertNotIn(SPEC, brief.file_sets["contract"])

    def test_review_json_has_the_sets_and_each_line_a_source_or_null(self) -> None:
        data = render.review_json(RUN, self.brief(), True)
        self.assertEqual(data["file_sets"], self.brief().file_sets)
        sources = {line["on"]: line["source"] for line in data["contract"]}
        self.assertEqual(sources["`Customer`"], {"path": CUSTOMER, "side": "R", "line": 5})
        listed = {line["on"]: line["sources"] for line in data["contract"]}
        self.assertEqual(listed["`Customer`"], [{"path": CUSTOMER, "side": "R", "line": 5}])
        self.assertEqual([line["sources"] for line in data["data"]], [[{"path": ENTITY, "side": "R", "line": 2}]])
        self.assertEqual([line["source"] for line in data["data"]], [{"path": ENTITY, "side": "R", "line": 2}])

    def test_a_line_nothing_in_the_pr_matches_has_a_null_source(self) -> None:
        data = render.review_json(RUN, self.brief(paths=[SPEC, MIGRATION]), True)
        self.assertEqual({line["source"] for line in data["contract"]} | {line["source"] for line in data["data"]}, {None})
        self.assertEqual([line["sources"] for line in data["contract"] + data["data"]], [[]] * len(data["contract"] + data["data"]))

    def test_the_comment_links_a_source_with_the_spec_second_and_lists_the_files(self) -> None:
        text = self.brief().body
        contract = text[text.index("<summary><strong>API</strong>"):text.index("<summary><strong>Data</strong>")]
        row = next(line for line in contract.splitlines() if "nickname" in line and line.startswith("| "))
        self.assertRegex(row, r"\[Customer\.java:5\]\(https://github\.com/acme/shop/pull/7/changes#diff-[0-9a-f]{64}R5\) · \[spec\]\(")
        listed = contract[contract.index("**API files**"):]
        for name in ("openapi.json", "Customer.java", "CustomerController.java"):
            self.assertIn(f"[{name}](", listed)
        self.assertNotIn("Untouched.java", listed)
        data = text[text.index("<summary><strong>Data</strong>"):]
        self.assertIn("**Data files** [CustomerBE.java](", data)
        self.assertIn("[V9__customers.sql](", data)

    def test_a_section_with_no_files_has_no_list(self) -> None:
        text = self.brief(paths=[MIGRATION]).body
        self.assertNotIn("Contract files", text)
        self.assertIn("**Data files** [V9__customers.sql](", text)


if __name__ == "__main__":
    unittest.main()
