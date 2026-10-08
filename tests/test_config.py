"""Tests for config.py: the `--config` file that replaces local.toml, and the reach and archetypes tables it may hold.
All data here is invented. Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402


class ConfigFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        home = mock.patch.object(config, "HOME", self.dir / "home")
        home.start()
        self.addCleanup(home.stop)
        (self.dir / "home").mkdir()
        environ = mock.patch.dict(os.environ)
        environ.start()
        self.addCleanup(environ.stop)
        os.environ.pop(config.CONFIG_ENV, None)

    def write(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text)
        return path

    def test_local_toml_under_home_is_read_without_the_flag(self) -> None:
        (self.dir / "home" / "local.toml").write_text('repo = "o/r"\n')
        self.assertEqual(config.load_local(), {"repo": "o/r"})

    def test_no_file_and_no_flag_means_no_settings(self) -> None:
        self.assertEqual(config.load_local(), {})

    def test_the_flag_names_the_file_read_in_place_of_local_toml(self) -> None:
        (self.dir / "home" / "local.toml").write_text('repo = "o/home"\n')
        named = self.write("pr-brief.toml", 'repo = "o/named"\nmodel = { copilot = "m" }\n')
        config.use_config_flag(["run.py", "7", "--config", str(named)])
        self.assertEqual(config.load_local(), {"repo": "o/named", "model": {"copilot": "m"}})

    def test_the_flag_also_takes_the_equals_form_and_makes_the_path_absolute(self) -> None:
        self.write("c.toml", 'repo = "o/r"\n')
        with mock.patch("os.getcwd", return_value=str(self.dir)):
            config.use_config_flag(["run.py", f"--config={self.dir}/c.toml"])
        self.assertEqual(os.environ[config.CONFIG_ENV], str((self.dir / "c.toml").resolve()))

    def test_without_the_flag_the_environment_is_left_alone(self) -> None:
        config.use_config_flag(["run.py", "7"])
        self.assertNotIn(config.CONFIG_ENV, os.environ)
        config.use_config_flag(["run.py", "--config"])
        self.assertNotIn(config.CONFIG_ENV, os.environ)

    def test_a_named_file_that_is_missing_is_an_error_rather_than_no_settings(self) -> None:
        os.environ[config.CONFIG_ENV] = str(self.dir / "absent.toml")
        with self.assertRaises(SystemExit) as stop:
            config.load_local()
        self.assertIn("absent.toml does not exist", str(stop.exception))

    def test_an_unknown_key_in_the_named_file_is_an_error_naming_that_file(self) -> None:
        os.environ[config.CONFIG_ENV] = str(self.write("pr-brief.toml", 'bogus = 1\n'))
        with self.assertRaises(SystemExit) as stop:
            config.load_local()
        self.assertEqual(str(stop.exception), "pr-brief.toml has unknown keys: bogus")

    def test_a_key_that_is_missing_stays_missing(self) -> None:
        os.environ[config.CONFIG_ENV] = str(self.write("c.toml", 'repo = "o/r"\n'))
        settings = config.load_local()
        self.assertNotIn("openapi_path", settings)
        self.assertNotIn("source_checkout", settings)

    def test_reach_and_archetypes_may_be_tables_of_the_same_file(self) -> None:
        os.environ[config.CONFIG_ENV] = str(self.write("c.toml", (
            'repo = "o/r"\n[[reach.app]]\nname = "web"\nglobs = ["web/**"]\n'
            '[archetypes]\norder = ["A", "B"]\n[archetypes.prs]\n7 = "A"\n')))
        self.assertEqual(config.config_section("reach"), {"app": [{"name": "web", "globs": ["web/**"]}]})
        self.assertEqual(config.config_section("archetypes"), {"order": ["A", "B"], "prs": {"7": "A"}})

    def test_a_section_without_a_table_falls_back_to_its_own_file_under_home_and_then_to_none(self) -> None:
        os.environ[config.CONFIG_ENV] = str(self.write("c.toml", 'repo = "o/r"\n'))
        self.assertIsNone(config.config_section("reach"))
        (self.dir / "home" / "reach.toml").write_text('[[app]]\nname = "api"\nglobs = ["api/**"]\n')
        self.assertEqual(config.config_section("reach"), {"app": [{"name": "api", "globs": ["api/**"]}]})


if __name__ == "__main__":
    unittest.main()
