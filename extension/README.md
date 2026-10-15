# PR Brief extension

A Chrome extension (Manifest V3) for GitHub's Files changed page. It reads the brief's `review.json` (schema 4, written by `render.py`) from the PR's own comment and puts the walkthrough's stops and the layers in GitHub's file pane, with GitHub's own tree one tab away. A switch in the list's header, or Alt+B, hands the whole page back to GitHub. It only reads, and posts nothing.

## Where the brief comes from

A reviewer needs the extension and nothing else: no server and no token.

The GitHub Action (`post.py`) closes its collapsed "PR Brief" comment with a nested, collapsed "Brief data" block, a code
fence holding the base64 of the gzip of `review.json` plus the run's `diagram.svg` (as `diagram_svg`). Older comments also
carry the run's `body.html` as `body_html`, which is dropped unread. `comment_source.js` finds the earliest such block in
the page's rendered comments, inflates it (`DecompressionStream`) and hands `source.js` the review and the diagram. The
files page fetches the conversation page with the user's own session (`credentials: "include"`) to read it. The review
must be schema 4 with `nodes` and a `walkthrough` and must name this repository and PR; otherwise the comment counts as no
brief, and the page is left as GitHub draws it.

Known gap: a comment behind GitHub's "Load more" pagination on a very long conversation is not in the page's HTML, so it is
not found. A comment over GitHub's size limit has no "Brief data" block (`post.py` drops it first), so it is not found
either. The block is read from whichever commenter posted it: the extension does not check the author, and takes the
earliest block in the page.

What the list shows, in GitHub's left column (the file tree's pane, `#pr-file-tree`, where it is the first child; in "Walkthrough" and "Layers" the pane's own children are hidden under it, in "Files" they stay; with no pane, as when GitHub's tree is closed, the list floats at the page's left edge):

- A toggle, "Walkthrough" / "Layers" / "Files" (drawn without a frame around it and the chips; the toggle and each chip keep their own shape). The page opens in "Walkthrough" for a brief that has stops, else in "Layers", else in "Files". "Files" shows GitHub's own file tree under the toggle and the chips (see "Files tab"); "Walkthrough"
  is the stop list and "Layers" (only for a brief that has layers, see "Layers tab") the layer list, and the toggle stays so you can switch again. At the toggle's right end a button labelled "← GitHub", with the tooltip "Switch to GitHub's own view (Alt+B)", hands the page back to the host (see "Handing the page back"). No mode or stop ever hides a diff, except a layer, which narrows the page to its hunks, and the Tests control in "Files" and "Layers", which hides the test files or every other file: otherwise every file's diff is always in the page, so the host's find
  and page-down work across the whole change.
