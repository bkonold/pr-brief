# pr-describe

Compares versions ("variants") of an AI-generated GitHub PR description, and feeds a browser
extension that guides a reviewer through a pull request. It sends PR-Agent's open-source `/describe`
prompt (vendored in `vendor/`) through `claude -p`, renders the YAML answer as the markdown PR-Agent
would publish, and puts the variants side by side in one HTML page per PR. It only reads from GitHub
and never posts anything. `HANDOFF.md` explains the purpose, findings and next steps.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install jinja2 pyyaml
```

You also need:

- the `claude` CLI, signed in (runs call `claude -p` with no tools);
- the `gh` CLI, signed in, which reads the PR and its diff;
- Google Chrome, for prerendering the diagram to `diagram.svg` (a run still works without it; the
  failure is noted in `error.txt`);
- Node 18 or later, only for the extension's tests.

### Per-repository settings

Everything that names one repository lives in files that git ignores, so the tool itself stays generic:

```bash
cp local.example.toml local.toml          # clone location, GitHub URL, wiki, OpenAPI path, ...
cp reach.example.toml reach.toml          # which app each path ships in
cp archetypes.example.toml archetypes.toml
cp review_floor.example.toml review_floor.toml
```

`local.example.toml` explains each key. All of them are optional. When `local.toml` or a key is missing,
the context-pack section that needs it is skipped, with the reason recorded under `context.dropped` in
`run.json`; nothing is cloned, fetched or crashed. `--repo` on `run.py` defaults to `local.toml`'s `repo`
and is required when that is unset. Without any of these files, use the `v15_nocontext` variant.

### Keeping settings and runs outside the tool

Set `PR_DESCRIBE_HOME` to a folder and the tool reads and writes everything there instead of in its own
folder: `local.toml`, `reach.toml`, `archetypes.toml`, `review_floor.toml` (and their `.example.toml`
fallbacks), `compare.toml`, `runs/` and the `.cache/` mirror. Variants are looked up in
`$PR_DESCRIBE_HOME/variants/` first, then in the tool's own `variants/`, so a variant of the same name there
shadows the tool's. Code, `vendor/` and `extension/` always come from the tool. Unset, the variable defaults
to the tool's folder and nothing changes. This lets a repository-specific overlay hold its config and runs
and carry this tool as a submodule.

## Commands

```bash
# run one variant on one PR (calls the model, then render.py)
.venv/bin/python run.py 42 --variant one_path_risk_chunked_v15_nocontext --repo owner/name
#   --with-body       show the model the PR's existing description (default: empty body)
#   --model opus      model passed to claude -p
#   --prompt-only     print the rendered prompt and stop

# re-render a run from its saved answer, without calling the model
.venv/bin/python render.py runs/42/one_path_risk_chunked_v15_nocontext

# build runs/42/index.html and runs/index.html; columns come from compare.toml
.venv/bin/python compare.py 42
#   --variants a,b    these variants, in this order, instead of compare.toml's
#   --all             every variant that has a run for the PR
```

`archetypes.toml` lists the kinds of change in display order and maps PR numbers to them; `compare.py`
groups the PR index (`runs/index.html`) by kind, with unmapped PRs under Unclassified, and falls back to
a plain list when the file is missing.

Each run writes `runs/<pr>/<variant>/`: `prompt.txt`, `answer.yaml` (raw model output), `pr.json` (the PR
data the run used), `run.json` (including `diagram_edges`, the labelled and total arrows of the diagram),
`body.md`, `body.html`, `diagram.svg`, `review.json` (chunked variants only; the extension reads it),
`context.md` (when the variant has a context pack) and `error.txt` on failure or when the renderer
dropped something. Open any `.html` straight from disk. A rerun of the same PR and variant overwrites its
folder. `runs/` is git-ignored: it holds the diffs and prompts of whatever repository you ran against.

## Serve the runs and load the extension

```bash
python3 -m http.server 8765 --bind 127.0.0.1     # from the repository root
```

Then open `chrome://extensions`, turn on Developer mode, choose Load unpacked and pick the `extension/`
folder. Open a PR's Files changed page (`https://github.com/<owner>/<repo>/pull/<n>/changes`). The
extension finds `runs/<n>/<variant>/review.json` on that server; it shows nothing when the run is missing.
`extension/README.md` lists what it does and every GitHub selector it depends on. Run its tests with
`node --test extension/test/extension.test.js`.

## Variants

