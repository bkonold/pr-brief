# PR Brief extension

A Chrome extension (Manifest V3) for GitHub's Files changed page and for a Forgejo pull request's files page
(`http://localhost:3300/{owner}/{repo}/pulls/{n}/files`). It reads the brief's `review.json` (schema 4, written by `render.py`) from the PR's own comment, or from an optional local server, and replaces the host's file tree with the walkthrough's list of stops. It only reads, and posts nothing. Both hosts behave the same; the text below says GitHub
where it describes the page, and the Forgejo selectors are in their own table at the end.

## Where the brief comes from

A reviewer needs the extension and nothing else: no server and no token.

1. **The PR's comment.** The GitHub Action (`post.py`) closes its collapsed "PR Brief" comment with a nested, collapsed "Brief data" block, a code fence
   holding the base64 of the gzip of `review.json` plus the run's `diagram.svg` and `body.html` (as `diagram_svg` and
   `body_html`). `comment_source.js` finds the earliest such block in the page's rendered comments, inflates it
   (`DecompressionStream`) and hands `source.js` the review, the body page and the diagram. On the PR's conversation page
   it reads the page's own document; on the files page it fetches the conversation page with the user's own session
   (`credentials: "include"`), once for the review and the brief together. The review must be schema 4 with `nodes` and a
   `walkthrough` and must name this repository and PR; otherwise the comment counts as no brief.
2. **The local run server, when one is set.** Only if the comment gives nothing does `source.js` ask `background.js`,
   which answers from the server named in the options page. With the field empty (the default) the background script
   answers `unset` at once and makes no request, a PR with no brief comment shows nothing, and no "Generate brief", server
   note or Regenerate button is drawn.

Known gap: a comment behind GitHub's "Load more" pagination on a very long conversation is not in the page's HTML, so it is
not found. A comment over GitHub's size limit has no "Brief data" block (`post.py` drops it first), so it is not found
either. The block is read from whichever commenter posted it: the extension does not check the author, and takes the
earliest block in the page.

What the list shows, in GitHub's left column between the "Filter files" box and the tree:

- A toggle, "Walkthrough" / "Files". The page opens in "Files", which shows the host's own file tree (GitHub's, or Forgejo's); "Walkthrough"
  swaps in the stop list, and the toggle stays so you can switch again. No mode or stop ever hides a diff: every file's diff is always in the page, so the host's find
  and page-down work across the whole change.