- Under the toggle, a filter line. In "Walkthrough" and "Files" its left side holds chips that pick which files the pane lists: "All N" (the PR's changed files), "API N" and
  "Data N", from `review.json`'s `file_sets`. A chip with no files is not shown, and a run with no contract or data files
  (or an older run without `file_sets`) has no chips. The chip is per tab and not remembered, stays through a switch of the toggle, and clicking one never
  moves the diagram. See "File sets" below.
  In "Layers" it holds the layer count instead (see "Layers tab"). At its right end, when the brief lists test files, sits the Tests control (see "Tests control"). A line with nothing to show is not drawn.
- Under the toggle in "Walkthrough" mode, one row per stop of the walkthrough (see "The walkthrough"): no tabs. The
  diagram's boxes in `review.json` drive the diagram's halo and the box named in each stop's callout. A muted line above
  the stops counts them, `6 stops, in reading order` (`1 stop`; with a file set, the stops listed), and says in its tooltip what the list is for; a run with no stops has none.
  The selected row, in this list and in the layer list, has an inset 2px bar and a faint tint of the guide purple (the callout's), and every row's number sits in a fixed two-digit column so titles line up.

## File sets

"API" and "Data" narrow the pane to the files that make up the PR's API contract change and its data change.

- In "Walkthrough" mode the list is the stops whose file is in the set, in walkthrough order, each with its file's name
  under its title. A set whose files have no stop says so.
- In every mode the diff shows only the set's files. In "Files" mode the host's own tree hides the others too, and a
  directory left with no visible file. The host re-renders its tree and loads diffs as the page scrolls, so the hiding is
  applied again on every refresh, as the callouts are. A tree row is matched to a file by the `#diff-…` link it holds; a row with no such link is left showing.
- A click on a diagram box, or on a stop, in a file outside the set puts the chip back on "All" first, so the file shows.

## Tests control

`review.json`'s `file_sets.tests` lists the PR's test files, as full paths. When it is not empty, the filter line (under the
toggle, in "Files" and "Layers" only) ends with the Tests control: a small GitHub-style dropdown button at the line's right
reading `Tests: All ▾` (the muted label "Tests:", the mode in effect in the default colour, a muted triangle-down icon). It is a styled
wrapper (24px high, 12px text, a 1px border, 6px radius, the button background and its hover) with a transparent native `<select>`
(`aria-label="Tests"`) laid over all of it, so a click anywhere opens the browser's own menu and the keyboard works natively;
the wrapper shows a focus ring when the select is keyboard-focused. Choosing an option picks that mode directly. The line's right
padding (14px) matches the list's, so the two end at the same place. A brief
without `file_sets.tests` (an older run, or a PR with no test files) has no control and shows every file. The "Walkthrough"
has no Tests control and no test behaviour: it shows the files its file set chooses, whatever the stored mode.

| Option | Value | Shows |
| --- | --- | --- |
| All | `all` | every file |
| Unit | `unit` | every file but the integration tests |
| Integration | `integration` | every file but the unit tests |
| Hidden | `hide` | every file but the tests |
| Only | `only` | the test files only |

A path is a test when it is in `file_sets.tests` or sits in a JVM source set other than `main` with "test" in its name; the pane's
lists and the page's filter use that one definition. A test is classified by its path and name alone: a fixture when its JVM source set
has "fixture" in its name (`src/testFixtures/`); an integration test when its source set has "integration" in its name
(`src/integrationTest/`), its name ends in `IT` or `IntegrationTest` before the extension, or it is named like `foo.integration.test.ts`
or `foo.integration.spec.js` (any js or ts extension); a unit test otherwise. "Unit" and "Integration" hide the other kind only, never a
fixture; "Hidden" hides every test, fixtures included.

- **Diff and tree.** In "Files", in "hide", "unit" and "integration" the page hides the diffs of the tests the mode hides and the host's tree rows for them, and a directory left
  with none, whatever the chip or the layer keeps (the `exclude` of `page.filter`, a third filter that only subtracts). In "only" the
  page is narrowed to the test files by the file filter (within the chosen chip, if any), so no list of the PR's other files is
  needed. Either way the host's own tree rows follow, as with a chip.
- **Layer file list.** In the selected layer's file list, the files the mode keeps out of view (the tests the mode hides, any other file in
  "only") are not drawn, and neither is a package line or module header left with nothing (a test source set's package line goes when all of its
  files are hidden). A blue-tinted chip above the list, "N tests hidden" (in "unit" "N integration tests hidden", in "integration" "N unit tests hidden") or "N files hidden", counts what the mode left out. In "Files" the same chip, counting the distinct files the page filter excludes among the page's diff blocks and the brief's paths, ends the panel, directly above the host's tree; it is left out in "all" and when nothing is excluded.
- **Layers.** The selected layer's ranges lose the excluded files' ranges, so its test hunks drop out in "hide" and its other
  hunks in "only". The layer's callout and its jump use the files of the hunks still in view, not all of the layer's hunks. A layer
  whose hunks are all kept out by the mode (a layer of tests only, with tests hidden) is shown whole instead, so that opening
  it still shows its lines and its callout.
- **Preference.** The mode is kept in this browser's `localStorage` under `prf-tests-mode` as the string `all`, `hide` or `only`
  (absent means `all`), across PRs, read and written in a try/catch. A review with no test files ignores it.

## The walkthrough

`review.json`'s `walkthrough` is an ordered list of stops, each `{i, title, why, path, side, line,
node}`: the model's reading order through the change, which can return to a box it has visited. `line` is null for a
stop that names only a file. `node` is the id of the diagram box the stop belongs to, or null when no box holds the
stop's file. `nodes` is an object from box id to `{title, files, stops}`, the box's title, the paths it covers and the
numbers of the stops that land on it. A run that is not schema 4 with `nodes` and a `walkthrough` (made by an earlier
variant) is not shown, and the page is left as GitHub draws it.

- The list has one row per stop: its number and its title. The current stop is highlighted and scrolled into view. A
  row goes to its stop: it makes the stop's file the active one, and jumps to the stop's line, or, for a stop with no line,
  to the file's callout above its header. Either way the callout's top edge lands 16px below the sticky chrome over the
  diffs and the file's own sticky header, both measured at that moment, so every stop appears in the same place and the
  Previous and Next buttons stay under the pointer. Near the end of the page it lands as close as the page can scroll.
  Once landed, a stop is held there while content above it shifts (diffs loading, files expanding), watched by a
  ResizeObserver on the diffs, until the user scrolls or clicks or another jump starts. The diagram follows the stop: its box takes the halo and the
  canvas centres on it. GitHub renders a diff's rows only once the diff is near the window, so the jump scrolls to the
  file's diff, waits up to 10 seconds for the row, then scrolls its callout into place, measuring again after each scroll and
  nudging until it sits there; on a timeout the view stays at the file's header. A diff the host does not render by
  default (GitHub's "Load Diff" button for a large or generated file) has no rows to wait for, so the jump clicks the
  button first and waits up to 30 seconds, since the host fetches the diff. Opening the files page on a link to
  a stop's line or file goes to that stop.
- Every stop that has loaded gets a callout above its line (above the file's header for a stop with no line), as soon as
  the review shows and as GitHub loads more of the diff, in both unified and split views. It is a full-width
  table row holding a neutral card (the host's muted surface, a 1px purple border, rounded, from the file pane's left
  edge, in 14px text, as wide as its left column plus a 24px gap plus its nav column, and never wider than the diff
  column) in two columns. The left column has a route icon and a header in bold default text, `Stop <i> of <n> · <box
  title>` (without the box part for a stop on no box), a small muted chevron, then the stop's title in
  normal weight, and then on its own line a small muted "Why stop here" over the stop's `why`, wrapping within the
  header's width, with backtick spans in it drawn as code. The right column is top-aligned with the header and right-aligned, with no divider before it, and always has two
  slots: a "↑ Previous" button (its tooltip is the previous stop's title) over a "Next ↓" button (its tooltip is the next stop's title). On the first stop the Previous slot, and on the last the Next slot,
  stays in the layout hidden (`visibility: hidden`, `inert`, `aria-hidden`, no tab stop), so the other slot does not
  move and the column keeps its height; a walkthrough of one stop hides both. On a diff too narrow for
  both columns the right column wraps below the text and stays right-aligned. A button goes to that stop, as a click on
  its row does, without the flash of its line. Clicking Previous or Next quickly ends at the last stop clicked. A callout is placed
  once per stop, so a re-render or a lazy load never doubles it. The callouts show only in "Walkthrough" mode.
- A stop with no line has its callout as the first child of that file's diff entry, so it sits directly above the file header and spans the entry's full width with the same card. The jump
  places the callout like a line stop's, so the header shows under it, and marks the callout alone. It is placed once, comes back if the host drops it, and goes with the callouts.
- Every callout of the shown mode (all stops in Walkthrough, all layers in Layers) has the same width: that of the widest
  card at its natural width, its heading and its Previous/Next column, not its summary, at least 480px and never more than
  the space it sits in. The host draws only the diff near the viewport, so the width is measured from the data: every card
  is built into a hidden container, and the widest, rounded up, is set as `--prf-callout-width` on the page, which
  `tree.css` reads. It is measured again whenever the shown set is rebuilt (the brief loading, a mode switch, a Tests
  change), not on scroll; Files mode keeps the last width.
- The stop's line is left exactly as the host draws it. Each callout card starts at the file pane's left edge, and the
  jumped-to stop's card border is the full purple where the other callouts' is purple at 45%. The file, line number and code are not repeated, since the diff row shows them. Only
  one card is marked as the target; the mark goes whenever the line target clears (another selection, a new jump or
  teardown) and comes back if the host re-renders the row. When a jump lands on a stop's line, the line flashes: a
  translucent purple overlay (the guide colour) fades in and out twice over 1.2 seconds on top of the row's cells, so the
  host's add/remove tint shows through. A stop with no line, and a layer, flash nothing, and no callout pulses. The flash
  fires on every jump from the list or the diagram (a stop or box click) and from a link to a stop, but not
  from the callout's own Next and ↑ buttons, since the reader is already following the callouts. Only the jumped-to
  line flashes, and not when the host re-renders the row. Under `prefers-reduced-motion` it does not flash.
- A banner appears when the review was generated for an older head commit than the page's.

Nothing about the review's state is remembered, except which layers are judged (see "Layers tab"), the Tests control's mode (see "Tests control") and who owns the pane (see "Handing the page back"): every load and every navigation into the files page opens
in "Walkthrough" mode (or "Layers", or "Files" for a brief with neither) with nothing selected, the diff where GitHub put it and the diagram collapsed. A
link to a stop's line selects that stop. The one thing kept is whether the diagram panel is expanded (see below).

## Files tab

"Files" is the host's own file tree, under the extension's toggle and chip line. The panel holds only those two; the pane's own children (GitHub's "Filter files" box and tree) stay showing below it.

- The chips and the Tests control filter the tree's rows as they filter the diff: a file row whose diff is hidden is hidden, then a
  directory row left with no visible file. A row is matched to its diff by the `#diff-…` link it is or holds, and a row with no
  such link is left showing. The rows are looked up inside the pane host only, never in the extension's own panel. Leaving "Files",
  choosing "All", or handing the page back shows every row again.
