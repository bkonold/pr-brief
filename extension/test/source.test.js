const test = require("node:test");
const assert = require("node:assert/strict");
const zlib = require("node:zlib");

const githubPage = require("../github_page.js");
const forgejoPage = require("../forgejo_page.js");
require("../comment_source.js");
const source = require("../source.js");

const REVIEW = { schema: 4, repo: "acme/widgets", pr: 7, head_sha: "a".repeat(40), variant: "brief", nodes: {}, walkthrough: [] };
const pack = (value) => zlib.gzipSync(Buffer.from(JSON.stringify(value), "utf8")).toString("base64");

// A Document stand-in holding one Brief data block.
function docWith(payload) {
  return {
    querySelectorAll: () => [
      {
        querySelector: (name) => (name === "summary" ? { textContent: "Brief data" } : { textContent: payload }),
      },
    ],
  };
}

const posted = (extra = {}, review = REVIEW) => docWith(pack({ ...review, diagram_svg: "<svg/>", body_html: "<p>brief</p>", ...extra }));

// Runs `body` with a chrome whose background answers `answer`, a fetch that serves `pages` (url to Document, or a function),
// and the page adapter on `location`. Returns what the background was asked and which pages were fetched.
async function scenario({ location = "/acme/widgets/pull/7/files", adapter = githubPage, pages = {}, answer = () => null, document: pageDocument }, body) {
  const saved = { chrome: globalThis.chrome, fetch: globalThis.fetch, DOMParser: globalThis.DOMParser, location: globalThis.location, document: globalThis.document, page: globalThis.prFocus.page };
  const asked = [];
  const fetched = [];
  globalThis.chrome = { runtime: { id: "abc", sendMessage: async (message) => (asked.push(message), answer(message)) } };
  globalThis.location = { pathname: location, host: "github.com" };
  if (pageDocument) globalThis.document = pageDocument;
  globalThis.prFocus.page = adapter;
  globalThis.DOMParser = class {
    parseFromString(text) {
      return pages[text];
    }
  };
  globalThis.fetch = async (url) => {
    fetched.push(url);
    const found = pages[url];
    return found ? { ok: true, text: async () => url } : { ok: false, status: 404 };
  };
  try {
    return await body({ asked, fetched });
  } finally {
    for (const [name, value] of Object.entries(saved)) {
      if (name === "page") globalThis.prFocus.page = value;
      else if (value === undefined) delete globalThis[name];
      else globalThis[name] = value;
    }
  }
}

const CONVERSATION = "https://github.com/acme/widgets/pull/7";

test("the review is read from the PR's comment, fetched from the conversation page, with no call to the background", async () => {
  await scenario({ pages: { [CONVERSATION]: posted() } }, async ({ asked, fetched }) => {
    assert.deepEqual(await source.loadReview("acme", "widgets", 7), { ...REVIEW, diagramSvg: "<svg/>" });
    assert.deepEqual(fetched, [CONVERSATION]);
    assert.deepEqual(asked, []);
  });
});

test("the brief from the comment names its origin, variant, sha, page and diagram", async () => {
  await scenario({ pages: { [CONVERSATION]: posted() } }, async ({ asked }) => {
    assert.deepEqual(await source.loadBrief("acme", "widgets", 7), { variant: "brief", bodyHtml: "<p>brief</p>", diagramSvg: "<svg/>", headSha: "a".repeat(40), origin: "comment" });
    assert.deepEqual(asked, []);
  });
});

test("on the PR's conversation page the page's own document is read and nothing is fetched", async () => {
  await scenario({ location: "/acme/widgets/pull/7", document: posted() }, async ({ asked, fetched }) => {
    assert.equal((await source.loadBrief("acme", "widgets", 7)).origin, "comment");
    assert.deepEqual([fetched, asked], [[], []]);
  });
});

