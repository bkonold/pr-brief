"""Tests for drawing the Contract and Data sections. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_lines import ADDITIVE, CALLERS, CONSUMERS, CONTRACT_LEVELS, DEPRECATED, Line, Member  # noqa: E402
from data_lines import DATA_LEVELS, DESTRUCTIVE, REWRITES  # noqa: E402
from layout import files_list, glance, middle, pill, section  # noqa: E402


def line(text: str, impact: str | None, *members: Member, loc: tuple[str, int] | None = ("R", 3), path: str = "api/openapi.json",
         change: str = "", on: str = "", side: str = "") -> Line:
    return Line(impact, text, path, loc, list(members), change=change, on=on, side=side)


def pills(text: str) -> list[str]:
    return re.findall(r"<span class=\"pill[^>]*>(?:<strong>)?([^<]*)", text)


def cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split(" | ")]


class Drawing(unittest.TestCase):
    def test_the_glance_line_has_a_chip_per_level_present_worst_first_with_no_counts(self) -> None:
        lines = [line("a", CALLERS), line("b", CALLERS), line("c", CONSUMERS), line("d", ADDITIVE), line("e", ADDITIVE), line("f", DEPRECATED)]
        self.assertEqual(pills(glance(lines, CONTRACT_LEVELS)), ["callers must change", "consumers may break", "additive", "deprecated"])
        self.assertEqual(pills(glance([line("a", ADDITIVE)], CONTRACT_LEVELS)), ["additive"])
        self.assertNotRegex(re.sub(r"<[^>]+>", "", glance(lines, CONTRACT_LEVELS)), r"\d")

    def test_the_glance_line_does_not_repeat_the_section_name(self) -> None:
        self.assertNotIn("Contract", glance([line("a", ADDITIVE)], CONTRACT_LEVELS))
        self.assertNotIn(":", re.sub(r"<[^>]+>", "", glance([line("a", ADDITIVE)], CONTRACT_LEVELS)))

    def test_the_data_glance_line_has_an_other_chip_for_lines_with_no_level(self) -> None:
        lines = [line("a", DESTRUCTIVE), line("b", REWRITES), line("c", REWRITES), line("d", None)]
        self.assertEqual(pills(glance(lines, DATA_LEVELS)), ["destructive", "rewrites rows", "other"])

    def test_the_top_level_is_bold_and_the_second_is_a_bold_outline(self) -> None:
        self.assertEqual(pill(CALLERS, CONTRACT_LEVELS), '<span class="pill p0"><strong>callers must change</strong></span>')
        self.assertEqual(pill(CONSUMERS, CONTRACT_LEVELS), '<span class="pill p1">consumers may break</span>')
        self.assertEqual(pill(ADDITIVE, CONTRACT_LEVELS), '<span class="pill p2">additive</span>')
        self.assertEqual(pill(None, DATA_LEVELS), "")

    def draw(self, lines, kind="contract", levels=CONTRACT_LEVELS) -> str:
        return section(kind, "API" if kind == "contract" else kind.capitalize(), levels, list(lines), lambda l: f"https://example.test/{l.loc[1]}")

    def lines(self, count: int, impact: str = ADDITIVE) -> list[Line]:
        return [line(f"t{n}", impact, change=f"`+ p{n}` optional", on=f"`S{n}`", side="request", loc=("R", n)) for n in range(count)]

    def rows(self, text: str) -> list[list[str]]:
        return [cells(row) for row in text.splitlines() if row.startswith("|")][2:]

    def test_a_section_is_one_closed_details_with_its_name_and_chips_in_the_summary(self) -> None:
        text = self.draw([line("a", CALLERS), line("b", ADDITIVE), line("c", ADDITIVE)])
        self.assertEqual(text.count("<details"), 1)
        self.assertTrue(text.startswith('<details class="section">\n<summary><strong>API</strong><br>\n<span class="pill p0">'))
        self.assertNotIn("open", text.split("\n")[0])
        summary = re.search(r"(?s)<summary>(.*?)</summary>", text).group(1)
        self.assertEqual(re.sub(r"<[^>]+>", "", summary), "API\ncallers must change additive 3 changes")
        self.assertEqual(pills(summary), ["callers must change", "additive"])
        self.assertTrue(summary.endswith(' <span class="muted">3 changes</span>'))
        self.assertTrue(text.endswith("</div>\n\n</details>"))

    def test_the_summary_is_the_heading_alone_then_a_break_and_the_chips_and_count(self) -> None:
        text = self.draw([line("a", CALLERS), line("b", ADDITIVE)])
        first, second = re.search(r"(?s)<summary>(.*?)</summary>", text).group(1).split("\n")
        self.assertEqual(first, "<strong>API</strong><br>")
        self.assertEqual(pills(second), ["callers must change", "additive"])
        self.assertTrue(second.endswith('<span class="muted">2 changes</span>'))

    def test_the_files_are_one_link_item_per_line_under_the_bold_label(self) -> None:
        text = section("contract", "API", CONTRACT_LEVELS, self.lines(1), lambda l: "https://example.test",
                       files=[("a/One.java", "https://x/1"), ("b/Two.ts", "https://x/2")])
        self.assertIn("\n\n**API files**\n\n- [One.java](https://x/1)\n- [Two.ts](https://x/2)\n\n</details>", text)
        self.assertEqual(files_list("Data files", [("a/Same.java", "u1"), ("b/Same.java", "u2")]),
                         "**Data files**\n\n- [a/Same.java](u1)\n- [b/Same.java](u2)")
        self.assertEqual(files_list("Data files", []), "")

    def test_the_total_is_singular_for_one_line_and_is_not_a_chip(self) -> None:
        text = self.draw(self.lines(1))
        summary = re.search(r"(?s)<summary>(.*?)</summary>", text).group(1)
        self.assertTrue(summary.endswith(' <span class="muted">1 change</span>'))
        self.assertEqual(pills(summary), ["additive"])

    def test_a_data_section_is_headed_data(self) -> None:
        text = self.draw([line("x", DESTRUCTIVE, change="c", on="`t`")], kind="data", levels=DATA_LEVELS)
        self.assertIn("<summary><strong>Data</strong><br>\n", text)

    def test_the_section_has_no_chunk_wording_and_no_per_group_markup(self) -> None:
        text = self.draw(self.lines(3))
        for gone in ("chunk", "group-row", "<strong><code>"):
            self.assertNotIn(gone, text)

    def test_a_single_line_is_still_a_table_in_the_details(self) -> None:
        text = self.draw(self.lines(1))
        self.assertEqual(text.count("<details"), 1)
        self.assertEqual(len(self.rows(text)), 1)
        self.assertNotIn("group-row", text)

    def test_the_table_has_a_row_per_line_and_the_link_last(self) -> None:
        group = [line("later", ADDITIVE, loc=("R", 9), change="`+ a` optional", on="`A`", side="response"),
                 line("first", CALLERS, loc=("L", 4), change="`+ b` required", on="`B`", side="both")]
        text = self.draw(group)
        table = [row for row in text.splitlines() if row.startswith("|")]
        self.assertEqual(cells(table[0]), ["Impact", "Side", "Change", "On", "↗"])
        self.assertEqual(cells(table[1]), ["---", "---", "---", "---", "---"])
        self.assertEqual(cells(table[2]), ['<span class="pill p0"><strong>callers must change</strong></span>', "both",
                                           "<code>+ b</code> required", "<code>B</code>", "[↗](https://example.test/4)"])
        self.assertEqual(cells(table[3]), ['<span class="pill p2">additive</span>', "response", "<code>+ a</code> optional",
                                           "<code>A</code>", "[↗](https://example.test/9)"])
        self.assertIn('<div class="table-wrap">\n\n| Impact', text)
        self.assertNotIn("<li>", text)

    def test_contract_rows_are_worst_first_then_request_before_response_then_on_alphabetically(self) -> None:
        def make(name, impact, side, on):
            return line(name, impact, change=name, on=on, side=side)
        rows = self.rows(self.draw([
            make("a", ADDITIVE, "request", "`Zed`"), make("b", CONSUMERS, "response", "`Alpha`"),
            make("c", ADDITIVE, "response", "`Alpha`"), make("d", CONSUMERS, "request", "`mid`"),
            make("e", ADDITIVE, "request", "`alpha`"), make("f", CALLERS, "response", "`Zed`"),
            make("g", CONSUMERS, "request", "`Beta`")]))
        self.assertEqual([r[2] for r in rows], ["f", "g", "d", "b", "e", "a", "c"])

    def test_data_rows_are_worst_first_then_table_then_file_order(self) -> None:
        def make(name, impact, on):
            return line(name, impact, change=name, on=on)
        rows = self.rows(self.draw([
            make("a", ADDITIVE, "`b_table`"), make("b", DESTRUCTIVE, "`z_table`"), make("c", ADDITIVE, "`a_table`"),
            make("d", ADDITIVE, "`b_table`"), make("e", REWRITES, "`m_table`"), make("f", DESTRUCTIVE, "`z_table`")],
            kind="data", levels=DATA_LEVELS))
        self.assertEqual([r[1] for r in rows], ["b", "f", "e", "c", "a", "d"])

    def test_a_pattern_line_stays_one_row(self) -> None:
        sweep = line("s", CONSUMERS, change="`number` → `string`, 3 properties: `p0`, `p1`, `p2`", on="9 schemas: `A`, `B`, `C` +6", side="response")
        rows = self.rows(self.draw([sweep, *self.lines(1)]))
        self.assertEqual(len(rows), 2)
        self.assertIn("9 schemas", rows[0][3])

    def test_a_data_table_has_no_side_column(self) -> None:
        group = [line("x", DESTRUCTIVE, change="`− old`", on="`legacy`"), line("y", ADDITIVE, change="new table", on="`items`")]
        text = self.draw(group, kind="data", levels=DATA_LEVELS)
        table = [row for row in text.splitlines() if row.startswith("|")]
        self.assertEqual(cells(table[0]), ["Impact", "Change", "Table", "↗"])
        self.assertEqual(cells(table[2])[1:3], ["<code>− old</code>", "<code>legacy</code>"])

    def test_a_line_with_no_level_has_an_empty_impact_cell(self) -> None:
        text = self.draw([line("DO block in V9.sql", None, change="DO block", on="`V9.sql`"), *self.lines(1)], kind="data", levels=DATA_LEVELS)
        self.assertTrue(any(row.startswith("|  | DO block") for row in text.splitlines()))

    def test_a_long_name_is_cut_in_the_middle_with_the_whole_name_in_its_title(self) -> None:
        name = "HomeCenterHiddenSlideKeysWithAVeryLongSchemaNameResponse"
        text = self.draw([line("x", ADDITIVE, change="c", on=f"`{name}`"), *self.lines(1)])
        shown = middle(name)
        self.assertLess(len(shown), len(name))
        self.assertTrue(shown.startswith("HomeCenter") and shown.endswith("Response") and "…" in shown)
        self.assertIn(f'<code title="{name}">{shown}</code>', text)

    def test_an_endpoint_is_never_cut(self) -> None:
        endpoint = "GET /api/home-center-report/deck/hidden-slides/with/a/very/long/path"
        text = self.draw([line("x", ADDITIVE, change="c", on=f"`{endpoint}`"), *self.lines(1)])
        self.assertIn(f"<code>{endpoint}</code>", text)

    def test_a_short_name_has_no_title(self) -> None:
        self.assertNotIn("title=", self.draw(self.lines(2)))

    def test_a_pipe_in_a_cell_does_not_split_the_row(self) -> None:
        text = self.draw([line("x", ADDITIVE, change="a | b", on="`c`"), *self.lines(1)])
        row = [r for r in text.splitlines() if "a &#124; b" in r][0]
        self.assertEqual(len(cells(row)), 5)


if __name__ == "__main__":
    unittest.main()
