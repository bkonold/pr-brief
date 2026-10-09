const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const REVIEW_BASE = { repo: "acme/widgets", pr: 7, head_sha: "a".repeat(40), variant: "diagram_walkthrough_v24", walkthrough: [] };

// Loads background.js against a fake chrome and a fake run server whose review.json is `review`, and asks it for the
// PR's run the way a content script does.
async function loadReview(review, { down = false, refused = false } = {}) {
  let listener;
  const responses = {
    "/api/config": { default_variant: "diagram_walkthrough_v24" },
    "/runs/7/diagram_walkthrough_v24/review.json": review,
  };
  const saved = { chrome: globalThis.chrome, fetch: globalThis.fetch };
  globalThis.chrome = {
    storage: { sync: { get: async () => ({}) }, local: { get: async () => ({}) } },
    runtime: { onMessage: { addListener: (callback) => (listener = callback) } },
  };
  globalThis.fetch = async (url) => {
    if (down) throw new TypeError("Failed to fetch");
    if (refused) return { ok: false, status: 403, json: async () => ({ error: "auth" }) };
    const body = responses[new URL(url).pathname];
    return body === undefined ? { ok: false, status: 404 } : { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
  };
  try {
    await import(`${pathToFileURL(path.join(__dirname, "../background.js")).href}?${Math.random()}`);
    return await new Promise((resolve) => listener({ type: "loadReview", owner: "acme", repo: "widgets", pr: 7 }, null, resolve));
  } finally {
    globalThis.chrome = saved.chrome;
    globalThis.fetch = saved.fetch;
  }
}

test("a schema 4 run with boxes and a walkthrough is the current run", async () => {
  const run = await loadReview({ ...REVIEW_BASE, schema: 4, nodes: {} });
  assert.equal(run.error, undefined);
  assert.equal(run.schema, 4);
});

test("a run of an older schema, or one without boxes, asks to be re-run", async () => {
  for (const review of [{ ...REVIEW_BASE, schema: 3, chunks: [] }, { ...REVIEW_BASE, schema: 4 }, { ...REVIEW_BASE, schema: 4, nodes: null }]) {
    assert.equal((await loadReview(review)).error, "old", JSON.stringify(review));
  }
});

test("the run shown is the server's default variant, and nothing else is looked for", async () => {
  const run = await loadReview({ ...REVIEW_BASE, schema: 4, nodes: {} });
  assert.equal(run.variant, "diagram_walkthrough_v24");
});

test("a server that is down, or one that refuses the token, leaves no run to show", async () => {
  const review = { ...REVIEW_BASE, schema: 4, nodes: {} };
  assert.equal((await loadReview(review, { down: true })).error, "server");
  assert.equal(await loadReview(review, { refused: true }), null);
});
