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

  // `key` is the PR's folder under runs/, which is not the PR number for every host.
  async function loadReview(owner, repo, pr, key = String(pr)) {
    if (!alive()) return null;
    try {
      return (await chrome.runtime.sendMessage({ type: "loadReview", owner, repo, pr, key })) ?? null;
    } catch {
      return null;
    }
  }

  // The run behind the PR brief card: { variant, bodyHtml, diagramSvg, headSha }, or null when the PR has no run or
  // the page server is down.
  async function loadBrief(owner, repo, pr, key = String(pr)) {
    if (!alive()) return null;
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

  ns.alive = alive;
  ns.source = { loadReview, loadBrief, startRun, runStatus, cancelRun, headSha };
})();

if (typeof module !== "undefined") module.exports = { alive: globalThis.prFocus.alive, ...globalThis.prFocus.source };
