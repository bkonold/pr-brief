# Review focus extension

A Chrome extension (Manifest V3) for GitHub's Files changed page. It reads the `review.json` that
`render.py` writes for a chunked variant and replaces GitHub's file tree with a list grouped by review
chunk, like a "group by importance" view. It only reads, and posts nothing to GitHub.

What the list shows, in GitHub's left column between the "Filter files" box and the tree:

- A toggle, "By review" / "GitHub tree", and an "Expand all" / "Collapse all" button. "GitHub tree" brings
  GitHub's own tree back and shows every diff; the toggle stays so you can switch again.
- One group per chunk, with its file count, review level and why.
  Groups are ordered by review level ("read carefully", "read", "skim"), then "Unchunked"; skim-level chunks and "Unchunked" are muted. A "Not in review" group lists loaded diffs no chunk names.
- Files show their basename, `+N` and `-N`. Each folder shared by consecutive files is named once in a dim monospace header above them, trimmed from the left when it doesn't fit; the file order is the chunk's own.
- Clicking a chunk header focuses the diffs on that chunk, expands it, collapses the others and scrolls to the
  chunk's first file; clicking it again shows all diffs. The chevron only expands or collapses.
  Clicking a file focuses its chunk and scrolls to its diff.
- A `↳` button on a chunk with a start line (the `start` field of `review.json`, the one line the model says to read
  first; hovering or keyboard-focusing it, after 300ms, shows a card with `path:line` and the quoted text directly below the
  chunk's header in the list, pushing the rows below it down; Esc closes it) jumps to that line, centres it, flashes the row amber three times over two seconds (under `prefers-reduced-motion`: no flash, a static amber tint on the row while it is the target). If another chunk is
  focused it focuses this chunk first, since the line's diff is hidden otherwise. GitHub renders a diff's rows only once
  the diff is near the window, so the jump scrolls to the file's diff, waits up to 10 seconds for the row, then centres
  it, measuring the row again after each scroll and nudging until it sits mid-window (GitHub's layout shifts while diffs
  load); on a timeout the view stays at the file's header. The target row keeps its class when GitHub re-renders it, until another selection, a new jump or teardown clears it.
- When a jump lands, a callout is pinned in the diff as a full-width table row directly above the line: `↳ Read first:`
  and the reason to read that line (the chunk's `start.why`, else the chunk's own `why`), in GitHub's attention colours,
  with a × button that removes it. The reason wraps onto as many lines as it needs and is never cut off; the file, line number
  and code are not repeated, since the diff row below shows them (the sidebar's hover card still does). Only one
  exists; it goes whenever the line target clears (another selection, a new jump, a variant switch or teardown) and
  comes back if GitHub re-renders the row, unless it was dismissed with ×.
- A banner appears when the review was generated for an older head commit than the page's.

The mode and selected chunk are remembered per PR in `sessionStorage`.

## When the page server is down

If fetching `review.json` fails outright (connection refused, a network error), the list's place above GitHub's tree shows a
note with the base URL, the command to start the server and a Retry button; GitHub's tree stays visible. Retry fetches again
and mounts the full list on success. A 404 or an unusable review stays silent.

## Variant switcher

`background.js` also fetches `runs/<pr>/variants.json` (`[{variant, label, description}]`, written by `compare.py`). When
the list has more than one entry, the toggle bar shows a `<select>` of the labels, each option titled with the variant's
description. Changing it stores the new default in `chrome.storage.sync`, reloads `review.json` and the diagram in place
and keeps the selected chunk when the new variant has a chunk of the same name; otherwise the selection and the focus are
cleared. If the stored default has no run for the PR, the first entry of `variants.json` is used; without the file, only the
stored default is tried. The saved per-PR selection is restored only for the variant it was made in.

## Boxes and files

When `review.json` has `nodes` (`[{id, number, files}]`, written for `v11*` runs), each file row in the list shows a small
badge with the number of every box that covers it. Clicking a box selects the chunk holding its first file, as a header click
does, and smooth-scrolls to that file. A context box (no files) is dashed, has a default cursor and does nothing when clicked.
The scroll lands the file's header just below GitHub's sticky chrome: the offset is measured when the click happens, as
the lowest stuck edge of the page's sticky or fixed elements that span the diff column (the file-row click and a chunk's
first-file scroll use the same code). The clicked box becomes the active box:

- Diagram: the box pulses once (stroke 2px to 3px to 2px with an accent tint, 600ms) after the scroll lands, then keeps a light
  accent fill tint, stronger than the chunk highlight.
- Diff: every loaded file the box covers gets a 3px accent bar on its header, which stays while the box is active, and a header
  background flash of about 1.2s. The first file's header also carries a chip, `Box 3 · <box title>` (the title is the first line
  of the box's SVG label), that fades out after 2.5s.
- List: the box's file rows get an accent background, its chunk expands and their box-number badges flash once.

The active state clears when another box, a chunk header (including unselecting it), a file row, the mode toggle or the jump
button is used, or the variant changes. Under `prefers-reduced-motion` only the end states show: no pulse, flash or fade; the
chip appears and is removed after 2.5s. Without `nodes` (V10) a box selects the first chunk, in list order, that lists it, without scrolling.

## The change diagram

When `review.json` names a `diagram` (`diagram.svg` in the run directory), `background.js` fetches it with the review
and `diagram.js` docks it between GitHub's file pane and the diffs, in GitHub's own flex row, so the page reads chunk
list, diagram, code, and the diff column narrows by the panel's width (280px by default) instead of being covered. The
panel is sticky at the file tree pane's offset and as tall as the pane, collapses with its chevron (`‹` expanded, `›`
collapsed; remembered in `sessionStorage`) into a 28px strip in the same spot, and clicking the card opens a larger
overlay; Esc or a click outside closes it.
- The chunk list and the diagram read as one region: the panel has the page surface the pane has, GitHub's own rule
  down the pane's right edge is made transparent while the panel is mounted, and the panel's right border is the one
  divider before the code.

