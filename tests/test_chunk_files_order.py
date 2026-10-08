"""Tests for the order of the files inside a chunk: the model's order, test files last. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import render  # noqa: E402
from layout import LineSet  # noqa: E402
from render import DEFAULT_TEST_GLOBS, build_chunks, is_test_path  # noqa: E402

PATHS = ["web/Page.tsx", "web/Page.test.tsx", "api/ItemService.java", "api/ItemServiceTest.java",
         "api/src/test/Fixtures.java", "api/ItemRepo.java"]
COUNTS = {path.lower(): (1, 0) for path in PATHS}


def build(files: list[str]) -> list:
    raw = {"name": "Items", "review": "read", "why": "w", "files": files}
    with mock.patch.object(render, "TEST_GLOBS", DEFAULT_TEST_GLOBS), mock.patch.object(render, "TEST_DIRS", []):
        return build_chunks([raw], COUNTS, files, {}, [], {}, None, LineSet([], []))


class ChunkFilesOrder(unittest.TestCase):
    def test_a_chunk_keeps_the_models_order_with_tests_last(self) -> None:
        chunk = build(PATHS)[0]
        self.assertEqual(chunk.files, ["web/Page.tsx", "api/ItemService.java", "api/ItemRepo.java",
                                       "web/Page.test.tsx", "api/ItemServiceTest.java", "api/src/test/Fixtures.java"])

    def test_the_catch_all_chunk_also_puts_tests_last(self) -> None:
        with mock.patch.object(render, "TEST_GLOBS", DEFAULT_TEST_GLOBS), mock.patch.object(render, "TEST_DIRS", []):
            chunks = build_chunks([], COUNTS, ["web/Page.test.tsx", "web/Page.tsx"], {}, [], {}, None, LineSet([], []))
        self.assertEqual(chunks[0].files, ["web/Page.tsx", "web/Page.test.tsx"])


class TestPaths(unittest.TestCase):
    def test_the_generic_rule(self) -> None:
        for path in ("a/test/x.py", "tests/x.py", "a/FooTest.java", "a/foo.test.ts", "a/foo_test.go", "a/FooTests.cs"):
            self.assertTrue(is_test_path(path, DEFAULT_TEST_GLOBS, []), path)
        for path in ("a/latest/x.py", "a/Contest.java", "a/testing.py", "a/foo.ts"):
            self.assertFalse(is_test_path(path, DEFAULT_TEST_GLOBS, []), path)

    def test_the_globs_and_test_dirs_are_overridable(self) -> None:
        self.assertTrue(is_test_path("a/foo.spec.ts", ["**/*.spec.*"], []))
        self.assertFalse(is_test_path("a/foo.test.ts", ["**/*.spec.*"], []))
        self.assertTrue(is_test_path("a/src/integrationTest/x.java", [], ["/src/integrationTest/"]))


if __name__ == "__main__":
    unittest.main()
