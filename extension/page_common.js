// The page behaviour shared by every host: scrolling a diff under the sticky chrome, jumping to a line, the
// pinned callout, and watching for changes. createPage(spec) returns the adapter the rest of the extension
// calls through prFocus.page (see page.js). The spec holds everything that differs per host, which is all
// the DOM knowledge and nothing else; a host's spec lives in its own file (github_page.js, forgejo_page.js).
//
// spec: {
//   name, treeLabel, hosts          display name, the label of the host's own tree, the location.host values it serves
//   origin, changesPage, pullPage   a base for relative URLs, and the patterns of the files page and of any page of a
//                                   PR, each capturing owner, repo and number
//   runKey(pr)                      the runs/<key> folder of a parsed PR
//   readHeadSha()                   the head commit sha the page shows, or null
//   blockSelector, pathOfBlock(b)   the element holding one file's diff, and the path it shows
//   entryOf(block)                  the element to hide so the spacing between diffs collapses with it
//   diffId(path)                    the id of a file's diff block (async)
//   findRow(anchor)                 the table row of a line anchor, or null
//   fileHeaderSelector              a file's header; stickySkip: elements the sticky-chrome scan ignores
//   containerSelector               the diffs' container, watched for rows that appear
//   contentSelector                 the diffs' column
//   diagramHost()                   where the diagram panel docks, or null
//   treeHost()                      the host's own file tree element, or null
// }
(() => {
  const ns = (globalThis.prFocus ??= {});

  const LINE_TARGET = "prf-line-target";
  const LINE_PULSE = "prf-line-pulse";
  const CALLOUT_ROW = "prf-callout-row";
  const FAR_VIEWPORTS = 1.5;
  const SCROLL_SETTLE_MS = 1200;
  const JUMP_TIMEOUT_MS = 10000;
  const STICKY_BAND_VIEWPORTS = 0.3;
  const LAND_TOLERANCE = 1;
  const CENTER_TOLERANCE = 4;
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

  // The distance still to scroll for a row with this rect to sit in the middle of a window `viewportHeight`
  // tall: 0 when it is within `tolerance` of the middle.
  function centeringDelta({ top, height }, viewportHeight, tolerance = CENTER_TOLERANCE) {
    const distance = top + height / 2 - viewportHeight / 2;
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

    function prFromUrl(location) {
      return parsePull(spec.changesPage, location);
    }

    function pullFromUrl(location) {
      return parsePull(spec.pullPage, location);
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

    function diffEntries() {
      return [...new Set([...document.querySelectorAll(spec.blockSelector)].map(entryOf))];
    }

    async function entryFor(path) {
      const block = document.getElementById(await spec.diffId(path));
      return entryOf(block);
    }

    // The host's anchor for a line of a file's diff: the diff block's id plus the side ("L" old file,
    // "R" new file) and line number.
    async function lineAnchor(path, side, line) {
      return `${await spec.diffId(path)}${side}${line}`;
    }

    // The row that is the line target now: its anchor, so a re-render of the row by the host can be undone, and the
    // factory of the callout pinned above it (null once dismissed, or when the jump had none).
    let lineTarget = null;

    function findRow(anchor) {
      return spec.findRow(anchor);
    }

    function removeCallout() {
      for (const element of document.querySelectorAll(`.${CALLOUT_ROW}`)) element.remove();
    }

    // The callout is a full-width table row directly above the target row, so the host's columns stay as they are.
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

    // The host re-renders diff rows, which drops our classes and the callout; the target row gets its class and its
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

    // The header of a file's diff entry: the host's header element when it can be found, else the entry's first child.
    function fileHeaderOf(entry) {
      return entry?.querySelector(spec.fileHeaderSelector) ?? entry?.firstElementChild ?? null;
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

    // Scrolls the row for `anchor` to the middle of the window. The row is looked up again on every measurement,
    // since the host can replace it while the diffs around it load.
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
        observer.observe(document.querySelector(spec.containerSelector) ?? document.body, { childList: true, subtree: true });
      });
    }

    // A diff's rows may be rendered only once the diff is near the window, so the file's diff is scrolled
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

    function cancelJump() {
      latestJump += 1;
      newScrollToken();
      cancelPendingJump?.();
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
      pullFromUrl,
      runKey: spec.runKey,
      headSha,
      fileBlocks,
      entryOf,
      diffEntries,
      entryFor,
      lineAnchor,
      scrollToElement,
      fileHeaderOf,
      stickyOffset,
      startDistance,
      landingDelta,
      centeringDelta,
      correctLanding,
      jumpToLine,
      clearLineTarget,
      restoreLineTarget,
      ownsLine,
      cancelJump,
      diagramHost: spec.diagramHost,
      treeHost: spec.treeHost,
      onChange,
      onNavigate,
    };
  }

  ns.pageCommon = { createPage };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.pageCommon;