- Under the toggle, chips that pick which files the pane lists: "All N" (the PR's changed files), "API N" and
  "Data N", from `review.json`'s `file_sets`. A chip with no files is not shown, and a run with no contract or data files
  (or an older run without `file_sets`) has no chips. The chip is per tab and not remembered, stays through a switch of the toggle, and clicking one never
  moves the diagram. See "File sets" below.
- Under the toggle in "Walkthrough" mode, one row per stop of the walkthrough (see "The walkthrough"): no tabs. The
  diagram's boxes in `review.json` drive the diagram's halo and the box named in each stop's callout. A muted line above
  the stops says what the list is for; a run with no stops has none.

## File sets

"API" and "Data" narrow the pane to the files that make up the PR's API contract change and its data change.

- In "Walkthrough" mode the list is the stops whose file is in the set, in walkthrough order, each with its file's name
  under its title. A set whose files have no stop says so.
- In "Files" mode the host's own tree hides the files that are not in the set, and a directory left with no visible file.
  The host re-renders its tree, so the hiding is applied again on every refresh, as the callouts are. A tree row is
  matched to a file by the `#diff-…` link it holds.
- Every diff stays in the page, whichever chip is chosen.

## The walkthrough

`review.json`'s `walkthrough` is an ordered list of stops, each `{i, title, why, path, side, line,
node}`: the model's reading order through the change, which can return to a box it has visited. `line` is null for a
stop that names only a file. `node` is the id of the diagram box the stop belongs to, or null when no box holds the
stop's file. `nodes` is an object from box id to `{title, files, stops}`, the box's title, the paths it covers and the
numbers of the stops that land on it. A run that is not schema 4 with `nodes` and a `walkthrough` (made by an earlier
variant) is not shown: see "Older runs".

- The list has one row per stop: its number and its title. The current stop is highlighted and scrolled into view. A
  row goes to its stop: it makes the stop's file the active one, and jumps to the stop's line, or, for a stop with no line,
  to the file's callout above its header. Either way the callout's top edge lands 16px below the sticky chrome over the
  diffs and the file's own sticky header, both measured at that moment, so every stop appears in the same place and the
  Previous and Next buttons stay under the pointer. Near the end of the page it lands as close as the page can scroll.
  Once landed, a stop is held there while content above it shifts (diffs loading, files expanding), watched by a
  ResizeObserver on the diffs, until the user scrolls or clicks or another jump starts. The diagram follows the stop: its box takes the halo and the
  canvas centres on it. GitHub renders a diff's rows only once the diff is near the window, so the jump scrolls to the
  file's diff, waits up to 10 seconds for the row, then scrolls its callout into place, measuring again after each scroll and
  nudging until it sits there; on a timeout the view stays at the file's header. Opening the files page on a link to
  a stop's line or file (the PR brief card's links) goes to that stop.
- Every stop that has loaded gets a callout above its line (above the file's header for a stop with no line), as soon as
  the review shows and as GitHub or Forgejo load more of the diff, in both unified and split views. It is a full-width
  table row holding a neutral card (the host's muted surface, a 1px purple border, rounded, from the file pane's left
  edge, in 14px text, as wide as its left column plus a 24px gap plus its nav column, and never wider than the diff
  column) in two columns. The left column has a route icon and a header in bold default text, `Stop <i> of <n> · <box
  title>` (without the box part for a stop on no box), a small muted chevron, then the stop's title in
  normal weight, and then on its own line a small muted "Why stop here" over the stop's `why`, wrapping within the
  header's width. The right column is top-aligned with the header and right-aligned, with no divider before it, and always has two
  slots: a "↑ Previous" button (its tooltip is the previous stop's title) over a row of the muted "Next" caption and a
  small button with the next stop's title and ↓. On the first stop the Previous slot, and on the last the Next slot,
  stays in the layout hidden (`visibility: hidden`, `inert`, `aria-hidden`, no tab stop), so the other slot does not
  move and the column keeps its height; a walkthrough of one stop hides both. On a diff too narrow for
  both columns the right column wraps below the text and stays right-aligned. A button goes to that stop, as a click on
  its row does, without the pulse. Clicking Previous or Next quickly ends at the last stop clicked. A callout is placed
  once per stop, so a re-render or a lazy load never doubles it. The callouts show only in "Walkthrough" mode.
- A stop with no line has its callout as the first child of that file's diff entry (the GitHub diff entry, the Forgejo
  file box), so it sits directly above the file header and spans the entry's full width with the same card. The jump
  places the callout like a line stop's, so the header shows under it, and marks and pulses the callout alone. It is placed once, comes back if the host drops it, and goes with the callouts.
- The stop's line is left exactly as the host draws it. Each callout card starts at the file pane's left edge, and the
  jumped-to stop's card border is the full purple where the other callouts' is purple at 45%. The file, line number and code are not repeated, since the diff row shows them. Only
  one card is marked as the target; the mark goes whenever the line target clears (another selection, a new jump or
  teardown) and comes back if the host re-renders the row. When a jump lands, its callout pulses once: a purple ring
  that swells from its resting width to 3px wider and back, three times over about two seconds (666ms each). It fires on
  every jump from the list or the diagram (a stop or box click) and from a link to a stop, but not
  from the callout's own Next and ↑ buttons, since the reader is already following the callouts. Only the jumped-to
  stop pulses, and not when the host re-renders the row. Under `prefers-reduced-motion` it does not pulse.
- A banner appears when the review was generated for an older head commit than the page's.

Nothing about the review's state is remembered: every load and every navigation into the files page opens as GitHub would,
in "Files" mode with nothing selected, the diff where GitHub put it and the diagram collapsed, with the default variant. A
link to a stop's line selects that stop. The one thing kept is whether the diagram panel is expanded (see below).

## When the page server is down

This applies only when a server URL is set and the PR's comment has no brief. If fetching `review.json` fails outright (connection refused, a network error), the list's place above GitHub's tree shows a
note with the base URL, the command to start the server (`pd serve`) and a Retry button; GitHub's tree stays visible. Retry
fetches again and mounts the full list on success. A 404 shows the "Generate brief" line below, and an older run shows the "Older runs" line, unless the run server says it will not run that repository.

## Boxes and files

Clicking a diagram box goes to the first stop on that box (the first of its `stops`). A box with files and no stop is
scrolled to its first file's header, which becomes the active file with a 3px accent bar, and no stop is current. The
box takes no stroke, tint or pulse of its own beyond the halo. A context box (dashed, default cursor, covering no file)
and an id the review does not list do nothing when clicked.

The active file clears when another box or stop is used or the mode toggle is. A landing on a file's header puts it just
below GitHub's sticky chrome (the offset is measured when the click happens, as the lowest stuck edge of the page's
sticky or fixed elements that span the diff column), then flashes the header for about 1.2s; under
`prefers-reduced-motion` the flash is skipped.

## The change diagram

When `review.json` names a `diagram` (`diagram.svg` in the run directory), `background.js` fetches it with the review
and `diagram.js` docks it as the leftmost pane, right before GitHub's file pane in GitHub's own flex row, so the page reads
diagram, stop list, code, and the other two columns narrow by the panel's width (by default the width at which the walkthrough draws the diagram's widest box with its halo at 100%, at most 40% of the viewport, at least 220px) instead of being
covered. The panel is sticky at the file tree pane's offset and as tall as the pane. It is mounted collapsed, as a 30px rail
in that spot with "Diagram" written vertically under a `›` button that expands it; the header's `‹` button collapses it
again. Whether this tab expanded it is remembered in `sessionStorage`, so a reload keeps it expanded.
- The diagram, the stop list and the code are separated by single dividers: the panel's right border, then GitHub's own
  rule down the pane's right edge.

- Motion: the line jump scrolls smoothly (a target more than 1.5 windows away is first approached instantly to one window
  short of it); newly visible diffs fade in over 150ms; diagram emphasis cross-fades over
  250ms. The emphasized box gets a concentric 8px halo (22% of the accent, `#534ab7` in the light theme and `#9d94f5` in the dark), an 11% accent tint over its fill and an accent-dark title, and keeps its own stroke. `prefers-reduced-motion: reduce` turns all of it off, leaving only the end states.
