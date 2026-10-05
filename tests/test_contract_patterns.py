"""Tests for the pattern lines of the Contract section. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from contract_block import file_diff_lines  # noqa: E402
from contract_lines import ADDITIVE, CALLERS, CONSUMERS, DEPRECATED, Line, contract_lines  # noqa: E402
from test_contract_block import SPEC, contract_of, document, make_diff  # noqa: E402
from test_contract_impact import body, operation, props, ref  # noqa: E402


def lines_for(base: dict, head: dict) -> list[Line]:
    diff = make_diff(SPEC, json.dumps(base, indent=2), json.dumps(head, indent=2))
    return contract_lines(contract_of(base, head), file_diff_lines(diff, SPEC), SPEC)


def texts(found: list[Line]) -> list[tuple[str | None, str]]:
    return [(line.impact, line.text) for line in found]


def response_paths(count: int) -> dict:
    return {f"/s{i}": {"get": operation(f"get{i}", "s-controller", response=f"S{i}")} for i in range(count)}


class Sweeps(unittest.TestCase):
    def test_one_property_added_to_nine_schemas_is_one_line_with_the_first_three_names(self) -> None:
        paths = response_paths(9)
        base = document(paths, {f"S{i}": props("id") for i in range(9)})
        head = document(paths, {f"S{i}": props("id", "visibility") for i in range(9)})
        self.assertEqual(texts(lines_for(base, head)),
                         [(ADDITIVE, "`visibility` added on 9 schemas, response only · `S0`, `S1`, `S2` +6")])

    def test_two_schemas_are_not_a_sweep(self) -> None:
        paths = response_paths(2)
        base = document(paths, {f"S{i}": props("id") for i in range(2)})
        head = document(paths, {f"S{i}": props("id", "visibility") for i in range(2)})
        self.assertEqual(texts(lines_for(base, head)),
                         [(ADDITIVE, "response: `visibility` added on `S0`"), (ADDITIVE, "response: `visibility` added on `S1`")])

    def test_the_same_change_on_different_sides_is_not_one_sweep(self) -> None:
        paths = {"/a": {"post": operation("a", request="In", response="Out")}}
        paths.update({f"/s{i}": {"get": operation(f"get{i}", response=f"S{i}")} for i in range(3)})
        base = document(paths, {"In": props("id"), "Out": props("id"), **{f"S{i}": props("id") for i in range(3)}})
        head = document(paths, {"In": props("id", "note"), "Out": props("id", "note"),
                                **{f"S{i}": props("id", "note") for i in range(3)}})
        found = texts(lines_for(base, head))
        self.assertIn((ADDITIVE, "`note` added on 4 schemas, response only · `Out`, `S0`, `S1` +1"), found)
        self.assertIn((ADDITIVE, "request: `note` added on `In`"), found)

    def test_a_response_only_required_property_across_schemas_is_additive(self) -> None:
        paths = response_paths(4)
        base = document(paths, {f"S{i}": props("id") for i in range(4)})
        head = document(paths, {f"S{i}": props("id", "owner", required=("owner",)) for i in range(4)})
        self.assertEqual(texts(lines_for(base, head)),
                         [(ADDITIVE, "`owner` added (required) on 4 schemas, response only · `S0`, `S1`, `S2` +1")])

    def test_removed_response_properties_may_break_consumers(self) -> None:
        paths = response_paths(3)
        base = document(paths, {f"S{i}": props("id", "old") for i in range(3)})
        head = document(paths, {f"S{i}": props("id") for i in range(3)})
        self.assertEqual(texts(lines_for(base, head)),
                         [(CONSUMERS, "`old` removed on 3 schemas, response only · `S0`, `S1`, `S2`")])

    def test_a_sweep_links_to_its_first_schema(self) -> None:
        paths = response_paths(3)
        base = document(paths, {f"S{i}": props("id") for i in range(3)})
        head = document(paths, {f"S{i}": props("id", "visibility") for i in range(3)})
        found = lines_for(base, head)
        self.assertEqual(found[0].path, SPEC)
        self.assertIsNotNone(found[0].loc)
        self.assertEqual([m.schema for m in found[0].members], ["S0", "S1", "S2"])


def inline_schema(*names: str, required: tuple[str, ...] = ()) -> dict:
    """A schema whose properties sit in an inline `allOf` member beside a `$ref` to a base, as a generated spec writes them."""
    return {"allOf": [ref("Base"), {"type": "object", "properties": {name: {"type": "string"} for name in names}}],
            "required": list(required)}


class RequiredWording(unittest.TestCase):
    def test_a_new_required_property_reads_added_required_never_now_required(self) -> None:
        paths = {"/i": {"post": operation("m", request="In")}}
        base = document(paths, {"In": props("a")})
        head = document(paths, {"In": props("a", "owner", required=("owner",))})
        self.assertEqual(texts(lines_for(base, head)), [(CALLERS, "request: `owner` added (required) on `In`")])

    def test_an_existing_optional_property_made_required_is_now_required(self) -> None:
        paths = {"/i": {"post": operation("m", request="In")}}
        base = document(paths, {"In": props("a", "owner")})
        head = document(paths, {"In": props("a", "owner", required=("owner",))})
        self.assertEqual(texts(lines_for(base, head)), [(CALLERS, "request: `owner` now required on `In`")])

    def test_a_property_declared_in_an_inline_all_of_member_is_new_when_the_base_lacked_it(self) -> None:
        paths = response_paths(4)
        names = {f"S{i}": inline_schema("id") for i in range(4)}
        base = document(paths, {"Base": props("kind"), **names})
        head = document(paths, {"Base": props("kind"), **{f"S{i}": inline_schema("id", "visibility", required=("visibility",)) for i in range(4)}})
        self.assertEqual(texts(lines_for(base, head)),
                         [(ADDITIVE, "`visibility` added (required) on 4 schemas, response only · `S0`, `S1`, `S2` +1")])

    def test_a_property_the_base_declared_in_an_inline_all_of_member_is_now_required(self) -> None:
        paths = response_paths(1)
        base = document(paths, {"Base": props("kind"), "S0": inline_schema("id", "visibility")})
        head = document(paths, {"Base": props("kind"), "S0": inline_schema("id", "visibility", required=("visibility",))})
        self.assertEqual(texts(lines_for(base, head)), [(ADDITIVE, "response: `visibility` now required on `S0`")])

    def test_contract_changes_lists_the_required_properties_the_base_did_not_declare(self) -> None:
        base = document({}, {"Base": props("kind"), "S": inline_schema("id", "old"), "T": props("a")})
        head = document({}, {"Base": props("kind"), "S": inline_schema("id", "old", "fresh", required=("old", "fresh")),
                             "T": props("a", "b", required=("b",))})
        self.assertEqual(contract_of(base, head)["added_required"], ["S.fresh", "T.b"])

    def test_a_required_parameter_added_reads_added_required(self) -> None:
        base = document({"/r": {"get": operation("g")}}, {})
        head = document({"/r": {"get": operation("g", parameters=[{"name": "kind", "in": "query", "required": True}])}}, {})
        self.assertEqual(texts(lines_for(base, head)), [(CALLERS, "`kind` parameter added (required) to `GET /r`")])


class Moves(unittest.TestCase):
    def test_a_removed_and_an_added_operation_with_a_similar_path_are_one_move(self) -> None:
        base = document({"/api/old-widgets/{id}": {"get": operation("a", "w-controller")}}, {})
        head = document({"/api/widgets/{id}": {"get": operation("b", "w-controller")}}, {})
        self.assertEqual(texts(lines_for(base, head)), [(CALLERS, "`/api/old-widgets/{id}` → `/api/widgets/{id}`")])

    def test_the_same_operation_id_is_a_move_whatever_the_path(self) -> None:
        base = document({"/a/list": {"get": operation("listThings")}}, {})
        head = document({"/b/everything": {"get": operation("listThings")}}, {})
        self.assertEqual(texts(lines_for(base, head)), [(CALLERS, "`/a/list` → `/b/everything`")])

    def test_a_different_verb_or_a_longer_path_is_not_a_move(self) -> None:
        base = document({"/api/widgets/{id}": {"get": operation("a")}}, {})
        head = document({"/api/widgets/{id}/archive": {"get": operation("b")}}, {})
        self.assertEqual(texts(lines_for(base, head)),
                         [(CALLERS, "`GET /api/widgets/{id}` removed"), (ADDITIVE, "new `GET /api/widgets/{id}/archive`")])

    def test_moves_that_only_change_a_prefix_are_one_line(self) -> None:
        base = document({f"/api/v1/r{i}/{{id}}": {"get": operation(f"g{i}", "r-controller")} for i in range(4)}, {})
        head = document({f"/api/v2/r{i}/{{id}}": {"get": operation(f"g{i}", "r-controller")} for i in range(4)}, {})
        found = lines_for(base, head)
        self.assertEqual(texts(found), [(CALLERS, "`/api/v1/*` → `/api/v2/*`, 4 endpoints")])
        self.assertEqual(len(found[0].members), 4)


class Families(unittest.TestCase):
    def test_new_operations_under_one_base_path_are_one_line_with_the_new_schema_count(self) -> None:
        paths = {"/api/widgets": {"get": operation("list", "widget-controller", response="Widget"),
                                  "post": operation("make", "widget-controller", request="WidgetRequest", response="Widget")},
                 "/api/widgets/{id}": {"patch": operation("edit", "widget-controller", request="WidgetRequest", response="Widget")}}
        base = document({}, {})
        head = document(paths, {"Widget": props("id"), "WidgetRequest": props("name")})
        found = lines_for(base, head)
        self.assertEqual(texts(found), [(ADDITIVE, "new `/api/widgets` GET POST PATCH · 2 new schemas")])
        self.assertEqual({m.tag for m in found[0].members}, {"widget-controller"})

    def test_a_lone_new_operation_names_its_verb_and_path(self) -> None:
        base = document({}, {})
        head = document({"/api/widgets/{id}/archive": {"post": operation("a", "widget-controller")}}, {})
        self.assertEqual(texts(lines_for(base, head)), [(ADDITIVE, "new `POST /api/widgets/{id}/archive`")])

    def test_two_controllers_make_two_families(self) -> None:
        base = document({}, {})
        head = document({"/api/a": {"get": operation("a", "a-controller")}, "/api/a/x": {"get": operation("ax", "a-controller")},
                         "/api/b": {"get": operation("b", "b-controller")}, "/api/b/y": {"post": operation("by", "b-controller")}}, {})
        self.assertEqual(texts(lines_for(base, head)),
                         [(ADDITIVE, "new `/api/a` GET"), (ADDITIVE, "new `/api/b` GET POST")])

    def test_removed_operations_under_one_base_path_are_one_line(self) -> None:
        base = document({"/api/widgets": {"get": operation("a", "w"), "post": operation("b", "w")}}, {})
        head = document({}, {})
        self.assertEqual(texts(lines_for(base, head)), [(CALLERS, "removed `/api/widgets` GET POST")])

    def test_deprecated_operations_have_their_own_level(self) -> None:
        base = document({"/old": {"get": operation("a")}}, {})
        head = document({"/old": {"get": operation("a", deprecated=True)}}, {})
        self.assertEqual(texts(lines_for(base, head)), [(DEPRECATED, "`GET /old` deprecated")])


class ParameterSweeps(unittest.TestCase):
    def paged(self, count: int, names: tuple[str, ...]) -> tuple[dict, dict]:
        base = document({f"/r{i}": {"get": operation(f"g{i}")} for i in range(count)}, {})
        parameters = [{"name": n, "in": "query", "schema": {"type": "integer"}} for n in names]
        head = document({f"/r{i}": {"get": operation(f"g{i}", parameters=parameters)} for i in range(count)}, {})
        return base, head

    def test_page_size_and_sort_added_to_many_operations_are_one_pagination_line(self) -> None:
        self.assertEqual(texts(lines_for(*self.paged(5, ("page", "size", "sort")))),
                         [(ADDITIVE, "pagination added to 5 endpoints")])

    def test_pagination_on_two_operations_stays_one_line_per_parameter(self) -> None:
        found = texts(lines_for(*self.paged(2, ("page",))))
        self.assertEqual(found, [(ADDITIVE, "`page` parameter added to `GET /r0`"), (ADDITIVE, "`page` parameter added to `GET /r1`")])

    def test_another_parameter_on_three_operations_is_one_line(self) -> None:
        self.assertEqual(texts(lines_for(*self.paged(3, ("kind",)))), [(ADDITIVE, "`kind` parameter added to 3 endpoints")])

    def test_a_required_parameter_added_to_one_operation_makes_callers_change(self) -> None:
        base = document({"/r": {"get": operation("g")}}, {})
        head = document({"/r": {"get": operation("g", parameters=[{"name": "kind", "in": "query", "required": True}])}}, {})
        self.assertEqual(texts(lines_for(base, head)), [(CALLERS, "`kind` parameter added (required) to `GET /r`")])

    def test_a_parameter_made_required_and_a_changed_type(self) -> None:
        optional = {"name": "kind", "in": "query", "schema": {"type": "string"}}
        base = document({"/r": {"get": operation("g", parameters=[optional])}}, {})
        head = document({"/r": {"get": operation("g", parameters=[{**optional, "required": True, "schema": {"type": "integer"}}])}}, {})
        found = {text for _, text in texts(lines_for(base, head))}
        self.assertEqual(found, {"`kind` parameter now required on `GET /r`", "`kind` parameter type changed on `GET /r`"})

    def test_parameters_of_a_new_operation_are_not_listed(self) -> None:
        base = document({}, {})
        head = document({"/r": {"get": operation("g", "r-controller", parameters=[{"name": "kind", "in": "query"}])}}, {})
        self.assertEqual(texts(lines_for(base, head)), [(ADDITIVE, "new `GET /r`")])


class EnumsAndTheRest(unittest.TestCase):
    def test_an_added_enum_value_is_a_line_that_links_to_its_entry(self) -> None:
        base = document({}, {"Kind": {"type": "string", "enum": ["A"]}})
        head = document({}, {"Kind": {"type": "string", "enum": ["A", "B", "C"]}})
        found = lines_for(base, head)
        self.assertEqual(texts(found), [(ADDITIVE, "`Kind` + `B`, `C`")])
        self.assertEqual(found[0].loc[0], "R")

    def test_a_property_enum_names_the_property(self) -> None:
        base = document({}, {"Item": {"properties": {"kind": {"type": "string", "enum": ["A"]}}}})
        head = document({}, {"Item": {"properties": {"kind": {"type": "string", "enum": ["A", "B"]}}}})
        self.assertEqual(texts(lines_for(base, head)), [(ADDITIVE, "`Item.kind` + `B`")])

    def test_a_removed_enum_value_on_a_request_makes_callers_change(self) -> None:
        paths = {"/i": {"post": operation("m", request="Item")}}
        item = lambda values: {"Item": {"properties": {"kind": {"type": "string", "enum": values}}}}  # noqa: E731
        self.assertEqual(texts(lines_for(document(paths, item(["A", "B"])), document(paths, item(["A"])))),
                         [(CALLERS, "`Item.kind` value `B` removed")])

    def test_lines_are_sorted_worst_first_and_nothing_is_capped(self) -> None:
        base = document({"/gone": {"get": operation("g")}, **{f"/p{i}": {"get": operation(f"p{i}", response=f"P{i}")} for i in range(30)}},
                        {f"P{i}": props("a") for i in range(30)})
        head = document({f"/p{i}": {"get": operation(f"p{i}", response=f"P{i}")} for i in range(30)},
                        {f"P{i}": props("a", f"extra{i}") for i in range(30)})
        found = lines_for(base, head)
        self.assertEqual(len(found), 31)
        self.assertEqual([line.impact for line in found], [CALLERS] + [ADDITIVE] * 30)

    def test_a_change_to_a_request_body_of_an_operation_may_break_consumers(self) -> None:
        base = document({"/i": {"post": operation("m", request="A")}}, {"A": props("x"), "B": props("x")})
        head = document({"/i": {"post": operation("m", request="B")}}, {"A": props("x"), "B": props("x")})
        self.assertEqual(texts(lines_for(base, head)), [(CONSUMERS, "`POST /i` request body changed")])

    def test_nothing_changed_is_no_lines(self) -> None:
        doc = document({"/i": {"get": operation("g")}}, {})
        self.assertEqual(lines_for(doc, doc), [])


if __name__ == "__main__":
    unittest.main()
