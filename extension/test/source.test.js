const test = require("node:test");
const assert = require("node:assert/strict");
const zlib = require("node:zlib");

const githubPage = require("../github_page.js");
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

const posted = (extra = {}, review = REVIEW) => docWith(pack({ ...review, diagram_svg: "<svg/>", ...extra }));

// Runs `body` with a live extension context, a fetch that serves `pages` (url to Document) and the GitHub adapter on
// `location`. Returns which pages were fetched.
async function scenario({ location = "/acme/widgets/pull/7/files", pages = {} }, body) {
  const saved = { chrome: globalThis.chrome, fetch: globalThis.fetch, DOMParser: globalThis.DOMParser, location: globalThis.location, page: globalThis.prFocus.page };
  const fetched = [];
  globalThis.chrome = { runtime: { id: "abc" } };
  globalThis.location = { pathname: location, host: "github.com" };
  globalThis.prFocus.page = githubPage;
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
    return await body({ fetched });
  } finally {
    for (const [name, value] of Object.entries(saved)) {
      if (name === "page") globalThis.prFocus.page = value;
      else if (value === undefined) delete globalThis[name];
      else globalThis[name] = value;
    }
  }
}

const CONVERSATION = "https://github.com/acme/widgets/pull/7";

test("the review is read from the PR's comment, fetched from the conversation page, with its diagram", async () => {
  await scenario({ pages: { [CONVERSATION]: posted() } }, async ({ fetched }) => {
    assert.deepEqual(await source.loadReview("acme", "widgets", 7), { ...REVIEW, diagramSvg: "<svg/>" });
    assert.deepEqual(fetched, [CONVERSATION]);
  });
});

test("an older comment's body page is left out of the review", async () => {
  await scenario({ pages: { [CONVERSATION]: posted({ body_html: "<p>brief</p>" }) } }, async () => {
    assert.deepEqual(await source.loadReview("acme", "widgets", 7), { ...REVIEW, diagramSvg: "<svg/>" });
  });
});

test("a comment of another PR, another repository or an older schema is no review", async () => {
  const bad = [
    { ...REVIEW, pr: 8 },
    { ...REVIEW, repo: "acme/other" },
    { ...REVIEW, schema: 3 },
    { ...REVIEW, nodes: null },
    { ...REVIEW, walkthrough: undefined },
  ];
  for (const review of bad) {
    await scenario({ pages: { [CONVERSATION]: posted({}, review) } }, async () => {
      assert.equal(await source.loadReview("acme", "widgets", 7), null, JSON.stringify(review));
    });
  }
});

test("with no comment, an unreadable page or a failed fetch there is no review", async () => {
  await scenario({ pages: {} }, async () => {
    assert.equal(await source.loadReview("acme", "widgets", 7), null);
  });
  await scenario({ pages: { [CONVERSATION]: docWith("garbage") } }, async () => {
    assert.equal(await source.loadReview("acme", "widgets", 7), null);
  });
});

test("a dead extension context reads nothing, not even the comment", async () => {
  await scenario({ pages: { [CONVERSATION]: posted() } }, async ({ fetched }) => {
    delete globalThis.chrome;
    assert.equal(await source.loadReview("acme", "widgets", 7), null);
    assert.deepEqual(fetched, []);
  });
});

async function withStorage({ stored = {}, throws = false, id = "abc" } = {}, body) {
  const saved = globalThis.chrome;
  const written = [];
  const listeners = new Set();
  globalThis.chrome = {
    runtime: { id },
    storage: {
      local: {
        get: async (defaults) => (throws ? Promise.reject(new Error("unreadable")) : { ...defaults, ...stored }),
        set: async (items) => (throws ? Promise.reject(new Error("unwritable")) : written.push(items)),
      },
      onChanged: { addListener: (listener) => listeners.add(listener), removeListener: (listener) => listeners.delete(listener) },
    },
  };
  try {
    return await body({ written, listeners });
  } finally {
    globalThis.chrome = saved;
  }
}

test("the pane owner is stored under the key defaults.js names, and is the brief's until the host is chosen", async () => {
  const { PANE_OWNER_KEY } = await import("../defaults.js");
  assert.equal(source.PANE_OWNER_KEY, PANE_OWNER_KEY);
  await withStorage({}, async () => assert.equal(await source.loadPaneOwner(), "brief"));
  await withStorage({ stored: { [PANE_OWNER_KEY]: "host" } }, async () => assert.equal(await source.loadPaneOwner(), "host"));
  await withStorage({ stored: { [PANE_OWNER_KEY]: "nope" } }, async () => assert.equal(await source.loadPaneOwner(), "brief"));
  await withStorage({ throws: true }, async () => assert.equal(await source.loadPaneOwner(), "brief"));
  await withStorage({ id: undefined }, async () => assert.equal(await source.loadPaneOwner(), "brief"));
});

test("savePaneOwner writes the owner, and ignores a value that is not one or a store that cannot be written", async () => {
  await withStorage({}, async ({ written }) => {
    await source.savePaneOwner("host");
    await source.savePaneOwner("brief");
    await source.savePaneOwner("nope");
    assert.deepEqual(written, [{ paneOwner: "host" }, { paneOwner: "brief" }]);
  });
  await withStorage({ throws: true }, async () => {
    await source.savePaneOwner("host");
  });
});

test("onPaneOwnerChange reports a change of the stored owner only, and stops when asked", async () => {
  await withStorage({}, async ({ listeners }) => {
    const seen = [];
    const stop = source.onPaneOwnerChange((owner) => seen.push(owner));
    const [listener] = listeners;
    listener({ paneOwner: { newValue: "host" } }, "local");
    listener({ paneOwner: { newValue: "bogus" } }, "local");
    listener({ paneOwner: { newValue: "host" } }, "sync");
    listener({ other: { newValue: "x" } }, "local");
    listener({ paneOwner: {} }, "local");
    assert.deepEqual(seen, ["host", "brief", "brief"]);
    stop();
    assert.equal(listeners.size, 0);
  });
  const saved = globalThis.chrome;
  globalThis.chrome = { runtime: { id: "abc" } };
  try {
    source.onPaneOwnerChange(() => {})();
  } finally {
    globalThis.chrome = saved;
  }
});
