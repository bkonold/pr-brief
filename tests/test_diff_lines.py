"""Tests for the diff line helpers. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_fixtures import SPEC, document, make_diff, operation  # noqa: E402
from diff_lines import SpecDiff, file_diff_lines, sql_name  # noqa: E402


def spec_lines(base: dict, head: dict) -> list:
    return file_diff_lines(make_diff(SPEC, json.dumps(base, indent=2), json.dumps(head, indent=2)), SPEC)


class FileDiffLines(unittest.TestCase):
    def test_lines_carry_side_number_kind_and_key(self) -> None:
        base = document({}, {})
        head = document({"/widgets": {"get": operation("listWidgets")}}, {})
        added = [line for line in spec_lines(base, head) if line.kind == "+"]
        found = next(line for line in added if line.key == "operationId")
        self.assertEqual((found.side, found.value), ("R", '"listWidgets",'))

    def test_only_the_named_files_lines_are_read(self) -> None:
        diff = make_diff("other.json", "{}", '{"a": 1}') + "\n" + make_diff(SPEC, "x", "y")
        self.assertEqual([line.text for line in file_diff_lines(diff, SPEC) if line.kind == "+"], ["y"])


class SpecDiffLookup(unittest.TestCase):
    def test_an_added_operation_is_found_by_its_id(self) -> None:
        base = document({}, {})
        head = document({"/widgets": {"get": operation("listWidgets")}}, {})
        lines = spec_lines(base, head)
        index = SpecDiff(lines).operation("GET", "/widgets", "listWidgets", "+")
        self.assertIsNotNone(index)
        self.assertEqual(lines[index].kind, "+")


class SqlName(unittest.TestCase):
    def test_quotes_and_trailing_punctuation_are_dropped(self) -> None:
        self.assertEqual(sql_name('"orders",'), "orders")
        self.assertEqual(sql_name("public.orders;"), "public.orders")


if __name__ == "__main__":
    unittest.main()
