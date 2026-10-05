# Review focus extension

A Chrome extension (Manifest V3) for GitHub's Files changed page and for a Forgejo pull request's files page
(`http://localhost:3300/{owner}/{repo}/pulls/{n}/files`). It reads the `review.json` that `render.py` writes for a
chunked variant and replaces the host's file tree with a list grouped by review chunk, like a "group by
importance" view. It only reads, and posts nothing. Both hosts behave the same; the text below says GitHub
where it describes the page, and the Forgejo selectors are in their own table at the end.

What the list shows, in GitHub's left column between the "Filter files" box and the tree:

- A toggle, "By review" / "GitHub tree", and an "Expand all" / "Collapse all" button. "GitHub tree" brings
  GitHub's own tree back and shows every diff; the toggle stays so you can switch again.
- One line per chunk: its number in bold and its name on the left and, right-aligned, its effort level as a word
  (`verify` in bold default text; `read` and `skim` in the secondary colour). A run from an older variant that says
  "read carefully" shows `verify`. Under the name, a row of check chips from the chunk's `labels` (`logic`, `contract`,
  `breaking`, `data`, `destructive`, `access`, `generated`): outlined 12px pills in the secondary colour, except
  `breaking` and `destructive`, which are filled in the text colour with the background colour as their text. No chip
  or level uses red, green or amber, which read as diff changes. Only the open chunk lists its files; the others stay
  one line plus chips. Groups are ordered by effort level (`verify`, `read`, `skim`), then "Unchunked"; skim-level chunks and "Unchunked" are muted.
  When the run's chunks carry a `step` (v16), the order is the flow of the change as `review.json` lists it, and a quiet
  "Order: by flow | by risk" switch under the toggle reorders the list. The
  switch changes only the order: numbers, selection, start jumps and the diagram highlight are by chunk, so they work in
  both. It is not remembered, so each load opens in flow order; a run with no steps opens by risk and has no switch. A "Not in review" group, in the same one-line style, lists loaded diffs no chunk names.
- Files show only their basename, in small monospace; the chunk's start file is in the primary text colour and the rest are
  muted. A basename shared by two files of the list gets its folder as a dim suffix; the full path is the row's tooltip. The
  file order is the chunk's own. Each row ends with the file's `+<additions> −<deletions>` in 11px tabular numbers, green and
  red from the host's success and danger colours, a zero side left out and none for a file with no lines; the counts are
  right-aligned to the same edge as the chunk rows' level words, and the name truncates before them.
- Clicking a chunk's line focuses the diffs on that chunk, opens it, closes the others and does what its "Start here"
  button does (below); clicking the open chunk jumps again. A chunk with no start scrolls to its first file
  instead. "GitHub tree" mode shows every diff again.
  Clicking a file focuses its chunk and scrolls to its diff. A chunk opened with "Expand all" closes again with "Collapse all" or when another chunk is clicked.
- A "Start here" button under the open chunk's files, when the chunk has a start (the `start` field of `review.json`: the
  one line the model says to read first, or, when no single line anchors the chunk, the file to open first, with `side` and
  `line` null), jumps to that line and centres it, or, for a file start, scrolls to the file's callout above its header. If another chunk is
  focused it focuses this chunk first, since the line's diff is hidden otherwise. GitHub renders a diff's rows only once
  the diff is near the window, so the jump scrolls to the file's diff, waits up to 10 seconds for the row, then centres
  it, measuring the row again after each scroll and nudging until it sits mid-window (GitHub's layout shifts while diffs
  load); on a timeout the view stays at the file's header. The button's tooltip is `file:line`, or the file's basename for a file start. Opening the files page on
  a link to a chunk's start (the PR brief card's links) does the same.