- GitHub's rows are ARIA tree items inside `#pr-file-tree`: `li[role="treeitem"]` without `aria-expanded` is a file, with it a directory.
- The host re-renders its tree and re-opens directories as the reader browses it, so a tree row the host adds or drops schedules a refresh that applies the filters again.
- The "All" chip counts the files of the diffs the page holds joined by every path the brief names.

## Handing the page back

The pane has one owner, the brief (the default) or the host.

- The button at the right end of the list's toggle, "← GitHub", gives the pane to the host: the list, the
  callouts, the file filter, the focus marks and the diagram panel are removed, and the page is as the host draws it, apart from a slim bar
  at the top of its file pane, `PR Brief · 6 stops, 3 layers` with a Show button, which gives the pane back.
- Alt+B does the same from the keyboard, in either direction (`commands.toggle-brief` in the manifests; rebind it at
  `chrome://extensions/shortcuts`). `background.js` flips the stored owner and every open PR page follows.
- The owner is kept in `chrome.storage.local` under `paneOwner`, `brief` or `host`, the same for every PR, and a change in one tab is applied in the others.
- A PR with no brief has no switch and no bar: the page is the host's.

## Layers tab

`review.json`'s `chunks` (the layers; the code calls them chunks), when the brief has them, is an ordered list of `{i, title, summary, risk, risk_reason, depends_on,
hunks}`: the change cut into pieces to judge one at a time. `risk` is `"low"`, `"medium"` or `"high"`, `depends_on` the
numbers of the layers this one builds on, and each hunk `{id, path, change, old: [start, count], new: [start, count], added, removed}`, the last two
being the lines the hunk adds and removes (a review made before they were written has none).
A brief with no `chunks` (an older run; `schema` is still 4) has no "Layers" entry in the toggle.

- The filter line has a muted line at its left, `6 layers · 1 judged`; the list has one row per layer: its number and title, and, at the right end of the title row, level with the title's first line, a quiet risk
  chip (the risk word at 12px in green, amber or red for low, medium and high, with a 1px border in the same colour at 40%, no fill) and, once it is judged, a green check icon (tooltip "Judged"). The panel shows no line counts. The selected row is marked as a
  stop's is, and scrolled into view when a layer is opened from its callout.
- The selected row, and only it, lists the files its layer touches, grouped by module and package. Each package is one line, not a button, with a
  muted folder icon (GitHub's `file-directory-fill`) and its label in the default text colour; a long label wraps rather than being cut off,
  preferring to break after a `/`, and hangs under its own first character, not under the icon. The folder's full directory is the tooltip.
  Its files sit under it, each file's icon 20px right of the package icon (a module header, a package and a file each step 20px, the rail under the centre of the header's icon; a module with no header starts its first level where it would be without one): one button per file with a muted file icon (`file`) and the
  file's name in the default text colour, and its full path as the tooltip. Files within a package come in the order of each file's first hunk. A click
  jumps to that file's first hunk of the layer, at the line the layer's own jump would use, and stays in the tab: the
  selection and the page filter do not change. A click on a file of a layer that is not selected opens that layer first. A file the
  Tests control keeps out of view is not drawn (see "Tests control").
- The files are grouped by module, then by package line. A JVM source folder, one shaped `<module>/src/<set>/<lang>/<package>`
  with `<lang>` java, kotlin, scala, groovy or resources, is in its module (`/` when `src` is at the repo root); any other path is
  in the module of its first directory (`/` for a file at the repo root), its package the rest of the directory. A module with two
  or more package lines in the layer gets a header (a box icon and its name) with a thin rail down its left side, and its package
  lines are labelled by the package alone; a module with one has no header, and its line reads `<module> › <package>` (a non-JVM
  directory in full). The package segments every JVM folder in the review shares at the front (not just this layer's) are dropped,
  always leaving each folder one segment. Each source set of a package has its own line; a source set other than main
  or a test set is kept in the label, e.g. `acme-api generated › gen`. A module's lines come in the order of their first hunk, the main (and other
  non-test) lines first and then the test source sets' lines (test, integrationTest, testFixtures), also in the order of their first hunk, and the header
  rule counts the test lines. A test source set's line has `src/<set>` (`src/test`, `src/integrationTest`) at its right end in 12px muted text, which never wraps (the
  label wraps first); main lines have none. Modules come in the order of their first hunk.
- A test is a file in `file_sets.tests`, or a file of a JVM source set other than `main` with "test" in its name. A test is not paired with a
  source file: it is a file button like any other, at file level in its package line, with a beaker icon and its full file name. A JVM test is in its
  source set's own line; a test of another language sits in its directory's line (`foo.test.ts` beside `foo.ts`, `__tests__` as a directory of its
  own), with no label.
- Selecting a layer narrows the page to it: the diffs of the layer's files only, and in each only the rows that show a
  line inside one of the layer's hunks. A hunk's new range filters the right side and its old range the left, so removed
  lines stay; a hunk header or an expand-context row left standing before a hidden hunk is hidden with it. The host's own
  tree is hidden under the panel in this tab, but its rows for the other files are hidden as in a file set. The view then
  lands on the layer's callout above its file's header, the way a stop on a file does, and the selection clears any stop, box or chip. Selecting a stop, a box or a file leaves the
  tab and shows the whole diff again; opening the tab with a layer already selected narrows to it again, and with none
  selects nothing and filters nothing.
- The layer's callout sits above the header of one file, outside the file's box, like a stop on a file: the first, in the page's
  order, of the files the layer's shown hunks touch (a Tests-hidden file does not count, unless every file of the layer is hidden). The
  page's order is the document order of the file entries; when none of the layer's entries is in the page yet, the first file of
  the layer's hunks stands in. A click on a file in the layer's list still lands on that file's first hunk line. Its header is shaped like a stop's: `Layer 2 of 6` in bold, a small muted chevron, then the title in
  normal weight; under it are the risk pill and `risk_reason` (muted) when there is one, the summary, and `Needs 1, 3` with a
  button per number that opens that layer. Beside them are the same "↑ Previous" and "Next ↓" slots as a stop's, opening
  the neighbouring layer, with the "Judged" checkbox under them. Only the selected layer's callout is shown, and none in the other tabs.
- "Judged" is the reader's own mark, kept in this browser's `localStorage` under `prf-judged:<host>/<owner>/<repo>#<pr>@<head_sha>`
  as a JSON array of layer numbers, so it is per PR head and comes back on reload; a new head starts empty. It is read and
  written in a try/catch, and without storage the marks last until the page is left. Nothing else about layers is remembered.
