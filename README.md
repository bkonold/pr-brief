# pr-brief

A short brief for a reviewer who did not write the change: what kind of change it is, the contract and data it
touches, a diagram, and a walkthrough of where to read, in order. It sends a modified PR-Agent `/describe` prompt
through `claude -p` or the GitHub Copilot CLI and renders the answer into `body.md`, `body.html`, `diagram.svg` and a
`review.json` that a browser extension reads. The brief is a guide, never a verdict.

## Use as a GitHub Action

A brief runs three ways:

- A `/brief` comment on a pull request starts one. Only an owner, member or collaborator can, and the Action reacts to the
  comment with a rocket when it starts and a +1 when the brief is posted.
- The Actions tab is the fallback: run the workflow by hand with the pull request number.
- From then on every push rewrites the brief in place: the Action finds its own comment and updates it, and a push to a
  pull request with no brief does nothing.

A comment run uses the workflow on the default branch, so the workflow must be merged there before `/brief` works. The Action skips a pull request from a fork whatever the trigger, ending the job successfully before it installs anything.
The workflow queues runs for one pull request instead of cancelling them, so a push during a `/brief` run waits for the brief to post and then refreshes it; a cancelled start would leave the pull request with no brief for that push to refresh. The brief is the Copilot CLI's: the diagram as a `mermaid` block, and a walkthrough linking
to the diff lines. The comment is one collapsed "PR Brief" block (its summary names the variant and the head commit) that ends with a collapsed "Brief data" block, the run's `review.json`, diagram and
body page gzipped and base64-encoded, which the browser extension reads so that a reviewer needs no server; a comment over
GitHub's size limit loses that block first. Pin
`bkonold/pr-brief` to a full commit SHA, and store a fine-grained personal access token with the "Copilot Requests"
permission as the secret `COPILOT_PAT`.

```yaml
# .github/workflows/pr-brief.yml
on:
  pull_request:
    types: [synchronize, ready_for_review]
  issue_comment:
    types: [created]
  workflow_dispatch:
    inputs:
      pr: {description: Pull request number, required: true}
      post: {description: Comment on the PR, type: boolean, default: false}
concurrency:
  group: pr-brief-${{ github.event.pull_request.number || github.event.issue.number || inputs.pr }}
  cancel-in-progress: false
permissions: {contents: read, pull-requests: write}
jobs:
  brief:
    if: >-
      github.event_name == 'workflow_dispatch'
      || (
        github.event_name == 'pull_request'
        && github.event.pull_request.draft == false
        && github.actor != 'dependabot[bot]'
        && github.event.pull_request.head.repo.full_name == github.repository
      )
      || (
        github.event_name == 'issue_comment'
        && github.event.issue.pull_request
        && startsWith(github.event.comment.body, '/brief')
        && contains(fromJSON('["OWNER", "MEMBER", "COLLABORATOR"]'), github.event.comment.author_association)
      )
    runs-on: ubuntu-latest
    env:
      PR: ${{ github.event.pull_request.number || github.event.issue.number || inputs.pr }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
          ref: ${{ github.event_name != 'pull_request' && format('refs/pull/{0}/head', env.PR) || '' }}
      - uses: bkonold/pr-brief@<full commit sha>
        with:
          copilot-token: ${{ secrets.COPILOT_PAT }}
          pr: ${{ env.PR }}
          post: ${{ github.event_name != 'workflow_dispatch' || inputs.post }}
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
| `pr` | empty | The PR number when the event has none (`workflow_dispatch`, `issue_comment`). |
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

A brief's layers group the diff's hunks into an ordered stack (review.json and the code call them `chunks`). They live in review.json for the browser extension, not in the comment, and `scripts/eval_chunks.py` scores a
brief run against a hand-written grouping (see [eval/](eval/README.md) and [docs/rendering.md](docs/rendering.md)).

## Browser extension

A teammate installs the extension and does nothing else: it reads the brief from the pull request's own comment (the
"Brief data" block the Action posts), with no server and no token. On a PR's conversation page it draws the brief above
the description, and on the Files changed page (GitHub or Forgejo) it steps through the walkthrough. The author can also
load `extension/` unpacked at `chrome://extensions`, start `serve.py` and set its URL and the token it keeps in
`~/.config/pr-brief/token` in the extension's options, which adds generating a brief from the page and showing runs that
were never posted. See [extension/README.md](extension/README.md); its tests run with
`node --test extension/test/*.test.js`.

### Install from a release

- **Chrome:** download `pr-brief-chrome-<version>.zip` from the [latest release](https://github.com/bkonold/pr-brief/releases/latest),
  unzip it, open `chrome://extensions`, turn on Developer mode and choose Load unpacked on the folder. To update, repeat
  that with the newer zip.
- **Firefox:** open the `.xpi` from the same release (Firefox 128 or later). Firefox 127 and later list a Manifest V3
  extension's host permissions in the install prompt and grant them on install, and any host permission can be revoked at
  `about:addons`, under the extension's Permissions tab. If the brief does not appear on GitHub, check that
  `github.com` is allowed there. A release has an `.xpi` only when the maintainer's Mozilla signing keys were set.

Either way that is all a reviewer needs. To generate briefs from your own machine, also start `serve.py` and set its
URL and token in the extension's options, as above.

### Cutting a release

Set `version` to the same value in `extension/manifest.json` and `extension/manifest.firefox.json` (the test workflow
checks that they agree), commit it, then push the tag `v<version>`. The Release workflow checks the tag against the
manifest, creates the release with the Chrome zip, and, when the secrets exist, signs the Firefox build as an unlisted
add-on and attaches the `.xpi`. For that, add the repository secrets `AMO_JWT_ISSUER` and `AMO_JWT_SECRET`, the API key
and secret from the [API keys page](https://addons.mozilla.org/developers/addon/api/key/) on addons.mozilla.org.

## Further reading

- [docs/rendering.md](docs/rendering.md): the variant, how the renderer treats the answer, and the run folder.
- [docs/prompt.md](docs/prompt.md): how the brief's prompt is assembled, with an example.
- [docs/context.md](docs/context.md): the context packs and how callers are matched.

## Vendored code

`vendor/` holds PR-Agent's `/describe` prompt and its diagram helpers, MIT licensed; `vendor/README.md` says
which upstream commits they come from.

## License

MIT, see `LICENSE`. `vendor/` keeps the MIT notice of PR-Agent, whose prompts and helpers it contains (`vendor/LICENSE`).