- Every chunk's start that has loaded gets a callout above its line (above the file's header for a file start), as soon as the review shows and as GitHub or Forgejo
  load more of the diff, in both unified and split views. It is a full-width table row holding a neutral card
  (the host's muted surface, a 1px purple border, rounded, from the file pane's left edge, in 14px text) with a route icon,
  a breadcrumb header, `<n> · <box title>` in bold default text, a small muted chevron, then the chunk name in normal weight
  (the box title is the bold title line of the chunk's first diagram box, read from the rendered diagram; a chunk with no
  box, or a box with no title, shows just the bold `<n> · <name>` with no chevron), then on its own line a small muted "Why the LLM picked this" over the
  reason, wrapping if it is long: the chunk's `start.why`, else the chunk's own `why`. Below a hairline, a last row starts
  with a "↑ Previous" button (its tooltip is the chunk's `<n> · <box title>`, else `<n> · <name>`) for the chunk numbered one lower when there is one, then "Next"
  followed by one small button per chunk to read next, `<n> · <box title> ↓` (else `<n> · <name> ↓`), or the quiet text "Last step" when there is none. A button does what a click on that
  chunk in the list does: it focuses, opens and jumps to its start line (a chunk with no start line scrolls to its
  first file). The chunks to read next are the `next` field of each chunk in `review.json`, the same in flow and risk
  order; a run without `next` goes to the chunk with the next higher number. A callout is placed once per chunk, so a
  re-render or a lazy load never doubles it. The callouts show only in "By review" mode, and a focused chunk shows only
  its own, since the other diffs are hidden.
- A file start's callout is the first child of that file's diff entry (the GitHub diff entry, the Forgejo file box), so it sits
  directly above the file header, spans the entry's full width with the same card, and is hidden with the entry. The jump scrolls
  the entry's top just below the sticky chrome, so the callout shows with the header under it, and marks and pulses the callout
  alone. It is placed once, comes back if the host drops it, and goes with the callouts.
- The start line itself is left exactly as the host draws it. Each callout card spans from the file pane's left edge, and
  the jumped-to chunk's card border is the full purple where the other callouts' is purple at 45%. The jump centres the callout and the line together.
  The file, line number and code are not repeated, since the diff row shows them. Only one card is marked as the target; the mark
  goes whenever the line target clears (another selection, a new jump or teardown) and comes back if the host re-renders the
  row. When a jump lands, its callout pulses once: a purple ring that swells from its resting
  width to 3px wider and back, three times over about two seconds (666ms each). It fires on
  every jump from the chunk list or the diagram (a chunk or box click, "Start here") and from a link to a start line, but not
  from the callout's own Next and ↑ buttons, since the reader is already following the callouts. Only the jumped-to chunk pulses,
  and not when the host re-renders the row. Under `prefers-reduced-motion` it does not pulse.
- A banner appears when the review was generated for an older head commit than the page's.

The mode and selected chunk are remembered per PR in `sessionStorage`.

## When the page server is down

If fetching `review.json` fails outright (connection refused, a network error), the list's place above GitHub's tree shows a
note with the base URL, the command to start the server (`pd serve`) and a Retry button; GitHub's tree stays visible. Retry
fetches again and mounts the full list on success. A 404 or an unusable review shows the "Generate brief" line below,
unless the run server says it will not run that repository.

## Which variant is shown

`background.js` fetches `runs/<pr>/variants.json` (`[{variant, label, description}]`, written by `compare.py`) and reads the
server's `GET /api/config` (`{default_variant, variants}`). The run shown is, in order: the server's `default_variant` if
the PR has it; the newest active variant the PR has (active: listed in the config's `variants`); the newest variant the PR
has at all. If the server's config can't be read (server down, token missing), the newest variant the PR has is shown.
Without `variants.json`, only the server's default is tried. "Newest" compares variant names with digit runs as numbers
(`v9` < `v10`). The saved per-PR selection is restored only for the variant it was made in. The files view has no variant
control; the PR brief card on the conversation page names the variant it shows.

## Boxes and files

Clicking a diagram box selects the first chunk, in the order the list shows, whose `nodes` include it and does what
clicking that chunk does: focus, open, jump to its start line. Once the jump has landed the clicked box pulses once (its outline swells from 2px to 3px with an accent tint over
600ms; skipped under `prefers-reduced-motion`). A jump from the list, "Start here" or a callout does not pulse a box. The clicked box keeps a light accent fill tint, stronger
than the chunk highlight, and the chunk's start file is the active file: its list row is bold and its diff header gets a
3px accent bar. A box no chunk lists, and a context box (dashed, default cursor), do nothing when clicked.

The active state clears when another box, a chunk's line, a file row or the mode toggle is used. A file row lands its
file's header just below GitHub's sticky chrome (the offset is measured when the click happens, as the lowest stuck edge
of the page's sticky or fixed elements that span the diff column), then flashes the row and the header for about 1.2s;
under `prefers-reduced-motion` the flash is skipped.

## The change diagram

When `review.json` names a `diagram` (`diagram.svg` in the run directory), `background.js` fetches it with the review
and `diagram.js` docks it as the leftmost pane, right before GitHub's file pane in GitHub's own flex row, so the page reads
diagram, chunk list, code, and the other two columns narrow by the panel's width (280px by default) instead of being
covered. The panel is sticky at the file tree pane's offset and as tall as the pane. Its header's `‹` button collapses it
(remembered in `sessionStorage`) into a 30px rail in the same spot, with "Diagram" written vertically under a `›` button
that expands it.
- The diagram, the chunk list and the code are separated by single dividers: the panel's right border, then GitHub's own
  rule down the pane's right edge.

- Motion: the line jump scrolls smoothly (a target more than 1.5 windows away is first approached instantly to one window
  short of it); newly visible diffs fade in over 150ms; diagram emphasis cross-fades over
  250ms. The emphasized box gets a 2px `#534ab7` stroke (`#b26a00` on save boxes); the diagrams carry no inline `!important`
  styles, so no glow is needed. `prefers-reduced-motion: reduce` turns all of it off, leaving only the end states.
- The panel's right edge is a drag handle: dragging it right widens the panel and narrows the diffs. Width is 220px up to 65% of
  the viewport, 280px by default (double-click the handle to reset), and is remembered in `chrome.storage.local`.
- In a v21 diagram each box shows `<n> · title` in bold at its top left, its effort level as a small secondary word at its
  top right and its chips along the bottom (the same pills as the chunk list), and its border follows the level: `verify`
  2px in the text colour, `read` 1px, `skim` dashed and muted. The selected box keeps the purple outline.
- A legend under the card lists only the styles the SVG uses (changed step, verify, read, skim,
  writes data, unchanged context), each swatch coloured from the page's computed style of a real box, plus "Selected
  chunk" (the emphasis outline) and, when the diagram has lanes, a note that columns are code layers.
- Selecting a chunk (header click, box click or the jump button) highlights its `nodes` and the edges between two of them, and
  dims the rest to 0.25 opacity. A chunk with no nodes dims the whole diagram slightly. "GitHub tree" mode or no
  selection restores it.
- Clicking a box selects its chunk and jumps to its start line (see "Boxes and files").
- The diagram is a pan-and-zoom canvas whose zoom is independent of the panel's width. Pinch, or Cmd/Ctrl + scroll,
  zooms around the pointer (25% to 400%); scroll or a two-finger swipe pans, Shift + scroll pans sideways, and a drag (or
  Space + drag) pans too. A drag that starts on a box pans once it moves more than 4px; a shorter press is a box click.
  The header has −, the current zoom (click it for 100%), + and Fit. While the pointer is over the panel and focus is
  not in a text field, Shift + 1 fits the diagram to the panel's width and Shift + 0 sets 100%. Panning stops when a
  diagram edge reaches the middle of the canvas. Each new diagram opens fitted; resizing the panel keeps the zoom and
  position, and a fitted diagram stays fitted. Zoom and position are not saved.
- The SVG is parsed with `DOMParser` and stripped of `<script>`, `on*` attributes and `javascript:` links first.
  GitHub's CSP allows the SVG's own `<style>` and inline `style` attributes, so no restyling is needed.
- Mermaid 11 ids: a node is `<g class="node" id="pr-diagram-flowchart-<nodeId>-<n>">`; an edge is a `path` with
  `data-id="L_<from>_<to>_<n>"` (its label group has the same `data-id`). Node ids can contain underscores, so edge
  ends are matched against the known node ids.

## Generating a brief on demand

`serve.py` (see the top-level README) can start a run for the PR on the page. The extension never talks to it from a
page script: `background.js` makes the calls (`startRun`, `runStatus`, `cancelRun` to `/api/run`, `/api/status`,
`/api/cancel`) and adds the server token, which the options page keeps in `chrome.storage.local` ("Server token":
paste the contents of `~/.config/pr-describe/token`). The server also requires an `Origin` of `chrome-extension://`,
which only the background script sends.

`run_control.js` owns one run's progress for a PR page: it starts the run, asks `/api/status` every 3 seconds, ticks
a one-second clock between polls and reports to the page. The card and the files view's line both draw from it.

- **Conversation page, no run:** the card is a bar with "PR brief", "local, not posted" and a "Generate brief" button.
- **Running:** "Writing brief · m:ss", a pill per stage (Fetch PR, Gather context, Write, Render; done ones green, the
  current one in the accent colour) and a Cancel link. Leaving the page does not stop the run; the next visit asks
  the server and resumes from where it is. When the run is done the brief is loaded and drawn, closed.
- **Stale:** when the run's `head_sha` differs from the PR's current head (`page.currentHeadSha`: the page's own value
  when it shows one, which on GitHub is only the files view's embedded page data, else the host's answer: Forgejo's
  read-only API, or for GitHub the server's `GET /api/head`, asked through `background.js`), the badge reads "for
  <short>, PR is at <short>" and a "Regenerate" button sits beside "Review in files view".
- **Current or unknown head:** a quiet "Regenerate" link in the card header does the same. Whenever generating is
  allowed, regeneration is offered; with it not allowed, neither the button nor the link is shown.
- **Failure:** the error line and a Retry button. A failed call says why: "Start the server with `pd serve` to generate
  briefs" (nothing listening), "Server token missing or wrong — set it in the extension options" (403) or "2 briefs
  already running" (429).
- **Files view, no run:** where the list would be, one line, "No brief for this PR yet" and a "Generate brief" button, which
  runs the same flow and mounts the full list when the run is done.
- Both are offered only where the server may run that repository: `/api/status` is asked with the host, owner and repo
  and says `allowed`. When it cannot be asked (server down, wrong token) they are shown anyway, so the reason can be.

## The PR brief card

On a PR's conversation page (GitHub `/{o}/{r}/pull/{n}`, Forgejo `/{o}/{r}/pulls/{n}`) the extension puts a "PR brief"
card above the PR's description when the PR has a run (`prFromUrl` returns `view: "conversation"`; the files page is
`view: "files"` and behaves as before). The card is local: its badge says "local, not posted", nothing is written to
the page's data, and its header links to the files view. Without a run it is the "Generate brief" bar described above.

- It is a `<details>` in a shadow root, built closed every time the page loads; nothing about it is stored. Its colours
  are the site's own Primer names (Forgejo's are mapped by its adapter), with light and dark fallbacks.
- `body.html` from `render.py` is a standalone page that draws itself: the description is a markdown string in a
  script, rendered by `marked` and `mermaid`. `brief_text.js` reads that string, renders the subset of markdown
  `render.py` writes, and drops every script, event handler and non-web link. The mermaid source, the title and the
  "Diagram Walkthrough" heading are left out; `diagram.svg` goes in its own closed "Diagram" `<details>` under the
  description's bullets and above the review order, with the legend under it, on a white panel in both themes. The
  card is one column, and each top-level bullet in the description has a blank line's space after it.
- A "Contract and data" section, when the run has one (v16), is a list of API operations and tables with badges; each
  line and badge is a link to the diff line it names, rewritten to this host's files view like the other links.
- The review order of a run with steps carries the same "Order: by flow | by risk" switch under its heading. It reorders
  the rows in place (their numbers stay the flow numbers, which are the diagram's labels), keeps the review order open,
  and is not remembered. The rows carry `data-flow` and `data-risk`; a body with none shows no switch.
- The review order shows with its `<details>` closed, and each chunk's file list is a closed `<details>` headed by the
  file count. A chunk's start (the file:line link and the quoted line, or the file link and the reason for a file start) sits in a closed "Start here" `<details>` under
  the chunk name. Links into the PR's files view are rewritten to this host's files view, fragment kept.
- A chunk's start link opens the files view with that line's anchor (a file start's, the file's diff id) in the fragment. When the files page loads with a
  fragment that is a chunk's start anchor, `content.js` runs the same jump as the chunk's "Start here" button; any other
  fragment is left to the page.
- `background.js` answers `loadBrief` by fetching `body.html` and `diagram.svg` of the run the variant choice above selects,
  the way it fetches `review.json` (and the run's `head_sha`). With no run, or the page server down, the card is the
  "Generate brief" bar, except where the server says it will not run the PR's repository: then nothing is mounted.
- The conversation page is watched while the card is mounted, so a host that re-renders its timeline gets the card
  back above the description; `onNavigate` mounts it again after client-side navigation, and one card exists at a time.

## Load it

1. From the `pr-describe` root, serve the runs and the API: `python3 serve.py` (an overlay's wrapper: `pd serve`).
2. Open `chrome://extensions`, turn on Developer mode, choose Load unpacked and pick this `extension/` folder.
3. Open a PR's Files changed page, such as `https://github.com/<owner>/<repo>/pull/<n>/changes`, or a Forgejo PR's
   `http://localhost:3300/<owner>/<repo>/pulls/<n>/files`.

The list appears only when `runs/<key>/<variant>/review.json` exists for the PR (404, a server that
is down or a different repo leave the page untouched). `<key>` is the PR number on GitHub and `fj-<number>` on
Forgejo (`run.py --host forgejo`). `review.json` records its `repo`, which the extension compares with the page's `owner/repo`; two repositories on one host with the same PR number would overwrite each other's runs. The variant comes from the server (`default_variant` in `local.toml`, see Which variant is shown); the extension's options page holds the server URL and token. The
manifest allows `http://127.0.0.1:8765` for the runs and `http://localhost:3300` for Forgejo, so another origin
also needs a `host_permissions` entry (and a `matches` entry for a Forgejo elsewhere). Loading a version that adds a host
makes Chrome ask for the new permission when the extension is reloaded.
After editing a file, reload the extension on `chrome://extensions` and refresh the GitHub tab.

Run the pure tests with `node --test test/*.test.js`.

## Files

| File | Role |
| --- | --- |
| `background.js` | Fetches `review.json` and the run's brief for the content script, and calls the run server's API with the token; the page server sends no CORS headers |
| `serve_api.js` | Sorts a run-server response into success or a problem (server down, token, busy, error); an ES module used by `background.js` |
| `run_control.js` | Starts a run and follows it: polling, the elapsed clock, stage pills, failure messages |
| `page_common.js` | What every host's page shares: sticky-offset scrolling, the line jump, the start-line callouts, change watching. `createPage(spec)` builds an adapter from a host's spec |
| `github_page.js` | The only module with GitHub selectors; builds the GitHub adapter |
| `forgejo_page.js` | The only module with Forgejo selectors; builds the Forgejo adapter |
| `page.js` | Picks the adapter whose `hosts` lists `location.host` and exposes it as `prFocus.page`, which `content.js`, `focus.js`, `tree.js` and `diagram.js` call |
| `focus.js` | Hides diffs outside a chunk and scrolls to a diff |
| `tree.js`, `tree.css`, `focus.css` | The grouped list, the start-line callout card and the next and previous chunk it links to, and the classes `focus.js` and the line jump toggle |
| `content.js` | Wiring: URL changes, debounced re-apply, expansion and selection state |
| `classify.js` | Tells a failed request (server down) from a non-OK response (no run) |
| `choose_variant.js` | Which variant to load (an ES module, used by `background.js`) |
| `diagram.js`, `diagram.css` | The diagram panel, its overlay and chunk emphasis |
| `source.js` | Content-script side of the fetch |
| `brief_text.js` | Turns a run's `body.html` into the card's safe HTML, and reorders the review-order rows by flow or risk (pure string work, tested without a DOM) |
| `brief.js` | Builds the PR brief card in a shadow root and draws its views: no run, running, failed, brief, stale |

The content scripts are classic scripts sharing `globalThis.prFocus`, loaded in the order listed in `manifest.json`.

### The page adapter

Everything the rest of the extension asks of the page goes through one object, `prFocus.page`: `name`, `treeLabel`,
`prFromUrl` (`{owner, repo, pr, view}`, `view` being `"files"` or `"conversation"`) / `pullFromUrl` (`{owner, repo, pr}`), `filesUrl(pr)`, `runKey(pr)` (the `runs/` folder), `headSha`, `fileBlocks`, `entryOf`,
`diffEntries`, `entryFor`, `lineAnchor`, `scrollToElement`, `fileHeaderOf`, `jumpToLine`, `clearLineTarget`,
`restoreLineTarget`, `ownsLine`, `cancelJump`, `diagramHost`, `treeHost`, `descriptionHost`, `onChange` and `onNavigate`. A new host is a
spec for `createPage` (see the comment at the top of `page_common.js`) plus an entry in `manifest.json` and `page.js`.

## GitHub selectors (observed 2026-10-04 on GitHub's React-based Files changed page)

All in `github_page.js`. Class names carry hashed suffixes, so they match on a `[class*="..."]` prefix.

| What | Selector or rule |
| --- | --- |
| Diff block | `div[id^="diff-"]` with class containing `Diff-module__diffTargetable`; id is `diff-` + sha256 hex of the file path |
| Entry hidden | the block's ancestor `div[class*="PullRequestDiffsList-module__diffEntry"]` |
| Block path, first choice | `"diff-" + sha256(path)` looked up with `getElementById` |
| Block path, fallbacks | a descendant `[data-file-path]`, else `table[data-diff-anchor]` with `aria-label` `Diff for: <path>` |
| Diagram host | `[class*="prc-PageLayout-PaneWrapper"]` (the file pane) and `[class*="prc-PageLayout-ContentWrapper"]` (the diffs' column), both inside `#diff-comparison-viewer-container`. The panel is inserted right before the pane with the pane's computed `order` (before the column with the column's order when there is no pane), so DOM order places it first and no GitHub element is restyled. Top offset copied from the pane |
| Tree host | `#pr-file-tree > [class*="PullRequestFileTree-module__FileTreeScrollable"]`: GitHub's tree with its "File tree" heading. `#pr-file-tree` also holds the "Filter files" box as its first child, so the list is inserted before the host and the host is hidden with a class |
| Line row | `[data-line-anchor="diff-<sha256 of path>R<line>"]` (`L` for a removed line); its closest `tr` is flashed and scrolled to the middle of the window. |
| Description host (conversation page) | `.js-discussion .js-comment-container`: the first one is the PR's opening comment, and the card is inserted before it. Observed 2026-10-05 on the server-rendered conversation page |
| Head SHA | `/"head(?:Oid\|Sha)"\s*:\s*"([0-9a-f]{40})"/` over `script[type="application/json"][data-target="react-app.embeddedData"]`, trusted only for the PR the page was first opened on |

If a chunk hides nothing, the list is missing, or the list says it couldn't find the diff blocks, GitHub changed these;
update `github_page.js` only.

When GitHub's file tree pane is closed there is no tree host, so no list is shown until the pane is reopened.

## Forgejo selectors (observed 2026-10-05 on a local Forgejo's pull request files page)

All in `forgejo_page.js`. The class names are semantic and stable, not hashed.

| What | Selector or rule |
| --- | --- |
| Page URL and run key | `/{owner}/{repo}/pulls/{n}/files`; the run folder is `fj-<n>` |
| Diff block and entry | `#diff-container .diff-file-box[id^="diff-"]`; the box is both, and hiding it collapses the spacing. Its id is `diff-` + sha1 hex of the file path |
| Block path | `data-new-filename`, else `data-old-filename` |
| File header | `.diff-file-header`, sticky at 44px inside the box, under the sticky summary bar `.diff-detail-box` (top 0, 44px) that the scroll offset is measured against |
| Line row | `.lines-num [rel="diff-<sha1 of path>R<line>"]` (`L` for a removed line); its closest `tr`. The cell is `td.lines-num-new` / `td.lines-num-old` with `data-line-num` |
| Tree host | `#diff-file-tree > .diff-file-tree-items`: the Vue-rendered tree inside the sticky 380px column `#diff-file-tree`. The list is mounted before it in that column and the tree is hidden with a class |
| Diagram host | pane `#diff-file-tree`, content `#diff-content-container`, both children of the flex row `#diff-container`; the panel goes right after the pane |
| Description host (conversation page) | `.ui.timeline > .timeline-item.comment.first`: the PR's opening comment, which the card is inserted before |
| Head SHA | `/src/commit/<sha>/` in the `href` of the first `#diff-container .diff-file-box a[href*="/src/commit/"]` ("View file"), trusted only for the PR the page was first opened on |
| Colours | the Primer custom properties the CSS uses are pointed at Forgejo's `--color-*` variables by a `<style id="prf-forgejo-theme">` added to the page |

Not covered: a file collapsed with "Viewed", and a diff Forgejo holds back behind a load button on a very large
change (neither occurred in the PRs observed), so a jump into such a file times out and stays at its header.
