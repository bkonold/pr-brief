// The GitHub adapter: the only module that knows GitHub's DOM. Class names carry hashed suffixes, so every
// selector matches a stable prefix with [class*="..."]. What is not about GitHub's DOM is in page_common.js.
(() => {
  const ns = (globalThis.prFocus ??= {});
  const { createPage } = ns.pageCommon ?? require("./page_common.js");

  const DIFF_BLOCK = 'div[id^="diff-"][class*="Diff-module__diffTargetable"]';
  const DIFF_ENTRY = 'div[class*="PullRequestDiffsList-module__diffEntry"]';
  const BLOCK_PATH = "[data-file-path]";
  const BLOCK_ANCHOR = "table[data-diff-anchor]";
  const TREE_HOST = '#pr-file-tree > [class*="PullRequestFileTree-module__FileTreeScrollable"]';
  // Primer's tree: a directory's row carries aria-expanded and a file's does not.
  const TREE_FILE = 'li[role="treeitem"]:not([aria-expanded])';
  const TREE_DIR = 'li[role="treeitem"][aria-expanded]';
  const LINE_CELL = "[data-line-anchor]";
  const DIFF_CONTAINER = "#diff-comparison-viewer-container";
  const DIFF_CONTENT = `${DIFF_CONTAINER} [class*="prc-PageLayout-ContentWrapper"]`;
  const DIFF_PANE = `${DIFF_CONTAINER} [class*="prc-PageLayout-PaneWrapper"]`;
  const EMBEDDED_DATA = 'script[type="application/json"][data-target="react-app.embeddedData"]';
  const HEAD_SHA = /"head(?:Oid|Sha)"\s*:\s*"([0-9a-f]{40})"/;
  const ARIA_PREFIX = "Diff for: ";
  const FILE_HEADER = '[class*="diffHeaderWrapper"], [class*="DiffFileHeader"], [class*="diff-file-header"]';
  const STICKY_SKIP = `${DIFF_ENTRY}, #pr-focus-tree, #pr-focus-diagram, .prd-overlay, svg, script, style`;

  const CHANGES_PAGE = /^\/([^/]+)\/([^/]+)\/pull\/(\d+)\/(?:changes|files)(?:\/|$)/;
  const PULL_PAGE = /^\/([^/]+)\/([^/]+)\/pull\/(\d+)(?:\/|$)/;
  const CONVERSATION_PAGE = /^\/([^/]+)\/([^/]+)\/pull\/(\d+)\/?$/;

  // The conversation page's timeline is a sequence of .TimelineItem.js-comment-container elements inside
  // .js-discussion, and the first is the PR's opening comment (the description).
  const DESCRIPTION = ".js-discussion .js-comment-container";

  const idCache = new Map();

  // GitHub derives each diff block's id from the sha256 of its file path.
  async function diffId(path) {
    if (!idCache.has(path)) {
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(path));
      const hex = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
      idCache.set(path, `diff-${hex}`);
    }
    return idCache.get(path);
  }

  function pathOfBlock(block) {
    const attribute = block.querySelector(BLOCK_PATH)?.getAttribute("data-file-path");
    if (attribute) return attribute;
    const label = block.querySelector(BLOCK_ANCHOR)?.getAttribute("aria-label") ?? "";
    return label.startsWith(ARIA_PREFIX) ? label.slice(ARIA_PREFIX.length) : null;
  }

  // The embedded JSON of a PR's conversation page and of its files page names the PR's head commit.
  function readHeadSha(doc = document) {
    const text = doc.querySelector(EMBEDDED_DATA)?.textContent ?? "";
    return HEAD_SHA.exec(text)?.[1] ?? null;
  }

  // The head commit when the page the script runs on does not show it: read from the PR's conversation page, then, only
  // when a run server is set, asked of it. `commentSource` and `source` are loaded after this adapter, so they are
  // looked up when the call is made.
  async function fetchHeadSha(pr) {
    const conversation = page.isConversationPage(pr) ? null : await ns.commentSource?.fetchConversation(page.conversationUrl(pr));
    const shown = conversation ? readHeadSha(conversation) : null;
    if (shown) return shown;
    return (await ns.source?.headSha({ host: "github", owner: pr.owner, repo: pr.repo, pr: pr.pr, key: String(pr.pr) })) ?? null;
  }

  function findRow(anchor) {
    return document.querySelector(`${LINE_CELL}[data-line-anchor="${anchor}"]`)?.closest("tr") ?? null;
  }

  // GitHub's page layout is a flex row of the file tree pane and the diffs' column. The diagram panel is the
  // row's leftmost item: it is inserted right before the pane, with the pane's own computed `order`, so DOM order
  // puts it ahead of the pane whatever values GitHub's CSS gives them, and no GitHub element is restyled. It sticks
  // at the pane's top offset. Without a pane it goes right before the diffs, with their order.
  function diagramHost() {
    const content = document.querySelector(DIFF_CONTENT);
    if (!content) return null;
    const pane = document.querySelector(DIFF_PANE);
    const anchor = pane ?? content;
    return { content, pane, top: pane ? getComputedStyle(pane).top : "0px", order: getComputedStyle(anchor).order };
  }

  // GitHub's own tree, including its "File tree" heading. The filter box above it is a sibling and
  // stays visible, so a list mounted before this element sits between the two.
  function treeHost() {
    return document.querySelector(TREE_HOST);
  }

  const page = createPage({
    name: "GitHub",
    treeLabel: "Files",
    hosts: ["github.com"],
    origin: "https://github.com",
    changesPage: CHANGES_PAGE,
    pullPage: PULL_PAGE,
    conversationPage: CONVERSATION_PAGE,
    conversationPath: (pr) => `/${pr.owner}/${pr.repo}/pull/${pr.pr}`,
    filesPath: (pr) => `/${pr.owner}/${pr.repo}/pull/${pr.pr}/files`,
    hostId: "github",
    runKey: (pr) => String(pr.pr),
    readHeadSha,
    fetchHeadSha,
    blockSelector: DIFF_BLOCK,
    pathOfBlock,
    // The whole entry of one file's diff, which holds the file callout above its header.
    entryOf: (block) => block.closest(DIFF_ENTRY) ?? block,
    diffId,
    findRow,
    fileHeaderSelector: FILE_HEADER,
    stickySkip: STICKY_SKIP,
    containerSelector: DIFF_CONTAINER,
    contentSelector: DIFF_CONTENT,
    diagramHost,
    treeHost,
    treeFileSelector: TREE_FILE,
    treeDirSelector: TREE_DIR,
    descriptionHost: () => document.querySelector(DESCRIPTION),
  });

  ns.githubPage = page;
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.githubPage;
