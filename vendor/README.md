# Vendored from PR-Agent

Source: https://github.com/qodo-ai/pr-agent, MIT license (`LICENSE` in this folder).

| File | Upstream path | Pinned upstream commit |
| --- | --- | --- |
| `pr_description_prompts.toml` | `pr_agent/settings/pr_description_prompts.toml` | `5e9fd335372da85f9c345392337b6f31615af803` (latest commit touching the file) |
| `pr_agent_helpers.py` | `pr_agent/tools/pr_description.py` | `9ed605cc992f18663d2527c35cf990813fba6654` (latest commit touching the file) |

`pr_description_prompts.toml` is byte-identical to upstream at that commit.

`pr_agent_helpers.py` holds the module-level helpers at the end of `pr_description.py`
(`sanitize_diagram`, `apply_diagram_direction` with its edge parsing, `insert_br_after_x_chars`,
`replace_code_tags`), copied verbatim. Only its import block and a `get_logger` stand-in are new.

`render.py` re-implements `_prepare_data`, `_prepare_pr_answer` and `process_pr_files_prediction`
from the same upstream file with PR-Agent's default settings.

To update, fetch both files at a newer commit, replace them, and change the shas above.
