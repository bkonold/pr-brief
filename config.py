"""Per-machine settings, kept out of git.

`local.toml` holds the settings that name one repository (see `local.example.toml`). `reach.toml`,
`archetypes.toml` and `review_floor.toml` describe one repository's layout; each ships as a
`*.example.toml` and the real file is git-ignored. A missing file or an unset key switches off
whatever depends on it.
"""
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
LOCAL = ROOT / "local.toml"

KEYS: frozenset[str] = frozenset({
    "repo", "source_checkout", "github_url", "mirror_name",
    "wiki_repo", "wiki_dir",
    "openapi_path", "migration_dirs",
    "sdk_dir", "sdk_specifier", "workspace_alias", "workspace_root",
    "test_dirs", "callers_exclude_globs", "routes_dir",
})


def load_local() -> dict[str, Any]:
    """The contents of local.toml, or an empty dict when the file does not exist."""
    if not LOCAL.exists():
        return {}
    settings: dict[str, Any] = tomllib.loads(LOCAL.read_text())
    unknown: list[str] = sorted(set(settings) - KEYS)
    if unknown:
        raise SystemExit(f"local.toml has unknown keys: {', '.join(unknown)}")
    return settings


def config_file(name: str, *, fall_back_to_example: bool = False) -> Path | None:
    """`<name>.toml` when it exists; otherwise `<name>.example.toml` if asked for, else None."""
    real: Path = ROOT / f"{name}.toml"
    if real.exists():
        return real
    example: Path = ROOT / f"{name}.example.toml"
    return example if fall_back_to_example and example.exists() else None