- The chip row ("All", "API", "Data") is not drawn in this tab: the selected layer owns the page filter, and a chip
  is not applied while the tab is open.
- Known limit: the host renders rows as the page scrolls, and a row it has not rendered yet is filtered when it appears
  (the filter runs again on every change of the document), so a row can show for an instant first. A diff the host holds
  back behind its load control is loaded, once, when its layer is selected.

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

When the comment carries a `diagram_svg`, `diagram.js` docks it as the leftmost pane, right before GitHub's file pane in GitHub's own flex row, so the page reads
diagram, stop list, code, and the other two columns narrow by the panel's width (by default the width at which the walkthrough draws the diagram's widest box with its halo at 100%, at most 40% of the viewport, at least 220px) instead of being
covered. The panel is sticky at the file tree pane's offset and as tall as the pane. It is mounted collapsed, as a 30px rail
in that spot with "Diagram" written vertically under a `›` button that expands it; the header's `‹` button collapses it
again. Whether this tab expanded it is remembered in `sessionStorage`, so a reload keeps it expanded.
- The diagram, the stop list and the code are separated by single dividers: the panel's right border, then GitHub's own
  rule down the pane's right edge.
- The diagram follows GitHub's theme: its text, outline and halo colours are the Primer names, with the system's
  `prefers-color-scheme` as the fallback, and the purple accents stay the same. The pane's own rules re-theme a diagram
  whose SVG was written with fixed colours.

