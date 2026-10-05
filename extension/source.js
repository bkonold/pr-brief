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

  // `variant` is a variant the user picked; without it the extension's stored default decides. `key` is the
  // PR's folder under runs/, which is not the PR number for every host.
  async function loadReview(owner, repo, pr, variant, key = String(pr)) {
    if (!alive()) return null;
    try {
      return (await chrome.runtime.sendMessage({ type: "loadReview", owner, repo, pr, variant, key })) ?? null;
    } catch {
      return null;
    }
  }

  // The run behind the PR brief card: { variant, bodyHtml, diagramSvg }, or null when the PR has no run or the page
  // server is down.
  async function loadBrief(owner, repo, pr, key = String(pr)) {
    if (!alive()) return null;
    try {
      const brief = await chrome.runtime.sendMessage({ type: "loadBrief", owner, repo, pr, key });
      return brief && !brief.error ? brief : null;
    } catch {
      return null;
    }
  }

  async function saveVariant(variant) {
    if (!alive()) return;
    try {
      await chrome.storage.sync.set({ variant });
    } catch {
      // The default just isn't remembered.
    }
  }

  ns.alive = alive;
  ns.source = { loadReview, loadBrief, saveVariant };
})();

if (typeof module !== "undefined") module.exports = { alive: globalThis.prFocus.alive, ...globalThis.prFocus.source };
