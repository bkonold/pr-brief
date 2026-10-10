// The page behaviour shared by every host: scrolling a diff under the sticky chrome, jumping to a line, the
// callouts shown above the stops' lines and files, and watching for changes. createPage(spec) returns the adapter the rest of the extension
// calls through prFocus.page (see page.js). The spec holds everything that differs per host, which is all
// the DOM knowledge and nothing else; a host's spec lives in its own file (github_page.js, forgejo_page.js).
//
// spec: {
//   name, treeLabel, hosts          display name, the label of the host's own tree, the location.host values it serves
//   origin, changesPage, pullPage   a base for relative URLs, and the patterns of the files page and of any page of a
//                                   PR, each capturing owner, repo and number
//   conversationPage                the pattern of the conversation page (same captures)
//   conversationPath(pr),           the paths of a PR's conversation page and of its files view
//   filesPath(pr)
//   hostId                          "github" or "forgejo": the host name the run server knows it by
//   runKey(pr)                      the runs/<key> folder of a parsed PR
//   readHeadSha(doc)                the head commit sha that `doc` (default: the page's document) shows, or null
//   fetchHeadSha(pr)                optional, async: the PR's head sha read from the host when the page does not show
//                                   it (null on failure)
//   blockSelector, pathOfBlock(b)   the element holding one file's diff, and the path it shows
//   entryOf(block)                  the whole entry of one file's diff, which holds the file callout above its header
//   diffId(path)                    the id of a file's diff block (async)
//   findRow(anchor)                 the table row of a line anchor, or null
//   rowLines(tr)                    the diff lines a table row shows, as [{ side, line }] with side "L" (old file) or "R"
//                                   (new file), read from the row's line anchors; empty for a row that shows no line
//   hunkRow(tr)                     whether a row that shows no line is a hunk header (the `@@` line) or an expand-context
//                                   row; optional, absent meaning no row is
//   loadDiff(id)                    optional: when the diff block with this id shows the host's control for loading a
//                                   diff it does not render by default, clicks it and returns true; else false. The host
//                                   may replace the block once the diff has loaded, so the block is looked up by id again
//   fileHeaderSelector              a file's header; stickySkip: elements the sticky-chrome scan ignores
//   containerSelector               the diffs' container, watched for rows that appear
//   contentSelector                 the diffs' column
//   diagramHost()                   where the diagram panel docks (before the file pane), or null
//   treeHost()                      the host's own file tree element, or null
//   treeFileSelector                the tree's file rows, each being or holding a link whose href ends in the file's
//                                   diff id (`#diff-…`)
//   treeDirSelector                 optional: the tree's directory rows, which hold their files' rows
//   descriptionHost()               the element the PR brief card is inserted before (the PR's opening comment on the
//                                   conversation page), or null
// }
(() => {
  const ns = (globalThis.prFocus ??= {});

  const LINE_TARGET = "prf-line-target";
  const CALLOUT_ROW = "prf-callout-row";
  const FILE_CALLOUT = "prf-callout-file";
  const PULSE = "prf-pulse";
  const FILE_HIDDEN = "prf-file-hidden";
  const HUNK_HIDDEN = "prf-hunk-hidden";
  const DIFF_LINK = 'a[href*="#diff-"]';
  const FAR_VIEWPORTS = 1.5;
  const SCROLL_SETTLE_MS = 1200;
  const JUMP_TIMEOUT_MS = 10000;
  const LOAD_TIMEOUT_MS = 30000;
  const STICKY_BAND_VIEWPORTS = 0.3;
  const LAND_TOLERANCE = 1;
  const CALLOUT_GAP = 16;
  const USER_INPUT_EVENTS = ["wheel", "touchstart", "pointerdown", "keydown"];
  const LAND_CORRECTIONS = 3;
  const IDLE_POLL_MS = 50;
  const IDLE_POLLS = 3;

  // The pure geometry below does not depend on the host.

  // The lowest edge of the sticky or fixed elements stuck at the top of the window over `column` (the
  // diffs' horizontal extent). Each entry is { top, height, left, right }, where `top` is where the element
  // sits once stuck. Elements stuck below `maxTop` or beside the column don't count.
  function stickyOffset(entries, column, maxTop) {
    let offset = 0;
    for (const { top, height, left, right } of entries) {
      if (right <= column.left || left >= column.right || top > maxTop || height <= 0) continue;
      offset = Math.max(offset, top + height);
    }
    return offset;
  }

  // How far to scroll so an entry whose top is at `entryTop` sits `offset` below the top of the window.
  function startDistance(entryTop, offset) {
    return entryTop - offset;
  }

  // The correction still needed once a scroll has settled: 0 when the entry is within `tolerance` of where it
  // belongs, else the distance to scroll.
  function landingDelta(entryTop, offset, tolerance = LAND_TOLERANCE) {
    const distance = startDistance(entryTop, offset);
    return Math.abs(distance) <= tolerance ? 0 : distance;
  }

  // The distance still to scroll for a callout whose top is at `top` to sit CALLOUT_GAP below `offset` (the bottom of the
  // sticky chrome), limited to what the page can scroll: a callout near the end of the page lands as close as the page
  // lets it. 0 when it is within `tolerance` of where it can get. `scrollTop` is the window's scroll position and
  // `scrollMax` the furthest it can go.
  function calloutDelta(top, offset, { scrollTop, scrollMax }, tolerance = LAND_TOLERANCE) {
    const wanted = startDistance(top, offset + CALLOUT_GAP);
    const distance = Math.max(-scrollTop, Math.min(wanted, scrollMax - scrollTop));
    return Math.abs(distance) <= tolerance ? 0 : distance;
  }

  // Waits for the scroll to go idle, then nudges by `delta()` until it reports 0, at most `passes` times. It
  // stops at once when `isCurrent()` turns false. Returns true when the landing is settled.
  async function correctLanding({ idle, delta, nudge, isCurrent, passes = LAND_CORRECTIONS }) {
    for (let pass = 0; pass < passes; pass += 1) {
      await idle();
      if (!isCurrent()) return false;
      const distance = delta();
      if (distance === 0) return true;
      nudge(distance);
    }
    return false;
  }

  // Keeps a landed target in place while the layout around it shifts. `observe(callback)` calls the callback whenever
  // the layout changes and returns how to stop; `onInput(callback)` calls it when the user scrolls or clicks and returns
  // how to stop. Each layout change nudges by `delta()`, the distance the target is off by. The user's first input
  // releases the hold, as does the returned function. Nothing runs after a release.
  function holdPlace({ delta, nudge, observe, onInput }) {
    let released = false;
    const stops = [];
    const release = () => {
      if (released) return;
      released = true;
      for (const stop of stops) stop();
    };
    stops.push(onInput(release));
    stops.push(
      observe(() => {
        if (released) return;
        const distance = delta();
        if (distance !== 0) nudge(distance);
      }),
    );
    return release;
  }

  function reducedMotion() {
    return Boolean(globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
  }

  // Resolves once the window's scroll position has stopped changing, or after `maxMs`. It polls with timers,
  // so it also finishes in a tab where smooth scrolling and scrollend never run.
  function scrollIdle(maxMs = SCROLL_SETTLE_MS * 2) {
    return new Promise((resolve) => {
      const started = Date.now();
      let last = scrollY;
      let still = 0;
      const poll = () => {
        still = scrollY === last ? still + 1 : 0;
        last = scrollY;
        if (still >= IDLE_POLLS || Date.now() - started > maxMs) resolve();
        else setTimeout(poll, IDLE_POLL_MS);
      };
      setTimeout(poll, IDLE_POLL_MS);
    });
  }

  function createPage(spec) {
    function parsePull(pattern, location) {
      const pathname = typeof location === "string" ? new URL(location, spec.origin).pathname : location.pathname;
      const match = pattern.exec(pathname);
      return match ? { owner: match[1], repo: match[2], pr: Number(match[3]) } : null;
    }

    // The PR a files page or a conversation page shows, with which of the two it is: view "files" or "conversation".
    function prFromUrl(location) {
      const files = parsePull(spec.changesPage, location);
      if (files) return { ...files, view: "files" };
      const conversation = parsePull(spec.conversationPage, location);
      return conversation ? { ...conversation, view: "conversation" } : null;
    }

    function filesUrl(pr) {
      return new URL(spec.filesPath(pr), spec.origin).href;
    }

    function pullFromUrl(location) {
      return parsePull(spec.pullPage, location);
    }

    // The URL of the PR's conversation page, where the Action's comment is.
    function conversationUrl(pr) {
      return new URL(spec.conversationPath(pr), spec.origin).href;
    }

    // Whether the page is the conversation page, of `pr` when one is given.
    function isConversationPage(pr) {
      const here = globalThis.location ? prFromUrl(globalThis.location) : null;
      if (here?.view !== "conversation") return false;
      return !pr || (here.owner.toLowerCase() === pr.owner.toLowerCase() && here.repo.toLowerCase() === pr.repo.toLowerCase() && here.pr === Number(pr.pr));
    }

    // The page's data belongs to the document that was loaded, so it describes only the PR that page was
    // first opened on.
    const initialPull = globalThis.location ? pullFromUrl(globalThis.location) : null;
    let cachedHeadSha;

    function headSha() {
      const current = prFromUrl(location);
      if (!initialPull || !current || initialPull.owner !== current.owner || initialPull.repo !== current.repo || initialPull.pr !== current.pr) {
        return null;
      }
      if (cachedHeadSha === undefined) cachedHeadSha = spec.readHeadSha() ?? null;
      return cachedHeadSha;
    }

    // The head sha of `pr`: the page's own when it shows one, else the host's answer.
    async function currentHeadSha(pr) {
      const shown = headSha();
      if (shown || !spec.fetchHeadSha) return shown;
      return (await spec.fetchHeadSha(pr)) ?? null;
    }

    function fileBlocks() {
      const blocks = new Map();
      for (const block of document.querySelectorAll(spec.blockSelector)) {
        const path = spec.pathOfBlock(block);
        if (path) blocks.set(path, block);
      }
      return blocks;
    }

    function entryOf(block) {
      return block ? spec.entryOf(block) : null;
    }

    // The entry of the diff block with this id, or null while that diff is not in the page.
    function entryOfId(id) {
      return entryOf(document.getElementById(id));
    }

    async function entryFor(path) {
      return entryOfId(await spec.diffId(path));
    }

    // The host's anchor for a line of a file's diff: the diff block's id plus the side ("L" old file,
    // "R" new file) and line number.
    async function lineAnchor(path, side, line) {
      return `${await spec.diffId(path)}${side}${line}`;
    }

    // The id of a file's diff block: the anchor of a file-level start, which has no line.
    function fileAnchor(path) {
      return spec.diffId(path);
    }

    const FOLLOWING = 4;

    // Of `paths`, the one whose diff entry comes first in the page's document order; the first of `paths` when none of
    // their entries is in the page yet, since the page's order is not known then. Null for no paths.
    async function firstInPage(paths) {
      const ids = await Promise.all(paths.map(fileAnchor));
      const present = paths.flatMap((path, index) => {
        const entry = entryOfId(ids[index]);
        return entry ? [{ path, entry }] : [];
      });
      if (present.length === 0) return paths[0] ?? null;
      return present.reduce((first, next) => (first.entry.compareDocumentPosition(next.entry) & FOLLOWING ? first : next)).path;
    }

    // What the jump landed on, so a re-render of it by the host can be undone: { anchor } is the line row with that
    // anchor, { anchor, file: true } is the callout at the top of the diff entry with that id.
    let lineTarget = null;
    // The callouts to show, as given to showCallouts.
    let callouts = [];

    function findRow(anchor) {
      return spec.findRow(anchor);
    }

    function calloutRowOf(row) {
      const above = row.previousElementSibling;
      return above?.classList.contains(CALLOUT_ROW) ? above : null;
    }

    // The callout at the top of a diff entry, above its file header, or null.
    function fileCalloutOf(entry) {
      const first = entry?.firstElementChild;
      return first?.classList.contains(CALLOUT_ROW) ? first : null;
    }

    function isPlaced(element, entry) {
      return entry.file ? fileCalloutOf(entryOfId(entry.anchor)) === element : element.nextElementSibling === findRow(entry.anchor);
    }

    // A line callout is a full-width table row directly above its stop's line, so the host's columns stay as they are.
    function placeLineCallout(entry) {
      const row = findRow(entry.anchor);
      if (!row || calloutRowOf(row)) return;
      const cell = document.createElement("td");
      cell.colSpan = Math.max(1, row.children.length);
      cell.append(entry.render());
      const callout = document.createElement("tr");
      callout.className = CALLOUT_ROW;
      callout.dataset.key = String(entry.key);
      callout.append(cell);
      row.before(callout);
    }

    // A file callout is the first child of the file's diff entry, so it spans the entry's width, sits above the file
    // header and is hidden with the entry.
    function placeFileCallout(entry) {
      const host = entryOfId(entry.anchor);
      if (!host || fileCalloutOf(host)) return;
      const callout = document.createElement("div");
      callout.className = `${CALLOUT_ROW} ${FILE_CALLOUT}`;
      callout.dataset.key = String(entry.key);
      callout.dataset.anchor = entry.anchor;
      callout.append(entry.render());
      host.prepend(callout);
    }

    // Each entry's place is found again on every call: it keeps the callout it has, makes one the host dropped, and
    // removes a callout that no longer sits at its place or belongs to no entry.
    function placeCallouts() {
      const wanted = new Map(callouts.map((entry) => [String(entry.key), entry]));
      for (const element of document.querySelectorAll(`.${CALLOUT_ROW}`)) {
        const entry = wanted.get(element.dataset.key);
        if (!entry || !isPlaced(element, entry)) element.remove();
      }
      for (const entry of callouts) {
        if (entry.file) placeFileCallout(entry);
        else placeLineCallout(entry);
      }
    }

    // Shows a callout for each stop: entries are { key, anchor, file?, render() }. `anchor` is a line's anchor, or, with
    // `file: true`, a file's diff id, whose callout goes above that file's header. `render` builds the content of one
    // callout. An empty list removes them all. Calling again with the same entries changes nothing.
    function showCallouts(entries) {
      callouts = entries;
      placeCallouts();
    }

    function clearLineTarget() {
      lineTarget = null;
      for (const row of document.querySelectorAll(`.${LINE_TARGET}, .${PULSE}`)) row.classList.remove(LINE_TARGET, PULSE);
    }

    // Pulses the stop's line and its callout together (a stop with no line, its callout alone), once the jump has landed: the
    // same animation, started at the same moment. Skipped under reduced motion.
    function pulseTarget(elements) {
      if (reducedMotion()) return;
      for (const element of elements) {
        if (!element) continue;
        element.classList.add(PULSE);
        element.addEventListener("animationend", () => element.classList.remove(PULSE), { once: true });
      }
    }

    function targetElement(target) {
      return target.file ? fileCalloutOf(entryOfId(target.anchor)) : findRow(target.anchor);
    }

    // The host re-renders diff rows, which drops our class; the target gets it back.
    function restoreLineTarget() {
      const element = lineTarget ? targetElement(lineTarget) : null;
      if (element && !element.classList.contains(LINE_TARGET)) element.classList.add(LINE_TARGET);
    }

    function ownsLine(node) {
      const element = node?.nodeType === 1 ? node : node?.parentElement;
      return Boolean(element?.closest(`.${CALLOUT_ROW}`));
    }

    // The header of a file's diff entry: the host's header element when it can be found, else the entry's first child
    // that is not our callout.
    function fileHeaderOf(entry) {
      if (!entry) return null;
      const first = entry.firstElementChild;
      const fallback = first?.classList.contains(CALLOUT_ROW) ? first.nextElementSibling : first;
      return entry.querySelector(spec.fileHeaderSelector) ?? fallback ?? null;
    }

    // The page's sticky and fixed elements outside the diffs, the list and the diagram, with their stuck tops.
    function stickyEntries() {
      const entries = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, {
        acceptNode(node) {
          if (node.matches(spec.stickySkip)) return NodeFilter.FILTER_REJECT;
          const { position } = getComputedStyle(node);
          return position === "sticky" || position === "fixed" ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
        },
      });
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const rect = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        const top = style.position === "fixed" ? rect.top : Number.parseFloat(style.top);
        if (Number.isFinite(top)) entries.push({ top, height: rect.height, left: rect.left, right: rect.right });
      }
      return entries;
    }

    function currentStickyOffset(entry) {
      const column = (document.querySelector(spec.contentSelector) ?? entry).getBoundingClientRect();
      return stickyOffset(stickyEntries(), column, innerHeight * STICKY_BAND_VIEWPORTS);
    }

    // Every scroll started through scrollToElement takes the next token, and cancelJump invalidates them all, so
    // a landing's corrections never undo a scroll that came after it.
    let scrollToken = 0;

    function newScrollToken() {
      scrollToken += 1;
      return scrollToken;
    }

    // Scrolls until `delta()` reports 0. A target more than FAR_VIEWPORTS windows away is first approached
    // instantly to one window short of it, so the smooth part is short and doesn't pass through every lazily
    // rendered diff on the way. The host can lay diffs out lazily, so heights above the target can change while
    // scrolling; once the scroll is idle the target is measured again and nudged into place. Resolves with
    // whether it landed.
    async function scrollUntilLanded(delta, token) {
      let distance = delta();
      if (reducedMotion()) {
        scrollBy({ top: distance, behavior: "instant" });
      } else {
        if (Math.abs(distance) > innerHeight * FAR_VIEWPORTS) {
          scrollBy({ top: distance - Math.sign(distance) * innerHeight, behavior: "instant" });
          distance = delta();
        }
        scrollBy({ top: distance, behavior: "smooth" });
      }
      return correctLanding({
        idle: scrollIdle,
        delta,
        nudge: (top) => scrollBy({ top, behavior: "instant" }),
        isCurrent: () => token === scrollToken,
      });
    }

    // Scrolls so a diff entry's top sits just below the sticky chrome over the diffs, with its header whole and
    // nothing of the previous file above it. The entry is measured, not its header: the header is sticky, so
    // while the file is being read its rect stays at the stuck offset whatever the scroll position.
    function scrollToElement(entry) {
      return scrollUntilLanded(() => landingDelta(entry.getBoundingClientRect().top, currentStickyOffset(entry)), newScrollToken());
    }

    // What the window can scroll: where it is and the furthest it can go.
    function scrollLimits() {
      return { scrollTop: scrollY, scrollMax: document.documentElement.scrollHeight - innerHeight };
    }

    // The distance to scroll for `callout`, a stop's callout inside `entry`'s diff, to sit CALLOUT_GAP below the sticky
    // chrome over the diffs and the file's own sticky header, so every stop lands in the same place. Both are measured
    // as they are now.
    function calloutPlace(callout, entry) {
      const header = fileHeaderOf(entry)?.getBoundingClientRect().height ?? 0;
      return calloutDelta(callout.getBoundingClientRect().top, currentStickyOffset(entry) + header, scrollLimits());
    }

    // The place of a line stop: its callout row above the line, else the line's row.
    function linePlace(anchor, entry) {
      const row = findRow(anchor);
      return row ? calloutPlace(calloutRowOf(row) ?? row, entry) : 0;
    }

    // A file stop's callout is above its header in the entry; with none, the entry's top stands in for it.
    function filePlace(id) {
      const entry = entryOfId(id);
      return entry ? calloutPlace(fileCalloutOf(entry) ?? entry, entry) : 0;
    }

    // The hold on the last landed stop, or null.
    let releaseHold = null;

    function watchLayout(callback) {
      const observer = new ResizeObserver(callback);
      observer.observe(document.querySelector(spec.containerSelector) ?? document.body);
      observer.observe(document.body);
      return () => observer.disconnect();
    }

    function watchInput(callback) {
      for (const type of USER_INPUT_EVENTS) globalThis.addEventListener(type, callback, { capture: true, passive: true });
      return () => {
        for (const type of USER_INPUT_EVENTS) globalThis.removeEventListener(type, callback, { capture: true });
      };
    }

    function endHold() {
      releaseHold?.();
      releaseHold = null;
    }

    // Keeps the landed stop in place while content above it shifts (diffs loading, files expanding) until the user scrolls
    // or clicks, a newer jump starts or the jump is cancelled.
    function holdStop(delta) {
      endHold();
      if (!globalThis.ResizeObserver) return;
      releaseHold = holdPlace({ delta, nudge: (top) => scrollBy({ top, behavior: "instant" }), observe: watchLayout, onInput: watchInput });
    }

    let cancelPendingJump = null;
    let latestJump = 0;

    // Resolves with the row for `anchor` as soon as it is in the DOM, or null after `timeoutMs` or when a
    // newer jump cancels this wait. The observer is disconnected on every outcome.
    function waitForRow(anchor, timeoutMs) {
      return new Promise((resolve) => {
        const found = findRow(anchor);
        if (found) return resolve(found);
        const observer = new MutationObserver(() => {
          const row = findRow(anchor);
          if (row) finish(row);
        });
        const timer = setTimeout(() => finish(null), timeoutMs);
        function finish(row) {
          observer.disconnect();
          clearTimeout(timer);
          if (cancelPendingJump === cancel) cancelPendingJump = null;
          resolve(row);
        }
        const cancel = () => finish(null);
        cancelPendingJump = cancel;
        observer.observe(document.querySelector(spec.containerSelector) ?? document.body, { childList: true, subtree: true });
      });
    }

    // A diff's rows may be rendered only once the diff is near the window, so the file's diff is scrolled
    // to first; then the line's row is waited for, highlighted, and scrolled so its callout sits in the stop place (see
    // calloutPlace), where it is held. A diff the host holds back behind a load control is loaded first, and the wait is
    // longer since the host fetches it. If the row never appears the view stays at the file's header. Returns whether the
    // callout ended in place. `pulse: false` lands without the pulse.
    async function jumpToLine(path, side, line, { pulse = true } = {}) {
      const mine = ++latestJump;
      cancelPendingJump?.();
      endHold();
      clearLineTarget();
      const id = await spec.diffId(path);
      const anchor = `${id}${side}${line}`;
      if (!entryOfId(id) || mine !== latestJump) return false;
      scrollToElement(entryOfId(id));
      const loading = !findRow(anchor) && Boolean(spec.loadDiff?.(id));
      const found = await waitForRow(anchor, loading ? LOAD_TIMEOUT_MS : JUMP_TIMEOUT_MS);
      if (!found || mine !== latestJump) return false;
      lineTarget = { anchor };
      found.classList.add(LINE_TARGET);
      placeCallouts();
      const place = () => linePlace(anchor, entryOfId(id));
      const landed = await scrollUntilLanded(place, newScrollToken());
      if (mine !== latestJump) return false;
      const row = findRow(anchor);
      if (!row) {
        clearLineTarget();
        return false;
      }
      row.classList.add(LINE_TARGET);
      holdStop(place);
      if (pulse) pulseTarget([row, calloutRowOf(row)]);
      return landed;
    }

    // Scrolls to a file's diff entry, whose callout is its first child, so the callout sits in the stop place (see
    // calloutPlace), where it is held. Returns whether the callout ended in place. `pulse: false` lands without the pulse.
    async function jumpToFile(path, { pulse = true } = {}) {
      const mine = ++latestJump;
      cancelPendingJump?.();
      endHold();
      clearLineTarget();
      const anchor = await fileAnchor(path);
      if (!entryOfId(anchor) || mine !== latestJump) return false;
      placeCallouts();
      const target = { anchor, file: true };
      const marked = targetElement(target);
      if (marked) {
        lineTarget = target;
        marked.classList.add(LINE_TARGET);
      }
      const place = () => filePlace(anchor);
      const landed = await scrollUntilLanded(place, newScrollToken());
      if (mine !== latestJump) return false;
      if (!marked) return landed;
      placeCallouts();
      const callout = targetElement(target);
      if (!callout) {
        clearLineTarget();
        return false;
      }
      callout.classList.add(LINE_TARGET);
      holdStop(place);
      if (pulse) pulseTarget([callout]);
      return landed;
    }

    function cancelJump() {
      latestJump += 1;
      newScrollToken();
      cancelPendingJump?.();
      endHold();
    }

    // The diff id a tree row links to, or null when it has no such link.
    function treeRowId(row) {
      const link = row.matches?.(DIFF_LINK) ? row : row.querySelector(DIFF_LINK);
      const href = link?.getAttribute("href") ?? "";
      const at = href.indexOf("#diff-");
      return at < 0 ? null : href.slice(at + 1);
    }

    // The diff ids of the files the page is narrowed to, keyed by the paths they came from; null for every file.
    let fileFilter = null;
    let filterToken = 0;
    // The line ranges the page is narrowed to: { key, byId, loading }, `byId` mapping a diff id to the ranges
    // [{ side, start, count }] of its file that stay, and `loading` the diffs whose load control was clicked.
    let hunkFilter = null;
    let hunkToken = 0;
    // The diff ids of the files that stay hidden whatever the filters above keep, keyed by the paths they came from; null
    // when none is.
    let excluded = null;
    let excludeToken = 0;

    // The diff ids the active filter keeps: the hunk filter's files when it is set, else the file filter's; null when no
    // file is hidden.
    function shownIds() {
      return hunkFilter ? new Set(hunkFilter.byId.keys()) : (fileFilter?.ids ?? null);
    }

    // Hides the diff blocks whose id is not in the filter or is excluded, and the tree's file rows whose diff is, then the
    // directory rows left with no visible file. A row with no diff link is left alone, as is a directory whose files are not in the
    // page (collapsed). The host re-renders its tree and loads diffs as the page scrolls, so this runs again on every
    // refresh.
    function applyFileFilter() {
      const ids = shownIds();
      const hidden = (id) => (Boolean(ids) && !ids.has(id)) || Boolean(excluded?.ids.has(id));
      for (const block of document.querySelectorAll(spec.blockSelector)) {
        block.classList.toggle(FILE_HIDDEN, hidden(block.id));
      }
      const host = spec.treeHost();
      if (!host) return;
      const files = [...host.querySelectorAll(spec.treeFileSelector)];
      for (const row of files) {
        const id = ids || excluded ? treeRowId(row) : null;
        row.classList.toggle(FILE_HIDDEN, id !== null && hidden(id));
      }
      if (!spec.treeDirSelector) return;
      for (const dir of host.querySelectorAll(spec.treeDirSelector)) {
        const inside = files.filter((row) => dir.contains(row));
        dir.classList.toggle(FILE_HIDDEN, Boolean(ids || excluded) && inside.length > 0 && inside.every((row) => row.classList.contains(FILE_HIDDEN)));
      }
    }

    function covers(ranges, { side, line }) {
      return ranges.some((range) => range.side === side && line >= range.start && line < range.start + range.count);
    }

    // Hides the rows of the kept diffs that show no line inside the hunk filter's ranges, and every hunk header or
    // expand row followed by a hidden row, which would otherwise stand alone. A row that shows no line and is no hunk
    // row (a callout, a comment thread) is left alone. A kept diff the host holds back behind its load control is loaded,
    // once. Without a filter every hidden row is shown again.
    function applyHunkFilter() {
      for (const row of document.querySelectorAll(`.${HUNK_HIDDEN}`)) row.classList.remove(HUNK_HIDDEN);
      if (!hunkFilter) return;
      for (const block of document.querySelectorAll(spec.blockSelector)) {
        const ranges = hunkFilter.byId.get(block.id);
        if (!ranges || excluded?.ids.has(block.id)) continue;
        if (!hunkFilter.loading.has(block.id) && spec.loadDiff?.(block.id)) hunkFilter.loading.add(block.id);
        const rows = [...block.querySelectorAll("tr")];
        let nextHidden = false;
        for (let index = rows.length - 1; index >= 0; index -= 1) {
          const row = rows[index];
          if (row.classList.contains(CALLOUT_ROW)) continue;
          const lines = spec.rowLines?.(row) ?? [];
          if (lines.length > 0) {
            nextHidden = !lines.some((line) => covers(ranges, line));
            row.classList.toggle(HUNK_HIDDEN, nextHidden);
          } else if (nextHidden && spec.hunkRow?.(row)) {
            row.classList.add(HUNK_HIDDEN);
          }
        }
      }
    }

    function applyFilters() {
      applyFileFilter();
      applyHunkFilter();
    }

    // Narrows the host's tree and the diff to the files at `paths`; null shows every file. Calling again with the same
    // paths only re-applies the filter, which hides diffs the host loaded since.
    async function filterFiles(paths) {
      const mine = ++filterToken;
      const key = paths ? paths.join("\n") : null;
      if (key !== null && fileFilter?.key !== key) {
        const ids = new Set(await Promise.all(paths.map((path) => spec.diffId(path))));
        if (mine !== filterToken) return;
        fileFilter = { key, ids };
      } else if (key === null) {
        fileFilter = null;
      }
      applyFilters();
    }

    // Narrows the page to the lines in `ranges`, [{ path, side, start, count }]: only the files they name are shown, and
    // in each only the rows showing a line inside one of its ranges. It takes the place of the file filter while set; null
    // shows every file and row again. Calling again with the same ranges only re-applies it, which covers the rows the
    // host rendered since.
    async function filterHunks(ranges) {
      const mine = ++hunkToken;
      const key = ranges ? JSON.stringify(ranges) : null;
      if (key !== null && hunkFilter?.key !== key) {
        const ids = await Promise.all(ranges.map((range) => spec.diffId(range.path)));
        if (mine !== hunkToken) return;
        const byId = new Map();
        ranges.forEach(({ side, start, count }, index) => byId.set(ids[index], [...(byId.get(ids[index]) ?? []), { side, start, count }]));
        hunkFilter = { key, byId, loading: new Set() };
      } else if (key === null) {
        hunkFilter = null;
      }
      applyFilters();
    }

    // Hides the files at `paths` from the diff and the host's tree, whatever the file filter and the hunk filter keep; null
    // hides none. Calling again with the same paths only re-applies the filters.
    async function excludeFiles(paths) {
      const mine = ++excludeToken;
      const key = paths ? paths.join("\n") : null;
      if (key !== null && excluded?.key !== key) {
        const ids = new Set(await Promise.all(paths.map((path) => spec.diffId(path))));
        if (mine !== excludeToken) return;
        excluded = { key, ids };
      } else if (key === null) {
        excluded = null;
      }
      applyFilters();
    }

    // How many files the page lists as changed: the tree's rows, or the diffs loaded when the tree is not showing.
    function changedFileCount() {
      const rows = spec.treeHost()?.querySelectorAll(spec.treeFileSelector).length ?? 0;
      return Math.max(rows, fileBlocks().size);
    }

    function onChange(callback) {
      const observer = new MutationObserver(callback);
      observer.observe(document.body, { childList: true, subtree: true });
      return () => observer.disconnect();
    }

    // A PR tab can change page under the content script without a reload.
    function onNavigate(callback) {
      const events = [
        [globalThis, "popstate"],
        [document, "turbo:load"],
        [document, "turbo:render"],
        [globalThis.navigation, "currententrychange"],
      ].filter(([target]) => target);
      for (const [target, name] of events) target.addEventListener(name, callback);
      return () => {
        for (const [target, name] of events) target.removeEventListener(name, callback);
      };
    }

    return {
      name: spec.name,
      treeLabel: spec.treeLabel,
      hosts: spec.hosts,
      prFromUrl,
      filesUrl,
      pullFromUrl,
      conversationUrl,
      isConversationPage,
      hostId: spec.hostId,
      runKey: spec.runKey,
      headSha,
      currentHeadSha,
      fileBlocks,
      entryOf,
      entryFor,
      lineAnchor,
      fileAnchor,
      firstInPage,
      loadDiff: spec.loadDiff,
      scrollToElement,
      fileHeaderOf,
      stickyOffset,
      startDistance,
      landingDelta,
      calloutDelta,
      holdPlace,
      correctLanding,
      jumpToLine,
      jumpToFile,
      clearLineTarget,
      restoreLineTarget,
      showCallouts,
      filterFiles,
      filterHunks,
      excludeFiles,
      changedFileCount,
      ownsLine,
      cancelJump,
      diagramHost: spec.diagramHost,
      treeHost: spec.treeHost,
      descriptionHost: spec.descriptionHost,
      onChange,
      onNavigate,
    };
  }

  ns.pageCommon = { createPage };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.pageCommon;
