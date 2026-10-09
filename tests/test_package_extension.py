"""Tests for packaging the extension for Chrome and Firefox. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import package_extension as packager  # noqa: E402

CHROME = {"manifest_version": 3, "name": "X", "version": "1.2.3", "permissions": ["storage"],
          "background": {"service_worker": "background.js", "type": "module"}}
FIREFOX = {**CHROME, "background": {"scripts": ["background.js"], "type": "module"},
           "browser_specific_settings": {"gecko": {"id": "x@example.test", "strict_min_version": "128.0"}}}


class Packaging(unittest.TestCase):
    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        self.source = self.root / "extension"
        self.out = self.root / "out"
        self.write("manifest.json", json.dumps(CHROME))
        self.write("manifest.firefox.json", json.dumps(FIREFOX))
        for name in ("background.js", "content.css", "sub/page.js", "README.md", "test/a.test.js", ".hidden", "sub/.also"):
            self.write(name, f"// {name}")

    def write(self, name: str, text: str) -> None:
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_the_chrome_zip_is_named_for_the_version_and_holds_the_files_at_its_root(self) -> None:
        archive, _ = packager.package(self.out, self.source)
        self.assertEqual(archive.name, "pr-brief-chrome-1.2.3.zip")
        with zipfile.ZipFile(archive) as zipped:
            self.assertEqual(sorted(zipped.namelist()), ["background.js", "content.css", "manifest.json", "sub/page.js"])
            self.assertEqual(json.loads(zipped.read("manifest.json")), CHROME)

    def test_the_tests_the_readme_dotfiles_and_the_firefox_manifest_are_left_out_of_both_builds(self) -> None:
        archive, directory = packager.package(self.out, self.source)
        built = sorted(str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file())
        self.assertEqual(built, ["background.js", "content.css", "manifest.json", "sub/page.js"])
        with zipfile.ZipFile(archive) as zipped:
            for name in zipped.namelist():
                for left_out in ("README", "test/", ".hidden", ".also", "firefox"):
                    self.assertNotIn(left_out, name)

    def test_the_firefox_directory_has_the_firefox_manifest_as_manifest_json(self) -> None:
        _, directory = packager.package(self.out, self.source)
        self.assertEqual(directory, self.out / "firefox")
        self.assertEqual(json.loads((directory / "manifest.json").read_text()), FIREFOX)
        self.assertEqual((directory / "sub" / "page.js").read_text(), "// sub/page.js")

    def test_packaging_twice_gives_the_same_zip_and_replaces_the_firefox_directory(self) -> None:
        archive, directory = packager.package(self.out, self.source)
        first = archive.read_bytes()
        (directory / "stale.js").write_text("old")
        packager.package(self.out, self.source)
        self.assertEqual(archive.read_bytes(), first)
        self.assertFalse((directory / "stale.js").exists())

    def test_a_version_that_differs_between_the_manifests_is_an_error_and_writes_nothing(self) -> None:
        self.write("manifest.firefox.json", json.dumps({**FIREFOX, "version": "1.2.4"}))
        with self.assertRaisesRegex(ValueError, "version differs"):
            packager.package(self.out, self.source)
        self.assertFalse(self.out.exists())

    def test_the_check_ignores_background_and_browser_specific_settings_only(self) -> None:
        self.assertEqual(packager.manifest_problems(self.source), [])
        self.write("manifest.firefox.json", json.dumps({**FIREFOX, "permissions": ["storage", "tabs"]}))
        self.assertEqual(packager.manifest_problems(self.source), ["permissions differs between manifest.json and manifest.firefox.json"])
        chrome_only = {**CHROME, "content_scripts": []}
        self.write("manifest.json", json.dumps(chrome_only))
        self.write("manifest.firefox.json", json.dumps(FIREFOX))
        self.assertEqual(packager.manifest_problems(self.source), ["content_scripts differs between manifest.json and manifest.firefox.json"])


class Command(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "package_extension.py"), *args], capture_output=True, text=True)

    def test_the_manifests_of_this_repository_agree(self) -> None:
        result = self.run_script("--check")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertIn(packager.version_of(), result.stdout)

    def test_out_writes_both_builds_with_the_version_of_the_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as out:
            result = self.run_script("--out", out)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((Path(out) / f"pr-brief-chrome-{packager.version_of()}.zip").exists())
            self.assertEqual(json.loads((Path(out) / "firefox" / "manifest.json").read_text())["browser_specific_settings"]["gecko"]["id"],
                             "pr-brief@bkonold.github.io")

    def test_without_out_or_check_it_exits_non_zero(self) -> None:
        self.assertNotEqual(self.run_script().returncode, 0)


if __name__ == "__main__":
    unittest.main()
