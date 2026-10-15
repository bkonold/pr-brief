(() => {
  const ns = (globalThis.prFocus ??= {});

  // False once the extension has been reloaded or removed: chrome.runtime.id is then unset and chrome.storage throws.
  function alive() {
    try {
      return Boolean(globalThis.chrome?.runtime?.id);
    } catch {
      return false;
    }
  }

  // The PR's brief read from its comment, or null: { review, diagramSvg } for a review of the current schema that names
  // this PR. The comment is on the PR's conversation page, which is fetched with the user's session.
  async function readComment(request) {
    const page = ns.page;
    const reader = ns.commentSource;
    if (!page || !reader) return null;
    try {
      const doc = await reader.fetchConversation(page.conversationUrl(request));
      const brief = doc ? await reader.readBrief(doc) : null;
      return brief && namesPr(brief.review, request.owner, request.repo, request.pr) && isCurrentRun(brief.review) ? brief : null;
    } catch {
      return null;
    }
  }

  function namesPr(review, owner, repo, pr) {
    return String(review?.repo).toLowerCase() === `${owner}/${repo}`.toLowerCase() && Number(review.pr) === Number(pr);
  }

  // A review.json this version reads: the current schema, with the walkthrough the pane lists.
  function isCurrentRun(review) {
    return review.schema === 4 && review.nodes !== null && typeof review.nodes === "object" && Array.isArray(review.walkthrough);
  }

  // The PR's review from its comment, with the diagram as `diagramSvg`, or null when the PR has none.
  async function loadReview(owner, repo, pr) {
    if (!alive()) return null;
    const posted = await readComment({ owner, repo, pr });
    return posted ? { ...posted.review, diagramSvg: posted.diagramSvg } : null;
  }

  // Who owns the file pane: "brief" or "host". It is kept in chrome.storage.local under the key defaults.js calls
  // PANE_OWNER_KEY, which a content script, not being a module, repeats here.
  const PANE_OWNER_KEY = "paneOwner";
  const PANE_OWNERS = ["brief", "host"];

  function paneOwnerOf(value) {
    return PANE_OWNERS.includes(value) ? value : "brief";
  }

  // The stored owner, "brief" when none is stored or the store cannot be read.
  async function loadPaneOwner() {
    if (!alive()) return "brief";
    try {
      return paneOwnerOf((await chrome.storage.local.get({ [PANE_OWNER_KEY]: "brief" }))[PANE_OWNER_KEY]);
    } catch {
      return "brief";
    }
  }

  async function savePaneOwner(owner) {
    if (!alive() || !PANE_OWNERS.includes(owner)) return;
    try {
      await chrome.storage.local.set({ [PANE_OWNER_KEY]: owner });
    } catch {
      // The choice holds for this page when the store cannot be written.
    }
  }

  // Calls `callback(owner)` whenever the stored owner changes, in this tab or any other. Returns how to stop.
  function onPaneOwnerChange(callback) {
    if (!alive()) return () => {};
    const listener = (changes, area) => {
      if (area === "local" && Object.hasOwn(changes, PANE_OWNER_KEY)) callback(paneOwnerOf(changes[PANE_OWNER_KEY].newValue));
    };
    try {
      chrome.storage.onChanged.addListener(listener);
    } catch {
      return () => {};
    }
    return () => {
      try {
        chrome.storage.onChanged.removeListener(listener);
      } catch {
        // The extension was reloaded; the listener went with it.
      }
    };
  }

  ns.alive = alive;
  ns.source = { loadReview, loadPaneOwner, savePaneOwner, onPaneOwnerChange, PANE_OWNER_KEY };
})();

if (typeof module !== "undefined") module.exports = { alive: globalThis.prFocus.alive, ...globalThis.prFocus.source };
