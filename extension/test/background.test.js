const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const REVIEW_BASE = { repo: "acme/widgets", pr: 7, head_sha: "a".repeat(40), variant: "brief", walkthrough: [] };

const SERVER = "http://127.0.0.1:8765";

// Loads background.js against a fake chrome whose stored server URL is `baseUrl` and a fake run server whose review.json
// is `review`, sends it `message` the way a content script does, and returns its answer with the URLs it fetched.
async function send(message, review, { baseUrl = SERVER, down = false, refused = false } = {}) {
  let listener;
  const responses = {
    "/api/config": { default_variant: "brief" },
    "/runs/7/brief/review.json": review,
    "/runs/7/brief/body.html": "<p>brief</p>",
    "/runs/7/brief/diagram.svg": "<svg/>",
  };
  const saved = { chrome: globalThis.chrome, fetch: globalThis.fetch };
  const fetched = [];
  globalThis.chrome = {
    storage: { sync: { get: async (defaults) => ({ ...defaults, ...(baseUrl === null ? {} : { baseUrl }) }) }, local: { get: async () => ({}) } },
    runtime: { onMessage: { addListener: (callback) => (listener = callback) } },
  };
  globalThis.fetch = async (url) => {
    fetched.push(url);
    if (down) throw new TypeError("Failed to fetch");
    if (refused) return { ok: false, status: 403, json: async () => ({ error: "auth" }) };
    const body = responses[new URL(url).pathname];
    return body === undefined
      ? { ok: false, status: 404 }
      : { ok: true, status: 200, json: async () => body, text: async () => (typeof body === "string" ? body : JSON.stringify(body)) };
  };
  try {
    await import(`${pathToFileURL(path.join(__dirname, "../background.js")).href}?${Math.random()}`);
    const answer = await new Promise((resolve) => listener(message, null, resolve));
    return { answer, fetched };
  } finally {
    globalThis.chrome = saved.chrome;
    globalThis.fetch = saved.fetch;
  }
}

async function loadReview(review, options) {
  return (await send({ type: "loadReview", owner: "acme", repo: "widgets", pr: 7 }, review, options)).answer;
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
  assert.equal(run.variant, "brief");
});

test("a server that is down, or one that refuses the token, leaves no run to show", async () => {
  const review = { ...REVIEW_BASE, schema: 4, nodes: {} };
  assert.equal((await loadReview(review, { down: true })).error, "server");
  assert.equal(await loadReview(review, { refused: true }), null);
});

const REQUESTS = [
  { type: "loadReview", owner: "acme", repo: "widgets", pr: 7 },
  { type: "loadBrief", owner: "acme", repo: "widgets", pr: 7 },
  { type: "startRun", host: "github", owner: "acme", repo: "widgets", pr: 7, key: "7" },
  { type: "runStatus", key: "7", host: "github", owner: "acme", repo: "widgets" },
  { type: "cancelRun", key: "7" },
  { type: "headSha", host: "github", owner: "acme", repo: "widgets", pr: 7 },
];

test("with no server URL set, every call answers at once and requests nothing", async () => {
  const review = { ...REVIEW_BASE, schema: 4, nodes: {} };
  for (const baseUrl of ["", null, "  "]) {
    for (const message of REQUESTS) {
      const { answer, fetched } = await send(message, review, { baseUrl });
      const loads = message.type === "loadReview" || message.type === "loadBrief";
      assert.deepEqual(answer, loads ? null : { ok: false, problem: "unset" }, `${message.type} with ${JSON.stringify(baseUrl)}`);
      assert.deepEqual(fetched, [], `${message.type} with ${JSON.stringify(baseUrl)}`);
    }
  }
});

test("the stored server URL is the only one asked, with its trailing slashes dropped", async () => {
  const review = { ...REVIEW_BASE, schema: 4, nodes: {} };
  const { fetched } = await send(REQUESTS[0], review, { baseUrl: `${SERVER}//` });
  assert.ok(fetched.length > 0 && fetched.every((url) => url.startsWith(`${SERVER}/`) && !url.startsWith(`${SERVER}//`)), fetched.join(" "));
});

test("a brief from the server names the server as its origin", async () => {
  const { answer } = await send(REQUESTS[1], { ...REVIEW_BASE, schema: 4, nodes: {}, diagram: "diagram.svg" });
  assert.deepEqual(answer, { variant: "brief", model: null, bodyHtml: "<p>brief</p>", diagramSvg: "<svg/>", headSha: "a".repeat(40), origin: "server" });
});
