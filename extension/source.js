(() => {
  const ns = (globalThis.prFocus ??= {});

  // False once the extension has been reloaded or removed: chrome.runtime.id is then unset and
  // chrome.runtime.sendMessage throws.
  function alive() {
    try {
      return Boolean(globalThis.chrome?.runtime?.id);
    } catch {
      return false;
    }
  }

  // The PR's brief read from its comment, or null: { review, bodyHtml, diagramSvg } for a review of the current schema
  // that names this PR. It comes from the page's own document on the PR's conversation page, else from that page
  // fetched with the user's session. The fetch is shared by the calls that overlap (a files page asks for the review
  // and the brief), and forgotten once it settles, so the next load reads the page again.
  const pending = new Map();

  function commentBrief(owner, repo, pr) {
    const id = `${owner}/${repo}#${pr}`.toLowerCase();
    if (!pending.has(id)) pending.set(id, readComment({ owner, repo, pr }).finally(() => pending.delete(id)));
    return pending.get(id);
  }

  async function readComment(request) {
    const page = ns.page;
    const reader = ns.commentSource;
    if (!page || !reader) return null;
    try {
      const doc = page.isConversationPage(request) ? document : await reader.fetchConversation(page.conversationUrl(request));
      const brief = doc ? await reader.readBrief(doc) : null;
      return brief && namesPr(brief.review, request.owner, request.repo, request.pr) && isCurrentRun(brief.review) ? brief : null;
    } catch {
      return null;
    }
  }

  // The same checks as background.js makes of a run the server holds.
  function namesPr(review, owner, repo, pr) {
    return String(review?.repo).toLowerCase() === `${owner}/${repo}`.toLowerCase() && Number(review.pr) === Number(pr);
  }

  function isCurrentRun(review) {
    return review.schema === 4 && review.nodes !== null && typeof review.nodes === "object" && Array.isArray(review.walkthrough);
  }

  // The PR's review: its comment's, else the run server's when one is set. `key` is the PR's folder under runs/, which
  // is not the PR number for every host.
  async function loadReview(owner, repo, pr, key = String(pr)) {
    if (!alive()) return null;
    const posted = await commentBrief(owner, repo, pr);
    if (posted) return { ...posted.review, diagramSvg: posted.diagramSvg };
    try {
      return (await chrome.runtime.sendMessage({ type: "loadReview", owner, repo, pr, key })) ?? null;
    } catch {
      return null;
    }
  }

  // The run behind the PR brief card: { variant, model, bodyHtml, diagramSvg, headSha, origin }, or null when the PR has
  // none. `origin` is "comment" or "server". With `{ server: true }` the comment is skipped, which is how a run the
  // local server has just written is read.
  async function loadBrief(owner, repo, pr, key = String(pr), { server = false } = {}) {
    if (!alive()) return null;
    const posted = server ? null : await commentBrief(owner, repo, pr);
    if (posted?.bodyHtml != null) {
      return { variant: posted.review.variant ?? null, model: posted.review.model ?? null, bodyHtml: posted.bodyHtml, diagramSvg: posted.diagramSvg, headSha: posted.review.head_sha ?? null, origin: "comment" };
    }
    try {
      const brief = await chrome.runtime.sendMessage({ type: "loadBrief", owner, repo, pr, key });
      return brief && !brief.error ? brief : null;
    } catch {
      return null;
    }
  }

  // A call to the run server through the background script: { ok, ... } or { problem, message? } (see serve_api.js).
  // `run` is { host, owner, repo, pr, key }.
  async function ask(message) {
    if (!alive()) return { problem: "error", message: "The extension was reloaded; reload this page" };
    try {
      return (await chrome.runtime.sendMessage(message)) ?? { problem: "error", message: "The extension did not answer" };
    } catch {
      return { problem: "error", message: "The extension did not answer" };
    }
  }

  const SHA = /^[0-9a-f]{40}$/i;

  // The PR's current head commit as the run server reads it from the host, or null when it cannot say (server down,
  // token wrong, repository not allowed, host unreachable). `run` is { host, owner, repo, pr, key }.
  async function headSha(run) {
    const answer = await ask({ type: "headSha", ...run });
    return answer.ok && typeof answer.sha === "string" && SHA.test(answer.sha) ? answer.sha : null;
  }

  const startRun = (run) => ask({ type: "startRun", ...run });
  const runStatus = (run) => ask({ type: "runStatus", ...run });
  const cancelRun = (run) => ask({ type: "cancelRun", ...run });

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
  ns.source = { loadReview, loadBrief, startRun, runStatus, cancelRun, headSha, loadPaneOwner, savePaneOwner, onPaneOwnerChange, PANE_OWNER_KEY };
})();

if (typeof module !== "undefined") module.exports = { alive: globalThis.prFocus.alive, ...globalThis.prFocus.source };
