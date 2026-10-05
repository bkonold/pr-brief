# pr-describe

Compares versions ("variants") of an AI-generated GitHub or Forgejo PR description, and feeds a browser
extension that guides a reviewer through a pull request. It sends PR-Agent's open-source `/describe`
prompt (vendored in `vendor/`) through `claude -p`, renders the YAML answer as the markdown PR-Agent
would publish, and puts the variants side by side in one HTML page per PR. It only reads from GitHub
or Forgejo and never posts anything. `HANDOFF.md` explains the purpose, findings and next steps.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install jinja2 pyyaml
```

You also need:

- the `claude` CLI, signed in (runs call `claude -p` with no tools);
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
(for the host `local.toml` names, GitHub unless `host` says otherwise) and is required when that is unset. Without any of these files, use the `v15_nocontext` variant.

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
#   --host forgejo    read the PR from the Forgejo in local.toml (forgejo_url, forgejo_token_file);
#                     --repo is then the Forgejo owner/name. Default: local.toml's `host`, else github

# re-render a run from its saved answer, without calling the model
.venv/bin/python render.py runs/42/one_path_risk_chunked_v15_nocontext

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
`body.md`, `body.html`, `diagram.svg`, `review.json` (chunked variants only; the extension reads it),
`context.md` and `contract.json` (when the variant has a context pack with a contract section) and `error.txt` on failure or when the renderer
dropped something. Open any `.html` straight from disk. `runs/<key>/status.json` (beside the variant folders) says how far the latest run has got (see Serve the runs). A rerun of the same PR and variant overwrites its
folder. `runs/` is git-ignored: it holds the diffs and prompts of whatever repository you ran against.

## Hosts

`hosts/github.py` runs `gh pr view` and `gh pr diff`; `hosts/forgejo.py` calls Forgejo's
`/api/v1/repos/{owner}/{repo}/pulls/{n}`, `.../commits`, `.../files` (paged) and `.../pulls/{n}.diff` with
`Authorization: token <contents of forgejo_token_file>`. Both return what `pr.json` stores: title, body, head
branch, base and head SHA, commits with headlines, and files with additions and deletions. On Forgejo the base
SHA is the PR's merge base, since the diff is taken against it. Both hosts only read. The body's file and
start-line links point at the host the run came from (`run.json`'s `host`; a run without one is GitHub).

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

One TOML per variant in `variants/` (see `PR_DESCRIBE_HOME` for adding your own). Keys: `description`, `context` (see Context packs),
`extra_instructions`, `schema_additions` and `example_additions` (inserted after the `changes_diagram`
field in the prompt's schema and example), and `[render]` with `diagram` (`as_is`, `force_td` or
`force_lr`), `wrapping_width`, `files` (`labels` or `chunks`), `numbering` (`chunks`, the default, or
`boxes` or `flow`), `chunk_order` (`risk`, the default, or `flow`), `start_line`, `file_start`, `chunk_box_fallback`, `one_box_per_chunk`, `contract_block`, `contract_layout`, `review_order` and `review_labels`. `review_floor.toml` sets the minimum review level per
path for the chunked file table; a rule's `deleted_from = "contract"` raises it to `level_if_deleted` only for a
breaking change (a removal or a newly required field) the run's `contract.json` lists (see `review_floor.example.toml`).

| Variant | What it is |
| --- | --- |
| `one_path_risk_chunked_v10` | One main path of at most 7 boxes, files grouped into review chunks (riskiest first), each with a `start` line to read first |
| `one_path_risk_chunked_v11b` | V10 plus `node_files` (each box's files); boxes read `step title`, then `code name: what changed`. The label comparison's winner |
| `one_path_risk_chunked_v12` | Render-only: v13's answer plus the renderer fallback that boxes any chunk still without one |
| `one_path_risk_chunked_v13` | v11b plus a prompt rule that every chunk owns a box; off-path chunks go in an `Also in this PR` subgraph |
| `one_path_risk_chunked_v14` | Render-only: v11b's answer plus the renderer fallback |
| `one_path_risk_chunked_v15` | v13's prompt plus a `why` of at most 15 words on each start line; renders with the fallback |
| `one_path_risk_chunked_v15_nocontext` | v15 without a context pack, for repositories with no `local.toml` |
| `one_path_risk_chunked_v16` | v15's prompt plus a `step` of one or two words on each chunk, chunks returned in the order the change flows through the system, and a "Contract and data" block after the description |
| `one_path_risk_chunked_v17` | v16 with a different `start` rule: the line where this step of the flow begins for a reviewer (the entry point or the method the previous step calls into), with a `why` saying what it sets up, instead of the line where the risk is decided |
| `one_path_risk_chunked_v18` | v17 with the diagram's main path capped at 10 nodes instead of 7 |
| `one_path_risk_chunked_v19` | v18 with one diagram box per chunk: each chunk's `nodes` is exactly one box, each changed box is exactly one chunk, and one file's changes that serve two steps are merged into one box |
| `one_path_risk_chunked_v20` | v19 with a start that is a line when one clearly anchors the chunk, else a file and why to open it first (`line_text` is optional; the renderer's `file_start` option keeps a file-only start) |
| `one_path_risk_chunked_v21` | v20 with effort levels (`verify`, `read`, `skim`) and check labels on each chunk: the model gives each chunk one level and up to three of `logic`, `contract`, `data`, `access`; the renderer adds `breaking`, `destructive` and `generated` (the `review_labels` render option) |
| `one_path_risk_chunked_v22` | v21's prompt with the "Contract and data" block replaced by a Contract section and a Data section grouped by chunk (the `contract_layout = "by_chunk"` render option) and no Review order in the brief (`review_order = false`); a chunk is `breaking` or `destructive` by the lines it owns |

A variant with `render_from = "<variant name>"` is render-only. `run.py` makes no model call for it: it
copies `prompt.txt`, `answer.yaml` and `pr.json` from `runs/<pr>/<that variant>/`, writes `run.json` with the
source run's model, timestamps and head sha plus its own name and file sha256, and renders with its own
`[render]` settings. That compares two renderings of one model answer, free of run-to-run variation. It
fails if the source run is missing.

`compare.toml` lists the variants that make up the default compare pages. `compare.py` also writes
`runs/<pr>/variants.json` (and so does `run.py` after a successful run, adding that run's variant when `compare.toml` does not list it, so the extension finds a PR run from the server) (`[{variant, label, description}]`) for the extension's choice of variant, using
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
  With `file_start = true` (v20), `line_text` is optional: a start that quotes no line, or whose line is not found exactly once,
  is kept as the file alone, with `side` and `line` null in `review.json` (a note records an unresolved line). Its review-order
  cell links the file's diff and shows the `why`.
- With `node_files` in the answer (`{node id: [paths]}`), the renderer drops paths that are not in the PR and
  node ids that are not on the diagram, gives every box with no files a dashed `context` style, and writes
  `review.json`'s top-level `nodes`: `[{id, number, files}]`.
- `contract_block = true` puts a "Contract and data" section right after the description, built without a model
  call: one line per API operation the OpenAPI diff touches (a badge each for new, removed, a field added or made
  required, a parameter added) and one per table the PR's migration files touch (`CREATE TABLE`, `ADD COLUMN`,
  `DROP`, and so on; destructive and breaking changes are bold). Each line and badge links to its line in the
  diff, or to the file's diff when the diff does not settle which line it is. A change to a shared schema is listed
  on the operations that use it. With no changes the section says "No API or database changes"; a side that could
  not be checked (no `openapi_path` or mirror, no `migration_globs`) is named. It needs `contract.json` for the API
  side and `migration_globs` in `local.toml` for the database side. `contract.json` lists `removals` and
  `newly_required` (the only entries that raise a review floor) and, for this block, `added`, `changed` (a changed property's `from` and `to` types when they differ),
  `schema_operations` and `added_required` (the newly required properties that the base schema did not declare, including
  in an inline `allOf` member; v22 words them `added (required)`, and the others `now required`).
- `contract_layout = "by_chunk"` (v22; needs `contract_block` and `files = "chunks"`) replaces the single block with two
  sections, **Contract** and **Data**. Each starts with a glance line, the section's name being the heading above it:
  the count at each level as chips, worst first, zeros left out (`2 callers must change` `1 consumer may break`
  `2 additive`). Then one group per chunk that owns lines, and a last group, "Not in any chunk", for the lines no chunk
  owns. A group of two or more lines is a closed `<details>` headed `<chunk number> · <chunk name>`, a chip for its worst
  level and `K changes` in muted text, holding a GitHub markdown table with a row per line, worst level first and
  otherwise in the document's order; a group of one line is that line as a plain row. Groups are sorted by worst level,
  then chunk number. With no lines a section says "No API changes" or "No database changes", or that its side was not
  checked.

  The Contract table has the columns Impact, Side, Change, On and ↗. The Data table has Impact, Change, Table and ↗.
  Impact is the chip; Side is `request`, `response` or `both` (empty for an operation or a schema no operation reaches);
  Change says what changed, with a `+` or `−` before an added or removed name (`+ productType` required param,
  `+ note` optional, `− archived`, `price` number → string, `moved`, `new GET POST PATCH, +3 schemas`, `+ col` nullable,
  `position` default 0, constraint `uq_x` dropped, `backfill (UPDATE)`); On is the endpoint, schema or family, or for a
  sweep `9 schemas: A, B, C +6`; Table is the table, or for a statement with none the migration file. ↗ is the row's
  only link, to its diff line or its file's diff; names are code, never links. In the "Not in any chunk" group a row
  naming the controller tag (Data: the table) precedes that tag's lines. A name longer than 36 characters is cut in its
  middle with the whole name as the element's `title`, and each table sits in an `overflow-x: auto` container. The chips
  are `<span class="pill p0|p1|p2">`: the top level is a filled inverted chip, the second a bold outlined chip and the
  rest plain outlined chips. In `body.md`, where GitHub drops `class`, the top level is bold and the others plain.
  Colour is not used.

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
  match. A subject with no such file goes to the chunk whose hand-written code names it (the probes of the breaking-change
  placement below). A line about several subjects goes where most of them do, so a sweep over schemas that sit in several
  chunks is shown in one. A line that nothing places goes under "Not in any chunk", under a row per controller tag (data:
  by table).

  With this layout `breaking` is set on a chunk that owns a "callers must change" or "consumers may break" line and
  `destructive` on a chunk that owns a destructive data line, instead of the rule below; both still raise the chunk to
  `verify`. `review.json` gains, on each chunk, `contract` and `data` (`[{impact, text, change, on, reaches, path, side, line}]`; `text` is
  the whole sentence, `change` and `on` its table cells and `reaches` the Side cell; `impact` is null for a line with no
  impact and `side` and `line` are null when the diff does not settle the line) and, at the
  top level, `unchunked: {contract, data}`. Both layouts' older variants render exactly as before; the schema stays 2.
- `review_order = false` (v22; needs `files = "chunks"`) leaves the Review order table out of `body.md` and `body.html`,
  so the brief holds the PR type, the description, Contract, Data and the diagram. The chunks, their order, steps, starts
  and whys are all in `review.json`, which the extension's files view reads, and `review.json` is the same either way.
  The default, `true`, writes the table.
- `chunk_order = "flow"` keeps the chunks in the model's order instead of sorting them by review level, so a
  floor raises a chunk's level without moving it; `numbering = "flow"` numbers the diagram's boxes with the flow
  step of the chunk that owns them. A chunk's optional `step` (one or two words, such as `UI`, `API`, `Database`)
  is kept in `review.json` and shown under its number; a longer `step` is dropped with a note. The review table
  rows (when `review_order` writes the table) carry `data-flow`, the chunk number, and `data-risk`, which the extension
  uses only for a run whose `review.json` it does not have.
- Inside every chunk, whatever the variant, the files are written in this order: the start file (when the chunk has a
  resolved start), then the other files in the model's order, test files last. A file is a test when it matches
  `test_globs` in `local.toml` (default: `**/test/**`, `**/tests/**`, `**/*Test.*`, `**/*Tests.*`, `**/*.test.*`,
  `**/*_test.*`) or contains a `test_dirs` marker. `review.json`'s `files` and the review table list them in that order.
- `numbering = "boxes"` numbers the diagram's boxes 1 to N in declaration order, prefixes each label with its
  number and gives the Review order table a `Boxes` column.
- Review levels, lowest to highest: `skim` (confirm it is what it claims to be: generated files, renames, fixtures),
  `read` (understand what it does and why) and `verify` (convince yourself it is correct, line by line). Nothing is
  skipped: every file gets at least `skim`, and the catch-all chunk of files the model left out is a `skim` chunk.
  Older variants ask for "read carefully"; the renderer reads it as `verify`, in `review.json` and in the floors.
- `review_labels = true` (v21): each chunk carries `labels`, written to `review.json` in this order.
  | Label | Set by | Meaning |
  | --- | --- | --- |
  | `logic` | model | behavior changes: branches, calculations, state transitions |
  | `contract` | model | changes a boundary others consume: REST shape, SDK, public method, event payload |
  | `breaking` | renderer | replaces `contract` when `contract.json` lists a removal or a newly required field |
  | `data` | model | changes persisted state: a migration, a backfill, a new meaning for a column |
  | `destructive` | renderer | replaces `data` when a migration file's added lines contain DROP, DELETE (not `ON DELETE`), TRUNCATE, `ALTER ... TYPE` or `SET NOT NULL` |
  | `access` | model | changes permissions, tenant scoping or authentication |
  | `generated` | renderer | every file of the chunk matches a `[[tag]] name = "generated"` glob; a chunk that mixes generated and hand-written files gets a note instead |

  `breaking` and `destructive` (v21; v22 sets them from the Contract and Data lines it owns, see `contract_layout`) raise the chunk to `verify` (the floors still apply; the highest level wins) and are
  named in `raised_by`. A breaking change is listed against the generated spec, so it is placed on the hand-written
  chunk that makes it, never on a chunk that holds only generated files. A schema's name in a changed file's name or
  diff, or the last literal segment of an operation's path in a changed line (test files left out), picks the
  chunks, preferring those the model labelled `contract`. When no code names the change it goes to the one chunk
  labelled `contract`; with several, to the chunk holding the spec file if that chunk has hand-written files, else to
  the first chunk labelled `contract`; each of these fallbacks is noted in `error.txt`.
  Migration files are the ones matching `migration_globs` in `local.toml`. With the option on, each diagram box
  gets a `lv-<level>` class and a `chk-<label>` class per label, which the theme draws as a level word at the box's
  top right, a row of chips along the bottom and a border by level (verify 2px, read 1px, skim dashed and muted).
- `chunk_box_fallback = true`: after the model's node ids are validated, each chunk still without a node gets
  a box `chunk<n>["<chunk name><br/><main file basename>"]` in the `also` subgraph. A box that only
  skim-level chunks own gets a muted grey `skim` class (variants without `review_labels`).
- `one_box_per_chunk = true`: after the model's node ids are validated, a note in `error.txt` names each box claimed by
  more than one chunk and each chunk with no box or with several. Rendering is unchanged.
- Diagrams in `body.html` and `diagram.svg` share one minimal-outline theme (`DIAGRAM_STYLE` in
  `render.py`): rounded outlines, open-chevron arrowheads, hairline subgraphs. `body.md` is untouched.
- `review.json` is schema 2: top-level `nodes` and `diagram`, and chunks with `n`, `name`, `review`, `why`,
  `files`, `start`, `nodes`, `next` and (v16) `step`. `next` lists the numbers of the up to three chunks to read after
  a chunk. The diagram's arrows are walked from the chunk's boxes: boxes of the same chunk or of no chunk are walked
  through, and a box of another chunk ends that branch and gives its chunk. The chunks come in the order their boxes are
  declared in the diagram. Dotted arrows (returns) and `~~~` links are not followed. A chunk with no boxes, or
  whose walk reaches no other chunk, is followed by the next higher number, and the last chunk by `[]`.
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
| callers | Files outside the PR that mention a changed symbol (at most 15 symbols; more than 50 caller files and the symbol is skipped as too common) | `source_checkout` (and `github_url` to fetch missing commits of a GitHub PR) |
| reach | Per app, the changed files and caller files, mapped by globs | `reach.toml` |
| contract | Removed operations, removed schema properties, newly required properties and removed enum values (at most 30 lines), only when the OpenAPI file changed | `openapi_path`, plus the mirror |
| migrations | `DELETE FROM`, `UPDATE`, `DROP`, `TRUNCATE` and `SET NOT NULL` statements in added migration files | `migration_dirs` (the "Contract and data" block uses `migration_globs`) |
| wiki | Up to four pages whose `resource: repo://` paths match the changed files (exact path 2 points, same folder 1) | `wiki_repo` (and `wiki_dir`) |

The pack is trimmed to 6000 estimated tokens by dropping whole items, wiki first, then callers, reach,
contract and migrations, and the text says how many were left out.

The mirror is a bare clone of your local checkout at `.cache/<mirror_name>` (git-ignored). `ensure_commits`
fetches any base or head commit it lacks, for a GitHub PR from `github_url` through the `gh` credential helper
and for a Forgejo PR from `source_checkout` (the commits of a Forgejo branch are normally already in your clone;
GitHub is never asked), under an
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
