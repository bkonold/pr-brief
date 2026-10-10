# Variants and rendering

## Variants

One TOML per variant in `variants/` (see `PR_BRIEF_HOME` in the [README](../README.md#run-it-locally) for adding your own). Keys: `description`, `context` (see
[Context packs](context.md)), `extra_instructions`, `schema_additions` and `example_additions` (inserted after the `changes_diagram`
field in the prompt's schema and example) and `[context_options]`. The renderer has one set of settings and a variant
cannot change them. [prompt.md](prompt.md) shows how the variant's rules and fields become the prompt.

| Variant | What it is |
| --- | --- |
| `brief` | One main path of at most 10 diagram boxes, each box the changed files of one step; a walkthrough of 3 to 10 stops in reading order, each stop on one box; a Contract and a Data section for the whole PR |

The prompt no longer asks for the per-file summaries (`pr_files`), which the renderer never used; the vendored prompt has
no switch for its `title` field, which is still asked for and discarded.

A variant should not be edited once runs have been made with it. To change one, add a new file; `run.json` records the sha256 of the
variant file that produced each run. A run made by an earlier variant is not shown by the extension, which offers to
re-run it instead.

## What the renderer does with the answer

- **Diagram.** The answer's `changes_diagram` is a Mermaid flowchart and `node_files` maps each box id to the changed
  files it covers (`{node id: [paths]}`). The renderer drops paths that are not in the PR and node ids that are not on
  the diagram, and gives every box with no files a dashed `context` style; a dashed box exists to show code the change
  reaches but does not edit, and a line under the diagram says "Dashed boxes are unchanged context" when there is one.
  Each box that stops land on starts with their numbers as a badge (`2 · 5`), and a box with no stop has none. Diagrams
  in `body.html` and `diagram.svg` share one minimal-outline theme (`DIAGRAM_STYLE` in `render.py`): rounded outlines,
  open-chevron arrowheads, hairline subgraphs. `body.md` carries the badge as the label's leading numbers.
- **Walkthrough.** The answer's `walkthrough` is 3 to 10 stops, `{node, file, title, why, line_text?}`, in the order a
  reader should follow the change; stops may return to a file or a box already visited. The renderer finds a stop's line
  in the diff the model was shown (embedded in `prompt.txt`), comparing it with every added, removed and context line of
  the file after stripping, and keeps it only when exactly one line matches. A kept line is `{path, side, line}` in
  `review.json`: `side` is `R` with the new-file line number for an added or context line, `L` with the old-file number
  for a removed one. A stop with no line, or whose line is missing or ambiguous, stays as the file alone (`side` and
  `line` null) with a note. A stop in a file outside the PR, or at a place an earlier stop already has, is dropped.
  A stop's `node` must be a box of the diagram that covers files; when it is missing or is not, the stop takes the first
  box, in diagram order, whose files include the stop's file, with a note, and when no box holds the file `node` is null
  with a note. A title over 6 words, a `why` over 20 and a count outside 3 to 10 leave a note in `error.txt`.
- **Contract and Data** are two sections after the description, built
  without a model call. Each is one closed `<details>` (class `section`) whose summary holds the section's name in bold,
  one chip for each level present, worst first (`callers must change` `additive`; no counts), and the number of table
  rows as muted text (`3 changes`, `1 change`), so they show while it is collapsed. Opened, it holds one GitHub markdown
  table with a row per line of the whole PR. Contract rows are sorted
  by worst level, then request before response before both (then no side), then On alphabetically; Data rows by worst
  level, then table, then the document's order; rows with equal keys keep the document's order. With no lines a section
  is a heading and "No API changes" or "No database changes", or that its side was not checked (no `openapi_path` or
  mirror, no `migration_globs`). The Contract side needs `contract.json`; the Data side needs `migration_globs` in
  `local.toml`.

  `contract.json` lists `removals`, `newly_required` and, for this
  section, `added`, `changed` (a changed property's `from` and `to` types when they differ), `schema_operations` and
  `added_required` (the newly required properties that the base schema did not declare, including in an inline `allOf`
  member; they read `added (required)`, and the others `now required`).

  Each section ends with its file set as a short list of links to the files' diffs, `Contract files` and `Data files`
  (see Sources and file sets below); a set with no files draws no list.

  The Contract table has the columns Impact, Side, Change, On and ↗. The Data table has Impact, Change, Table and ↗.
  Impact is the chip; Side is `request`, `response` or `both` (empty for an operation or a schema no operation reaches);
  Change says what changed, with a `+` or `−` before an added or removed name (`+ productType` required param,
  `+ note` optional, `− archived`, `price` number → string, `moved`, `new GET POST PATCH, +3 schemas`, `+ col` nullable,
  `position` default 0, constraint `uq_x` dropped, `backfill (UPDATE)`); On is the endpoint, schema or family, or for a
  sweep `9 schemas: A, B, C +6`; Table is the table, or for a statement with none the migration file. ↗ is the row's
  link, to its diff line or its file's diff. A contract row whose line has a source (below) shows the source instead,
  `Customer.java:18`, with `spec` as a second link to the spec's diff line. Names are code, never links. A schema or table name longer than 40
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
- **Sources and file sets.** The spec is generated from the Java code, so a contract line can say where the code
  declares what changed (`sources.py`). springdoc names a schema after the simple name of its record, class or enum and
  an operation's `operationId` after the controller method (an overload's `_1` suffix is dropped). Among the PR's
  changed files, and never a test file, the renderer finds, in the diff at the head commit:

  | Line | Source |
  | --- | --- |
  | property added, removed, changed or deprecated | the line declaring it as a record component or field, in the changed Java file named `<Schema>.java` (or, for a nested record, the only changed Java file that declares it) |
  | schema added or removed | that file's `record <Schema>`, `class <Schema>` or `enum <Schema>` line |
  | enum value added or removed | the line of the constant, in the schema's file, else a file named for the property that holds the enum (`Status` for `status`), else the only changed Java file that declares it |
  | operation added, removed, changed or moved, or a parameter change | the method whose name is the operationId, in a changed Java file that is a controller, or the `@...Mapping` annotation above it when the diff shows that |
  | data line with a table | the changed Java file whose `@Table(name = "<table>")` names it, at that annotation; when the diff does not show the annotation, the file at the head commit is read from the mirror |

  A controller is a Java file with `@RestController` or `@Controller`, in the file at the head commit or else in its
  diff. No directory settings are involved: every changed non-test Java file is searched.

  The generated TypeScript client under `sdk_dir` declares the same things, so a contract line also has a source in each
  changed non-test `.ts` file there that declares it, found in the diff first and then in the file at the head commit:

  | Line | Source |
  | --- | --- |
  | schema | the `export interface`, `export type` or `export const` line of its name |
  | property | the `name:` row of that interface or type, between its `export` line and the next declaration |
  | enum value | the `VALUE: "VALUE"` row of the `export const` object of the enum |
  | operation | the `operationId: (` member of the client's operations |

  A line the PR's files do not settle has no source (a removed endpoint whose controller the PR does not touch, for one).
  A line that stands for several schemas or operations has the source of its first match in `source`, and every source,
  Java first and then the client, in `sources`; the table row links the first one.

  `file_sets` is `{"contract": [paths], "data": [paths]}`, each sorted without repeats and empty when the PR has none.
  Contract is the spec when the PR changes it and the source of every contract line, so a changed file that no line
  traces to is not in it; data is the migration files and the source of every data line.
- **`review.json` is schema 4:** `schema`, `repo`, `pr`, `head_sha`, `variant`, `diagram` (when there is one),
  `nodes: {id: {title, files, stops}}` (every box of the diagram in order; `title` is the first line of its label,
  `files` the paths it covers and `stops` the numbers of the stops that land on it), `walkthrough: [{i, title, why, path,
  side, line, node}]`, the table lines `contract` and `data`: `[{impact, text, change, on, reaches, path, side,
  line, source, sources}]`, where `text` is the whole sentence, `change` and `on` its table cells and `reaches` the Side cell;
  `impact` is null for a line with no impact, `side` and `line` are null when the diff does not settle the line, and
  `source` is `{path, side, line}` in the PR's own code or null (`side` is `L` for a removed line) and `sources` is every
  such location in a list; and `file_sets`. A run made before `source` and `file_sets` existed has neither, and one made
  before `sources` existed has no `sources`.

## Run folder

Each run writes `runs/<key>/<variant>/`, where `<key>` is the PR number on GitHub and `fj-<number>` on
Forgejo, so the two hosts' numbers cannot collide: `prompt.txt`, `answer.yaml` (raw model output), `pr.json` (the PR
data the run used), `run.json` (including `diagram_edges`, the labelled and total arrows of the diagram),
`body.md`, `body.html`, `diagram.svg`, `review.json` (the extension reads it, from the PR comment's "Brief data" block or from the local server; `post.py` packs `review.json`, `diagram.svg` and `body.html` into that block),
`context.md` and `contract.json` (when the variant has a context pack with a contract section) and `error.txt` on failure or when the renderer
dropped something. Open any `.html` straight from disk. `runs/<key>/status.json` (beside the variant folders) says how far the latest run has got. A rerun of the same PR and variant overwrites its
folder, whichever runner made it; `run.json` records the `runner` and `model`. `runs/` is git-ignored: it holds the diffs and prompts of whatever repository you ran against.