- Motion: the line jump scrolls smoothly (a target more than 1.5 windows away is first approached instantly to one window
  short of it), then flashes the row; newly visible diffs fade in over 150ms; diagram emphasis cross-fades over
  250ms. The emphasized box gets a 2px `#534ab7` stroke (`#b26a00` on save boxes); the diagrams carry no inline `!important`
  styles, so no glow is needed. `prefers-reduced-motion: reduce` turns all of it off, leaving only the end states.
- The panel's right edge is a drag handle: dragging it right widens the panel and narrows the diffs. Width is 220px up to 65% of
  the viewport, 280px by default (double-click the handle to reset), and is remembered in `chrome.storage.local`.
- A legend under the card, and under the large overlay's diagram, lists only the styles the SVG uses (changed step,
  writes data, unchanged context), each swatch coloured from the page's computed style of a real box, plus "Selected
  chunk" (the emphasis outline) and, when the diagram has lanes, a note that columns are code layers.
- Selecting a chunk (header click or the jump button) highlights its `nodes` and the edges between two of them, and
  dims the rest to 0.25 opacity. A chunk with no nodes dims the whole diagram slightly. "GitHub tree" mode or no
  selection restores it.
- Clicking a box selects the first chunk, in list order, whose `nodes` include it, without scrolling the diff.
- The SVG is parsed with `DOMParser` and stripped of `<script>`, `on*` attributes and `javascript:` links first.
  GitHub's CSP allows the SVG's own `<style>` and inline `style` attributes, so no restyling is needed.
- Mermaid 11 ids: a node is `<g class="node" id="pr-diagram-flowchart-<nodeId>-<n>">`; an edge is a `path` with
  `data-id="L_<from>_<to>_<n>"` (its label group has the same `data-id`). Node ids can contain underscores, so edge
  ends are matched against the known node ids.

## Load it

1. From the `pr-describe` root, serve the runs: `python3 -m http.server 8765 --bind 127.0.0.1`.
2. Open `chrome://extensions`, turn on Developer mode, choose Load unpacked and pick this `extension/` folder.
3. Open a PR's Files changed page, such as `https://github.com/<owner>/<repo>/pull/<n>/changes`.

