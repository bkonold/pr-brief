const test = require("node:test");
const assert = require("node:assert/strict");

const githubPage = require("../github_page.js");
const forgejoPage = require("../forgejo_page.js");
const { createPage } = require("../page_common.js");

class Node {
  constructor(name) {
    this.name = name;
    this.children = [];
    this.parentElement = null;
    this.classes = new Set();
    this.moves = 0;
    this.classList = {
      add: (value) => this.classes.add(value),
      remove: (value) => this.classes.delete(value),
      toggle: (value, on) => (on ? this.classes.add(value) : this.classes.delete(value)),
      contains: (value) => this.classes.has(value),
    };
  }
  get firstElementChild() {
    return this.children[0] ?? null;
  }
  adopt(node) {
    node.remove();
    node.parentElement = this;
    node.moves += 1;
  }
  contains(other) {
    return other === this || this.children.some((child) => child.contains(other));
  }
  prepend(node) {
    this.adopt(node);
    this.children.unshift(node);
  }
  append(node) {
    this.adopt(node);
    this.children.push(node);
  }
  remove() {
    if (this.parentElement) this.parentElement.children = this.parentElement.children.filter((child) => child !== this);
    this.parentElement = null;
  }
}

class FakeObserver {
  static all = [];
  constructor(callback) {
    this.callback = callback;
    this.targets = [];
    this.connected = true;
    FakeObserver.all.push(this);
  }
  observe(target) {
    this.targets.push(target);
  }
  disconnect() {
    this.connected = false;
  }
  takeRecords() {
    return [];
  }
}

const live = () => FakeObserver.all.filter((observer) => observer.connected);
const fire = () => live().forEach((observer) => observer.callback([]));

function paneFixture(initialHost) {
  const body = new Node("body");
  const state = { host: initialHost };
  FakeObserver.all = [];
  globalThis.document = { body, querySelectorAll: () => [] };
  globalThis.MutationObserver = FakeObserver;
  const page = createPage({ name: "Test", blockSelector: "block", paneHost: () => state.host, findRow: () => null, entryOf: (block) => block, diffId: async (path) => path });
  return { body, state, page };
}

function hostWith(...names) {
  const parent = new Node("parent");
  const host = new Node("host");
  parent.append(host);
  const kids = names.map((name) => {
    const kid = new Node(name);
    host.append(kid);
    return kid;
  });
  return { parent, host, kids };
}

const names = (node) => node.children.map((child) => child.name);
const hidden = (nodes) => nodes.map((node) => node.classes.has("prf-pane-hidden"));

test.afterEach(() => {
  delete globalThis.document;
  delete globalThis.MutationObserver;
});

test("each host's paneHost is its file tree's pane: GitHub's by id alone, Forgejo's by its structural classes", () => {
  const asked = [];
  const pane = { id: "pane" };
  globalThis.document = {
    getElementById: (id) => (asked.push(["id", id]), id === "pr-file-tree" ? pane : {}),
    querySelector: (selector) => (asked.push(["query", selector]), pane),
  };
  assert.equal(githubPage.paneHost(), pane);
  assert.deepEqual(asked, [["id", "pr-file-tree"]]);
  asked.length = 0;
  assert.equal(forgejoPage.paneHost(), pane);
  assert.deepEqual(asked.at(-1), ["query", "#diff-file-tree > .diff-file-tree-items"]);
  globalThis.document = { getElementById: (id) => (id === "pr-file-tree" ? null : {}), querySelector: () => null };
  assert.equal(githubPage.paneHost(), null);
  assert.equal(forgejoPage.paneHost(), null);
});

test("mount puts the panel first in the pane host and hides the host's other children, and unmount restores them", () => {
  const { host, kids } = hostWith("tree", "footer");
  const { page } = paneFixture(host);
  const panel = new Node("panel");
  page.mount(panel);
  assert.deepEqual(names(host), ["panel", "tree", "footer"]);
  assert.deepEqual(hidden([panel, ...kids]), [false, true, true]);
  page.unmount();
  assert.deepEqual(names(host), ["tree", "footer"]);
  assert.deepEqual(hidden(kids), [false, false]);
});

test("mount with hideRest false leaves the host's children showing", () => {
  const { host, kids } = hostWith("tree");
  const { page } = paneFixture(host);
  page.mount(new Node("bar"), { hideRest: false });
  assert.deepEqual([names(host), hidden(kids)], [["bar", "tree"], [false]]);
});

