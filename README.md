# pr-brief

A short brief for a reviewer who did not write the change: what kind of change it is, the contract and data it
touches, a diagram, and a walkthrough of where to read, in order. It sends a modified PR-Agent `/describe` prompt
through `claude -p` or the GitHub Copilot CLI and renders the answer into `body.md`, `body.html`, `diagram.svg` and a
`review.json` that a browser extension reads. The brief is a guide, never a verdict.

## Use as a GitHub Action

A brief appears on a pull request when someone starts it from the Actions tab (the `workflow_dispatch` run below). From
then on every push rewrites it in place: the Action finds its own comment and updates it, and a push to a pull request
with no brief does nothing. The brief is the Copilot CLI's: the diagram as a `mermaid` block, and a walkthrough linking
to the diff lines. Pin
`bkonold/pr-brief` to a full commit SHA, and store a fine-grained personal access token with the "Copilot Requests"
permission as the secret `COPILOT_PAT`.

```yaml
# .github/workflows/pr-brief.yml
on:
  pull_request:
    types: [synchronize, ready_for_review]
  workflow_dispatch:
    inputs:
      pr: {description: Pull request number, required: true}
      post: {description: Comment on the PR, type: boolean, default: false}
concurrency:
  group: pr-brief-${{ github.event.pull_request.number || inputs.pr }}
  cancel-in-progress: true
permissions: {contents: read, pull-requests: write}
jobs:
  brief:
    if: >-  # pull_request runs skip drafts, Dependabot and forks, which get no secrets
      github.event_name == 'workflow_dispatch' || (github.event.pull_request.draft == false &&
      github.actor != 'dependabot[bot]' && github.event.pull_request.head.repo.full_name == github.repository)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
          ref: ${{ github.event_name == 'workflow_dispatch' && format('refs/pull/{0}/head', inputs.pr) || '' }}
      - uses: bkonold/pr-brief@<full commit sha>
        with:
          copilot-token: ${{ secrets.COPILOT_PAT }}
          pr: ${{ inputs.pr }}
          post: ${{ github.event_name == 'pull_request' || inputs.post }}
          only-if-present: ${{ github.event_name == 'pull_request' }}
```

The settings file takes the keys of `local.example.toml` and a `[reach]` table (which app each path ships in):

```toml
# .github/pr-brief.toml
openapi_path = "api/openapi.json"
migration_dirs = ["db/migrations/"]
[[reach.app]]
name = "web app"
globs = ["web/app/**"]
```

| Input | Default | Meaning |
| --- | --- | --- |
| `copilot-token` | required | The token above, passed to the CLI as `COPILOT_GITHUB_TOKEN`. |
| `config` | `.github/pr-brief.toml` | Settings file in the checkout; a missing file means no settings. |
| `model` | `claude-opus-5.5` | The Copilot model id. |
| `github-token` | `${{ github.token }}` | Reads the PR and writes the comment. |
| `post` | `true` | `false` writes the comment to the job summary and posts nothing. |
| `pr` | empty | The PR number when the event has none (`workflow_dispatch`). |
| `only-if-present` | `false` | `true` refreshes a brief the Action already commented and otherwise ends the job successfully, before installing anything. |

The run folder, with the prompt and repository context, is uploaded as the artifact `pr-brief-<pr>`, so whoever can read
the workflow runs can read it. The checkout needs `fetch-depth: 0`: the callers and contract sections read its history.
If the runner's Chrome cannot start with its sandbox, the diagram is drawn through a wrapper that adds `--no-sandbox`.

## Run it locally

```bash
python3 -m venv .venv && .venv/bin/pip install jinja2 pyyaml
npm ci        # the pinned Mermaid build that draws diagram.svg
```

You need the `claude` CLI signed in (or the Copilot CLI with `copilot login`), the `gh` CLI signed in, Node 24 and
Chrome or Chromium on `PATH` (or named by `PR_BRIEF_CHROME` or the `chrome` key). Copy `local.example.toml` to
`local.toml` and `reach.example.toml` to `reach.toml`; both are git-ignored and every key is optional, and a section
that needs a missing key is skipped, with the reason in `run.json`. Set `PR_BRIEF_HOME` to keep `local.toml`,
`reach.toml`, `runs/` and the mirror in another folder, with your own variants in its `variants/`.

## Commands

```bash
.venv/bin/python run.py 42 --repo owner/name       # write a brief into runs/42/<variant>/, then render it
#   --runner copilot  use the Copilot CLI instead of `claude -p`; --model ID picks the model
#   --config FILE     read FILE in place of local.toml; --variant NAME; --with-body; --prompt-only
#   --host forgejo    read the PR from the Forgejo named in local.toml (forgejo_url, forgejo_token_file); --repo is its owner/name
.venv/bin/python render.py runs/42/<variant>       # re-render a run from its saved answer
.venv/bin/python post.py runs/42 --dry-run         # print the PR comment; without --dry-run, post it with GH_TOKEN
python3 serve.py                                   # serve runs/ on 127.0.0.1:8765 for the extension
```

## Browser extension

Load `extension/` unpacked at `chrome://extensions`, start `serve.py` and paste the token it keeps in
`~/.config/pr-brief/token` into the extension's options. On a PR's Files changed page (GitHub or Forgejo) it draws the
brief and steps through the walkthrough, and offers to generate one when the PR has none. See
[extension/README.md](extension/README.md); its tests run with `node --test extension/test/*.test.js`.

## Further reading

- [docs/rendering.md](docs/rendering.md): the variant, how the renderer treats the answer, and the run folder.
- [docs/prompt.md](docs/prompt.md): how the brief's prompt is assembled, with an example.
- [docs/context.md](docs/context.md): the context packs and how callers are matched.

## Vendored code

`vendor/` holds PR-Agent's `/describe` prompt and its diagram helpers, MIT licensed; `vendor/README.md` says
which upstream commits they come from.

## License

MIT, see `LICENSE`. `vendor/` keeps the MIT notice of PR-Agent, whose prompts and helpers it contains (`vendor/LICENSE`).
