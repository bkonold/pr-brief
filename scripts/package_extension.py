"""Packages the browser extension for Chrome and Firefox.

    python scripts/package_extension.py --out DIR      write DIR/pr-brief-chrome-<version>.zip and DIR/firefox/
    python scripts/package_extension.py --check        only compare the two manifests

The Chrome zip holds the files of `extension/` at its root, with `manifest.json`. `DIR/firefox/` holds the same files
with `manifest.firefox.json` in place as `manifest.json`; `web-ext sign` turns it into the `.xpi`. The tests, the README,
the other manifest and dotfiles are left out of both. The version comes from `manifest.json`, and the two manifests must
agree on it, and on every key but the ones Firefox needs different (`FIREFOX_ONLY`).
"""
import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "extension"
CHROME_MANIFEST = "manifest.json"
FIREFOX_MANIFEST = "manifest.firefox.json"
FIREFOX_ONLY = ("background", "browser_specific_settings")
EXCLUDED_DIRS = {"test"}
EXCLUDED_FILES = {"README.md", CHROME_MANIFEST, FIREFOX_MANIFEST}
ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def load(source: Path, name: str) -> dict:
    return json.loads((source / name).read_text(encoding="utf-8"))


def manifest_problems(source: Path = SOURCE) -> list[str]:
    """What differs between the two manifests apart from the keys that are Firefox's own; empty when they agree."""
    chrome: dict = load(source, CHROME_MANIFEST)
    firefox: dict = load(source, FIREFOX_MANIFEST)
    problems: list[str] = []
    for key in sorted((chrome.keys() | firefox.keys()) - set(FIREFOX_ONLY)):
        if chrome.get(key) != firefox.get(key):
            problems.append(f"{key} differs between {CHROME_MANIFEST} and {FIREFOX_MANIFEST}")
    return problems


def version_of(source: Path = SOURCE) -> str:
    return load(source, CHROME_MANIFEST)["version"]


def files_of(source: Path = SOURCE) -> list[Path]:
    """The files that go in a build, as paths relative to `source`, sorted. Dotfiles, the tests and the README are left out."""
    kept: list[Path] = []
    for path in sorted(source.rglob("*")):
        relative: Path = path.relative_to(source)
        if not path.is_file() or any(part.startswith(".") for part in relative.parts) or relative.parts[0] in EXCLUDED_DIRS:
            continue
        if len(relative.parts) == 1 and relative.name in EXCLUDED_FILES:
            continue
        kept.append(relative)
    return kept


def package(out: Path, source: Path = SOURCE) -> tuple[Path, Path]:
    """Writes the Chrome zip and the Firefox directory into `out`; returns their paths. Raises ValueError when the manifests disagree."""
    problems: list[str] = manifest_problems(source)
    if problems:
        raise ValueError("; ".join(problems))
    firefox: dict = load(source, FIREFOX_MANIFEST)
    version: str = version_of(source)
    out.mkdir(parents=True, exist_ok=True)
    files: list[Path] = files_of(source)

    archive: Path = out / f"pr-brief-chrome-{version}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name, data in [(CHROME_MANIFEST, (source / CHROME_MANIFEST).read_bytes())] + [(p.as_posix(), (source / p).read_bytes()) for p in files]:
            info = zipfile.ZipInfo(name, ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zipped.writestr(info, data)

    directory: Path = out / "firefox"
    if directory.exists():
        shutil.rmtree(directory)
    for path in files:
        (directory / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / path, directory / path)
    (directory / CHROME_MANIFEST).write_bytes((source / FIREFOX_MANIFEST).read_bytes())
    if load(directory, CHROME_MANIFEST) != firefox:
        raise ValueError("the Firefox manifest was not copied as written")
    return archive, directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, help="the folder to write the Chrome zip and firefox/ into")
    parser.add_argument("--check", action="store_true", help="only compare the two manifests")
    args = parser.parse_args(argv)
    problems: list[str] = manifest_problems()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    if args.check:
        print(f"manifests agree, version {version_of()}")
        return 0
    if not args.out:
        parser.error("give --out DIR, or --check")
    archive, directory = package(args.out)
    print(f"{archive}\n{directory}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
