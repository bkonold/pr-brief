"""Per-machine settings, kept out of git.

Settings, runs and the mirror live under HOME: the folder named by the PR_DESCRIBE_HOME environment
variable, or the tool's own folder (ROOT) when it is unset. A repository can therefore keep its own
config, variants and runs outside the tool and point PR_DESCRIBE_HOME at itself. Code, `vendor/` and the
tool's own `variants/` always come from ROOT.

`local.toml` holds the settings that name one repository (see `local.example.toml`). `reach.toml`
and `archetypes.toml` describe one repository's layout; each ships as a
`*.example.toml` and the real file is git-ignored. A missing file or an unset key switches off
whatever depends on it.
"""
import os
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
HOME = Path(os.environ["PR_DESCRIBE_HOME"]).expanduser() if os.environ.get("PR_DESCRIBE_HOME") else ROOT
LOCAL = HOME / "local.toml"

KEYS: frozenset[str] = frozenset({
    "repo", "source_checkout", "github_url", "mirror_name",
    "wiki_repo", "wiki_dir",
    "openapi_path", "migration_dirs", "migration_globs",
    "sdk_dir", "sdk_specifier", "workspace_alias", "workspace_root",
    "test_dirs", "callers_exclude_globs",
    "host", "forgejo_url", "forgejo_token_file",
    "default_variant", "serve_repos",
    "chrome", "model",
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
    real: Path = HOME / f"{name}.toml"
    if real.exists():
        return real
    example: Path = HOME / f"{name}.example.toml"
    return example if fall_back_to_example and example.exists() else None


def variant_file(name: str) -> Path | None:
    """`variants/<name>.toml` under HOME if it exists there, else the tool's own; None when neither has it."""
    for folder in (HOME / "variants", ROOT / "variants"):
        candidate: Path = folder / f"{name}.toml"
        if candidate.exists():
            return candidate
    return None