- The panel's right edge is a drag handle: dragging it right widens the panel and narrows the diffs. Width is 220px up to 65% of
  the viewport, by default the width that shows the widest box at 100%. A width dragged to lasts until the page is left and is not stored, so every load starts at the default; the extension removes the `diagramWidth` key an earlier version saved in `chrome.storage.local`.
- Each box shows the numbers of the stops that land on it as a purple badge (`2 · 5`) before its bold title, and a
  box with no stop has no badge. A box covering no changed file is dashed and muted. When the diagram has one, a line
  under the card reads "Dashed boxes are unchanged context".
- Focusing a stop highlights its box and dims nothing. The box keeps its own stroke and fill and gains a halo: a 5px
  ring in the accent colour at 30% opacity, 6px outside the box. Every edge with an end on the highlighted box, incoming
  or outgoing and dashed return edges included, is drawn 2px in the accent colour with an accent arrowhead. The halo is
  not part of the box's bounds, so centring and following measure the box itself. A selection with no box leaves the
  diagram as it was; "Files" mode or no selection restores it.
- Clicking a box goes to its first stop (see "Boxes and files").
- The diagram draws at 1:1, so text on screen is the size it was rendered at (16px), and it rests there. Only the
  walkthrough zooms it (below). It is a pan-and-zoom canvas: any scroll wheel or trackpad scroll over the canvas zooms around the pointer (25% to
  400%), as does a pinch (Chrome reports a trackpad pinch as Ctrl + wheel); the page does not scroll while the pointer
  is over the canvas. Pressing and dragging anywhere on the canvas pans it; a drag that starts on a box pans once it
  moves more than 4px, and a shorter press is a box click. The header has −, the current zoom (click it for 100%), +
  and ↺ (Reset). Reset clears the selection: no box or stop selected, no line, box or stop
  callout highlighted, the pane's mode as it is, and the canvas
  back at its resting view. The stop callouts stay in the diff. Panning stops when a diagram edge
  reaches the middle of the canvas.