- Motion: the line jump scrolls smoothly (a target more than 1.5 windows away is first approached instantly to one window
  short of it); newly visible diffs fade in over 150ms; diagram emphasis cross-fades over
  250ms. The emphasized box gets a concentric 8px halo (22% of the accent, `#534ab7` in the light theme and `#9d94f5` in the dark), an 11% accent tint over its fill and an accent-dark title, and keeps its own stroke. `prefers-reduced-motion: reduce` turns all of it off, leaving only the end states.
- The panel's right edge is a drag handle: dragging it right widens the panel and narrows the diffs. Width is 220px up to 65% of
  the viewport, by default the width that shows the widest box at 100%. A width dragged to lasts until the page is left and is not stored, so every load starts at the default.
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

## Load it

1. Open `chrome://extensions`, turn on Developer mode, choose Load unpacked and pick this `extension/` folder.
2. Open a PR's Files changed page, such as `https://github.com/<owner>/<repo>/pull/<n>/changes`. A PR whose brief comment
   the Action has posted shows its brief.

The list appears only when the PR has a brief comment (no comment, or one for a different repo or PR, leaves the page
untouched). `review.json` records its `repo` and `pr`, which the extension compares with the page's.
After editing a file, reload the extension on `chrome://extensions` and refresh the GitHub tab.

