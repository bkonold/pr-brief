const test = require("node:test");
const assert = require("node:assert/strict");

const githubPage = require("../github_page.js");
const forgejoPage = require("../forgejo_page.js");
const { resizeHandle } = require("../page_common.js");

class FakeElement {
  constructor() {
    this.children = [];
    this.parentElement = null;
    this.classes = new Set();
    this.listeners = new Map();
    this.styles = new Map();
    this.style = { setProperty: (name, value) => this.styles.set(name, value), removeProperty: (name) => this.styles.delete(name) };
    this.classList = {
      add: (value) => this.classes.add(value),
      remove: (value) => this.classes.delete(value),
      contains: (value) => this.classes.has(value),
    };
  }
  set className(value) {
    this.classes = new Set(value.split(" "));
  }
  get clientHeight() {
    return 800;
  }
  getBoundingClientRect() {
    return { width: 380 };
  }
  append(node) {
    node.remove();
    node.parentElement = this;
    this.children.push(node);
  }
  prepend(node) {
    node.remove();
    node.parentElement = this;
    this.children.unshift(node);
  }
  remove() {
    if (this.parentElement) this.parentElement.children = this.parentElement.children.filter((child) => child !== this);
    this.parentElement = null;
  }
  addEventListener(type, handler) {
    this.listeners.set(type, handler);
  }
  setPointerCapture() {}
  fire(type, event = {}) {
    this.listeners.get(type)?.({ button: 0, pointerId: 1, preventDefault() {}, ...event });
  }
}

const element = () => new FakeElement();

class FakeObserver {
  static all = [];
  constructor(callback) {
    this.callback = callback;
    this.connected = true;
    FakeObserver.all.push(this);
  }
  observe() {}
  disconnect() {
    this.connected = false;
  }
}

const fireObservers = () => FakeObserver.all.filter((observer) => observer.connected).forEach((observer) => observer.callback([]));
const flush = () => new Promise((resolve) => setImmediate(resolve));

function scenario(body, { innerWidth = 1200, stored = null } = {}) {
  const saved = { document: globalThis.document, MutationObserver: globalThis.MutationObserver, innerWidth: globalThis.innerWidth };
  const container = element();
  const state = { pane: element() };
  container.append(state.pane);
  FakeObserver.all = [];
  globalThis.document = {
    body: element(),
    querySelector: (selector) => (selector === "#diff-file-tree" ? state.pane : null),
    createElement: () => element(),
  };
  globalThis.MutationObserver = FakeObserver;
  globalThis.innerWidth = innerWidth;
  const writes = [];
  const options = { load: async () => stored, save: (width) => writes.push(width) };
  return Promise.resolve(body({ state, container, options, writes })).finally(() => {
    Object.assign(globalThis, { document: saved.document, MutationObserver: saved.MutationObserver, innerWidth: saved.innerWidth });
    if (saved.document === undefined) delete globalThis.document;
    if (saved.MutationObserver === undefined) delete globalThis.MutationObserver;
    if (saved.innerWidth === undefined) delete globalThis.innerWidth;
  });
}

const handleOf = (pane) => pane.children.filter((child) => child.classes.has("prf-pane-handle"));

function drag(handle, from, to) {
  handle.fire("pointerdown", { clientX: from });
  handle.fire("pointermove", { clientX: to });
  handle.fire("pointerup");
}

test("the Forgejo pane gets one handle, and dragging it sets the pane's flex and lifts max-width", () =>
  scenario(({ state, options, writes }) => {
    const stop = forgejoPage.resizePane(options);
    const [handle] = handleOf(state.pane);
    assert.equal(handleOf(state.pane).length, 1);
    drag(handle, 400, 480);
    assert.equal(state.pane.styles.get("flex"), "0 0 460px");
    assert.equal(state.pane.styles.get("max-width"), "none");
    assert.deepEqual(writes, [460]);
    stop();
  }));

test("a dragged width stays between 240px and half the viewport", () =>
  scenario(({ state, options, writes }) => {
    forgejoPage.resizePane(options);
    const [handle] = handleOf(state.pane);
    drag(handle, 400, 100);
    assert.equal(state.pane.styles.get("flex"), "0 0 240px");
    drag(handle, 400, 1500);
    assert.equal(state.pane.styles.get("flex"), "0 0 600px");
    assert.deepEqual(writes, [240, 600]);
  }));

test("a click on the handle without a drag saves nothing", () =>
  scenario(({ state, options, writes }) => {
    forgejoPage.resizePane(options);
    const [handle] = handleOf(state.pane);
    handle.fire("pointerdown", { clientX: 400 });
    handle.fire("pointerup");
    assert.deepEqual(writes, []);
    assert.equal(state.pane.styles.has("flex"), false);
  }));