test("mounting again keeps the panel in place, and a different panel replaces the first", () => {
  const { host, kids } = hostWith("tree");
  const { page } = paneFixture(host);
  const first = new Node("first");
  page.mount(first);
  page.mount(first);
  assert.equal(first.moves, 1);
  const second = new Node("second");
  page.mount(second, { hideRest: false });
  assert.deepEqual([names(host), hidden(kids)], [["second", "tree"], [false]]);
  assert.deepEqual(live().length, 1);
});

test("a host with no pane gets the panel floating at the page's edge, and it moves into the pane when one appears", () => {
  const { body, state, page } = paneFixture(null);
  const panel = new Node("panel");
  page.mount(panel);
  assert.deepEqual([names(body), panel.classes.has("prf-pane-float")], [["panel"], true]);
  const { host, kids } = hostWith("tree");
  state.host = host;
  fire();
  assert.deepEqual([names(host), names(body), panel.classes.has("prf-pane-float"), hidden(kids)], [["panel", "tree"], [], false, [true]]);
});

test("a pane that re-renders drops the panel and adds children of its own; the panel returns first and the new child is hidden", () => {
  const { host, kids } = hostWith("tree");
  const { page } = paneFixture(host);
  const panel = new Node("panel");
  page.mount(panel);
  panel.remove();
  const later = new Node("later");
  host.append(later);
  fire();
  assert.deepEqual([names(host), hidden([panel, ...kids, later])], [["panel", "tree", "later"], [false, true, true]]);
});

test("the remount does not trigger itself: a pass that finds the panel in place moves nothing", () => {
  const { host } = hostWith("tree");
  const { page } = paneFixture(host);
  const panel = new Node("panel");
  page.mount(panel);
  fire();
  fire();
  assert.equal(panel.moves, 1);
});

test("a replaced pane host takes the panel, gives back what it hid and is watched in place of the old one", () => {
  const old = hostWith("tree");
  const { state, page } = paneFixture(old.host);
  const panel = new Node("panel");
  page.mount(panel);
  const next = hostWith("fresh");
  state.host = next.host;
  fire();
  assert.deepEqual([names(next.host), hidden(old.kids), hidden(next.kids), live().length], [["panel", "fresh"], [false], [true], 1]);
  assert.deepEqual(live()[0].targets, [next.host, next.parent]);
});

test("unmount stops watching the pane, and nothing is put back after it", () => {
  const { host } = hostWith("tree");
  const { page } = paneFixture(host);
  const panel = new Node("panel");
  page.mount(panel);
  page.unmount();
  assert.equal(live().length, 0);
  fire();
  assert.deepEqual(names(host), ["tree"]);
  page.unmount();
});

test("a page without MutationObserver still mounts and unmounts", () => {
  const { host } = hostWith("tree");
  const { page } = paneFixture(host);
  delete globalThis.MutationObserver;
  const panel = new Node("panel");
  page.mount(panel);
  page.unmount();
  assert.deepEqual(names(host), ["tree"]);
});

class Row {
  constructor(href, ...inside) {
    Object.assign(this, { href, inside, hidden: false });
    this.classList = { toggle: (_name, on) => (this.hidden = Boolean(on)), contains: () => this.hidden };
  }
  matches() {
    return false;
  }
  contains(other) {
    return other === this || this.inside.includes(other);
  }
  querySelector() {
    return this.href ? { getAttribute: () => this.href } : null;
  }
}

function treeFixture(links, { page: extra = {}, host: hostOptions = {} } = {}) {
  const files = links.map((href) => new Row(href));
  const dir = new Row(null, ...files);
  const host = new Node("host");
  host.querySelectorAll = (selector) => (selector === "file" ? files : selector === "dir" ? [dir] : []);
  Object.assign(host, hostOptions);
  const state = { host };
  const blocks = [];
  FakeObserver.all = [];
  globalThis.document = { body: new Node("body"), querySelectorAll: (selector) => (selector === "block" ? blocks : []) };
  globalThis.MutationObserver = FakeObserver;
  const asked = [];
  const page = createPage({
    name: "Test",
    blockSelector: "block",
    treeFileSelector: "file",
    treeDirSelector: "dir",
    paneHost: () => state.host,
    findRow: () => null,
    entryOf: (block) => block,
    diffId: async (path) => (asked.push(path), `diff-${path}`),
    ...extra,
  });
  return { files, dir, host, state, page, asked };
}