- Focusing a stop, whether from a stop row, a callout's Previous/Next or a click on its box, moves the canvas over about
  200ms (at once under reduced motion). From a stop row, a callout's Previous/Next, or a stop's link or
  anchor, it also zooms so the box, halo included, takes 90% of the pane's width, kept between 0.5
  and 1.25 (titles between 8px and 20px), and set to exactly 1 when it comes within 5% of it; at the default pane width it
  is exactly 1. A click on a box in the
  diagram, dragging, the wheel, a pinch and Reset never change the zoom: a box click only pans, at the reader's zoom.
  The box is centred horizontally; a box wider than
  the pane has its left edge at a 16px margin instead. The canvas moves vertically only as far as it takes to bring the
  box and the boxes joined to it by solid arrows into view (dotted return arrows count for nothing); when they already
  are, it does not move vertically. When they are taller than the pane, the side the box is nearer shows, and the box
  stays in view. The pane's size is read at that moment. A stop on no box leaves the canvas where it is, and a
  collapsed panel moves to the focused box when it is expanded again. A new diagram opens at its resting view: 1:1,
  centred horizontally when it is narrower than the pane, else at the left edge, at the top. Resizing the panel puts the
  focused box back where a click on it would, at the new width (with its walkthrough zoom, when it came from the
  list or Next/Previous), and a diagram still at rest stays at rest. When the page replaces the panel (GitHub re-renders the files page
  after it loads), the new panel goes back to the box the old one was following. Zoom and position are not saved.
