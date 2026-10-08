# pr-describe

Helps a reviewer who did not write a change orient in under a minute: what kind of change it is, its shape,
the contract and data it touches, and a walkthrough of where to read, in order. It sends a modified PR-Agent
`/describe` prompt (vendored in `vendor/`) through `claude -p` (or the Copilot CLI), renders the YAML answer into
a brief (`body.md`, `body.html`, `diagram.svg`) and a `review.json` that a browser extension reads to guide the
reviewer through a GitHub or Forgejo pull request. It only reads from GitHub or Forgejo and never posts
anything. The brief is a guide, never a verdict: highlights can anchor a reviewer toward what is flagged, and
the first file shown is the likeliest to have its bug found.

One variant is current, `one_path_risk_chunked_v23`. Earlier variants live in git history (see "Variant history").

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install jinja2 pyyaml
```

You also need:

- the `claude` CLI, signed in (runs call `claude -p` with no tools), or the GitHub Copilot CLI signed in with
  `copilot login` for `--runner copilot`;
- the `gh` CLI, signed in, which reads a GitHub PR and its diff (not needed for Forgejo, which is read
  through its REST API with a token file named in `local.toml`);
- Google Chrome, for prerendering the diagram to `diagram.svg` (a run still works without it; the
  failure is noted in `error.txt`);
- Node 18 or later, only for the extension's tests (`node --test extension/test/*.test.js`). The host
  and mirror tests run with `.venv/bin/python -m unittest discover -s tests`.

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
(for the host `local.toml` names, GitHub unless `host` says otherwise) and is required when that is unset.

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
.venv/bin/python run.py 42 --variant one_path_risk_chunked_v23 --repo owner/name
#   --with-body       show the model the PR's existing description (default: empty body)
#   --model opus      model passed to the runner (default: opus for claude, claude-opus-5.5 for copilot)
#   --runner copilot  run through the Copilot CLI instead of `claude -p`: the system prompt and the user prompt go on
#                     stdin in two fenced blocks, GH_TOKEN and GITHUB_TOKEN are removed from its environment so the
#                     CLI uses its own login, and the run is written beside the Claude run, to
#                     runs/<key>/<variant>_copilot/ (run.json records `runner` and `model`; `compare.py` shows it
#                     as its own column). Prose around the YAML is stripped and recorded as `answer_cleanup`, the
#                     raw output kept in answer.raw.txt
#   --prompt-only     print the rendered prompt and stop
#   --host forgejo    read the PR from the Forgejo in local.toml (forgejo_url, forgejo_token_file);
#                     --repo is then the Forgejo owner/name. Default: local.toml's `host`, else github

# re-render a run from its saved answer, without calling the model
.venv/bin/python render.py runs/42/one_path_risk_chunked_v23

# build runs/42/index.html and runs/index.html; columns come from compare.toml
# (a Forgejo PR's folder is fj-<number>: compare.py fj-42)
.venv/bin/python compare.py 42
#   --variants a,b    these variants, in this order, instead of compare.toml's
#   --all             every variant that has a run for the PR
```

`archetypes.toml` lists the kinds of change in display order and maps PR numbers to them; `compare.py`
groups the PR index (`runs/index.html`) by kind, with unmapped PRs under Unclassified, and falls back to
a plain list when the file is missing.

Each run writes `runs/<key>/<variant>/`, where `<key>` is the PR number on GitHub and `fj-<number>` on
Forgejo, so the two hosts' numbers cannot collide: `prompt.txt`, `answer.yaml` (raw model output), `pr.json` (the PR
data the run used), `run.json` (including `diagram_edges`, the labelled and total arrows of the diagram),
`body.md`, `body.html`, `diagram.svg`, `review.json` (the extension reads it),
`context.md` and `contract.json` (when the variant has a context pack with a contract section) and `error.txt` on failure or when the renderer
dropped something. Open any `.html` straight from disk. `runs/<key>/status.json` (beside the variant folders) says how far the latest run has got (see Serve the runs). A rerun of the same PR and variant overwrites its
folder. `runs/` is git-ignored: it holds the diffs and prompts of whatever repository you ran against.

## Hosts

`hosts/github.py` runs `gh pr view` and `gh pr diff`; `hosts/forgejo.py` calls Forgejo's
`/api/v1/repos/{owner}/{repo}/pulls/{n}`, `.../commits`, `.../files` (paged) and `.../pulls/{n}.diff` with
`Authorization: token <contents of forgejo_token_file>`. Both return what `pr.json` stores: title, body, head
branch, base and head SHA, commits with headlines, and files with additions and deletions. On Forgejo the base
SHA is the PR's merge base, since the diff is taken against it. Both hosts only read. The body's file and line
links point at the host the run came from (`run.json`'s `host`; a run without one is GitHub).

## Serve the runs and load the extension

```bash
python3 serve.py        # from the repository root; an overlay's own wrapper does the same (`pd serve`)
```

`serve.py` binds to 127.0.0.1:8765 only, uses the standard library, and does two things:

- it serves `$PR_DESCRIBE_HOME` (default: the tool's folder) as static files, so the extension can read the runs;
- it lets the extension start a brief on demand and read which variant to show, through the endpoints under `/api/`.

| Endpoint | Input | Output |
| --- | --- | --- |
| `POST /api/run` | `{host, owner, repo, n}` | `{key, state}`; starts `run.py` in the background with `default_variant` |
| `GET /api/status?key=` | `key` (`7` or `fj-7`); optionally `host`, `owner`, `repo` | `{state, stage, elapsed, error?, allowed?}` from `runs/<key>/status.json` |
| `POST /api/cancel` | `{key}` | `{state}`; kills the run's process group |
| `GET /api/config` | none | `{default_variant, variants}`: the variant a brief shows, and the active variants, which are `compare.toml`'s `variants` read at startup (`[default_variant]` without that file) |
| `GET /api/head?host=&owner=&repo=&n=` | the PR | `{sha}`: the PR's current head commit, read through the host module (`gh` for GitHub, the REST API for Forgejo), or `{sha: null}` with 200 when the host cannot say (logged as one line). Read only, allow-listed repositories only, answers kept 30 seconds |

`state` is `idle`, `running`, `done`, `failed` or `canceled`; `stage` is `fetch`, `context`, `write` or `render`.
`run.py` writes `status.json` at each stage and, on failure, the last line of the error. One run per key (a second
request for a running key returns it), at most two runs at once (a third gets 429), and a run left `running` by a
server that died is marked `failed` ("server restarted") at startup. `local.toml` needs `default_variant` and
`serve_repos` (the repositories a run may be started for); a request for any other repository is refused.

Every `/api/` request must carry the server token in an `X-PR-Describe-Token` header and an `Origin` starting with
`chrome-extension://`, or it gets 403. The token is created on first start in `~/.config/pr-describe/token`
(mode 0600) and is never logged; paste it into the extension's options page ("Server token"). Static files need
neither.

Then open `chrome://extensions`, turn on Developer mode, choose Load unpacked and pick the `extension/`
folder. Open a PR's Files changed page (`https://github.com/<owner>/<repo>/pull/<n>/changes`, or a Forgejo PR's
`<forgejo_url>/<owner>/<repo>/pulls/<n>/files`). The extension finds `runs/<key>/<variant>/review.json` on that
server (`<key>` is `<n>` on GitHub and `fj-<n>` on Forgejo); for a PR with no run it offers to generate one (see Serve the runs, and paste the server token into the extension's options).
`extension/README.md` lists what it does and every GitHub selector it depends on. Run its tests with
`node --test extension/test/*.test.js`.

## Variants

One TOML per variant in `variants/` (see `PR_DESCRIBE_HOME` for adding your own). Keys: `description`, `context` (see
Context packs), `extra_instructions`, `schema_additions` and `example_additions` (inserted after the `changes_diagram`
field in the prompt's schema and example), `[context_options]` and `[render]`. The renderer works with one set of
render settings; a variant's `[render]` may only repeat them, and any other key or value is refused:

| Setting | Value | Effect |
| --- | --- | --- |
| `diagram` | `force_td` | the diagram flows top to bottom |
| `wrapping_width` | 400 | label wrap width of the Mermaid diagram |
| `files` | `chunks` | the changed files are grouped into review chunks |
| `numbering` | `flow` | a box is numbered with the flow number of the chunk that owns it |
| `chunk_order` | `flow` | chunks stay in the model's order; a floor raises a level without moving a chunk |
| `chunk_box_fallback` | true | each chunk still without a diagram box gets one in the `Also in this PR` subgraph |
| `one_box_per_chunk` | true | a note in `error.txt` names every box claimed by several chunks and every chunk with no box or several |
| `contract_block` | true | the Contract and Data sections are built without a model call |
| `contract_layout` | `by_chunk` | each section is one table; each line is placed in the chunk that owns it |
| `review_labels` | true | each chunk carries check labels |
| `review_order` | false | the brief has no review-order table; the chunks are in `review.json` |
| `walkthrough` | true | the model's reading order is resolved into `review.json`'s `walkthrough` |

| Variant | What it is |
| --- | --- |
| `one_path_risk_chunked_v23` | One main path of at most 10 diagram boxes, one box per chunk; chunks with an effort level and check labels; a Contract and a Data section; a walkthrough of 3 to 10 stops in reading order |

`review_floor.toml` sets the minimum review level per path; a rule's `deleted_from = "contract"` raises it to
`level_if_deleted` only for a breaking change (a removal or a newly required field) the run's `contract.json` lists
(see `review_floor.example.toml`).

`compare.toml` lists the variants that make up the default compare pages. `compare.py` also writes
`runs/<pr>/variants.json` (and so does `run.py` after a successful run, adding that run's variant when `compare.toml`
does not list it, so the extension finds a PR run from the server) (`[{variant, label, description}]`) for the
extension's choice of variant, using the labels in `VARIANT_LABELS`.

Variants are frozen once they have been compared. To change one, add a new file; `run.json` records the sha256 of the
variant file that produced each run. A run made by an earlier variant is not shown by the extension, which offers to
re-run it instead.

### What the renderer does with the answer

- **Chunks.** Each chunk is `{name, review, why, files, nodes, checks, step?}` in the answer. The renderer keeps the
  model's order (`chunk_order = "flow"`). A chunk's optional `step` (one or two words, such as `UI`, `API`, `Database`)
  is shown under its number; a longer `step` is dropped with a note. Files the model left out go into a last
  catch-all chunk, which is `skim`.
- **Files inside a chunk** are written in the model's order, with test files last. A file is a test when it matches
  `test_globs` in `local.toml` (default: `**/test/**`, `**/tests/**`, `**/*Test.*`, `**/*Tests.*`, `**/*.test.*`,
  `**/*_test.*`) or contains a `test_dirs` marker.
- **Diagram.** With `node_files` in the answer (`{node id: [paths]}`), the renderer drops paths that are not in the PR
  and node ids that are not on the diagram, gives every box with no files a dashed `context` style, and writes
  `review.json`'s top-level `nodes`: `[{id, files}]`. `chunk_box_fallback` then adds a box
  `chunk<n>["<chunk name><br/><main file basename>"]` in the `also` subgraph to each chunk still without one. A box that
  only skim-level chunks own gets a muted grey `skim` class. Diagrams in `body.html` and `diagram.svg` share one
  minimal-outline theme (`DIAGRAM_STYLE` in `render.py`): rounded outlines, open-chevron arrowheads, hairline
  subgraphs. `body.md` is untouched. Each box gets a `lv-<level>` class and a `chk-<label>` class per label, which the
  theme draws as a level word at the box's top right, a row of chips along the bottom and a border by level (verify
  2px, read 1px, skim dashed and muted).
- **Review levels,** lowest to highest: `skim` (confirm it is what it claims to be: generated files, renames,
  fixtures), `read` (understand what it does and why) and `verify` (convince yourself it is correct, line by line).
  Nothing is skipped: every file gets at least `skim`. A chunk's level is the highest of the model's level and the floors of
  its files, and `raised_by` names what raised it.
- **Labels.** Each chunk carries `labels`, written to `review.json` in this order:

  | Label | Set by | Meaning |
  | --- | --- | --- |
  | `logic` | model | behavior changes: branches, calculations, state transitions |
  | `contract` | model | changes a boundary others consume: REST shape, SDK, public method, event payload |
  | `breaking` | renderer | replaces `contract` on a chunk that owns a "callers must change" or "consumers may break" Contract line |
  | `data` | model | changes persisted state: a migration, a backfill, a new meaning for a column |
  | `destructive` | renderer | replaces `data` on a chunk that owns a destructive Data line |
  | `access` | model | changes permissions, tenant scoping or authentication |
  | `generated` | renderer | every file of the chunk matches a `[[tag]] name = "generated"` glob; a chunk that mixes generated and hand-written files gets a note instead |

  The model gives at most three labels per chunk. `breaking` and `destructive` also raise the chunk to `verify`
  (the floors still apply; the highest level wins) and are named in `raised_by`.
- **Walkthrough.** The answer's `walkthrough` is 3 to 10 stops, `{file, title, why, line_text?}`, in the order a
  reader should follow the change; it is separate from the chunks, and stops may return to a file or chunk already
  visited. The renderer finds a stop's line in the diff the model was shown (embedded in `prompt.txt`), comparing it
  with every added, removed and context line of the file after stripping, and keeps it only when exactly one line
  matches. A kept line is `{path, side, line}` in `review.json`: `side` is `R` with the new-file line number for an
  added or context line, `L` with the old-file number for a removed one. A stop with no line, or whose line is
  missing or ambiguous, stays as the file alone (`side` and `line` null) with a note. A stop in a file outside the PR,
  or at a place an earlier stop already has, is dropped. Each stop records the chunk whose files hold its file, or
  null. A title over 6 words, a `why` over 20, a count outside 3 to 10 and a `verify` chunk that no stop visits each
  leave a note in `error.txt`.
- **Contract and Data** (`contract_block`, `contract_layout = "by_chunk"`) are two sections after the description, built
  without a model call. Each is one closed `<details>` (class `section`) whose summary holds the section's name in bold,
  one chip for each level present, worst first (`callers must change` `additive`; no counts), and the number of table
  rows as muted text (`3 changes`, `1 change`), so they show while it is collapsed. Opened, it holds one GitHub markdown
  table with a row per line, wherever the line was placed. The brief does not mention chunks. Contract rows are sorted
  by worst level, then request before response before both (then no side), then On alphabetically; Data rows by worst
  level, then table, then the document's order; rows with equal keys keep the document's order. With no lines a section
  is a heading and "No API changes" or "No database changes", or that its side was not checked (no `openapi_path` or
  mirror, no `migration_globs`). The Contract side needs `contract.json`; the Data side needs `migration_globs` in
  `local.toml`.

  `contract.json` lists `removals` and `newly_required` (the only entries that raise a review floor) and, for this
  section, `added`, `changed` (a changed property's `from` and `to` types when they differ), `schema_operations` and
  `added_required` (the newly required properties that the base schema did not declare, including in an inline `allOf`
  member; they read `added (required)`, and the others `now required`).

  The Contract table has the columns Impact, Side, Change, On and ↗. The Data table has Impact, Change, Table and ↗.
  Impact is the chip; Side is `request`, `response` or `both` (empty for an operation or a schema no operation reaches);
  Change says what changed, with a `+` or `−` before an added or removed name (`+ productType` required param,
  `+ note` optional, `− archived`, `price` number → string, `moved`, `new GET POST PATCH, +3 schemas`, `+ col` nullable,
  `position` default 0, constraint `uq_x` dropped, `backfill (UPDATE)`); On is the endpoint, schema or family, or for a
  sweep `9 schemas: A, B, C +6`; Table is the table, or for a statement with none the migration file. ↗ is the row's
  only link, to its diff line or its file's diff; names are code, never links. A schema or table name longer than 40
  characters is cut in its middle with the whole name as the element's `title` (an endpoint wraps instead), and each
  table sits in an `overflow-x: auto` container. The chips are `<span class="pill p0|p1|p2">`: the top level is a filled
  inverted chip, the second a bold outlined chip and the rest plain outlined chips. In `body.md`, where GitHub drops
  `class`, the top level is bold and the others plain. Colour is not used.

  Contract levels, worst first. Every change records the side it reaches, request (a body or a parameter) or response; a
  schema used on both sides counts as both and takes the worse level, and a schema no operation reaches counts as both.
  `contract_impact` in `contract_lines.py` holds the full table (every kind of change, per side) in its docstring and is
  the only place that classifies. In short:

  | Level | Changes |
  | --- | --- |
  | callers must change | endpoint removed or moved; parameter or request property added as required, or an existing one made required; request enum value removed; request type changed |
  | consumers may break | response property, schema or enum value removed; response type changed; a constraint changed; a property no longer required (on a response); a request body or security change on an operation |
  | additive | endpoint, schema, parameter or property added (a required property is additive on a response); enum value added; responses changed |
  | deprecated | an operation or property marked `deprecated` |

  Repeated changes collapse into one line, with no cap on the number of lines:

  | Pattern | Line |
  | --- | --- |
  | One property added, removed or changed on 3 or more schemas | `visibility` added on 9 schemas, with its side and the first names |
  | Three or more moves that change only a path prefix | `/old/*` → `/new/*`, 12 endpoints |
  | Operations removed, added or deprecated under one base path | `new /api/base GET POST PATCH`, with the number of new schemas |
  | A pagination parameter (`page`, `size`, `sort`, ...) added to 3 or more endpoints | `pagination added to 12 endpoints` |
  | The same type change (old type → new type) on 3 or more properties, on the same sides | `` `number` → `string` `` on 23 properties in 9 schemas, with its side, then the first three property names and `+N` |
  | Another parameter change on 3 or more endpoints | one line with the endpoint count |
  | Enum values added to one enum | `Enum` + `A`, `B` |
  | Anything else | one line per change |

  Data levels, per migration statement (comments dropped; `;` inside strings and `$$` bodies does not split):

  | Level | Statements |
  | --- | --- |
  | destructive | `DROP TABLE`, `DROP COLUMN`, `TRUNCATE`, `DELETE`, `ALTER COLUMN ... TYPE` to a size-limited or small fixed type |
  | rewrites rows | `UPDATE`; `SET NOT NULL`; any other `ALTER COLUMN ... TYPE`; `ADD CONSTRAINT` (check, unique, primary or foreign key); `ADD COLUMN ... NOT NULL` with no default; `DROP CONSTRAINT`; `DROP INDEX`; any rename (table, column, constraint, index) |
  | additive | `CREATE TABLE`, `CREATE INDEX`, `CREATE VIEW`; `ADD COLUMN` that is nullable or has a default; `SET DEFAULT`; `DROP DEFAULT`; `INSERT` |
  | none | anything else (a `DO` block, a grant): one line naming the kind and the file, such as `DO block in V9.sql`, with no chip |

  The same statement on one table is one line with its count; one column added or dropped on 3 or more tables is one line.

  Placement: an operation goes to the chunk holding the file named for its OpenAPI tag (the tag `item-list-controller`
  is `ItemListController`; `tag_file_templates` in `local.toml` lists other templates), a schema or property to the chunk
  holding a file named for the schema, and a migration statement to the chunk holding its migration file. File names match
  on the part before the first dot, ignoring case; test files and files of a chunk that holds only generated files never
  match. A subject with no such file goes to the chunk whose hand-written code names it: a schema's name in a changed
  file's name or diff, or the last literal segment of an operation's path in a changed line (test files left out),
  preferring the chunks the model labelled `contract`. When no code names the change it goes to the one chunk labelled
  `contract`; with several, to the chunk holding the spec file if that chunk has hand-written files, else to the first
  chunk labelled `contract`; each of these fallbacks is noted in `error.txt`. A line about several subjects goes where
  most of them do, so a sweep over schemas that sit in several chunks is shown in one. A line that nothing places is kept
  in `review.json`'s `unchunked`; the brief shows it like any other. Migration files are the ones matching
  `migration_globs` in `local.toml`.
- **`review.json` is schema 3:** `schema`, `repo`, `pr`, `head_sha`, `variant`, `diagram` (when there is one), `nodes`,
  `unchunked: {contract, data}` and `walkthrough: [{i, title, why, path, side, line, chunk}]`, and a list of chunks
  `{n, name, review, raised_by, why, nodes, labels, contract, data, files[{path, additions, deletions}][, step]}`. A
  chunk's `contract` and `data` are `[{impact, text, change, on, reaches, path, side, line}]`: `text` is the whole
  sentence, `change` and `on` its table cells and `reaches` the Side cell; `impact` is null for a line with no impact and
  `side` and `line` are null when the diff does not settle the line. The chunks come in the model's order; the
  catch-all chunk is last.

## Context packs

A variant with `context = ["callers", "reach", "contract", "migrations", "wiki"]` (any subset, in that
order) fills the prompt's `repo_context` slot with a pack built by `context_pack.py`. Variants without
`context` leave the slot empty. The pack is written to `runs/<pr>/<variant>/context.md`, and `run.json` gets
a `context` key with the item count per section, symbols skipped as too common, sections dropped and why,
and estimated tokens (characters / 4). `run.py --prompt-only` builds the pack too.

| Section | What it lists | Needs (in `local.toml` unless noted) |
| --- | --- | --- |
| callers | Files outside the PR that mention a changed symbol (at most 15 symbols; more than 50 caller files and the symbol is skipped as too common) | `source_checkout` (and `github_url` to fetch missing commits of a GitHub PR) |
| reach | Per app, the changed files and caller files, mapped by globs | `reach.toml` |
| contract | Removed operations, removed schema properties, newly required properties and removed enum values (at most 30 lines), only when the OpenAPI file changed | `openapi_path`, plus the mirror |
| migrations | `DELETE FROM`, `UPDATE`, `DROP`, `TRUNCATE` and `SET NOT NULL` statements in added migration files | `migration_dirs` (the "Contract and data" block uses `migration_globs`) |
| wiki | Up to four pages whose `resource: repo://` paths equal a changed non-test file, ranked by the number of exact matches | `wiki_repo` (and `wiki_dir`) |

The pack is trimmed to 6000 estimated tokens by dropping whole items, wiki first, then callers, reach,
contract and migrations, and the text says how many were left out.

The mirror is a bare clone of your local checkout at `.cache/<mirror_name>` (git-ignored). `ensure_commits`
fetches any base or head commit it lacks, for a GitHub PR from `github_url` through the `gh` credential helper
and for a Forgejo PR from `source_checkout` (the commits of a Forgejo branch are normally already in your clone;
GitHub is never asked), under an
`fcntl` lock on `.cache/mirror.lock`, so parallel runs are safe. With several PRs, call it once for all their
commits before starting parallel runs. When a commit still cannot be found, the callers and contract sections
are dropped, the reason goes in `run.json`, and the run carries on.

Callers are always matched precisely and wiki pages exactly (see below); a variant can set `[context_options]` to
change the rest. An unknown key or value is an error.

| Option | Default | Effect |
| --- | --- | --- |
| `callers_code_only` | `false` | Restricts the callers search to `*.java`, `*.kt`, `*.ts`, `*.tsx`, `*.js`, `*.jsx` and `*.sql` files and excludes markdown, lock files and `callers_exclude_globs`. Reach narrows with it. |
| `callers_skip_new_files` | `false` | Skips the caller search for a symbol declared only in files the PR adds, and lists them as `New in this PR (no outside callers possible)`. |
| `callers_skip_fields` | `false` | Drops names that do not name a Java method with a return type, a type or a TypeScript export, before the 15-symbol cap. |
| `callers_mode` | `"precise"` | Fixed. Only callers that pass rules specific to the declaration are listed, so every listed file really uses the symbol and many real callers are missing. The section says the list is partial. |
| `wiki_match` | `"exact"` | Fixed. Only pages with a `repo://` resource equal to a changed non-test file are kept, ranked by the number of exact matches; pages with no description are skipped. |
| `callers_require_owner` | | Accepted and ignored: precise matching already requires the owner. |

### Precise callers

A file is a caller of a changed symbol only when it passes the rule for the
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

## Variant history

The variants before v23 (v10 to v22, with v11b and v15_nocontext) and their render options are gone from the tree. The
last commit that has them, with their tests and the review-order table, start lines and `next` links they used, is
`c499fc0`: `git show c499fc0:variants/` lists them and `git show c499fc0:README.md` describes each. In short, v10 to v15
grouped files into review chunks with a start line to read first; v16 added `step` and a Contract and data block; v17
to v20 changed what a start line anchors and capped the diagram at 10 boxes with one box per chunk; v21 added effort
levels and check labels; v22 split the block into Contract and Data sections and dropped the review order; v23 replaced
the start lines with the walkthrough. Runs made by those variants are not shown by the extension.
