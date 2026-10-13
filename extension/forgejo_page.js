// The Forgejo adapter: the only module that knows Forgejo's DOM (observed 2026-10-05 on a local Forgejo's
// pull request files page, /{owner}/{repo}/pulls/{n}/files). Unlike GitHub's, its class names are stable
// semantic ones. What is not about Forgejo's DOM is in page_common.js.
(() => {
  const ns = (globalThis.prFocus ??= {});
  const { createPage, resizeHandle } = ns.pageCommon ?? require("./page_common.js");

  // The flex row holding the file tree (a sticky 380px column) and the diffs' column.
  const DIFF_CONTAINER = "#diff-container";
  // The element of one file's diff. It carries id="diff-<sha1 hex of the path>" and data-new-filename /
  // data-old-filename; the whole box is both block and entry.
  const DIFF_BLOCK = `${DIFF_CONTAINER} .diff-file-box[id^="diff-"]`;
  // The diffs' column, a sibling of the tree after it.
  const DIFF_CONTENT = "#diff-content-container";
  // The sticky tree column. Its Vue-rendered tree sits in `.diff-file-tree-items`, which is the pane host.
  const DIFF_PANE = "#diff-file-tree";
  const PANE_HOST = `${DIFF_PANE} > .diff-file-tree-items`;
  // A file's row in the tree is a link to the file's diff. Directory rows are not matched: they stay.
  const TREE_FILE = ".item-file";
  // A file's header: a sticky bar (top 44px) inside the box, under the sticky summary bar `.diff-detail-box`
  // (top 0, 44px high, as wide as the page), which is what the scroll offset is measured against.
  const FILE_HEADER = ".diff-file-header";
  // Line numbers sit in td.lines-num cells; each holds an empty <span rel="diff-<sha1>R<n>"> (L<n> for the old
  // file) that is the line's anchor. The row is the span's tr.
  const LOAD_BUTTON = "a.diff-load-button";
  const LINE_REL = ".lines-num [rel]";
  const LINE_ANCHOR = /^diff-[0-9a-f]+([LR])(\d+)$/;
  // A hunk header and an expand-context row are both rows of class tag-code (data-line-type="tag").
  const HUNK_ROW = "tag-code";
  // The header's "view file" links point at /src/commit/<head sha>/<path>.
  const HEAD_LINK = `${DIFF_BLOCK} a[href*="/src/commit/"]`;
  const HEAD_SHA = /\/src\/commit\/([0-9a-f]{40})\//;
  const STICKY_SKIP = ".diff-file-box, #pr-focus-tree, #pr-focus-diagram, .prd-overlay, svg, script, style";

  const CHANGES_PAGE = /^\/([^/]+)\/([^/]+)\/pulls\/(\d+)\/files(?:\/|$)/;
  const PULL_PAGE = /^\/([^/]+)\/([^/]+)\/pulls\/(\d+)(?:\/|$)/;
  const CONVERSATION_PAGE = /^\/([^/]+)\/([^/]+)\/pulls\/(\d+)\/?$/;

  // The conversation page's .ui.timeline holds the opening comment (the description) as its first
  // .timeline-item.comment, marked .first.
  const DESCRIPTION = ".ui.timeline > .timeline-item.comment.first";

  // The CSS the extension ships uses GitHub Primer's custom properties, with light fallbacks. Forgejo defines
  // its own colours (light and dark), so the Primer names are pointed at them for as long as this adapter runs.
  const THEME_ID = "prf-forgejo-theme";
  const THEME_CSS = `:root {
    --fgColor-default: var(--color-text);
    --fgColor-muted: var(--color-text-light-2);
    --fgColor-accent: var(--color-primary);
    --fgColor-attention: var(--color-warning-text);
    --fgColor-danger: var(--color-red);
    --fgColor-success: var(--color-green);
    --bgColor-default: var(--color-body);
    --bgColor-muted: var(--color-box-header);
    --bgColor-neutral-muted: var(--color-hover);
    --bgColor-accent-muted: color-mix(in srgb, var(--color-primary) 18%, transparent);
    --bgColor-attention-muted: var(--color-warning-bg);
    --borderColor-default: var(--color-secondary);
    --borderColor-muted: var(--color-secondary);
    --borderColor-accent-emphasis: var(--color-primary);
    --borderColor-attention-emphasis: var(--color-warning-border);
    --controlTrack-bgColor-rest: var(--color-box-header);
    --controlTrack-bgColor-hover: var(--color-hover);
    --controlKnob-bgColor-rest: var(--color-body);
    --controlKnob-borderColor-rest: var(--color-secondary);
  }`;

  function installTheme() {
    if (typeof document === "undefined" || document.getElementById(THEME_ID)) return;
    const style = document.createElement("style");
    style.id = THEME_ID;
    style.textContent = THEME_CSS;
    document.head.append(style);
  }

  // Forgejo names the id of a file's diff from the sha1 of its path.
  const idCache = new Map();

  async function diffId(path) {
    if (!idCache.has(path)) {
      const digest = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(path));
      const hex = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
      idCache.set(path, `diff-${hex}`);
    }
    return idCache.get(path);
  }

  function pathOfBlock(block) {
    return block.dataset.newFilename || block.dataset.oldFilename || null;
  }

  function readHeadSha(doc = document) {
    return HEAD_SHA.exec(doc.querySelector(HEAD_LINK)?.getAttribute("href") ?? "")?.[1] ?? null;
  }

  function findRow(anchor, root = document) {
    return root.querySelector(`${LINE_REL}[rel="${anchor}"]`)?.closest("tr") ?? null;
  }

  // The lines a row shows: each line-number cell holds a span whose `rel` is the diff's id, the side and the number; an
  // added row's old-number span and a removed row's new-number span have an empty `rel`.
  function rowLines(tr) {
    const lines = [];
    for (const span of tr.querySelectorAll(LINE_REL)) {
      const match = LINE_ANCHOR.exec(span.getAttribute("rel") ?? "");
      if (match) lines.push({ side: match[1], line: Number(match[2]) });
    }
    return lines;
  }

  function hunkRow(tr) {
    return tr.classList.contains(HUNK_ROW);
  }

  // A file Forgejo holds back (a very large diff) shows a "Load diff" link in its box. Clicking it fetches the file's
  // rows, which replace the link's container inside the box; the box itself stays.
  function loadDiff(id) {
    const button = document.getElementById(id)?.querySelector(LOAD_BUTTON);
    if (!button) return false;
    button.click();
    return true;
  }

  // The conversation page names no head commit (its timeline links only the commits of force pushes), so it is asked of
  // the instance's read-only API, from the page's own origin and session; no run server is involved.
  async function fetchHeadSha(pr) {
    try {
      const response = await fetch(`/api/v1/repos/${pr.owner}/${pr.repo}/pulls/${pr.pr}`, { headers: { Accept: "application/json" } });
      const sha = response.ok ? (await response.json())?.head?.sha : null;
      return typeof sha === "string" && /^[0-9a-f]{40}$/i.test(sha) ? sha : null;
    } catch {
      return null;
    }
  }

  // The diagram panel is the flex row's leftmost item, before the tree column, sticking where the tree sticks.
  function diagramHost() {
    const content = document.querySelector(DIFF_CONTENT);
    if (!content) return null;
    const pane = document.querySelector(DIFF_PANE);
    const anchor = pane ?? content;
    return { content, pane, top: pane ? getComputedStyle(pane).top : "0px", order: getComputedStyle(anchor).order };
  }

  // The element holding Forgejo's own tree.
  function paneHost() {
    installTheme();
    return document.querySelector(PANE_HOST);
  }

  // The file pane has no divider of its own. A handle on its right edge sets its width, which replaces Forgejo's
  // `flex: 0 0 20%; max-width: 380px`; a double-click on the handle gives that back.
  const PANE_HANDLE = "prf-pane-handle";
  const PANE_DRAGGING = "prf-pane-dragging";
  const MIN_PANE_WIDTH = 240;
  const MAX_PANE_SHARE = 0.5;

  // A usable pane width for this viewport: at least MIN_PANE_WIDTH, at most MAX_PANE_SHARE of the viewport.
  function clampPaneWidth(width, viewportWidth) {
    return Math.round(Math.max(MIN_PANE_WIDTH, Math.min(width, viewportWidth * MAX_PANE_SHARE)));
  }

  // Makes the pane resizable and keeps it so: the handle is added once, as the first child, to each pane element the
  // page holds, and the stored width is applied to it. The page re-renders the pane or replaces it, so the pane and
  // its parent are watched, and the page itself while there is no pane. `options.load()` gives the stored width or null
  // and `options.save(width)` stores one (null forgets it); they default to the stored width in source.js. Returns how
  // to stop, which removes the handle and gives the pane back its own width.
  function paneResize({ load = () => ns.source?.loadPaneWidth() ?? null, save = (width) => ns.source?.savePaneWidth(width) } = {}) {
    let width = null;
    let touched = false;
    let stopped = false;
    let watched;
    let sized = null;
    let observer = null;

    const paneOf = () => document.querySelector(DIFF_PANE);
    const handleOf = (pane) => [...pane.children].find((child) => child.classList.contains(PANE_HANDLE)) ?? null;

    function apply(pane) {
      if (width === null) {
        pane.style.removeProperty("flex");
        pane.style.removeProperty("max-width");
      } else {
        pane.style.setProperty("flex", `0 0 ${width}px`);
        pane.style.setProperty("max-width", "none");
      }
      sized = pane;
    }

    function setWidth(pane, next) {
      touched = true;
      width = next === null ? null : clampPaneWidth(next, innerWidth);
      apply(pane);
    }

    function buildHandle(pane) {
      return resizeHandle({
        className: PANE_HANDLE,
        title: "Drag to resize, double-click to reset",
        widthOf: () => pane.getBoundingClientRect().width,
        setWidth: (next) => setWidth(pane, next),
        onStart: () => pane.classList.add(PANE_DRAGGING),
        onEnd: (last) => {
          pane.classList.remove(PANE_DRAGGING);
          if (last !== null) save(width);
        },
        onReset: () => {
          setWidth(pane, null);
          save(null);
        },
      });
    }

    // The handle is as tall as the pane's visible area, whatever the pane's scroll position.
    function fitHandle(pane) {
      handleOf(pane)?.style.setProperty("--prf-pane-handle-height", `${pane.clientHeight}px`);
    }

    function ensure() {
      if (stopped) return;
      const pane = paneOf();
      if (pane !== watched) {
        watched = pane;
        watch(pane);
      }
      if (!pane) return;
      if (!handleOf(pane)) pane.prepend(buildHandle(pane));
      if (sized !== pane) apply(pane);
      fitHandle(pane);
    }

    function watch(pane) {
      observer?.disconnect();
      observer = null;
      if (!globalThis.MutationObserver) return;
      observer = new MutationObserver(ensure);
      if (pane) {
        observer.observe(pane, { childList: true });
        if (pane.parentElement) observer.observe(pane.parentElement, { childList: true });
      } else {
        observer.observe(document.body, { childList: true, subtree: true });
      }
    }

    const refit = () => {
      const pane = paneOf();
      if (pane) fitHandle(pane);
    };

    ensure();
    globalThis.addEventListener?.("resize", refit);
    Promise.resolve(load()).then((stored) => {
      if (stopped || touched || !Number.isFinite(stored) || stored <= 0) return;
      width = clampPaneWidth(stored, innerWidth);
      const pane = paneOf();
      if (pane) apply(pane);
    });

    return () => {
      stopped = true;
      observer?.disconnect();
      globalThis.removeEventListener?.("resize", refit);
      const pane = paneOf();
      if (!pane) return;
      handleOf(pane)?.remove();
      pane.classList.remove(PANE_DRAGGING);
      width = null;
      apply(pane);
    };
  }

  const page = createPage({
    name: "Forgejo",
    hosts: ["localhost:3300"],
    origin: "http://localhost:3300",
    changesPage: CHANGES_PAGE,
    pullPage: PULL_PAGE,
    conversationPage: CONVERSATION_PAGE,
    conversationPath: (pr) => `/${pr.owner}/${pr.repo}/pulls/${pr.pr}`,
    filesPath: (pr) => `/${pr.owner}/${pr.repo}/pulls/${pr.pr}/files`,
    hostId: "forgejo",
    // Forgejo's PR numbers are its own, so its runs sit beside GitHub's under a prefix.
    runKey: (pr) => `fj-${pr.pr}`,
    readHeadSha,
    fetchHeadSha,
    blockSelector: DIFF_BLOCK,
    pathOfBlock,
    entryOf: (block) => block,
    diffId,
    findRow,
    rowLines,
    hunkRow,
    loadDiff,
    fileHeaderSelector: FILE_HEADER,
    stickySkip: STICKY_SKIP,
    containerSelector: DIFF_CONTAINER,
    contentSelector: DIFF_CONTENT,
    diagramHost: () => {
      installTheme();
      return diagramHost();
    },
    paneHost,
    paneResize,
    treeFileSelector: TREE_FILE,
    descriptionHost: () => {
      installTheme();
      return document.querySelector(DESCRIPTION);
    },
  });

  ns.forgejoPage = page;
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.forgejoPage;
