"""Per-machine settings, kept out of git.

Settings, runs and the mirror live under HOME: the folder named by the PR_BRIEF_HOME environment
variable, or the tool's own folder (ROOT) when it is unset. A repository can therefore keep its own
config, variants and runs outside the tool and point PR_BRIEF_HOME at itself. Code, `vendor/` and the
tool's own `variants/` always come from ROOT.

`local.toml` holds the settings that name one repository (see `local.example.toml`). `reach.toml`
and `archetypes.toml` describe one repository's layout; each ships as a
`*.example.toml` and the real file is git-ignored. A missing file or an unset key switches off
whatever depends on it.

`--config <file>` on run.py and render.py names another TOML to read in place of `local.toml`, with the same keys. It
may also hold the `[reach]` and `[archetypes]` tables, so a repository can keep all its settings in one file; a table
there takes the place of `reach.toml` or `archetypes.toml`. The flag is passed on to the programs a run starts through the
PR_BRIEF_CONFIG environment variable, which can be set instead of the flag.
"""
import os
import tomllib
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).parent
HOME = Path(os.environ["PR_BRIEF_HOME"]).expanduser() if os.environ.get("PR_BRIEF_HOME") else ROOT
CONFIG_ENV = "PR_BRIEF_CONFIG"
DEFAULT_VARIANT = "diagram_walkthrough_v25"

KEYS: frozenset[str] = frozenset({
    "repo", "source_checkout", "github_url", "mirror_name",
    "openapi_path", "migration_dirs", "migration_globs",
    "sdk_dir", "sdk_specifier", "workspace_alias", "workspace_root",
    "test_dirs", "callers_exclude_globs",
    "host", "forgejo_url", "forgejo_token_file",
    "default_variant", "serve_repos",
    "chrome", "model",
    "reach", "archetypes",
})


def use_config_flag(argv: Sequence[str]) -> None:
    """Points PR_BRIEF_CONFIG at the file `--config <file>` (or `--config=<file>`) names in `argv`, as an absolute path, so
    that the settings every module reads when it is imported come from that file. A program calls this before importing
    them; a run's child programs inherit the variable. Does nothing without the flag."""
    for at, argument in enumerate(argv):
        value: str | None = argument.partition("=")[2] if argument.startswith("--config=") else (
            argv[at + 1] if argument == "--config" and at + 1 < len(argv) else None)
        if value:
            os.environ[CONFIG_ENV] = str(Path(value).expanduser().resolve())
            return


def local_path() -> Path:
    """The settings file: the one PR_BRIEF_CONFIG names, else local.toml under HOME."""
    configured: str | None = os.environ.get(CONFIG_ENV)
    return Path(configured).expanduser() if configured else HOME / "local.toml"


def load_local() -> dict[str, Any]:
    """The contents of the settings file (see `local_path`), or an empty dict when it does not exist. A file named with
    `--config` or PR_BRIEF_CONFIG that does not exist is an error."""
    path: Path = local_path()
    if not path.exists():
        if os.environ.get(CONFIG_ENV):
            raise SystemExit(f"the config file {path} does not exist")
        return {}
    settings: dict[str, Any] = tomllib.loads(path.read_text())
    unknown: list[str] = sorted(set(settings) - KEYS)
    if unknown:
        raise SystemExit(f"{path.name} has unknown keys: {', '.join(unknown)}")
    return settings


def config_section(name: str) -> dict[str, Any] | None:
    """The `[<name>]` table of the settings file when it has one, else the contents of `<name>.toml` under HOME, else
    None."""
    inline: Any = load_local().get(name)
    if isinstance(inline, dict):
        return inline
    real: Path = HOME / f"{name}.toml"
    return tomllib.loads(real.read_text()) if real.exists() else None


def variant_file(name: str) -> Path | None:
    """`variants/<name>.toml` under HOME if it exists there, else the tool's own; None when neither has it."""
    for folder in (HOME / "variants", ROOT / "variants"):
        candidate: Path = folder / f"{name}.toml"
        if candidate.exists():
            return candidate
    return None