One TOML per variant in `variants/` (see `PR_DESCRIBE_HOME` for adding your own). Keys: `description`, `context` (see Context packs),
`extra_instructions`, `schema_additions` and `example_additions` (inserted after the `changes_diagram`
field in the prompt's schema and example), and `[render]` with `diagram` (`as_is`, `force_td` or
`force_lr`), `wrapping_width`, `files` (`labels` or `chunks`), `numbering` (`chunks`, the default, or
`boxes`), `start_line` and `chunk_box_fallback`. `review_floor.toml` sets the minimum review level per
path for the chunked file table.

| Variant | What it is |
| --- | --- |
| `one_path_risk_chunked_v10` | One main path of at most 7 boxes, files grouped into review chunks (riskiest first), each with a `start` line to read first |
| `one_path_risk_chunked_v11b` | V10 plus `node_files` (each box's files); boxes read `step title`, then `code name: what changed`. The label comparison's winner |
| `one_path_risk_chunked_v12` | Render-only: v13's answer plus the renderer fallback that boxes any chunk still without one |
| `one_path_risk_chunked_v13` | v11b plus a prompt rule that every chunk owns a box; off-path chunks go in an `Also in this PR` subgraph |
| `one_path_risk_chunked_v14` | Render-only: v11b's answer plus the renderer fallback |
| `one_path_risk_chunked_v15` | v13's prompt plus a `why` of at most 15 words on each start line; renders with the fallback |
| `one_path_risk_chunked_v15_nocontext` | v15 without a context pack, for repositories with no `local.toml` |

A variant with `render_from = "<variant name>"` is render-only. `run.py` makes no model call for it: it
copies `prompt.txt`, `answer.yaml` and `pr.json` from `runs/<pr>/<that variant>/`, writes `run.json` with the
source run's model, timestamps and head sha plus its own name and file sha256, and renders with its own
`[render]` settings. That compares two renderings of one model answer, free of run-to-run variation. It
fails if the source run is missing.

`compare.toml` lists the variants that make up the default compare pages. `compare.py` also writes
`runs/<pr>/variants.json` (`[{variant, label, description}]`) for the extension's variant dropdown, using
the labels in `VARIANT_LABELS`.

Variants are frozen once they have been compared. To change one, add a new file; `run.json` records the
sha256 of the variant file that produced each run.

### What the renderer does with a chunked answer

- Each chunk's `start` is `{file, line_text}` in the answer. The renderer finds that line in the diff the
  model was shown (embedded in `prompt.txt`), compares it with every added, removed and context line of the
  file after stripping, and keeps it only when exactly one line matches. A kept start is `{path, side, line,
  text}` in `review.json`: `side` is `R` with the new-file line number for an added or context line, `L` with
  the old-file number for a removed one. A start that is missing, ambiguous or names a file outside the
  chunk is dropped, with a note in `error.txt`. v15 adds `why`; the renderer keeps it only when it is one to
  15 words.
- With `node_files` in the answer (`{node id: [paths]}`), the renderer drops paths that are not in the PR and
  node ids that are not on the diagram, gives every box with no files a dashed `context` style, and writes
  `review.json`'s top-level `nodes`: `[{id, number, files}]`.
- `numbering = "boxes"` numbers the diagram's boxes 1 to N in declaration order, prefixes each label with its
  number and gives the Review order table a `Boxes` column.
- `chunk_box_fallback = true`: after the model's node ids are validated, each chunk still without a node gets
  a box `chunk<n>["<chunk name><br/><main file basename>"]` in the `also` subgraph. A box that only
  skim-level chunks own gets a muted grey `skim` class.
- Diagrams in `body.html` and `diagram.svg` share one minimal-outline theme (`DIAGRAM_STYLE` in
  `render.py`): rounded outlines, open-chevron arrowheads, hairline subgraphs. `body.md` is untouched.
- `review.json` is schema 2: top-level `nodes` and `diagram`, and chunks with `n`, `name`, `review`, `why`,
  `files`, `start` and `nodes`.
- With `routes_dir` set in `local.toml`, files under it are labelled by their React Router flat-route URL in
  the grouped file list.

## Context packs

A variant with `context = ["callers", "reach", "contract", "migrations", "wiki"]` (any subset, in that
order) fills the prompt's `repo_context` slot with a pack built by `context_pack.py`. Variants without
`context` leave the slot empty. The pack is written to `runs/<pr>/<variant>/context.md`, and `run.json` gets
a `context` key with the item count per section, symbols skipped as too common, sections dropped and why,
and estimated tokens (characters / 4). `run.py --prompt-only` builds the pack too.

| Section | What it lists | Needs (in `local.toml` unless noted) |
| --- | --- | --- |
| callers | Files outside the PR that mention a changed symbol (at most 15 symbols; more than 50 caller files and the symbol is skipped as too common) | `source_checkout` (and `github_url` to fetch missing commits) |
| reach | Per app, the changed files and caller files, mapped by globs | `reach.toml` |
| contract | Removed operations, removed schema properties, newly required properties and removed enum values (at most 30 lines), only when the OpenAPI file changed | `openapi_path`, plus the mirror |
| migrations | `DELETE FROM`, `UPDATE`, `DROP`, `TRUNCATE` and `SET NOT NULL` statements in added migration files | `migration_dirs` |
| wiki | Up to four pages whose `resource: repo://` paths match the changed files (exact path 2 points, same folder 1) | `wiki_repo` (and `wiki_dir`) |

The pack is trimmed to 6000 estimated tokens by dropping whole items, wiki first, then callers, reach,
contract and migrations, and the text says how many were left out.

The mirror is a bare clone of your local checkout at `.cache/<mirror_name>` (git-ignored). `ensure_commits`
fetches any base or head commit it lacks from `github_url` through the `gh` credential helper, under an
`fcntl` lock on `.cache/mirror.lock`, so parallel runs are safe. With several PRs, call it once for all their
commits before starting parallel runs. When a commit still cannot be found, the callers and contract sections
are dropped, the reason goes in `run.json`, and the run carries on.

A variant can set `[context_options]`; without it, or with any option left out, the pack is built as
described above. An unknown key or value is an error.

| Option | Default | Effect |
| --- | --- | --- |
| `callers_code_only` | `false` | Restricts the callers search to `*.java`, `*.kt`, `*.ts`, `*.tsx`, `*.js`, `*.jsx` and `*.sql` files and excludes markdown, lock files and `callers_exclude_globs`. Reach narrows with it. |
| `list_uncalled` | `false` | Adds `No callers outside this PR: A, B` for changed symbols with no outside caller; `run.json` gets `context.uncalled`. |
| `wiki_match` | `"folder"` | `"exact"` keeps only pages with a `repo://` resource equal to a changed non-test file, ranked by the number of exact matches, and skips pages with no description. |
| `callers_skip_new_files` | `false` | Skips the caller search for a symbol declared only in files the PR adds, and lists them as `New in this PR (no outside callers possible)`. |
| `callers_require_owner` | `false` | Keeps a caller only when its file also references the symbol's declaring class (Java) or imports its defining module (TypeScript). |
| `callers_skip_fields` | `false` | Drops names that do not name a Java method with a return type, a type or a TypeScript export, before the 15-symbol cap. |
| `callers_mode` | `"default"` | `"precise"` lists only callers that pass rules specific to the declaration, so every listed file really uses the symbol and many real callers are missing. The section says the list is partial. See below. |

### Precise callers

With `callers_mode = "precise"`, a file is a caller of a changed symbol only when it passes the rule for the
symbol's kind. A candidate file must first match the name as a word in the base commit, in the declaration's
language and outside the PR's files and test directories. Comments are ignored in every check, string
literals in Java ones, and Java `import` lines do not count as a use.

| Declaration | A file counts when |
| --- | --- |
| Java static method | it contains `Owner.method(`, where Owner is the declaring file's class name |
| Java instance method | the name is declared in one class across the base commit's Java sources (implementations that name the declaring type in `implements` or `extends` count as that class; anything else drops the symbol as `ambiguous name`), and the file calls `.method(` on a variable, field or parameter declared with the owner's type |
| TS/TSX export (function, const, type alias, class, interface, enum) | it has an import statement that names the symbol, with multi-line braces, and whose specifier resolves to the defining module: a relative path, or a workspace alias (`workspace_alias` and `workspace_root`); for a symbol under `sdk_dir`, `sdk_specifier` and its subpaths also count |
| Java class, interface, record or enum | it is a Java file that uses the name and either imports the type (its exact import or its package's wildcard) or sits in the declaring file's directory |

A method that is not declared in the base commit's declaring file has no confirmed callers. A name found only
in files of the other language is dropped as `cross-language`; any other symbol without a confirmed caller is
dropped as `no qualified match`.

## Vendored code

`vendor/` holds PR-Agent's `/describe` prompt and its diagram helpers, MIT licensed; `vendor/README.md` says
which upstream commits they come from.