- Loading the files page selects nothing: no box is highlighted, the canvas stays at its resting view and the diff is not
  scrolled. A stop the URL links to (`#diff-…` naming a stop's line or file) is opened instead, as a click on it would,
  which switches to "Walkthrough" mode.
- The SVG is parsed with `DOMParser` and stripped of `<script>`, `on*` attributes and `javascript:` links first.
  GitHub's CSP allows the SVG's own `<style>` and inline `style` attributes, so no restyling is needed.
- Mermaid 11 ids: a node is `<g class="node" id="pr-diagram-flowchart-<nodeId>-<n>">`; an edge is a `path` with
  `data-id="L_<from>_<to>_<n>"` (its label group has the same `data-id`). Node ids can contain underscores, so edge
  ends are matched against the known node ids.

## Generating a brief on demand

`serve.py` (see the [top-level README](../README.md#commands)) can start a run for the PR on the page, for the author who has set a server URL in the options. With none set nothing here is offered. The extension never talks to it from a
page script: `background.js` makes the calls (`startRun`, `runStatus`, `cancelRun` to `/api/run`, `/api/status`,
`/api/cancel`) and adds the server token, which the options page keeps in `chrome.storage.local` ("Server token":
paste the contents of `~/.config/pr-brief/token`). The server also requires an `Origin` of `chrome-extension://`,
which only the background script sends.

`run_control.js` owns one run's progress for a PR page: it starts the run, asks `/api/status` every 3 seconds, ticks
a one-second clock between polls and reports to the page. The card and the files view's line both draw from it.

- **Conversation page, no run:** the card is a bar with "PR brief", "local, not posted" and a "Generate brief" button
  (nothing at all when no server URL is set).
- **Running:** "Writing brief · m:ss", a pill per stage (Fetch PR, Gather context, Write, Render; done ones green, the
  current one in the accent colour) and a Cancel link. Leaving the page does not stop the run; the next visit asks
  the server and resumes from where it is. When the run is done the brief is loaded and drawn, closed.
- **Stale:** when the run's `head_sha` differs from the PR's current head (`page.currentHeadSha`: the page's own value
  when it shows one, which on GitHub is only the files view's embedded page data, else the host's answer: Forgejo's
  read-only API, or for GitHub the server's `GET /api/head`, asked through `background.js`), the badge reads "for
  <short>, PR is at <short>" and a "Regenerate" button sits beside "Review in files view".
- **Current or unknown head:** a quiet "Regenerate" link in the card header does the same. Whenever generating is
  allowed, regeneration is offered; with it not allowed, neither the button nor the link is shown. A brief read from the
  PR's comment has them only when a server URL is set, and once a run it started is done the card shows that run, read from
  the server, rather than the older comment.
- **Failure:** the error line and a Retry button. A failed call says why: "Start the server with `pd serve` to generate
  briefs" (nothing listening), "Server token missing or wrong — set it in the extension options" (403) or "2 briefs
  already running" (429).
- **Files view, no run:** where the list would be, one line, "No brief for this PR yet" and a "Generate brief" button, which
  runs the same flow and mounts the full list when the run is done.
- Both are offered only where a server URL is set and the server may run that repository: `/api/status` is asked with the host, owner and repo
  and says `allowed`. When it cannot be asked (server down, wrong token) they are shown anyway, so the reason can be.

## Older runs

A run whose `review.json` names this PR but is not schema 4 with `nodes` and a `walkthrough` was made by an earlier
variant. `background.js` answers it with `{error: "old"}` and the files view shows one line, "This brief predates v1;
re-run it.", with a "Re-run" button that starts a run with the server's `default_variant` like "Generate brief". Nothing
else of the old run is shown.

## The PR brief card

On a PR's conversation page (GitHub `/{o}/{r}/pull/{n}`, Forgejo `/{o}/{r}/pulls/{n}`) the extension puts a "PR brief"
card above the PR's description when the PR has a brief (`prFromUrl` returns `view: "conversation"`; the files page is
`view: "files"` and behaves as before). Its badge says "from the PR's comment" for a brief read from the comment and "local,
not posted" for one the local server holds, nothing is written to the page's data, and its header links to the files
view. Without a brief it is the "Generate brief" bar described above, and only where a server URL is set.

- It is a `<details>` in a shadow root, built closed every time the page loads; nothing about it is stored. Its colours
  are the site's own Primer names (Forgejo's are mapped by its adapter), with light and dark fallbacks.
- The diagram, in the card and in the diagram pane, follows the host's theme: its text, outline and halo colours are the
  Primer names (Forgejo's mapped by its adapter), with the system's `prefers-color-scheme` as the fallback, and the
  purple accents stay the same. The card's and the pane's own rules re-theme a diagram whose SVG was written with fixed colours.
- `body.html` from `render.py` is a standalone page that draws itself: the description is a markdown string in a
  script, rendered by `marked` and `mermaid`. `brief_text.js` reads that string, renders the subset of markdown
  `render.py` writes, and drops every script, event handler and non-web link. The mermaid source, the title and the
  "Diagram Walkthrough" heading are left out; `diagram.svg` goes in its own closed "Diagram" `<details>` under the
  description's bullets, with the caption about dashed boxes under it, on the site's own surface colour. The
  card is one column, and each top-level bullet in the description has a blank line's space after it.
- The brief's "API" and "Data" sections are each a closed block like the Diagram's, its summary the section's name
  in bold, one chip for each impact level present and the number of rows as muted text, so they stay visible while it is
  collapsed. Opened it is one table of every line (API: Impact, Side, Change, On, ↗; Data: Impact, Change, Table,
  ↗), for the whole PR. The body's pipe tables are drawn by `brief_text.js`; each table scrolls sideways in its
  own container, and a name cut in the middle shows its whole name as a tooltip. The ↗ link is rewritten to this host's
  files view like the others. The chips come from the run's `<span class="pill p0|p1|p2">` markup: the top level is a
  filled chip, the second a bold outlined one and the rest outlined, drawn by the card's own style. The brief has no
  review-order table; the files view lists the stops.
- Links into the PR's files view are rewritten to this host's files view, fragment kept. When the files page loads with a
  fragment that is a stop's anchor, `content.js` goes to that stop; any other fragment is left to the page.
- `source.js` answers `loadBrief` from the PR's comment (`body_html`, `diagram_svg` and the review's `head_sha`) and, when
  the comment has none, from `background.js`, which fetches `body.html` and `diagram.svg` of the run for the server's
  `default_variant` (`GET /api/config`), the way it fetches `review.json`. With no brief, or the page server down, the card is
  the "Generate brief" bar, except where no server is set or the server says it will not run the PR's repository: then
  nothing is mounted.
- The conversation page is watched while the card is mounted, so a host that re-renders its timeline gets the card
  back above the description; `onNavigate` mounts it again after client-side navigation, and one card exists at a time.

## Load it

1. Open `chrome://extensions`, turn on Developer mode, choose Load unpacked and pick this `extension/` folder.
2. Open a PR's Files changed page, such as `https://github.com/<owner>/<repo>/pull/<n>/changes`, or a Forgejo PR's
   `http://localhost:3300/<owner>/<repo>/pulls/<n>/files`. A PR whose brief comment the Action has posted shows its brief.
3. Optional, to generate briefs from your own machine: serve the runs and the API with `python3 serve.py` (an overlay's
   wrapper: `pd serve`), and in the extension's options set the server URL and token.

The list appears only when the PR has a brief comment or, with a server set, `runs/<key>/<variant>/review.json` exists for the PR (no comment, a
404, a server that is down or a different repo leave the page untouched). `<key>` is the PR number on GitHub and `fj-<number>` on
Forgejo (`run.py --host forgejo`). `review.json` records its `repo`, which the extension compares with the page's `owner/repo`; two repositories on one host with the same PR number would overwrite each other's runs. The variant comes from the server (`default_variant` in `local.toml`, see Which variant is shown); the extension's options page holds the optional server URL and token. The
manifest allows `http://127.0.0.1:8765` for the runs and `http://localhost:3300` for Forgejo, so another origin
also needs a `host_permissions` entry (and a `matches` entry for a Forgejo elsewhere). Loading a version that adds a host
makes Chrome ask for the new permission when the extension is reloaded.
After editing a file, reload the extension on `chrome://extensions` and refresh the GitHub tab.

Run the pure tests with `node --test test/*.test.js`.

## Files

| File | Role |
| --- | --- |
| `background.js` | When a server URL is set: fetches `review.json` and the run's brief for the content script, and calls the run server's API with the token; the page server sends no CORS headers. With none set it answers `unset` and requests nothing |
| `serve_api.js` | Sorts a run-server response into success or a problem (server down, token, busy, error); an ES module used by `background.js` |
| `run_control.js` | Starts a run and follows it: polling, the elapsed clock, stage pills, failure messages |
| `page_common.js` | What every host's page shares: sticky-offset scrolling, the line jump, the stop callouts, change watching. `createPage(spec)` builds an adapter from a host's spec |
| `github_page.js` | The only module with GitHub selectors; builds the GitHub adapter |
| `forgejo_page.js` | The only module with Forgejo selectors; builds the Forgejo adapter |
| `page.js` | Picks the adapter whose `hosts` lists `location.host` and exposes it as `prFocus.page`, which `content.js`, `focus.js`, `tree.js` and `diagram.js` call |
| `focus.js` | Marks the active file's header, and scrolls to a diff. It hides nothing |
| `tree.js`, `tree.css`, `focus.css` | The stop list, the stop callout card with its previous and next stop, and the classes `focus.js` and the line jump toggle |
| `content.js` | Wiring: URL changes, debounced re-apply, expansion and selection state |
| `classify.js` | Tells a failed request (server down) from a non-OK response (no run) |
| `diagram.js`, `diagram.css` | The diagram panel, its overlay and box emphasis |
| `comment_source.js` | Reads the brief from the PR's "Brief data" comment block (inflate, split, fetch the conversation page). Loaded before `source.js` |
| `source.js` | Content-script side of loading: the PR's comment first, then the background script |
| `brief_text.js` | Turns a run's `body.html` into the card's safe HTML (pure string work, tested without a DOM) |
| `brief.js` | Builds the PR brief card in a shadow root and draws its views: no run, running, failed, brief, stale |

The content scripts are classic scripts sharing `globalThis.prFocus`, loaded in the order listed in `manifest.json`.

### The page adapter

Everything the rest of the extension asks of the page goes through one object, `prFocus.page`: `name`, `treeLabel`,
`prFromUrl` (`{owner, repo, pr, view}`, `view` being `"files"` or `"conversation"`) / `pullFromUrl` (`{owner, repo, pr}`), `filesUrl(pr)`, `conversationUrl(pr)`, `isConversationPage(pr?)`, `runKey(pr)` (the `runs/` folder), `headSha`, `fileBlocks`, `entryOf`,
`entryFor`, `lineAnchor`, `scrollToElement`, `fileHeaderOf`, `jumpToLine`, `clearLineTarget`,
`restoreLineTarget`, `ownsLine`, `cancelJump`, `diagramHost`, `treeHost`, `descriptionHost`, `onChange` and `onNavigate`. A new host is a
spec for `createPage` (see the comment at the top of `page_common.js`) plus an entry in `manifest.json` and `page.js`.

## GitHub selectors (observed 2026-10-04 on GitHub's React-based Files changed page)

All in `github_page.js`. Class names carry hashed suffixes, so they match on a `[class*="..."]` prefix.

| What | Selector or rule |
| --- | --- |
| Diff block | `div[id^="diff-"]` with class containing `Diff-module__diffTargetable`; id is `diff-` + sha256 hex of the file path |
| Entry | the block's ancestor `div[class*="PullRequestDiffsList-module__diffEntry"]` |
| Block path, first choice | `"diff-" + sha256(path)` looked up with `getElementById` |
| Block path, fallbacks | a descendant `[data-file-path]`, else `table[data-diff-anchor]` with `aria-label` `Diff for: <path>` |
| Diagram host | `[class*="prc-PageLayout-PaneWrapper"]` (the file pane) and `[class*="prc-PageLayout-ContentWrapper"]` (the diffs' column), both inside `#diff-comparison-viewer-container`. The panel is inserted right before the pane with the pane's computed `order` (before the column with the column's order when there is no pane), so DOM order places it first and no GitHub element is restyled. Top offset copied from the pane |
| Tree host | `#pr-file-tree > [class*="PullRequestFileTree-module__FileTreeScrollable"]`: GitHub's tree with its "File tree" heading. `#pr-file-tree` also holds the "Filter files" box as its first child, so the list is inserted before the host and the host is hidden with a class |
| Tree rows | `li[role="treeitem"]` without `aria-expanded` is a file, with it a directory; a file row is matched to its diff by the `a[href*="#diff-"]` it holds (the diff's id). A directory row is hidden only when it has file rows in the page and all of them are hidden |
| Line row | `[data-line-anchor="diff-<sha256 of path>R<line>"]` (`L` for a removed line); its closest `tr` is flashed, and its callout row is scrolled to the stop place. |
| Description host (conversation page) | `.js-discussion .js-comment-container`: the first one is the PR's opening comment, and the card is inserted before it. Observed 2026-10-05 on the server-rendered conversation page |
| Head SHA | `/"head(?:Oid\|Sha)"\s*:\s*"([0-9a-f]{40})"/` over `script[type="application/json"][data-target="react-app.embeddedData"]`, on the files page and (observed 2026-10-09) on the conversation page; trusted only for the PR the page was first opened on. For any other page the PR's conversation page is fetched and read the same way (`readHeadSha(doc)`), and only then a set run server is asked |
| Brief data (conversation page) | `.markdown-body details` (a comment's body is `div.comment-body.markdown-body.js-comment-body`; the block renders as `details > summary` + `pre.notranslate > code`, observed 2026-10-09 through GitHub's markdown API) whose `summary` text is exactly `Brief data`, and the text of the `pre` inside it; the earliest in document order wins. The files page fetches `/{owner}/{repo}/pull/{n}` and reads the parsed document the same way |

If the list is missing, or the list says it couldn't find the diff blocks, GitHub changed these;
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
| Tree rows | `.item-file` is a file row, matched to its diff by the `a[href*="#diff-"]` it is or holds. Directory rows are left showing |
| Diagram host | pane `#diff-file-tree`, content `#diff-content-container`, both children of the flex row `#diff-container`; the panel goes right after the pane |
| Description host (conversation page) | `.ui.timeline > .timeline-item.comment.first`: the PR's opening comment, which the card is inserted before |
| Head SHA | `/src/commit/<sha>/` in the `href` of the first `#diff-container .diff-file-box a[href*="/src/commit/"]` ("View file"), trusted only for the PR the page was first opened on. The conversation page (observed 2026-10-09) links only the commits of force-push events, so it is no source: `GET /api/v1/repos/{owner}/{repo}/pulls/{n}` from the page's own origin and session gives `head.sha`, with no run server involved |
| Brief data (conversation page) | `.render-content.markup details` (a comment's body is `div.render-content.markup`, observed 2026-10-09) whose `summary` text is exactly `Brief data`, and the text of the `pre` inside it; the earliest in document order wins. Forgejo's own `details.collapsible` ("View command line instructions") is outside `.markup` and ignored |
| Colours | the Primer custom properties the CSS uses are pointed at Forgejo's `--color-*` variables by a `<style id="prf-forgejo-theme">` added to the page |

Not covered: a file collapsed with "Viewed", and a diff Forgejo holds back behind a load button on a very large
change (neither occurred in the PRs observed), so a jump into such a file times out and stays at its header.