Run the pure tests with `node --test test/*.test.js`.

## Files

| File | Role |
| --- | --- |
| `background.js` | Flips the stored pane owner on the Alt+B command |
| `page_common.js` | What every host's page shares: sticky-offset scrolling, the line jump, the stop callouts, the file, hunk and exclude filters, mounting the panel in the host's file pane, change watching, and `resizeHandle`, the diagram panel's drag handle. `createPage(spec)` builds an adapter from a host's spec |
| `github_page.js` | The only module with GitHub selectors; builds the GitHub adapter |
| `page.js` | Picks the adapter whose `hosts` lists `location.host` and exposes it as `prFocus.page`, which `content.js`, `focus.js`, `tree.js` and `diagram.js` call |
| `focus.js` | Marks the active file's header, and scrolls to a diff. It hides nothing |
| `tree.js`, `tree.css`, `focus.css` | The stop list and the layer list, the off bar, the stop and layer callout cards with their previous and next, and the classes `focus.js` and the line jump toggle |
| `content.js` | Wiring: URL changes, debounced re-apply, expansion and selection state, the layer selection and the judged marks |
| `diagram.js`, `diagram.css` | The diagram panel, its overlay and box emphasis |
| `comment_source.js` | Reads the brief from the PR's "Brief data" comment block (inflate, split, fetch the conversation page). Loaded before `source.js` |
| `source.js` | Content-script side of loading: the review from the PR's comment, and the stored pane owner |

The content scripts are classic scripts sharing `globalThis.prFocus`, loaded in the order listed in `manifest.json`.

### The page adapter

Everything the rest of the extension asks of the page goes through one object, `prFocus.page`: `name`,
`prFromUrl` (`{owner, repo, pr, view}`, `view` being `"files"` or `"conversation"`) / `pullFromUrl` (`{owner, repo, pr}`), `conversationUrl(pr)`, `headSha`, `fileBlocks`, `entryOf`,
`entryFor`, `lineAnchor`, `scrollToElement`, `fileHeaderOf`, `jumpToLine`, `clearLineTarget`,
`restoreLineTarget`, `ownsLine`, `cancelJump`, `filter({ files, hunks, exclude })` (each `null` for none: `files` and `exclude` are paths, `hunks` is `[{path, side, start, count}]`; one call sets all three and applies them in one pass), `blockCount()`, `changedFileCount(reviewPaths?)` (the files of the diff blocks in the page joined by the paths the brief names), `diagramHost`, `paneHost()` (the element of the host's file pane, or null; the host's tree rows are looked up inside it), `mount(panel, { hideRest })` (puts the panel first in the pane, hides the pane's other children unless `hideRest` is false, floats it at the page's left edge when there is no pane, and puts it back when the host re-renders the pane), `unmount()` (removes the panel and shows what it hid), `onChange`, `quietly(fn)` (runs `fn` so that the `onChange` watchers do not see its own changes to the page, after handing them the changes made before it), `isStructural(node)` (whether a node a mutation added or removed is, or holds, a table row, diff block or tree row) and `onNavigate`, and `loadDiff(id)` when the host has one. A new host is a
spec for `createPage` (see the comment at the top of `page_common.js`) plus an entry in `manifest.json` and `page.js`.

