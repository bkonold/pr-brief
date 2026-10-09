const test = require("node:test");
const assert = require("node:assert/strict");
const zlib = require("node:zlib");

const { extractPayload, inflate, readBrief, fetchConversation } = require("../comment_source.js");

const pack = (value) => zlib.gzipSync(Buffer.from(JSON.stringify(value), "utf8")).toString("base64");

// A hand-built stand-in for the parts of a Document that extractPayload touches: the elements its selector matches, in
// document order, each with a summary and a pre.
function fakeDoc(blocks) {
  const selectors = [];
  const doc = {
    selectors,
    querySelectorAll(selector) {
      selectors.push(selector);
      return blocks.map(({ summary, pre }) => ({
        querySelector: (name) => (name === "summary" ? (summary === undefined ? null : { textContent: summary }) : name === "pre" ? (pre === undefined ? null : { textContent: pre }) : null),
      }));
    },
  };
  return doc;
}

test("extractPayload returns the trimmed fence text of the earliest Brief data block", () => {
  const doc = fakeDoc([
    { summary: "Contract", pre: "not this" },
    { summary: " Brief data\n", pre: "\nFIRST\n" },
    { summary: "Brief data", pre: "SECOND" },
  ]);
  assert.equal(extractPayload(doc), "FIRST");
});

test("extractPayload needs the exact summary and some text in the fence", () => {
  assert.equal(extractPayload(fakeDoc([{ summary: "Brief data (old)", pre: "A" }, { summary: "brief data", pre: "A" }])), null);
  assert.equal(extractPayload(fakeDoc([{ summary: "Brief data" }])), null);
  assert.equal(extractPayload(fakeDoc([{ summary: "Brief data", pre: "  \n" }, { summary: "Brief data", pre: "LATER" }])), "LATER");
  assert.equal(extractPayload(fakeDoc([{ pre: "A" }])), null);
  assert.equal(extractPayload(fakeDoc([])), null);
});

test("extractPayload looks only inside GitHub's and Forgejo's rendered markdown", () => {
  const doc = fakeDoc([]);
  extractPayload(doc);
  assert.deepEqual(doc.selectors, [".markdown-body details, .render-content.markup details"]);
});

test("inflate returns the JSON object of a gzip, with its non-ASCII text intact", async () => {
  assert.deepEqual(await inflate(pack({ schema: 4, title: "Ünï — ok", nested: { a: [1, 2] } })), { schema: 4, title: "Ünï — ok", nested: { a: [1, 2] } });
  assert.deepEqual(await inflate(`  ${pack({ a: 1 })}\n`), { a: 1 });
  const wrapped = pack({ a: "x".repeat(500) }).replace(/(.{40})/g, "$1\n");
  assert.deepEqual(await inflate(wrapped), { a: "x".repeat(500) });
});

test("inflate returns null for anything but a gzip of a JSON object", async () => {
  assert.equal(await inflate("not base64 !!"), null);
  assert.equal(await inflate(Buffer.from("plain text").toString("base64")), null);
  assert.equal(await inflate(zlib.gzipSync("not json").toString("base64")), null);
  assert.equal(await inflate(pack([1, 2])), null);
  assert.equal(await inflate(pack(null)), null);
  assert.equal(await inflate(pack("text")), null);
  assert.equal(await inflate(""), null);
  assert.equal(await inflate(undefined), null);
  const truncated = zlib.gzipSync(JSON.stringify({ a: "x".repeat(1000) }));
  assert.equal(await inflate(truncated.subarray(0, truncated.length - 12).toString("base64")), null);
});

test("inflate refuses a payload that inflates past the size cap", async () => {
  const huge = zlib.gzipSync(Buffer.from(`{"a":"${"x".repeat(17 * 1024 * 1024)}"}`)).toString("base64");
  assert.equal(await inflate(huge), null);
});

test("readBrief splits the posted review from the diagram and the body page", async () => {
  const review = { schema: 4, repo: "o/r", pr: 7, head_sha: "a".repeat(40), variant: "v", nodes: {}, walkthrough: [], file_sets: [{ id: "all" }] };
  const doc = fakeDoc([{ summary: "Brief data", pre: pack({ ...review, diagram_svg: "<svg/>", body_html: "<p>hi</p>" }) }]);
  assert.deepEqual(await readBrief(doc), { review, bodyHtml: "<p>hi</p>", diagramSvg: "<svg/>" });
});

test("readBrief gives null for a missing diagram or body page, and null when there is no readable block", async () => {
  const review = { schema: 4, nodes: {}, walkthrough: [] };
  assert.deepEqual(await readBrief(fakeDoc([{ summary: "Brief data", pre: pack({ ...review, diagram_svg: null }) }])), { review, bodyHtml: null, diagramSvg: null });
  assert.equal(await readBrief(fakeDoc([])), null);
  assert.equal(await readBrief(fakeDoc([{ summary: "Brief data", pre: "garbage" }])), null);
});

test("fetchConversation reads the page with the session and parses it, and gives null on a refusal or a network error", async () => {
  const saved = { fetch: globalThis.fetch, DOMParser: globalThis.DOMParser };
  const calls = [];
  globalThis.DOMParser = class {
    parseFromString(text, type) {
      return { text, type };
    }
  };
  try {
    globalThis.fetch = async (url, options) => (calls.push([url, options]), { ok: true, text: async () => "<html>page</html>" });
    assert.deepEqual(await fetchConversation("https://github.com/o/r/pull/7"), { text: "<html>page</html>", type: "text/html" });
    assert.deepEqual(calls, [["https://github.com/o/r/pull/7", { credentials: "include", cache: "no-store" }]]);
    globalThis.fetch = async () => ({ ok: false, status: 404, text: async () => "x" });
    assert.equal(await fetchConversation("https://github.com/o/r/pull/7"), null);
    globalThis.fetch = async () => {
      throw new TypeError("Failed to fetch");
    };
    assert.equal(await fetchConversation("https://github.com/o/r/pull/7"), null);
  } finally {
    globalThis.fetch = saved.fetch;
    globalThis.DOMParser = saved.DOMParser;
    if (saved.DOMParser === undefined) delete globalThis.DOMParser;
  }
});
