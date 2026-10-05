"""Tests for compare.write_variants_json, which makes a freshly run PR findable by the extension.
Run with `python3 -m unittest discover -s tests` from the tool's folder. All data here is invented."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import compare  # noqa: E402


class VariantsJsonTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        patch = mock.patch.object(compare, "HOME", self.home)
        patch.start()
        self.addCleanup(patch.stop)
        self.pr_dir = self.home / "runs" / "fj-7"
        for variant in ("listed", "unlisted", "no_review"):
            (self.pr_dir / variant).mkdir(parents=True)
        for variant in ("listed", "unlisted"):
            (self.pr_dir / variant / "review.json").write_text("{}")

    def written(self) -> list[str]:
        return [entry["variant"] for entry in json.loads((self.pr_dir / "variants.json").read_text())]

    def test_lists_compare_toml_variants_that_have_a_review(self) -> None:
        (self.home / "compare.toml").write_text('variants = ["listed", "no_review"]\n')
        compare.write_variants_json(self.pr_dir)
        self.assertEqual(self.written(), ["listed"])

    def test_adds_the_variant_just_run_when_compare_toml_does_not_list_it(self) -> None:
        (self.home / "compare.toml").write_text('variants = ["listed"]\n')
        compare.write_variants_json(self.pr_dir, "unlisted")
        self.assertEqual(self.written(), ["listed", "unlisted"])

    def test_works_without_a_compare_toml(self) -> None:
        compare.write_variants_json(self.pr_dir, "unlisted")
        self.assertEqual(self.written(), ["unlisted"])


if __name__ == "__main__":
    unittest.main()
