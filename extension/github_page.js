// The only module that knows GitHub's DOM. Class names carry hashed suffixes, so every selector
// matches a stable prefix with [class*="..."].
(() => {
  const ns = (globalThis.prFocus ??= {});

  const DIFF_BLOCK = 'div[id^="diff-"][class*="Diff-module__diffTargetable"]';
  const DIFF_ENTRY = 'div[class*="PullRequestDiffsList-module__diffEntry"]';
  const BLOCK_PATH = "[data-file-path]";
  const BLOCK_ANCHOR = "table[data-diff-anchor]";
  const TREE_HOST = '#pr-file-tree > [class*="PullRequestFileTree-module__FileTreeScrollable"]';
  const LINE_CELL = "[data-line-anchor]";
  const LINE_TARGET = "prf-line-target";
  const LINE_PULSE = "prf-line-pulse";
  const CALLOUT_ROW = "prf-callout-row";
  const FAR_VIEWPORTS = 1.5;
  const SCROLL_SETTLE_MS = 1200;
  const DIFF_CONTAINER = "#diff-comparison-viewer-container";
  const JUMP_TIMEOUT_MS = 10000;
  const DIFF_CONTENT = `${DIFF_CONTAINER} [class*="prc-PageLayout-ContentWrapper"]`;
  const DIFF_PANE = `${DIFF_CONTAINER} [class*="prc-PageLayout-PaneWrapper"]`;
  const EMBEDDED_DATA = 'script[type="application/json"][data-target="react-app.embeddedData"]';
  const HEAD_SHA = /"head(?:Oid|Sha)"\s*:\s*"([0-9a-f]{40})"/;
  const ARIA_PREFIX = "Diff for: ";
  const FILE_HEADER = '[class*="diffHeaderWrapper"], [class*="DiffFileHeader"], [class*="diff-file-header"]';
  const STICKY_SKIP = `${DIFF_ENTRY}, #pr-focus-tree, #pr-focus-diagram, .prd-overlay, svg, script, style`;
  const STICKY_BAND_VIEWPORTS = 0.3;
  const LAND_TOLERANCE = 1;
  const CENTER_TOLERANCE = 4;
  const LAND_CORRECTIONS = 3;
  const IDLE_POLL_MS = 50;
  const IDLE_POLLS = 3;

  const CHANGES_PAGE = /^\/([^/]+)\/([^/]+)\/pull\/(\d+)\/(?:changes|files)(?:\/|$)/;
  const PULL_PAGE = /^\/([^/]+)\/([^/]+)\/pull\/(\d+)(?:\/|$)/;

  function pathnameOf(location) {
    return typeof location === "string" ? new URL(location, "https://github.com").pathname : location.pathname;
  }

  function parsePull(pattern, location) {
    const match = pattern.exec(pathnameOf(location));
    return match ? { owner: match[1], repo: match[2], pr: Number(match[3]) } : null;
  }

  function prFromUrl(location) {
    return parsePull(CHANGES_PAGE, location);
  }

  function pullFromUrl(location) {
    return parsePull(PULL_PAGE, location);
  }

  // The embedded JSON belongs to the document that was loaded, so it describes only the PR that
  // page was first opened on.
  const initialPull = globalThis.location ? pullFromUrl(globalThis.location) : null;
  let cachedHeadSha;

  function headSha() {
    const current = prFromUrl(location);
    if (!initialPull || !current || initialPull.owner !== current.owner || initialPull.repo !== current.repo || initialPull.pr !== current.pr) {
      return null;
    }
    if (cachedHeadSha === undefined) {
      const text = document.querySelector(EMBEDDED_DATA)?.textContent ?? "";
      cachedHeadSha = HEAD_SHA.exec(text)?.[1] ?? null;
    }
    return cachedHeadSha;
  }

  function pathOfBlock(block) {
    const attribute = block.querySelector(BLOCK_PATH)?.getAttribute("data-file-path");
    if (attribute) return attribute;
    const label = block.querySelector(BLOCK_ANCHOR)?.getAttribute("aria-label") ?? "";
    return label.startsWith(ARIA_PREFIX) ? label.slice(ARIA_PREFIX.length) : null;
  }

  function fileBlocks() {
    const blocks = new Map();
    for (const block of document.querySelectorAll(DIFF_BLOCK)) {
      const path = pathOfBlock(block);
      if (path) blocks.set(path, block);
    }
    return blocks;
  }

  // The element to hide so the spacing between diffs collapses with it.
  function entryOf(block) {
    return block ? (block.closest(DIFF_ENTRY) ?? block) : null;
  }

  function diffEntries() {
    return [...new Set([...document.querySelectorAll(DIFF_BLOCK)].map(entryOf))];
  }

  const idCache = new Map();

  async function diffId(path) {
    if (!idCache.has(path)) {
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(path));
      const hex = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
      idCache.set(path, `diff-${hex}`);
    }
    return idCache.get(path);
  }

  // GitHub derives each diff block's id from the sha256 of its file path.
  async function entryFor(path) {
    const block = document.getElementById(await diffId(path));
    return entryOf(block);
  }

  // GitHub's anchor for a line of a file's diff: the diff block's id plus the side ("L" old file,
  // "R" new file) and line number.
  async function lineAnchor(path, side, line) {
    return `${await diffId(path)}${side}${line}`;
  }

  // The row that is the line target now: its anchor, so a re-render of the row by GitHub can be undone, and the
  // factory of the callout pinned above it (null once dismissed, or when the jump had none).
  let lineTarget = null;

  function findRow(anchor) {
    return document.querySelector(`${LINE_CELL}[data-line-anchor="${anchor}"]`)?.closest("tr") ?? null;
  }

  function removeCallout() {
    for (const element of document.querySelectorAll(`.${CALLOUT_ROW}`)) element.remove();
  }

  // The callout is a full-width table row directly above the target row, so GitHub's columns stay as they are.
  // `makeCallout(dismiss)` builds its content; dismissing removes it and it stays gone.
  function syncCallout(row) {
    if (!lineTarget.makeCallout) return removeCallout();
    if (row.previousElementSibling?.classList.contains(CALLOUT_ROW)) return;
    removeCallout();
    const cell = document.createElement("td");
    cell.colSpan = Math.max(1, row.children.length);
    cell.append(
      lineTarget.makeCallout(() => {
        lineTarget.makeCallout = null;
        removeCallout();
      }),
    );
    const callout = document.createElement("tr");
    callout.className = CALLOUT_ROW;
    callout.append(cell);
    row.before(callout);
  }

  function clearLineTarget() {
    lineTarget = null;
    removeCallout();
    for (const row of document.querySelectorAll(`.${LINE_TARGET}`)) row.classList.remove(LINE_TARGET, LINE_PULSE);
  }

  // GitHub re-renders diff rows, which drops our classes and the callout; the target row gets its class and its
  // callout back, without the pulse.
  function restoreLineTarget() {
    const row = lineTarget ? findRow(lineTarget.anchor) : null;
    if (!row) return;
    if (!row.classList.contains(LINE_TARGET)) row.classList.add(LINE_TARGET);
    syncCallout(row);
  }

  function ownsLine(node) {
    const element = node?.nodeType === 1 ? node : node?.parentElement;
    return Boolean(element?.closest(`.${CALLOUT_ROW}`));
  }

  function reducedMotion() {
    return Boolean(globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
  }

  // The header of a file's diff entry: GitHub's header element when it can be found, else the entry's first child.
  function fileHeaderOf(entry) {
    return entry?.querySelector(FILE_HEADER) ?? entry?.firstElementChild ?? null;
  }

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

  // The page's sticky and fixed elements outside the diffs, the list and the diagram, with their stuck tops.
  function stickyEntries() {
    const entries = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, {
      acceptNode(node) {
        if (node.matches(STICKY_SKIP)) return NodeFilter.FILTER_REJECT;
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
    const column = (document.querySelector(DIFF_CONTENT) ?? entry).getBoundingClientRect();
    return stickyOffset(stickyEntries(), column, innerHeight * STICKY_BAND_VIEWPORTS);
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

  // The distance still to scroll for a row with this rect to sit in the middle of a window `viewportHeight`
  // tall: 0 when it is within `tolerance` of the middle.
  function centeringDelta({ top, height }, viewportHeight, tolerance = CENTER_TOLERANCE) {
    const distance = top + height / 2 - viewportHeight / 2;
    return Math.abs(distance) <= tolerance ? 0 : distance;
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

  // Every scroll started through scrollToElement takes the next token, and cancelJump invalidates them all, so
  // a landing's corrections never undo a scroll that came after it.
  let scrollToken = 0;

  function newScrollToken() {
    scrollToken += 1;
    return scrollToken;
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

  // Scrolls until `delta()` reports 0. A target more than FAR_VIEWPORTS windows away is first approached
  // instantly to one window short of it, so the smooth part is short and doesn't pass through every lazily
  // rendered diff on the way. GitHub lays diffs out lazily, so heights above the target can change while
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
  // nothing of the previous file above it. The entry is measured, not its header: GitHub's header is sticky, so
  // while the file is being read its rect stays at the stuck offset whatever the scroll position.
  function scrollToElement(entry) {
    return scrollUntilLanded(() => landingDelta(entry.getBoundingClientRect().top, currentStickyOffset(entry)), newScrollToken());
  }

  // Scrolls the row for `anchor` to the middle of the window. The row is looked up again on every measurement,
  // since GitHub can replace it while the diffs around it load.
  function scrollToRow(anchor, token) {
    return scrollUntilLanded(() => {
      const row = findRow(anchor);
      return row ? centeringDelta(row.getBoundingClientRect(), innerHeight) : 0;
    }, token);
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
      observer.observe(document.querySelector(DIFF_CONTAINER) ?? document.body, { childList: true, subtree: true });
    });
  }

  // GitHub renders a diff's rows only once the diff is near the window, so the file's diff is scrolled
  // to first; then the line's row is waited for, scrolled to the centre, outlined and pulsed. If it never
  // appears the view stays at the file's header. Returns whether the row ended centred.
  async function jumpToLine(path, side, line, makeCallout = null) {
    const mine = ++latestJump;
    cancelPendingJump?.();
    clearLineTarget();
    const [anchor, entry] = await Promise.all([lineAnchor(path, side, line), entryFor(path)]);
    if (!entry || mine !== latestJump) return false;
    scrollToElement(entry);
    const found = await waitForRow(anchor, JUMP_TIMEOUT_MS);
    if (!found || mine !== latestJump) return false;
    // The callout goes in before the final scroll, so the row is centred with it above.
    lineTarget = { anchor, makeCallout };
    syncCallout(found);
    const landed = await scrollToRow(anchor, newScrollToken());
    if (mine !== latestJump) return false;
    const row = findRow(anchor);
    if (!row) {
      clearLineTarget();
      return false;
    }
    row.classList.add(LINE_TARGET, LINE_PULSE);
    syncCallout(row);
    return landed;
  }

  // GitHub's 1px rule down the pane's right edge, inside the pane wrapper. The panel is the pane's next sibling,
  // so the rule would sit between the chunk list and the diagram; it is made transparent while the panel is
  // there (until hovered, so the drag affordance stays), leaving the panel's own divider before the diffs as
  // the only one.
  const PANE_DIVIDER = '[class*="prc-PageLayout-PaneVerticalDivider"]';
  const PANE_DIVIDER_CSS = `${DIFF_PANE}:has(+ #pr-focus-diagram) ${PANE_DIVIDER}:not(:hover):not(:active) { background: transparent; }`;

  // GitHub's page layout is a flex row of the file tree pane and the diffs' column. The diagram panel goes
  // between them: it is inserted right after the pane, with the pane's own computed `order`, so DOM order puts it
  // ahead of the diffs whatever values GitHub's CSS gives them, and no GitHub element is restyled. It sticks at the
  // pane's top offset. Without a pane it goes right before the diffs, with their order.
  function diagramHost() {
    const content = document.querySelector(DIFF_CONTENT);
    if (!content) return null;
    const pane = document.querySelector(DIFF_PANE);
    const anchor = pane ?? content;
    return { content, pane, top: pane ? getComputedStyle(pane).top : "0px", order: getComputedStyle(anchor).order, paneDividerCss: PANE_DIVIDER_CSS };
  }

  function cancelJump() {
    latestJump += 1;
    newScrollToken();
    cancelPendingJump?.();
  }

  // GitHub's own tree, including its "File tree" heading. The filter box above it is a sibling and
  // stays visible, so a list mounted before this element sits between the two.
  function treeHost() {
    return document.querySelector(TREE_HOST);
  }

  function onChange(callback) {
    const observer = new MutationObserver(callback);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }

  // GitHub navigates without reloading, so a PR tab can change page under the content script.
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

  ns.githubPage = { prFromUrl, pullFromUrl, headSha, fileBlocks, entryOf, diffEntries, entryFor, lineAnchor, scrollToElement, fileHeaderOf, stickyOffset, startDistance, landingDelta, centeringDelta, correctLanding, jumpToLine, clearLineTarget, restoreLineTarget, ownsLine, cancelJump, diagramHost, treeHost, onChange, onNavigate };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.githubPage;
