# Context packs

A variant with `context = ["callers", "reach", "contract", "migrations"]` (any subset, in that
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

The pack is trimmed to 6000 estimated tokens by dropping whole items, callers first, then reach,
contract and migrations, and the text says how many were left out.

The mirror is a bare clone of your local checkout at `.cache/<mirror_name>` (git-ignored). `ensure_commits`
fetches any base or head commit it lacks, for a GitHub PR from `github_url` (in a GitHub Actions job, the job's own repository when
the config names none) through the `gh` credential helper
and for a Forgejo PR from `source_checkout` (the commits of a Forgejo branch are normally already in your clone;
GitHub is never asked), under an
`fcntl` lock on `.cache/mirror.lock`, so parallel runs are safe. With several PRs, call it once for all their
commits before starting parallel runs. When a commit still cannot be found, the callers and contract sections
are dropped, the reason goes in `run.json`, and the run carries on.

Callers are always matched precisely (see below); a variant can set `[context_options]` to
change the rest. An unknown key or value is an error.

| Option | Default | Effect |
| --- | --- | --- |
| `callers_code_only` | `false` | Restricts the callers search to `*.java`, `*.kt`, `*.ts`, `*.tsx`, `*.js`, `*.jsx` and `*.sql` files and excludes markdown, lock files and `callers_exclude_globs`. Reach narrows with it. |
| `callers_skip_new_files` | `false` | Skips the caller search for a symbol declared only in files the PR adds, and lists them as `New in this PR (no outside callers possible)`. |
| `callers_skip_fields` | `false` | Drops names that do not name a Java method with a return type, a type or a TypeScript export, before the 15-symbol cap. |
| `callers_mode` | `"precise"` | Fixed. Only callers that pass rules specific to the declaration are listed, so every listed file really uses the symbol and many real callers are missing. The section says the list is partial. |
| `callers_require_owner` | | Accepted and ignored: precise matching already requires the owner. |

## Precise callers

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
