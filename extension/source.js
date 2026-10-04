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

  // `variant` is a variant the user picked; without it the extension's stored default decides.
  async function loadReview(owner, repo, pr, variant) {
    if (!alive()) return null;
    try {
      return (await chrome.runtime.sendMessage({ type: "loadReview", owner, repo, pr, variant })) ?? null;
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
  ns.source = { loadReview, saveVariant };
})();

if (typeof module !== "undefined") module.exports = { alive: globalThis.prFocus.alive, ...globalThis.prFocus.source };
