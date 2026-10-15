# Vendored from PR-Agent

Source: https://github.com/qodo-ai/pr-agent, MIT license (`LICENSE` in this folder).

| File | Upstream path | Pinned upstream commit |
| --- | --- | --- |
| `pr_agent_helpers.py` | `pr_agent/tools/pr_description.py` | `9ed605cc992f18663d2527c35cf990813fba6654` (latest commit touching the file) |

`prompt.toml`, at the tool's root, is adapted from upstream's `pr_agent/settings/pr_description_prompts.toml` at
`5e9fd335372da85f9c345392337b6f31615af803`: it keeps the diagram field and the answer format, and drops the title,
type and description.

`pr_agent_helpers.py` holds the module-level helpers at the end of `pr_description.py`
(`sanitize_diagram`, `apply_diagram_direction` with its edge parsing), copied verbatim. Only its import block and a `get_logger` stand-in are new.

To update, fetch the file at a newer commit, replace it, and change the sha above.
