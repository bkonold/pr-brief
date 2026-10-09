"""Tests for drawing the Contract and Data sections. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_lines import ADDITIVE, BREAKING, MAY_BREAK, CONTRACT_LEVELS, Line, Member  # noqa: E402
from data_lines import DATA_LEVELS, DESTRUCTIVE, REWRITES  # noqa: E402
from layout import glance, pill, section  # noqa: E402


def line(text: str, impact: str | None, *members: Member, loc: tuple[str, int] | None = ("R", 3), path: str = "api/openapi.json",
         change: str = "", on: str = "", side: str = "") -> Line:
    return Line(impact, text, path, loc, list(members), change=change, on=on, side=side)


URL = "https://example.test/pull/7/files"
FILES = [("api/openapi.json", "https://example.test/a"), ("api/models/Widget.java", "https://example.test/b")]


def pills(text: str) -> list[str]:
    return re.findall(r"<span class=\"pill[^>]*>(?:<strong>)?([^<]*)", text)


class Drawing(unittest.TestCase):
    def test_the_glance_line_has_a_chip_per_level_present_worst_first_with_no_counts(self) -> None:
        lines = [line("a", BREAKING), line("b", BREAKING), line("c", MAY_BREAK), line("d", ADDITIVE), line("e", ADDITIVE)]
        self.assertEqual(pills(glance(lines, CONTRACT_LEVELS)), ["breaking", "may break", "additive"])
        self.assertEqual(pills(glance([line("a", ADDITIVE)], CONTRACT_LEVELS)), ["additive"])
        self.assertNotRegex(re.sub(r"<[^>]+>", "", glance(lines, CONTRACT_LEVELS)), r"\d")

    def test_the_glance_line_does_not_repeat_the_section_name(self) -> None:
        self.assertNotIn("Contract", glance([line("a", ADDITIVE)], CONTRACT_LEVELS))
        self.assertNotIn(":", re.sub(r"<[^>]+>", "", glance([line("a", ADDITIVE)], CONTRACT_LEVELS)))

    def test_the_data_glance_line_has_an_other_chip_for_lines_with_no_level(self) -> None:
        lines = [line("a", DESTRUCTIVE), line("b", REWRITES), line("c", REWRITES), line("d", None)]
        self.assertEqual(pills(glance(lines, DATA_LEVELS)), ["destructive", "rewrites rows", "other"])

    def test_the_top_level_is_bold_and_the_second_is_a_bold_outline(self) -> None:
        self.assertEqual(pill(BREAKING, CONTRACT_LEVELS), '<span class="pill p0"><strong>breaking</strong></span>')
        self.assertEqual(pill(MAY_BREAK, CONTRACT_LEVELS), '<span class="pill p1">may break</span>')
        self.assertEqual(pill(ADDITIVE, CONTRACT_LEVELS), '<span class="pill p2">additive</span>')
        self.assertEqual(pill(None, DATA_LEVELS), "")

    def draw(self, lines, kind="contract", levels=CONTRACT_LEVELS, files=FILES) -> str:
        return section(kind, kind.capitalize(), levels, list(lines), URL, files)

    def test_a_section_is_a_heading_line_a_chip_line_and_a_closed_list_of_files(self) -> None:
        text = self.draw([line("a", BREAKING), line("b", ADDITIVE), line("c", ADDITIVE)])
        self.assertEqual(text, f"**Contract** · [View files]({URL}?pr-brief=contract)<br>\n"
                               '<span class="pill p0"><strong>breaking</strong></span> <span class="pill p2">additive</span>\n\n'
                               "<details>\n<summary>2 files</summary>\n\n"
                               "- [openapi.json](https://example.test/a)\n- [Widget.java](https://example.test/b)\n\n</details>")

    def test_there_is_no_table_and_no_count_of_changes(self) -> None:
        text = self.draw([line("a", BREAKING), line("b", ADDITIVE)])
        for gone in ("|", "<table", "table-wrap", "change", "muted", "↗", " · <span"):
            self.assertNotIn(gone, text)

    def test_the_chips_are_each_level_once_worst_first(self) -> None:
        text = self.draw([line("a", ADDITIVE), line("b", MAY_BREAK), line("c", ADDITIVE), line("d", BREAKING)])
        self.assertEqual(pills(text), ["breaking", "may break", "additive"])

    def test_a_level_the_section_does_not_know_is_an_other_chip(self) -> None:
        self.assertEqual(pills(self.draw([line("a", "deprecated"), line("b", ADDITIVE)])), ["additive", "other"])

    def test_one_file_is_singular(self) -> None:
        self.assertIn("<summary>1 file</summary>", self.draw(self.lines(1), files=FILES[:1]))

    def test_a_data_section_has_the_data_chips_and_the_data_parameter(self) -> None:
        text = self.draw([line("x", DESTRUCTIVE), line("y", ADDITIVE)], kind="data", levels=DATA_LEVELS)
        self.assertTrue(text.startswith(f"**Data** · [View files]({URL}?pr-brief=data)<br>\n"))
        self.assertEqual(pills(text), ["destructive", "additive"])
        self.assertIn(f"[View files]({URL}?pr-brief=data)", text)

    def test_two_files_with_the_same_name_are_listed_by_path(self) -> None:
        text = self.draw(self.lines(1), files=[("a/Item.java", "https://example.test/1"), ("b/Item.java", "https://example.test/2")])
        self.assertIn("- [a/Item.java](https://example.test/1)\n- [b/Item.java](https://example.test/2)", text)

    def test_with_no_file_there_is_no_link_and_no_list(self) -> None:
        text = self.draw(self.lines(1), files=[])
        self.assertEqual(text, '**Contract**<br>\n<span class="pill p2">additive</span>')

    def lines(self, count: int, impact: str = ADDITIVE) -> list[Line]:
        return [line(f"t{n}", impact) for n in range(count)]


if __name__ == "__main__":
    unittest.main()