test("a Forgejo PR's conversation page is fetched from its pulls url", async () => {
  const url = "http://localhost:3300/acme/widgets/pulls/7";
  await scenario({ adapter: forgejoPage, location: "/acme/widgets/pulls/3/files", pages: { [url]: posted() } }, async ({ fetched }) => {
    assert.equal((await source.loadBrief("acme", "widgets", 7, "fj-7")).origin, "comment");
    assert.deepEqual(fetched, [url]);
  });
});

test("the review and the brief of one load share one fetch of the conversation page, and a later load fetches again", async () => {
  await scenario({ pages: { [CONVERSATION]: posted() } }, async ({ fetched }) => {
    await Promise.all([source.loadReview("acme", "widgets", 7), source.loadBrief("acme", "widgets", 7)]);
    assert.equal(fetched.length, 1);
    await source.loadBrief("acme", "widgets", 7);
    assert.equal(fetched.length, 2);
  });
});

test("a comment of another PR, another repository or an older schema is not used, and the background is asked", async () => {
  const bad = [
    { ...REVIEW, pr: 8 },
    { ...REVIEW, repo: "acme/other" },
    { ...REVIEW, schema: 3 },
    { ...REVIEW, nodes: null },
    { ...REVIEW, walkthrough: undefined },
  ];
  for (const review of bad) {
    await scenario({ pages: { [CONVERSATION]: posted({}, review) }, answer: () => ({ from: "server" }) }, async ({ asked }) => {
      assert.deepEqual(await source.loadReview("acme", "widgets", 7), { from: "server" }, JSON.stringify(review));
      assert.deepEqual(asked.map((message) => message.type), ["loadReview"]);
    });
  }
});

test("with no comment, an unreadable page or a failed fetch, the background answers as before", async () => {
  await scenario({ pages: {}, answer: (message) => (message.type === "loadBrief" ? { variant: "v", bodyHtml: "<p/>", diagramSvg: null, headSha: null, origin: "server" } : null) }, async ({ asked }) => {
    assert.equal(await source.loadReview("acme", "widgets", 7, "7"), null);
    assert.equal((await source.loadBrief("acme", "widgets", 7, "7")).origin, "server");
    assert.deepEqual(asked.map((message) => [message.type, message.key]), [["loadReview", "7"], ["loadBrief", "7"]]);
  });
  await scenario({ pages: { [CONVERSATION]: docWith("garbage") } }, async ({ asked }) => {
    assert.equal(await source.loadReview("acme", "widgets", 7), null);
    assert.equal(asked.length, 1);
  });
});

test("a comment with no body page leaves the brief to the server, while the review still comes from the comment", async () => {
  await scenario({ pages: { [CONVERSATION]: posted({ body_html: null }) }, answer: () => ({ origin: "server", bodyHtml: "<p/>" }) }, async ({ asked }) => {
    assert.equal((await source.loadReview("acme", "widgets", 7)).repo, "acme/widgets");
    assert.equal((await source.loadBrief("acme", "widgets", 7)).origin, "server");
    assert.deepEqual(asked.map((message) => message.type), ["loadBrief"]);
  });
});

test("loadBrief with server: true skips the comment", async () => {
  await scenario({ pages: { [CONVERSATION]: posted() }, answer: () => ({ origin: "server", bodyHtml: "<p/>" }) }, async ({ asked, fetched }) => {
    assert.equal((await source.loadBrief("acme", "widgets", 7, "7", { server: true })).origin, "server");
    assert.deepEqual([fetched, asked.length], [[], 1]);
  });
});

test("a background error answer is no brief", async () => {
  await scenario({ answer: () => ({ error: "server" }) }, async () => {
    assert.equal(await source.loadBrief("acme", "widgets", 7), null);
  });
});

test("a dead extension context reads nothing, not even the comment", async () => {
  await scenario({ pages: { [CONVERSATION]: posted() } }, async ({ fetched }) => {
    delete globalThis.chrome;
    assert.equal(await source.loadReview("acme", "widgets", 7), null);
    assert.equal(await source.loadBrief("acme", "widgets", 7), null);
    assert.deepEqual(fetched, []);
  });
});