The list appears only when `runs/<pr>/<variant>/review.json` exists for the PR (404, a server that
is down or a different repo leave the page untouched). Runs are keyed by PR number alone and `review.json` records its `repo`, which the extension compares with the page's `owner/repo`; two repositories with the same PR number would overwrite each other's runs. The variant defaults to
`one_path_risk_chunked_v11b`; change it and the server URL on the extension's options page. The
manifest only allows `http://127.0.0.1:8765`, so another origin also needs a `host_permissions` entry.
After editing a file, reload the extension on `chrome://extensions` and refresh the GitHub tab.

Run the pure tests with `node --test test/extension.test.js`.

## Files

| File | Role |
| --- | --- |
| `background.js` | Fetches `review.json` for the content script; the page server sends no CORS headers |
| `github_page.js` | The only module with GitHub selectors |
| `focus.js` | Hides diffs outside a chunk and scrolls to a diff |
| `tree.js`, `tree.css`, `focus.css` | The grouped list and the class `focus.js` toggles |
| `content.js` | Wiring: URL changes, debounced re-apply, expansion and selection state |
| `classify.js` | Tells a failed request (server down) from a non-OK response (no run) |
| `choose_variant.js` | Which variant to load (an ES module, used by `background.js`) |
| `boxes.js` | Box badges for file rows and a box's target file |
| `variants.js` | Which chunk stays selected after a variant switch |
| `diagram.js`, `diagram.css` | The diagram panel, its overlay and chunk emphasis |
| `source.js` | Content-script side of the fetch |

The content scripts are classic scripts sharing `globalThis.prFocus`, loaded in the order listed in `manifest.json`.

## GitHub selectors (observed 2026-10-04 on GitHub's React-based Files changed page)

All in `github_page.js`. Class names carry hashed suffixes, so they match on a `[class*="..."]` prefix.

| What | Selector or rule |
| --- | --- |
| Diff block | `div[id^="diff-"]` with class containing `Diff-module__diffTargetable`; id is `diff-` + sha256 hex of the file path |
| Entry hidden | the block's ancestor `div[class*="PullRequestDiffsList-module__diffEntry"]` |
| Block path, first choice | `"diff-" + sha256(path)` looked up with `getElementById` |
| Block path, fallbacks | a descendant `[data-file-path]`, else `table[data-diff-anchor]` with `aria-label` `Diff for: <path>` |
| Diagram host | `[class*="prc-PageLayout-PaneWrapper"]` (the file pane) and `[class*="prc-PageLayout-ContentWrapper"]` (the diffs' column), both inside `#diff-comparison-viewer-container`. The panel is inserted right after the pane with the pane's computed `order` (before the column with the column's order when there is no pane), so DOM order places it between them and no GitHub element is restyled. Top offset copied from the pane |
| Pane divider | `[class*="prc-PageLayout-PaneVerticalDivider"]` inside the pane, made transparent by a `<style>` carried in the panel (`:has(+ #pr-focus-diagram)`, so it applies only while the panel follows the pane) |
| Tree host | `#pr-file-tree > [class*="PullRequestFileTree-module__FileTreeScrollable"]`: GitHub's tree with its "File tree" heading. `#pr-file-tree` also holds the "Filter files" box as its first child, so the list is inserted before the host and the host is hidden with a class |
| Line row | `[data-line-anchor="diff-<sha256 of path>R<line>"]` (`L` for a removed line); its closest `tr` is flashed and scrolled to the middle of the window. |
| Head SHA | `/"head(?:Oid\|Sha)"\s*:\s*"([0-9a-f]{40})"/` over `script[type="application/json"][data-target="react-app.embeddedData"]`, trusted only for the PR the page was first opened on |

If a chunk hides nothing, the list is missing, or the list says it couldn't find the diff blocks, GitHub changed these;
update `github_page.js` only.

When GitHub's file tree pane is closed there is no tree host, so no list is shown until the pane is reopened.