test("the stored width is applied on load, clamped to the viewport", async () => {
  await scenario(
    async ({ state, options }) => {
      forgejoPage.resizePane(options);
      await flush();
      assert.equal(state.pane.styles.get("flex"), "0 0 500px");
      assert.equal(state.pane.styles.get("max-width"), "none");
    },
    { stored: 500 },
  );
  await scenario(
    async ({ state, options }) => {
      forgejoPage.resizePane(options);
      await flush();
      assert.equal(state.pane.styles.get("flex"), "0 0 600px");
    },
    { stored: 5000 },
  );
});

test("no stored width leaves Forgejo's own width alone", () =>
  scenario(async ({ state, options }) => {
    forgejoPage.resizePane(options);
    await flush();
    assert.equal(state.pane.styles.has("flex"), false);
    assert.equal(state.pane.styles.has("max-width"), false);
  }));

test("a double-click on the handle forgets the width and gives the pane Forgejo's own", () =>
  scenario(async ({ state, options, writes }) => {
    forgejoPage.resizePane(options);
    const [handle] = handleOf(state.pane);
    drag(handle, 400, 480);
    handle.fire("dblclick");
    assert.equal(state.pane.styles.has("flex"), false);
    assert.equal(state.pane.styles.has("max-width"), false);
    assert.deepEqual(writes, [460, null]);
  }));

test("the handle is added once however often the page changes, and is added to a pane the page replaces", () =>
  scenario(({ state, container, options }) => {
    forgejoPage.resizePane(options);
    fireObservers();
    fireObservers();
    assert.equal(handleOf(state.pane).length, 1);
    const [handle] = handleOf(state.pane);
    handle.fire("pointerdown", { clientX: 400 });
    handle.fire("pointermove", { clientX: 500 });
    handle.fire("pointerup");
    const replaced = element();
    state.pane.remove();
    state.pane = replaced;
    container.append(replaced);
    fireObservers();
    fireObservers();
    assert.equal(handleOf(replaced).length, 1);
    assert.equal(replaced.styles.get("flex"), "0 0 480px");
  }));

test("a pane that is not in the page yet gets its handle once it appears", () =>
  scenario(({ state, container, options }) => {
    const present = state.pane;
    present.remove();
    state.pane = null;
    forgejoPage.resizePane(options);
    state.pane = present;
    container.append(present);
    fireObservers();
    assert.equal(handleOf(present).length, 1);
  }));

test("stopping removes the handle and the width", () =>
  scenario(({ state, options }) => {
    const stop = forgejoPage.resizePane(options);
    drag(handleOf(state.pane)[0], 400, 480);
    stop();
    assert.equal(handleOf(state.pane).length, 0);
    assert.equal(state.pane.styles.has("flex"), false);
    assert.equal(FakeObserver.all.some((observer) => observer.connected), false);
  }));

test("the handle is as tall as the pane's visible area", () =>
  scenario(({ state, options }) => {
    forgejoPage.resizePane(options);
    assert.equal(handleOf(state.pane)[0].styles.get("--prf-pane-handle-height"), "800px");
  }));

test("GitHub has a divider of its own and its pane gets no handle", () =>
  scenario(({ state, options }) => {
    assert.equal(githubPage.nativeResize, true);
    assert.equal(forgejoPage.nativeResize, false);
    const stop = githubPage.resizePane(options);
    assert.equal(handleOf(state.pane).length, 0);
    assert.equal(state.pane.styles.has("flex"), false);
    assert.equal(FakeObserver.all.length, 0);
    stop();
  }));

test("resizeHandle ignores other buttons, and reports no width for a drag that never moved", () =>
  scenario(() => {
    const calls = [];
    const handle = resizeHandle({
      className: "x",
      widthOf: () => 100,
      setWidth: (width) => calls.push(["set", width]),
      onStart: () => calls.push(["start"]),
      onEnd: (width) => calls.push(["end", width]),
    });
    handle.fire("pointerdown", { button: 2, clientX: 10 });
    handle.fire("pointerup");
    assert.deepEqual(calls, []);
    handle.fire("pointerdown", { clientX: 10 });
    handle.fire("pointerup");
    handle.fire("pointerdown", { clientX: 10 });
    handle.fire("pointermove", { clientX: 35 });
    handle.fire("pointercancel");
    assert.deepEqual(calls, [["start"], ["end", null], ["start"], ["set", 125], ["end", 125]]);
    assert.equal(handle.listeners.has("dblclick"), false);
  }));
