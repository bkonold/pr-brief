"""Tests for placing contract and data lines in chunks and drawing the two sections. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_lines import ADDITIVE, CALLERS, CONSUMERS, CONTRACT_LEVELS, DEPRECATED, Line, Member  # noqa: E402
from data_lines import DATA_LEVELS, DESTRUCTIVE, REWRITES  # noqa: E402
from layout import DEFAULT_TAG_TEMPLATES, glance, middle, place, pill, section, stem, tag_stems  # noqa: E402

FILES = ["api/ItemController.java", "api/models/Item.java", "db/V9__items.sql", "api/openapi.json", "web/WidgetPage.tsx"]
HELD = [{FILES[0]}, {FILES[1]}, {FILES[2]}, {FILES[3]}, {FILES[4]}]
STEMS = [{"itemcontroller"}, {"item"}, {"v9__items"}, set(), {"widgetpage"}]
CODE = {0: ["ItemController", 'path = "/items"'], 1: ["Item"], 2: ["V9__items"], 4: ["WidgetPage", 'fetch("/widgets/stats")']}


def line(text: str, impact: str | None, *members: Member, loc: tuple[str, int] | None = ("R", 3), path: str = "api/openapi.json",
         change: str = "", on: str = "", side: str = "") -> Line:
    return Line(impact, text, path, loc, list(members), change=change, on=on, side=side)


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


def pills(text: str) -> list[str]:
    return re.findall(r"<span class=\"pill[^>]*>(?:<strong>)?([^<]*)", text)


def cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split(" | ")]


class Drawing(unittest.TestCase):
    def test_the_glance_line_counts_levels_worst_first_and_omits_zeros(self) -> None:
        lines = [line("a", CALLERS), line("b", CALLERS), line("c", CONSUMERS), line("d", ADDITIVE), line("e", ADDITIVE), line("f", DEPRECATED)]
        self.assertEqual(pills(glance(lines, CONTRACT_LEVELS)),
                         ["2 callers must change", "1 consumer may break", "2 additive", "1 deprecated"])
        self.assertEqual(pills(glance([line("a", ADDITIVE)], CONTRACT_LEVELS)), ["1 additive"])

    def test_the_glance_line_does_not_repeat_the_section_name(self) -> None:
        self.assertNotIn("Contract", glance([line("a", ADDITIVE)], CONTRACT_LEVELS))
        self.assertNotIn(":", re.sub(r"<[^>]+>", "", glance([line("a", ADDITIVE)], CONTRACT_LEVELS)))

    def test_the_data_glance_line_counts_lines_with_no_level_as_other(self) -> None:
        lines = [line("a", DESTRUCTIVE), line("b", REWRITES), line("c", REWRITES), line("d", None)]
        self.assertEqual(pills(glance(lines, DATA_LEVELS)), ["1 destructive", "2 rewrite rows", "1 other"])

    def test_the_top_level_is_bold_and_the_second_is_a_bold_outline(self) -> None:
        self.assertEqual(pill(CALLERS, CONTRACT_LEVELS), '<span class="pill p0"><strong>callers must change</strong></span>')
        self.assertEqual(pill(CONSUMERS, CONTRACT_LEVELS), '<span class="pill p1">consumers may break</span>')
        self.assertEqual(pill(ADDITIVE, CONTRACT_LEVELS), '<span class="pill p2">additive</span>')
        self.assertEqual(pill(None, DATA_LEVELS), "")

    def draw(self, owned, loose=(), kind="contract", levels=CONTRACT_LEVELS) -> str:
        return section(kind, levels, owned, list(loose), lambda l: f"https://example.test/{l.loc[1]}",
                       lambda l: l.members[0].tag or "untagged")

    def lines(self, count: int, impact: str = ADDITIVE) -> list[Line]:
        return [line(f"t{n}", impact, change=f"`+ p{n}` optional", on=f"`S{n}`", side="request", loc=("R", n)) for n in range(count)]

    def test_groups_are_closed_sorted_by_worst_level_then_number_with_the_loose_group_last(self) -> None:
        owned = [(1, "Screen", self.lines(2)), (3, "Api `x`", [*self.lines(2), line("hard", CALLERS)]),
                 (2, "Model", [*self.lines(1), line("break", CONSUMERS)]), (4, "Empty", [])]
        loose = [line("odd", ADDITIVE, Member(tag="a-controller")), line("odder", CONSUMERS, Member(tag="b-controller"))]
        text = self.draw(owned, loose)
        heads = re.findall(r"<summary>(.*?)</summary>", text)
        self.assertEqual([re.sub(r"<[^>]+>", "", h) for h in heads],
                         ["3 · Api x callers must change 3 changes", "2 · Model consumers may break 2 changes",
                          "1 · Screen additive 2 changes", "Not in any chunk consumers may break 2 changes"])
        self.assertEqual(text.count("<details>"), 4)
        self.assertNotIn("<details open", text)
        self.assertIn("3 · Api <code>x</code>", text)
        self.assertIn('<span class="muted">3 changes</span>', text)

    def test_a_group_summary_has_no_first_line_and_no_more_count(self) -> None:
        text = self.draw([(1, "A", [line("first line", CALLERS), line("second", ADDITIVE)])])
        self.assertNotIn("first line", re.search(r"<summary>.*?</summary>", text).group())
        self.assertNotIn("more", text)

    def test_a_group_is_a_table_with_a_row_per_line_worst_first_and_the_link_last(self) -> None:
        group = [line("later", ADDITIVE, loc=("R", 9), change="`+ a` optional", on="`A`", side="response"),
                 line("first", CALLERS, loc=("L", 4), change="`+ b` required", on="`B`", side="both")]
        text = self.draw([(1, "A", group)])
        table = [row for row in text.splitlines() if row.startswith("|")]
        self.assertEqual(cells(table[0]), ["Impact", "Side", "Change", "On", "↗"])
        self.assertEqual(cells(table[1]), ["---", "---", "---", "---", "---"])
        self.assertEqual(cells(table[2]), ['<span class="pill p0"><strong>callers must change</strong></span>', "both",
                                           "<code>+ b</code> required", "<code>B</code>", "[↗](https://example.test/4)"])
        self.assertEqual(cells(table[3]), ['<span class="pill p2">additive</span>', "response", "<code>+ a</code> optional",
                                           "<code>A</code>", "[↗](https://example.test/9)"])
        self.assertIn('<div class="table-wrap">\n\n| Impact', text)
        self.assertNotIn("<li>", text)

    def test_a_data_table_has_no_side_column(self) -> None:
        group = [line("x", DESTRUCTIVE, change="`− old`", on="`legacy`"), line("y", ADDITIVE, change="new table", on="`items`")]
        text = self.draw([(1, "A", group)], kind="data", levels=DATA_LEVELS)
        table = [row for row in text.splitlines() if row.startswith("|")]
        self.assertEqual(cells(table[0]), ["Impact", "Change", "Table", "↗"])
        self.assertEqual(cells(table[2])[1:3], ["<code>− old</code>", "<code>legacy</code>"])

    def test_a_line_with_no_level_has_an_empty_impact_cell(self) -> None:
        text = self.draw([(1, "A", [line("DO block in V9.sql", None, change="DO block", on="`V9.sql`"), *self.lines(1)])], kind="data", levels=DATA_LEVELS)
        table = [row for row in text.splitlines() if row.startswith("|")]
        self.assertTrue(table[3].startswith("|  | DO block"), table[3])

    def test_a_group_of_one_line_is_a_plain_row_without_details(self) -> None:
        text = self.draw([(2, "Model", [line("t", CALLERS, change="`+ p` required", on="`S`", side="request", loc=("R", 5))])])
        row = [part for part in text.split("\n\n") if "group-row" in part][0]
        self.assertEqual(row, '<p class="group-row">2 · Model <span class="pill p0"><strong>callers must change</strong></span> '
                              '<code>+ p</code> required · <code>S</code> <span class="muted">request</span> '
                              '<a href="https://example.test/5">↗</a></p>')
        self.assertNotIn("<details", text)
        self.assertNotIn("|", text)

    def test_a_loose_group_of_one_line_is_a_plain_row_too(self) -> None:
        text = self.draw([], [line("t", ADDITIVE, Member(tag="a"), change="x", on="`y`")])
        self.assertIn('<p class="group-row">Not in any chunk', text)
        self.assertNotIn("<details", text)

    def test_the_loose_group_has_a_sub_header_row_per_key(self) -> None:
        loose = [line("one", ADDITIVE, Member(tag="a-controller"), change="1", on="`a`"),
                 line("two", ADDITIVE, Member(tag="b-controller"), change="2", on="`b`"),
                 line("three", ADDITIVE, Member(tag="a-controller"), change="3", on="`c`")]
        text = self.draw([], loose)
        subs = [cells(row) for row in text.splitlines() if row.startswith("| <strong>")]
        self.assertEqual(subs, [["<strong><code>a-controller</code></strong>", "", "", "", ""],
                                ["<strong><code>b-controller</code></strong>", "", "", "", ""]])
        rows = [row for row in text.splitlines() if row.startswith("|")]
        self.assertEqual([cells(r)[3] for r in rows[2:] if "<strong>" not in r], ["<code>a</code>", "<code>c</code>", "<code>b</code>"])
        self.assertIn('<span class="muted">3 changes</span>', text)

    def test_a_long_name_is_cut_in_the_middle_with_the_whole_name_in_its_title(self) -> None:
        name = "HomeCenterHiddenSlideKeysWithAVeryLongSchemaNameResponse"
        text = self.draw([(1, "A", [line("x", ADDITIVE, change="c", on=f"`{name}`"), *self.lines(1)])])
        shown = middle(name)
        self.assertLess(len(shown), len(name))
        self.assertTrue(shown.startswith("HomeCenter") and shown.endswith("Response") and "…" in shown)
        self.assertIn(f'<code title="{name}">{shown}</code>', text)

    def test_a_short_name_has_no_title(self) -> None:
        self.assertNotIn("title=", self.draw([(1, "A", self.lines(2))]))

    def test_a_pipe_in_a_cell_does_not_split_the_row(self) -> None:
        text = self.draw([(1, "A", [line("x", ADDITIVE, change="a | b", on="`c`"), *self.lines(1)])])
        row = [r for r in text.splitlines() if "a &#124; b" in r][0]
        self.assertEqual(len(cells(row)), 5)


if __name__ == "__main__":
    unittest.main()
