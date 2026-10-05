"""Tests for placing contract and data lines in chunks and drawing the two sections. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_lines import ADDITIVE, CALLERS, CONSUMERS, CONTRACT_LEVELS, DEPRECATED, Line, Member  # noqa: E402
from data_lines import DATA_LEVELS, DESTRUCTIVE, REWRITES  # noqa: E402
from layout import DEFAULT_TAG_TEMPLATES, glance, place, pill, section, stem, tag_stems  # noqa: E402

FILES = ["api/ItemController.java", "api/models/Item.java", "db/V9__items.sql", "api/openapi.json", "web/WidgetPage.tsx"]
HELD = [{FILES[0]}, {FILES[1]}, {FILES[2]}, {FILES[3]}, {FILES[4]}]
STEMS = [{"itemcontroller"}, {"item"}, {"v9__items"}, set(), {"widgetpage"}]
CODE = {0: ["ItemController", 'path = "/items"'], 1: ["Item"], 2: ["V9__items"], 4: ["WidgetPage", 'fetch("/widgets/stats")']}


def line(text: str, impact: str | None, *members: Member, loc: tuple[str, int] | None = ("R", 3), path: str = "api/openapi.json") -> Line:
    return Line(impact, text, path, loc, list(members))


def where(lines: list[Line], **overrides) -> tuple[dict[int, list[str]], list[str]]:
    args = {"held": HELD, "stems": STEMS, "code": CODE, "preferred": set(), "templates": DEFAULT_TAG_TEMPLATES, **overrides}
    owned, loose = place(lines, **args)
    return {index: [l.text for l in found] for index, found in owned.items()}, [l.text for l in loose]


class TagFiles(unittest.TestCase):
    def test_a_tag_becomes_a_pascal_case_file_name(self) -> None:
        self.assertEqual(tag_stems("dynamic-attribute-enum-value-controller", ["{pascal}"]),
                         {"dynamicattributeenumvaluecontroller"})

    def test_templates_may_add_a_suffix_or_use_other_cases(self) -> None:
        self.assertEqual(tag_stems("item-list", ["{pascal}", "{pascal}Controller", "{camel}", "{kebab}"]),
                         {"itemlist", "itemlistcontroller", "item-list"})

    def test_a_stem_is_the_name_before_the_first_dot_in_lowercase(self) -> None:
        self.assertEqual(stem("web/ItemList.test.tsx"), "itemlist")
        self.assertEqual(stem("db/V9__items.sql"), "v9__items")


class Placement(unittest.TestCase):
    def test_an_operation_goes_to_the_chunk_holding_its_controller(self) -> None:
        owned, loose = where([line("a", CALLERS, Member(operation="POST /items", tag="item-controller"))])
        self.assertEqual((owned, loose), ({0: ["a"]}, []))

    def test_a_schema_goes_to_the_chunk_holding_the_file_named_after_it(self) -> None:
        self.assertEqual(where([line("a", CONSUMERS, Member(schema="Item"))]), ({1: ["a"]}, []))

    def test_a_migration_line_goes_to_the_chunk_holding_its_file(self) -> None:
        owned, _ = where([line("a", DESTRUCTIVE, Member(file="db/V9__items.sql", table="items"))])
        self.assertEqual(owned, {2: ["a"]})

    def test_a_subject_with_no_file_goes_to_the_chunk_whose_code_names_it(self) -> None:
        owned, loose = where([line("a", CALLERS, Member(operation="GET /widgets/stats", tag="stats-controller"))])
        self.assertEqual((owned, loose), ({4: ["a"]}, []))
        owned, _ = where([line("b", CALLERS, Member(schema="Widget"))], code={**CODE, 4: ["Widget panel"]})
        self.assertEqual(owned, {4: ["b"]})

    def test_a_probe_does_not_match_part_of_a_longer_name(self) -> None:
        owned, loose = where([line("a", CALLERS, Member(schema="Wid"))], code={**CODE, 4: ["Widget panel"]})
        self.assertEqual((owned, loose), ({}, ["a"]))

    def test_a_line_about_several_subjects_goes_where_most_of_them_do(self) -> None:
        sweep = line("sweep", ADDITIVE, Member(schema="Item"), Member(schema="Item"), Member(schema="Other"))
        self.assertEqual(where([sweep])[0], {1: ["sweep"]})

    def test_a_chunk_with_only_generated_files_owns_nothing(self) -> None:
        owned, loose = where([line("a", CALLERS, Member(schema="Spec"))], held=HELD, stems=[*STEMS[:3], {"spec"}, STEMS[4]])
        self.assertEqual((owned, loose), ({}, ["a"]))

    def test_a_line_nothing_matches_is_loose(self) -> None:
        owned, loose = where([line("a", ADDITIVE, Member(operation="GET /nowhere", tag="orphan-controller"))])
        self.assertEqual((owned, loose), ({}, ["a"]))

    def test_the_chunk_the_model_flagged_wins_a_tie(self) -> None:
        stems = [{"item"}, {"item"}, set(), set(), set()]
        self.assertEqual(where([line("a", ADDITIVE, Member(schema="Item"))], stems=stems)[0], {0: ["a"]})
        self.assertEqual(where([line("a", ADDITIVE, Member(schema="Item"))], stems=stems, preferred={1})[0], {1: ["a"]})


class Drawing(unittest.TestCase):
    def test_the_glance_line_counts_levels_worst_first_and_omits_zeros(self) -> None:
        lines = [line("a", CALLERS), line("b", CALLERS), line("c", CONSUMERS), line("d", ADDITIVE), line("e", ADDITIVE), line("f", DEPRECATED)]
        self.assertEqual(glance("Contract", lines, CONTRACT_LEVELS),
                         "Contract: 2 callers must change · 1 consumer may break · 2 additive · 1 deprecated")
        self.assertEqual(glance("Contract", [line("a", ADDITIVE)], CONTRACT_LEVELS), "Contract: 1 additive")

    def test_the_data_glance_line_counts_lines_with_no_level_as_other(self) -> None:
        lines = [line("a", DESTRUCTIVE), line("b", REWRITES), line("c", REWRITES), line("d", None)]
        self.assertEqual(glance("Data", lines, DATA_LEVELS), "Data: 1 destructive · 2 rewrite rows · 1 other")

    def test_the_top_level_is_bold_and_the_second_is_a_bold_outline(self) -> None:
        self.assertEqual(pill(CALLERS, CONTRACT_LEVELS), '<span class="pill p0"><strong>callers must change</strong></span>')
        self.assertEqual(pill(CONSUMERS, CONTRACT_LEVELS), '<span class="pill p1">consumers may break</span>')
        self.assertEqual(pill(ADDITIVE, CONTRACT_LEVELS), '<span class="pill p2">additive</span>')
        self.assertEqual(pill(None, DATA_LEVELS), "")

    def draw(self, owned, loose=()) -> str:
        return section("Contract", CONTRACT_LEVELS, owned, list(loose), lambda l: f"https://example.test/{l.loc[1]}",
                       lambda l: l.members[0].tag or "untagged", "controller")

    def test_groups_are_closed_sorted_by_worst_level_then_number_with_the_loose_group_last(self) -> None:
        owned = [(1, "Screen", [line("minor", ADDITIVE)]), (3, "Api `x`", [line("add", ADDITIVE), line("hard", CALLERS)]),
                 (2, "Model", [line("break", CONSUMERS)]), (4, "Empty", [])]
        loose = [line("odd", ADDITIVE, Member(tag="a-controller")), line("odder", CONSUMERS, Member(tag="b-controller"))]
        text = self.draw(owned, loose)
        heads = re.findall(r"<summary>(.*?)</summary>", text)
        self.assertEqual([re.sub(r"<[^>]+>", "", h) for h in heads],
                         ["3 · Api x callers must change hard +1 more", "2 · Model consumers may break break",
                          "1 · Screen additive minor", "Not in any chunk consumers may break 2 changes in 2 controllers"])
        self.assertEqual(text.count("<details>"), 4)
        self.assertNotIn("<details open", text)
        self.assertIn("3 · Api <code>x</code>", text)

    def test_a_group_lists_every_line_with_its_pill_and_link_worst_first(self) -> None:
        text = self.draw([(1, "A", [line("later", ADDITIVE, loc=("R", 9)), line("first", CALLERS, loc=("L", 4))])])
        items = re.findall(r"<li>(.*?)</li>", text)
        self.assertEqual(items, ['<span class="pill p0"><strong>callers must change</strong></span> <a href="https://example.test/4">first</a>',
                                 '<span class="pill p2">additive</span> <a href="https://example.test/9">later</a>'])

    def test_a_line_with_no_level_has_no_pill(self) -> None:
        self.assertIn("<li><a href=", self.draw([(1, "A", [line("other statement in V9.sql", None)])]))

    def test_the_loose_group_is_split_by_key(self) -> None:
        loose = [line("one", ADDITIVE, Member(tag="a-controller")), line("two", ADDITIVE, Member(tag="b-controller")),
                 line("three", ADDITIVE, Member(tag="a-controller"))]
        text = self.draw([], loose)
        self.assertEqual(re.findall(r"<li><code>(.*?)</code><ul>", text), ["a-controller", "b-controller"])
        self.assertIn("3 changes in 2 controllers", text)


if __name__ == "__main__":
    unittest.main()