test("filter with files hides the tree's file rows outside the set and a directory left empty, and shows them all for null", async () => {
  const { files, dir, page } = treeFixture(["#diff-a", "#diff-b", "https://host/pull/1/files#diff-c"]);
  await page.filter({ files: ["a", "c"] });
  assert.deepEqual([files.map((row) => row.hidden), dir.hidden], [[false, true, false], false]);
  await page.filter({ files: ["b"] });
  assert.deepEqual(files.map((row) => row.hidden), [true, false, true]);
  await page.filter({ files: ["zzz"] });
  assert.equal(dir.hidden, true);
  await page.filter({ files: null });
  assert.deepEqual([...files, dir].map((row) => row.hidden), [false, false, false, false]);
});

test("filter with exclude hides the tree rows of its files whatever the file filter keeps, and a directory left with none", async () => {
  const { files, dir, page } = treeFixture(["#diff-a", "#diff-b", "#diff-c"]);
  await page.filter({ exclude: ["b"] });
  assert.deepEqual([files.map((row) => row.hidden), dir.hidden], [[false, true, false], false]);
  await page.filter({ files: ["a", "b"], exclude: ["b"] });
  assert.deepEqual(files.map((row) => row.hidden), [false, true, true]);
  await page.filter({ files: ["a", "b"], exclude: ["a", "b", "c"] });
  assert.equal(dir.hidden, true);
  await page.filter();
  assert.deepEqual([...files, dir].map((row) => row.hidden), [false, false, false, false]);
});

test("the tree rows are filtered again after the host re-renders them, without asking for the ids again", async () => {
  const { files, page, asked } = treeFixture(["#diff-a", "#diff-b"]);
  await page.filter({ files: ["a"] });
  for (const row of files) row.hidden = false;
  await page.filter({ files: ["a"] });
  assert.deepEqual([files.map((row) => row.hidden), asked], [[false, true], ["a"]]);
});

test("a tree row with no diff link is left showing, and a directory whose files are not in the page is left alone", async () => {
  const { files, dir, page } = treeFixture([null, "#diff-b"]);
  await page.filter({ files: ["a"] });
  assert.deepEqual([files.map((row) => row.hidden), dir.hidden], [[false, true], false]);
  const bare = treeFixture([]);
  await bare.page.filter({ files: ["a"] });
  assert.equal(bare.dir.hidden, false);
});

test("a page with no pane host, or a host with no tree selector, leaves the tree alone", async () => {
  const none = treeFixture(["#diff-a"]);
  none.state.host = null;
  await none.page.filter({ files: ["zzz"] });
  assert.deepEqual(none.files.map((row) => row.hidden), [false]);
  const bare = treeFixture(["#diff-a"], { page: { treeFileSelector: undefined, treeDirSelector: undefined } });
  await bare.page.filter({ files: ["zzz"] });
  assert.deepEqual([bare.files.map((row) => row.hidden), bare.dir.hidden], [[false], false]);
});

test("the tree rows are looked up inside the pane host only, and never the panel mounted in it", async () => {
  const { files, host, page } = treeFixture(["#diff-a", "#diff-b"]);
  const decoy = new Node("decoy");
  const panel = new Node("panel");
  panel.append(decoy);
  const selected = host.querySelectorAll;
  host.querySelectorAll = (selector) => (selector === "file" ? [...selected(selector), decoy] : selected(selector));
  page.mount(panel, { hideRest: false });
  await page.filter({ files: ["a"] });
  assert.deepEqual([files.map((row) => row.hidden), decoy.classes.size], [[false, true], 0]);
});

test("a tree row, a directory row and anything holding one is structural", () => {
  const { page } = treeFixture([]);
  const element = (tag, ...inside) => {
    const node = { nodeType: 1, inside, matches: (selector) => selector.split(", ").includes(tag) };
    node.querySelector = (selector) => inside.find((child) => child.matches(selector)) ?? inside.map((child) => child.querySelector(selector)).find(Boolean) ?? null;
    return node;
  };
  assert.deepEqual([element("file"), element("dir"), element("div", element("span", element("file"))), element("div", element("button"))].map((node) => page.isStructural(node)), [true, true, true, false]);
  const noDirs = treeFixture([], { page: { treeDirSelector: undefined } }).page;
  assert.equal(noDirs.isStructural(element("dir")), false);
});
