"""The model runners `run.py` can send a prompt through: `claude -p` (the default) and the GitHub Copilot CLI.

Each runner turns the system and user prompts into one `Invocation`: the command, what to pipe on its stdin and the
environment to run it in. Nothing here starts a process or reads a token.
"""
import re
import shlex
from dataclasses import dataclass
from typing import Any, Mapping

import yaml

CLAUDE = "claude"
COPILOT = "copilot"
RUNNERS: tuple[str, ...] = (CLAUDE, COPILOT)
DEFAULT_MODELS: dict[str, str] = {CLAUDE: "claude-opus-5-5", COPILOT: "claude-opus-5.5"}

# Copilot takes the system prompt as part of its one input, so the two prompts are fenced off from each other.
SYSTEM_OPEN = "=====SYSTEM INSTRUCTIONS====="
SYSTEM_CLOSE = "=====END SYSTEM INSTRUCTIONS====="
USER_OPEN = "=====USER====="

# The text of `-p`; the prompt itself arrives on stdin, which is too long for an argument.
COPILOT_PROMPT = "The input holds the system instructions and the request. Follow them exactly and reply with only what they ask for."

# The CLI uses its own stored login; a GitHub token in the environment would override it, and a classic PAT is refused.
STRIPPED_ENV: tuple[str, ...] = ("GH_TOKEN", "GITHUB_TOKEN")

FENCED_YAML = re.compile(r"```(?:yaml|yml)[^\n]*\n(.*?)\n```", re.DOTALL)


@dataclass(frozen=True)
class Invocation:
    argv: list[str]
    input: str
    env: dict[str, str] | None


def command_line(call: Invocation) -> str:
    """The command a run starts, as a shell would read it. The arguments never hold a token or the prompt, which
    arrives on stdin."""
    return shlex.join(call.argv)


def resolve_model(runner: str, flag: str | None, local: Mapping[str, Any]) -> str:
    """The model id a run uses: `--model`, else local.toml's `[model]` table entry for the runner, else the runner's
    pinned default. Raises ValueError when local.toml's `model` is not a table of runner names to ids."""
    if flag:
        return flag
    configured: Any = local.get("model", {})
    if not isinstance(configured, dict) or not all(name in RUNNERS and isinstance(model, str) and model
                                                   for name, model in configured.items()):
        raise ValueError(f"`model` in local.toml must be a table of runner ({', '.join(RUNNERS)}) to model id, not {configured!r}")
    return configured.get(runner) or DEFAULT_MODELS[runner]


def copilot_input(system: str, user: str) -> str:
    return f"{SYSTEM_OPEN}\n{system}\n{SYSTEM_CLOSE}\n\n{USER_OPEN}\n\n{user}"


def invocation(runner: str, system: str, user: str, model: str, environ: Mapping[str, str]) -> Invocation:
    if runner == CLAUDE:
        return Invocation(["claude", "-p", "--system-prompt", system, "--tools", "", "--model", model], user, None)
    if runner == COPILOT:
        env: dict[str, str] = {k: v for k, v in environ.items() if k not in STRIPPED_ENV}
        # An empty tool list leaves the model none, and without --allow-all-tools none could run unasked anyway.
        argv: list[str] = ["copilot", "-p", COPILOT_PROMPT, "--model", model, "-s", "--available-tools=",
                           "--no-ask-user", "--no-custom-instructions", "--disable-builtin-mcps"]
        return Invocation(argv, copilot_input(system, user), env)
    raise ValueError(f"unknown runner {runner!r}")


def run_dir_name(variant: str, runner: str) -> str:
    """The folder under runs/<key>/ a run is written to: a Claude run keeps the variant's name, any other runner's
    run sits beside it as `<variant>_<runner>`."""
    return variant if runner == CLAUDE else f"{variant}_{runner}"


def is_mapping(text: str) -> bool:
    """Whether `text` is a YAML mapping once a fence around the whole of it is removed, as render.py reads an answer."""
    stripped: str = re.sub(r"^```(?:yaml)?\n|\n```$", "", text.strip())
    try:
        return isinstance(yaml.safe_load(stripped), dict)
    except yaml.YAMLError:
        return False


def clean_answer(runner: str, raw: str) -> tuple[str, str | None]:
    """The answer text to hand render.py, and what was removed from `raw` to get it (None when nothing was).

    Claude's output is used as it comes. Copilot's is too when it already reads as a YAML mapping; otherwise the first
    fenced yaml block is taken out of the prose around it."""
    if runner == CLAUDE or is_mapping(raw):
        return raw, None
    block: re.Match[str] | None = FENCED_YAML.search(raw)
    if block and is_mapping(block.group(1)):
        return block.group(1) + "\n", "took the first fenced yaml block out of the text around it"
    return raw, None
