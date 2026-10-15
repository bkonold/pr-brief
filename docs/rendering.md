# Variants and rendering

## Variants

One TOML per variant in `variants/` (see `PR_BRIEF_HOME` in the [README](../README.md#run-it-locally) for adding your own). Keys: `description`, `context` (see
[Context packs](context.md)), `extra_instructions`, `schema_additions` and `example_additions` (placed after the `changes_diagram`
field in the schema and example of `prompt.toml`), `hunk_ids` (default false: the prompt's diff carries a `[hNN]` tag at the end of
each `@@` line, and the repository context lists the hunks that belong together; the `brief` variant sets it), `diagram` (default true: false leaves the
`changes_diagram` field out of the prompt) and `[context_options]`. The renderer has one set of settings and a variant
cannot change them. [prompt.md](prompt.md) shows how the variant's rules and fields become the prompt.

| Variant | What it is |
| --- | --- |
| `brief` | One main path of at most 10 diagram boxes, each box the changed files of one step; a walkthrough of 3 to 10 stops in reading order, each stop on one box; and the diff's hunks, each assigned by its `[hNN]` tag to one of an ordered stack of 2 to 7 layers with a title, a summary, the earlier layers it depends on and a risk |

The prompt asks for nothing else: no title, type or description of the PR.

A variant should not be edited once runs have been made with it. To change one, add a new file; `run.json` records the sha256 of the
variant file that produced each run.

## What the renderer does with the answer

- **Diagram.** The answer's `changes_diagram` is a Mermaid flowchart and `node_files` maps each box id to the changed
  files it covers (`{node id: [paths]}`). The renderer drops paths that are not in the PR and node ids that are not on
  the diagram, and gives every box with no files a dashed `context` style; a dashed box exists to show code the change
  reaches but does not edit.
  Each box that stops land on starts with their numbers as a badge (`2 · 5`), and a box with no stop has none.
  `diagram.svg` is drawn in one minimal-outline theme (`DIAGRAM_STYLE` in `render.py`): rounded outlines,
  open-chevron arrowheads, hairline subgraphs. `diagram.md`, the Mermaid text the PR comment shows, carries the badge as
  the label's leading numbers. The text, outline and halo colours follow the page's light or dark theme through Primer's
  `--fgColor-*`, `--bgColor-*` and `--borderColor-*` variables and, where the page defines none, the system's
  `prefers-color-scheme`; the purple accents are the same in both.
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
- **Layers.** The JSON key and the code call them `chunks`. A layer is a set of hunks that tells one story a reviewer can judge on its own, and the layers are an ordered
  stack, each layer sitting on the ones below it. In the `brief` variant, which sets `hunk_ids`, `hunks.py` numbers every hunk of the diff `h01`, `h02`, ... in diff order and tags its
  `@@` line; the answer's `chunks` is `[{title, summary, hunks, depends_on, risk, risk_reason}]` where `hunks` holds only
  those ids, so the model never copies code. The prompt's repository context also lists the hunks that hold one contract or
  data line (the spec line and the code that declares it, the migration statement and its entity) as hunks that belong
  together. The renderer drops an unknown hunk id and one an earlier layer already has (the first assignment wins), drops a
  layer left with no hunk and renumbers the rest, resets a `risk` that is not low, medium or high to low, drops a
  `depends_on` entry that is not a whole number or does not name an earlier layer (and renumbers the rest after drops), and
  gathers the hunks no layer has into a last layer, `Unassigned`; each fix, a title over 8 words, a missing summary and a
  count outside 1 to 7 leave a note in `error.txt`. The layers go to `review.json` for the browser extension, not to the comment.
  `review.json` gets `chunks: [{i, title, summary, risk, risk_reason, depends_on, hunks:
  [{id, path, change, old: [start, count], new: [start, count], added, removed}]}]` only when the answer has a `chunks`
  key, `added` and `removed` being how many of the hunk's lines start with `+` and with `-` (a `\ No newline at end of
  file` marker is neither); the schema is still 4, the two counts being additive. Layers are additive: a missing diagram
  or walkthrough is noted, and no stop left is an error, layers or not. `scripts/eval_chunks.py` scores a run against `eval/<pr>.toml`.
- **Contract and data lines** are built without a model call and are never shown. `contract_lines.py` turns the
  PR's OpenAPI change (`contract.json`, from the context pack) into one line per change or repeated pattern, and
  `data_lines.py` turns each statement of an added migration (by `migration_globs`) into one line; each module's
  docstrings hold its classification tables. The lines feed two things: the file sets below, and the hunks that belong
  together, which the prompt's repository context lists so that the spec line and the code that declares it, or the
  migration statement and its entity, stay in one layer.
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
  Java first and then the client, in `sources`.

  `file_sets` is `{"contract": [paths], "data": [paths], "tests": [paths]}`, each sorted without repeats and empty when
  the PR has none. Contract is the spec when the PR changes it and the source of every contract line, so a changed file that no line
  traces to is not in it; data is the migration files and the source of every data line; tests is the PR's test files,
  by the repo's `test_dirs` and the fixed conventions (`/src/test/`, `.test.`, `Test.java`), for the extension's Tests switch.
- **`review.json` is schema 4:** `schema`, `repo`, `pr`, `head_sha`, `variant`, `diagram` (when there is one),
  `nodes: {id: {title, files, stops}}` (every box of the diagram in order; `title` is the first line of its label,
  `files` the paths it covers and `stops` the numbers of the stops that land on it), `walkthrough: [{i, title, why, path,
  side, line, node}]`, `chunks` (see Layers, only when the answer has them) and `file_sets`.

## Run folder

Each run writes `runs/<pr>/<variant>/`: `prompt.txt`, `answer.yaml` (raw model output), `pr.json` (the PR
data the run used), `run.json`, `diagram.md`, `diagram.svg`, `review.json` (the extension reads it from the PR
comment's "Brief data" block, into which `post.py` packs `review.json` and `diagram.svg`),
`context.md` and `contract.json` (when the variant has a context pack with a contract section) and `error.txt` on failure or when the renderer
dropped something. A rerun of the same PR and variant overwrites its
folder, whichever runner made it; `run.json` records the `runner` and `model`. `runs/` is git-ignored: it holds the diffs and prompts of whatever repository you ran against.
