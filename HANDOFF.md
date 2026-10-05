# Handoff

For an agent starting on a new machine with none of this project's history. Read `README.md` for commands
and settings; this file says what the tool is for, what has been learned, and what to do next.

## Purpose

Help a reviewer who did not write a change orient in under a minute: what kind of change it is, why it was
made, its shape, and its riskiest part first. The output is a short brief (a diagram, review chunks ordered by
how carefully to read them, and one line per chunk to read first) shown on GitHub's Files changed page by a
browser extension.

Two risks are known and unresolved, so the brief should be treated as a guide and never as a verdict:

- Highlights anchor reviewers toward what is flagged, and they may stop looking elsewhere.
- File order changes what reviewers catch: the first file shown is the likeliest to have its bug found.

## Pipeline

1. `run.py` reads the PR through a host (`hosts/`: `gh` for GitHub, the REST API for Forgejo), builds a prompt from a modified PR-Agent `/describe` prompt (`vendor/`,
   plus the variant's `extra_instructions`, `schema_additions` and `example_additions`) and sends it through
   `claude -p` with no tools. Nothing is posted anywhere.
2. Optionally a context pack (`context_pack.py`, only when `local.toml` configures it): callers of changed
   symbols, app reach, contract diff, destructive migrations and wiki pages. Caller matching is precise
   (`callers_mode = "precise"`), and the pack is capped at 6000 estimated tokens.
3. `render.py` turns `answer.yaml` into the artefacts the extension reads. It:
   - validates each chunk's start line (it must match exactly one line of the diff) and `node_files`;
   - prerenders the Mermaid diagram to `diagram.svg` with headless Chrome;
   - writes `review.json` (schema 2): top level `nodes` and `diagram`; chunks with `n`, `name`, `review`,
     `why`, `files`, `start {path, side, line, text, why?}` and `nodes`;
   - applies the `chunk_box_fallback` (a box for every chunk the model left without one).
4. `compare.py` builds side-by-side pages per PR and `variants.json` for the extension's choice of variant.

`PR_DESCRIBE_HOME` (default: the tool's folder) moves config, `compare.toml`, `runs/`, `.cache/` and extra
variants out of the tool, so a repository can keep them in its own overlay repo with this tool as a submodule
(variants there shadow same-named ones here). Code and `vendor/` stay with the tool.

Config that names a repository is git-ignored: `local.toml`, `reach.toml`, `archetypes.toml`,
`review_floor.toml` (each has a `*.example.toml`). `runs/` is git-ignored too.

## Variant findings

- B (`v11b`) is a single path whose boxes read "step title, then `code: what changed`". It was picked over V10,
  A (code names) and D (layer lanes) because its chunks map to its boxes best. A and D are not in this export.
- Every chunk should get a box. On 13 PRs of a private codebase, `v13` (a prompt rule) and `v12` (the same answer
  plus the fallback) were identical, with 48 of 48 chunks boxed. `v14` (fallback only, on B's answer) boxed
  every chunk but pushed many off the path.
- `v15` adds a reason of at most 15 words to each start line: 32 of 34 were valid, and over-long ones fall back
  to the chunk's `why`.
- On personal repositories, diff-only `v15_nocontext` worked well: every start line resolved and nothing was
  invented. Its weakest case was a doc-only change. Its prompt still contains the paragraph about a
  "Repository context" section, which is simply absent; removing it is untested.

## Diagram style

One minimal-outline style for every kind of change: rounded outlines, the box number before the title, open
arrowheads. The kind of change decides which diagrams appear, not how they look.

| Kind of change | Planned diagram(s) | Status |
| --- | --- | --- |
| Client feature | B: one path, step title then `code: what changed` | B picked overall, not judged per kind |
| Bumps, tests, docs | none, or one muted "Also in this PR" box | hypothesis |
| Infra | resource and permission diff, not a flow | untested |
| API in place | B | picked |
| System or integration | B, maybe plus a system picture | picture untested |
| Thread a field | B plus a field-by-layer table | table untested |
| Mechanical refactor | the pattern once, before and after, plus exceptions; no flow | hypothesis |
| New operation | B plus a contract block (method, request, response, permission) | contract block untested |
| Shared UI | consumer list and screenshots | hypothesis |

## Extension state

What it does (see `extension/README.md`):

- A "By review" chunk list, ordered read carefully, read, skim, replaces GitHub's file tree, one line per chunk;
  the open chunk lists its files by basename.
- A diagram panel is the leftmost pane, before the chunk list. It collapses, resizes, highlights the selected
  chunk's boxes, and has a legend and motion.
- A chunk click lands its first file flush under the pinned toolbar.
- The "Start here" button under the open chunk jumps to the start line: it waits up to 10 seconds for GitHub to render the
  row, re-centres, highlights it and shows the reason on a row beneath it. Clicking a diagram box selects its chunk.
- A "server down" note offers Retry. `variants.json` tells the extension which variants a PR has.

Verified only by injecting code into the page, never through a real extension reload: the start-line highlight and
reason row, the panel move, the light theme, and the saved width and collapsed state. Reload
the unpacked extension on a real PR and check each of them first.

Brittleness: every GitHub selector lives in `extension/github_page.js`. The CSS-module class prefixes
(`[class*="PullRequestDiffsList-module__..."]`, `prc-PageLayout-...`) carry the highest risk, since GitHub can
rename them in any deploy.

Runs are keyed by PR number on GitHub and `fj-<number>` on Forgejo (`runs/<key>/...`). `review.json` records its
`repo` and the extension drops a review for a different `owner/repo`, but two repositories on one host with the same
PR number would overwrite each other. Add an owner/repo key (`runs/<owner>/<repo>/<pr>/`) before using it across
several repositories.

## Next steps, in priority order

1. Make the context pack configurable per repository: `local.toml` and the `*.example.toml` files are in place;
   test them against a real repository, then key runs by owner/repo/PR (see above).
2. Add a selector health check to the extension: when the expected diff blocks, tree host or pane are missing,
   show a clear "GitHub changed its page" note instead of silently doing nothing.
3. A GitHub Action that posts the brief as a sticky PR comment (Mermaid renders in comments), triggered by a
   `/brief` comment or a label, optionally on ready-for-review. The model can run through Copilot CLI with
   `GITHUB_TOKEN` plus the `copilot-requests: write` permission and the organisation policy "Allow use of
   Copilot CLI billed to the organization", or through `openai/codex-action` with an API key. Borrow the
   hardening from the BuilderIO/skills `pr-visual-recap` workflow: plain `pull_request` (not
   `pull_request_target`), skip changes to `.claude/` and CLAUDE.md, a concurrency group per PR, a head-SHA
   check before posting, an upserted sticky comment, and a comment that explains any skip.
4. Ideas from BuilderIO's visual-recap: deterministic before/after contract and migration panels built from the
   diff, and validation that every file, endpoint or table named in chunk text exists in the diff.
5. Optionally, a standalone read-only review page built on the GitHub API, to escape the extension's brittleness.

## First hour on the new machine

```bash
python3 -m venv .venv && .venv/bin/pip install jinja2 pyyaml
node --test extension/test/extension.test.js
.venv/bin/python run.py <pr> --variant one_path_risk_chunked_v15_nocontext --repo <owner>/<repo>
.venv/bin/python compare.py <pr>
python3 -m http.server 8765 --bind 127.0.0.1
```

Then load `extension/` unpacked in Chrome and open the PR's Files changed page. The Python files have no tests;
`render.py` is the part most worth covering (start-line resolution, `node_files` validation, the fallback).