## GitHub selectors (observed 2026-10-04 on GitHub's React-based Files changed page)

All in `github_page.js`. Class names carry hashed suffixes, so the stable hooks are ids, ARIA roles and data attributes; a `[class*="..."]` prefix is the last resort (the page and pane wrappers below).

| What | Selector or rule |
| --- | --- |
| Diff block | `div[role="region"][id^="diff-"]`; id is `diff-` + sha256 hex of the file path |
| Entry | the block's parent element, which holds only the block |
| Block path, first choice | `"diff-" + sha256(path)` looked up with `getElementById` |
| Block path, fallbacks | a descendant `[data-file-path]`, else `table[data-diff-anchor]` with `aria-label` `Diff for: <path>` |
| Diagram host | `[class*="prc-PageLayout-PaneWrapper"]` (the file pane) and `[class*="prc-PageLayout-ContentWrapper"]` (the diffs' column), both inside `#diff-comparison-viewer-container`. The panel is inserted right before the pane with the pane's computed `order` (before the column with the column's order when there is no pane), so DOM order places it first and no GitHub element is restyled. Top offset copied from the pane |
| Pane host | `#pr-file-tree`, by id alone: the pane holding the "Filter files" box and the tree. The panel goes first in it; in "Walkthrough" and "Layers" its other children are hidden with a class |
| Tree rows | `li[role="treeitem"]` inside the pane host, whose class names are generated and so not used: without `aria-expanded` a file, with it a directory; a file row is matched to its diff by the `a[href*="#diff-"]` it holds (the diff's id). A directory row is hidden only when it has file rows in the page and all of them are hidden |
| Line row | `[data-line-anchor="diff-<sha256 of path>R<line>"]` (`L` for a removed line); its closest `tr` is flashed, and its callout row is scrolled to the stop place. |
| Row lines, hunk rows | `rowLines(tr)` reads the row's `[data-line-anchor]` cell as `diff-<hash>(L\|R)<n>`, one per row: R for an added or a context line, L for a removed one. `hunkRow(tr)` is a row holding `td.diff-hunk-cell`: the `@@` header and the expand-context row. That cell carries an anchor too, for the line just before or after the hunk (`R0` above a new file's first hunk, `R133` above a hunk starting at 134), so it is skipped as a line. Observed 2026-10-09 on a files page in the React view
| Load Diff control | A diff GitHub does not render by default (observed 2026-10-09 on the `/changes` page: "Large diffs are not rendered by default.", "Some generated files are not rendered by default.") is the same diff block with no `tr` and no `[data-line-anchor]`, holding a `button[data-component="Button"]` whose trimmed text is "Load Diff" (inner `span[data-component="text"]`) beside a `span.fgColor-muted` with the sentence. `loadDiff(id)` clicks that button, found by its text and not by the sentence. A second later (1 to 9 s) the block is replaced by a new node with the same id (the old one is detached), so the jump looks the block up by id again after the wait; the entry wrapper stays |
| Head SHA | `/"head(?:Oid\|Sha)"\s*:\s*"([0-9a-f]{40})"/` over `script[type="application/json"][data-target="react-app.embeddedData"]`, on the files page and (observed 2026-10-09) on the conversation page; trusted only for the PR the page was first opened on. With no head SHA no stale-head banner is drawn |
| Brief data (conversation page) | `.markdown-body details` (a comment's body is `div.comment-body.markdown-body.js-comment-body`; the block renders as `details > summary` + `pre.notranslate > code`, observed 2026-10-09 through GitHub's markdown API) whose `summary` text is exactly `Brief data`, and the text of the `pre` inside it; the earliest in document order wins. The files page fetches `/{owner}/{repo}/pull/{n}` and reads the parsed document the same way |

If the list is missing, or the list says it couldn't find the diff blocks, GitHub changed these;
update `github_page.js` only.

When GitHub's file tree pane is closed there is no pane host, so the panel floats at the page's left edge until the pane is reopened, when it moves into it.
