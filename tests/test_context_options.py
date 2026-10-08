import unittest

from context_pack import build

V23_OPTIONS = {
    "callers_code_only": True,
    "wiki_match": "exact",
    "callers_skip_new_files": True,
    "callers_require_owner": True,
    "callers_skip_fields": True,
    "callers_mode": "precise",
}
PR = {"baseRefOid": "a" * 40, "headRefOid": "b" * 40, "files": []}


class ContextOptions(unittest.TestCase):
    def test_the_options_of_the_v23_variant_are_accepted(self) -> None:
        self.assertEqual(build(PR, "", [], V23_OPTIONS).items, {})

    def test_no_options_are_accepted(self) -> None:
        self.assertEqual(build(PR, "", [], None).items, {})

    def test_wiki_matching_and_callers_have_one_legal_value_each(self) -> None:
        for name, value in (("wiki_match", "folder"), ("callers_mode", "default")):
            with self.assertRaisesRegex(ValueError, f"unknown {name}: {value}"):
                build(PR, "", [], {name: value})

    def test_an_option_that_no_longer_exists_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown context options: list_uncalled"):
            build(PR, "", [], {"list_uncalled": True})

    def test_a_flag_must_be_true_or_false(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be true or false: callers_code_only"):
            build(PR, "", [], {"callers_code_only": "yes"})


if __name__ == "__main__":
    unittest.main()
