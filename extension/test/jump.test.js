const test = require("node:test");
const assert = require("node:assert/strict");

const { createPage } = require("../page_common.js");
const githubPage = require("../github_page.js");
const forgejoPage = require("../forgejo_page.js");

const realSetTimeout = globalThis.setTimeout;
const JUMP_MS = 10000;
const LOAD_MS = 30000;

class FakeNode {
  constructor(className = "") {
    this.classes = new Set(className.split(" ").filter(Boolean));
    this.children = [];
    this.classList = {
      contains: (name) => this.classes.has(name),
      add: (...names) => names.forEach((name) => this.classes.add(name)),
      remove: (...names) => names.forEach((name) => this.classes.delete(name)),
    };
  }
  get firstElementChild() {
    return this.children[0] ?? null;
  }
  get previousElementSibling() {
    return null;
  }
  getBoundingClientRect() {
    return { top: 0, height: 0, bottom: 0, left: 0, right: 0 };
  }
  addEventListener() {}
  querySelector() {
    return null;
  }
}

// A page whose one diff block has no rows until `showRows()` replaces the block by a new node with the same id, the way
// GitHub swaps in a loaded diff. `timers` records the delays of the long waits, which never fire unless `expire()` runs.
function fakeJumpPage({ loadDiff }) {
  const originals = {};
  const state = { blocks: new Map([["diff-a", new FakeNode("entry")]]), rows: new Map(), observers: [], delays: [], expiry: [], loads: 0 };
  const row = new FakeNode("row");
  const install = (name, value) => {
    originals[name] = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
  };
  install("document", {
    getElementById: (id) => state.blocks.get(id) ?? null,
    querySelector: () => null,
    querySelectorAll: () => [],
    createTreeWalker: () => ({ nextNode: () => null }),
    createElement: () => new FakeNode(),
    body: {},
    documentElement: { scrollHeight: 5000 },
  });
  install("MutationObserver", class {
    constructor(callback) {
      this.callback = callback;
      state.observers.push(this);
    }
    observe() {}
    disconnect() {
      state.observers.splice(state.observers.indexOf(this), 1);
    }
  });
  install("NodeFilter", { SHOW_ELEMENT: 1, FILTER_ACCEPT: 1, FILTER_SKIP: 3, FILTER_REJECT: 2 });
  install("innerHeight", 800);
  install("scrollY", 0);
  install("scrollBy", () => {});
  install("setTimeout", (callback, ms) => {
    if (ms < JUMP_MS) return realSetTimeout(callback, ms);
    state.delays.push(ms);
    state.expiry.push(callback);
    return state.expiry.length;
  });
  state.showRows = () => {
    const replacement = new FakeNode("entry");
    state.blocks.set("diff-a", replacement);
    state.rows.set("diff-aR5", row);
    for (const observer of [...state.observers]) observer.callback();
  };
  state.expire = () => state.expiry.splice(0).forEach((callback) => callback());
  state.row = row;
  // The scroll to the entry is not awaited by the jump, so its idle polling can outlast a jump that gave up.
  state.done = async () => {
    await new Promise((resolve) => realSetTimeout(resolve, 400));
    for (const [name, descriptor] of Object.entries(originals)) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  };
  state.page = createPage({
    entryOf: (block) => block,
    diffId: async (path) => `diff-${path}`,
    findRow: (anchor) => state.rows.get(anchor) ?? null,
    fileHeaderSelector: ".file-header",
    stickySkip: ".none",
    contentSelector: ".content",
    loadDiff: loadDiff && ((id) => loadDiff(state, id)),
  });
  return state;
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

test("jumpToLine does not ask the host to load a diff whose row is already there", async () => {
  const dom = fakeJumpPage({ loadDiff: (state) => ((state.loads += 1), true) });
  try {
    dom.rows.set("diff-aR5", dom.row);
    assert.equal(await dom.page.jumpToLine("a", "R", 5), true);
    assert.equal(dom.loads, 0);
    assert.equal(dom.row.classes.has("prf-line-target"), true);
  } finally {
    await dom.done();
  }
});

test("jumpToLine loads a diff the host holds back, waits the longer budget, and lands on the row of the replaced block", async () => {
  const dom = fakeJumpPage({ loadDiff: (state, id) => ((state.loads += 1), state.blocks.has(id)) });
  try {
    const jump = dom.page.jumpToLine("a", "R", 5);
    await tick();
    await tick();
    assert.deepEqual([dom.loads, dom.delays], [1, [LOAD_MS]]);
    dom.showRows();
    assert.equal(await jump, true);
    assert.equal(dom.row.classes.has("prf-line-target"), true);
    assert.equal(dom.observers.length, 0);
  } finally {
    await dom.done();
  }
});

test("jumpToLine gives up after the longer budget when the loaded diff never shows the row", async () => {
  const dom = fakeJumpPage({ loadDiff: () => true });
  try {
    const jump = dom.page.jumpToLine("a", "R", 5);
    await tick();
    await tick();
    assert.deepEqual(dom.delays, [LOAD_MS]);
    dom.expire();
    assert.equal(await jump, false);
    assert.equal(dom.observers.length, 0);
  } finally {
    await dom.done();
  }
});

test("jumpToLine keeps the short budget when the host has no load control for the diff", async () => {
  for (const loadDiff of [undefined, () => false]) {
    const dom = fakeJumpPage({ loadDiff });
    try {
      const jump = dom.page.jumpToLine("a", "R", 5);
      await tick();
      await tick();
      assert.deepEqual(dom.delays, [JUMP_MS]);
      dom.expire();
      assert.equal(await jump, false);
    } finally {
      await dom.done();
    }
  }
});

function fakeLoadDocument(blocks) {
  const original = Object.getOwnPropertyDescriptor(globalThis, "document");
  globalThis.document = { getElementById: (id) => blocks[id] ?? null };
  return () => {
    if (original) Object.defineProperty(globalThis, "document", original);
    else delete globalThis.document;
  };
}

const control = (text) => ({ textContent: text, clicks: 0, click() { this.clicks += 1; } });

test("GitHub's loadDiff clicks the block's Load Diff button, whatever its case and padding, and no other button", () => {
  const load = control("  Load diff\n");
  const other = control("Copy path");
  const done = fakeLoadDocument({ "diff-a": { querySelectorAll: () => [other, load] }, "diff-b": { querySelectorAll: () => [control("Large diffs are not rendered by default.")] } });
  try {
    assert.equal(githubPage.loadDiff("diff-a"), true);
    assert.deepEqual([load.clicks, other.clicks], [1, 0]);
    assert.equal(githubPage.loadDiff("diff-b"), false);
    assert.equal(githubPage.loadDiff("diff-missing"), false);
  } finally {
    done();
  }
});

test("Forgejo's loadDiff clicks the box's load link when it has one", () => {
  const link = control("Load diff");
  const done = fakeLoadDocument({ "diff-a": { querySelector: (selector) => (selector === "a.diff-load-button" ? link : null) }, "diff-b": { querySelector: () => null } });
  try {
    assert.equal(forgejoPage.loadDiff("diff-a"), true);
    assert.equal(link.clicks, 1);
    assert.equal(forgejoPage.loadDiff("diff-b"), false);
    assert.equal(forgejoPage.loadDiff("diff-missing"), false);
  } finally {
    done();
  }
});
