const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// content.js runs on load, so it is loaded into a context of fakes: a page on `view` ("files" or "conversation"), a
// source that answers with `review`, and a tree, a diagram and a page that record what they are asked to do.
function loadContent({ view = "files", review = null, hash = "", stored = {}, local = {}, cardWidth = () => 0, pageOrder = [], owner = "brief", blocks = new Map(), pagePaths = [] }) {
  const navigations = [];
  const changes = [];
  const reviewArgs = [];
  const renders = [];
  const jumps = [];
  const fileJumps = [];
  const callouts = [];
  const emphasized = [];
  const centered = [];
  const centeredWith = [];
  const lineEvents = [];
  const diagramHandlers = [];
  const revealed = [];
  const boxes = [];
  const scrolled = [];
  const quiet = { depth: 0 };
  const filters = [];
  const hunkFilters = [];
  const excluded = [];
  const properties = {};
  const ownerChanges = [];
  const ownerSaved = [];
  const bars = [];
  const diagramRemoved = [];
  const countArgs = [];
  const measuring = { appended: [], removed: [], measured: 0 };
  const withBox = (card) =>
    Object.defineProperties(card, {
      style: { value: {} },
      getBoundingClientRect: { value: () => (measuring.measured++, { width: cardWidth(card) }) },
    });
  const fakeDocument = {
    createElement: () => ({ style: {}, children: [], append(...nodes) { this.children.push(...nodes); }, remove() { measuring.removed.push(this); } }),
    body: { append: (host) => measuring.appended.push(host) },
    documentElement: { style: { setProperty: (name, value) => (properties[name] = value) } },
  };
  const prFocus = {
    page: {
      name: "Fake",
      prFromUrl: () => ({ owner: "acme", repo: "widgets", pr: 7, view }),
      onNavigate: (callback) => (navigations.push(callback), () => {}),
      onChange: (callback) => (changes.push(callback), () => {}),
      cancelJump: () => lineEvents.push("cancelJump"),
      clearLineTarget: () => lineEvents.push("clearLineTarget"),
      fileBlocks: () => blocks,
      headSha: () => null,
      restoreLineTarget() {},
      ownsLine: (node) => Boolean(node?.owned),
      lineAnchor: async (path, side, line) => `${path}${side}${line}`,
      fileAnchor: async (path) => `diff-${path}`,
      firstInPage: async (paths) => pageOrder.find((path) => paths.includes(path)) ?? paths[0] ?? null,
      showCallouts: (entries) => callouts.push(entries),
      filter: ({ files = null, hunks = null, exclude = null } = {}) => (filters.push(files), hunkFilters.push(hunks), excluded.push(exclude)),
      blockCount: () => 0,
      isStructural: (node) => Boolean(node.structural),
      quietly: (fn) => {
        quiet.depth += 1;
        try {
          return fn();
        } finally {
          quiet.depth -= 1;
        }
      },
      changedFilePaths: (paths) => (countArgs.push(paths), [...new Set([...pagePaths, ...paths])]),
      jumpToLine: async (...args) => jumps.push(args),
      jumpToFile: async (...args) => fileJumps.push(args),
    },
    source: {
      loadReview: async (...args) => (reviewArgs.push(args), review),
      loadPaneOwner: async () => owner,
      savePaneOwner: async (next) => ownerSaved.push(next),
      onPaneOwnerChange: (callback) => (ownerChanges.push(callback), () => {}),
    },
    tree: {
      render: (shownReview, state, handlers) => renders.push({ review: shownReview, state, handlers, quiet: quiet.depth > 0 }),
      offBar: (counts, onShow) => bars.push({ counts, onShow }),
      briefPaths: require("../tree.js").briefPaths,
      stopsOf: require("../tree.js").stopsOf,
      chunksOf: require("../tree.js").chunksOf,
      fileChips: require("../tree.js").fileChips,
      fileSetOf: require("../tree.js").fileSetOf,
      testsOf: require("../tree.js").testsOf,
      isTestPath: require("../tree.js").isTestPath,
      testKind: require("../tree.js").testKind,
      hidesTestKind: require("../tree.js").hidesTestKind,
      widestWidth: require("../tree.js").widestWidth,
      stopCallout: (stop, stops, onGo, nodes) => withBox({ stop, stops, onGo, nodes }),
      chunkCallout: (chunk, chunks, onGo, onJudged, judged) => withBox({ chunk, chunks, onGo, onJudged, judged }),
      revealStop: (i) => revealed.push(i),
      revealChunk: (i) => revealed.push(`chunk ${i}`),
      remove() {},
      owns: () => false,
    },
    focus: { clearBox() {}, markBox: (paths) => boxes.push(paths), scrollTo: async (path) => scrolled.push(path), announceBox() {} },
    diagram: {
      render: (svg, handlers) => diagramHandlers.push(handlers),
      emphasize: (nodes) => emphasized.push(nodes),
      centerOn: (nodeIds, options) => (centered.push(nodeIds), centeredWith.push(options)),
      remove: () => diagramRemoved.push(true),
      owns: () => false,
    },
    alive: () => true,
  };
  const output = [];
  const consoleSpy = { log: (...a) => output.push(a), warn: (...a) => output.push(a), error: (...a) => output.push(a), info: (...a) => output.push(a), debug: (...a) => output.push(a) };
  const unref = (start) => (...args) => {
    const timer = start(...args);
    timer.unref?.();
    return timer;
  };
  const sessionStorage = { getItem: (key) => stored[key] ?? null, setItem: (key, value) => (stored[key] = value) };
  const localStorage = { getItem: (key) => local[key] ?? null, setItem: (key, value) => (local[key] = value) };
  const context = { prFocus, sessionStorage, localStorage, location: { href: "x", host: "forge.example", hash }, console: consoleSpy, setTimeout: unref(setTimeout), clearTimeout, setInterval: unref(setInterval), clearInterval, Date, Promise, document: fakeDocument };
  context.globalThis = context;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../content.js"), "utf8"), context);
  return { reviewArgs, changes, navigations, output, renders, jumps, fileJumps, callouts, emphasized, centered, centeredWith, lineEvents, stored, diagramHandlers, revealed, boxes, scrolled, filters, hunkFilters, excluded, local, properties, measuring, ownerChanges, ownerSaved, bars, diagramRemoved, countArgs };
}

const plain = (value) => JSON.parse(JSON.stringify(value));
const settle = () => new Promise((resolve) => setImmediate(resolve));
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test("the callouts are shown in the review and removed in the host's own tree view", async () => {
  const { renders, callouts } = loadContent({ review: WALK_REVIEW });
  await settle();
  assert.equal(callouts.at(-1).length, 4);
  await renders.at(-1).handlers.onMode("files");
  assert.deepEqual(plain(callouts.at(-1)), []);
});

async function loadWalkthrough(review = WALK_REVIEW) {
  const loaded = loadContent({ review });
  await settle();
  await loaded.renders.at(-1).handlers.onMode("review");
  return loaded;
}

const WALK_REVIEW = {
  schema: 4,
  repo: "acme/widgets",
  pr: 7,
  variant: "brief",
  diagramSvg: "<svg></svg>",
  nodes: {
    a: { title: "Screen", files: ["src/ui.js"], stops: [1, 3] },
    b: { title: "Endpoint", files: ["src/api.js"], stops: [4] },
    c: { title: "Table", files: ["db/V1.sql"], stops: [2] },
    d: { title: "Search index", files: [], stops: [] },
  },
  walkthrough: [
    { i: 1, title: "List is built", why: "Entry point.", path: "src/ui.js", side: "R", line: 4, node: "a" },
    { i: 2, title: "Query filters", why: "The call lands here.", path: "db/V1.sql", side: "R", line: 2, node: "c" },
    { i: 3, title: "Back to the screen", why: "It renders here.", path: "src/ui.js", side: "R", line: 30, node: "a" },
    { i: 4, title: "The whole endpoint", why: "No single line.", path: "src/api.js", side: null, line: null, node: "b" },
  ],
};

test("a walkthrough run has a callout for every stop and a file stop anchored at its file's diff", async () => {
  const { callouts } = await loadWalkthrough();
  assert.deepEqual(
    callouts.at(-1).map((entry) => [entry.key, entry.anchor, entry.file ?? false]),
    [[1, "src/ui.jsR4", false], [2, "db/V1.sqlR2", false], [3, "src/ui.jsR30", false], [4, "diff-src/api.js", true]],
  );
  const { stop, stops, nodes } = callouts.at(-1)[1].render();
  assert.deepEqual([stop.i, stops.length, Object.keys(nodes)], [2, 4, ["a", "b", "c", "d"]]);
});

test("walking the stops with a callout's buttons gives each stop's box the halo and centres on it", async () => {
  const { callouts, jumps, fileJumps, centered, emphasized } = await loadWalkthrough();
  const { onGo, stops } = callouts.at(-1)[0].render();
  const walked = [];
  for (const stop of stops) {
    await onGo(stop);
    walked.push([stop.i, emphasized.at(-1), centered.at(-1)]);
  }
  assert.deepEqual(plain(walked), [
    [1, ["a"], ["a"]],
    [2, ["c"], ["c"]],
    [3, ["a"], ["a"]],
    [4, ["b"], ["b"]],
  ]);
  assert.equal(JSON.stringify(jumps), JSON.stringify([["src/ui.js", "R", 4, { pulse: false }], ["db/V1.sql", "R", 2, { pulse: false }], ["src/ui.js", "R", 30, { pulse: false }]]));
  assert.equal(JSON.stringify(fileJumps), JSON.stringify([["src/api.js"]]));
});

test("a stop on no box selects no box but still jumps there", async () => {
  const outside = { ...WALK_REVIEW, walkthrough: [{ i: 1, title: "Docs", why: "w", path: "docs/readme.md", side: "R", line: 3, node: null }] };
  const { callouts, jumps, renders, emphasized, centered } = await loadWalkthrough(outside);
  jumps.length = 0;
  await callouts.at(-1)[0].render().onGo(outside.walkthrough[0]);
  assert.equal(JSON.stringify(jumps), JSON.stringify([["docs/readme.md", "R", 3, { pulse: false }]]));
  assert.deepEqual(plain([renders.at(-1).state.selectedStop, emphasized.at(-1), centered]), [1, null, []]);
});

test("clicking Previous or Next quickly ends at the last stop clicked, jumping only there", async () => {
  const { callouts, jumps, emphasized } = await loadWalkthrough();
  const { onGo, stops } = callouts.at(-1)[0].render();
  await Promise.all([onGo(stops[1]), onGo(stops[2])]);
  assert.equal(JSON.stringify(jumps), JSON.stringify([["src/ui.js", "R", 30, { pulse: false }]]));
  assert.deepEqual(plain(emphasized.at(-1)), ["a"]);
});

test("opening the files page on a stop's diff anchor goes to that stop", async () => {
  const { fileJumps, emphasized, renders } = loadContent({ review: WALK_REVIEW, hash: "#diff-src/api.js" });
  await settle();
  assert.deepEqual([renders.at(-1).state.mode, renders.at(-1).state.selectedStop], ["review", 4]);
  assert.deepEqual(fileJumps, [["src/api.js"]]);
  assert.deepEqual(plain(emphasized.at(-1)), ["b"]);
});

test("the sidebar opens in the walkthrough with every stop listed and none current", async () => {
  const { renders, emphasized } = loadContent({ review: WALK_REVIEW });
  await settle();
  const { state } = renders.at(-1);
  assert.deepEqual([state.stops.map((stop) => stop.i), state.mode, state.selectedStop], [[1, 2, 3, 4], "review", null]);
  assert.deepEqual(Object.keys(state).sort(), ["chips", "chunks", "fileSet", "hiddenFiles", "judged", "mode", "note", "pageSha", "selectedChunk", "selectedStop", "stops", "tests", "testsMode"]);
  assert.deepEqual(plain(emphasized.filter((nodes) => nodes !== null)), []);
});

test("a fresh load selects nothing: the walkthrough, no jump, no pan and no emphasis", async () => {
  const { renders, emphasized, centered, revealed, jumps, fileJumps, callouts } = loadContent({ review: WALK_REVIEW });
  await settle();
  assert.deepEqual(plain([renders.at(-1).state.mode, renders.at(-1).state.selectedStop, emphasized.filter((nodes) => nodes !== null), centered, revealed, jumps, fileJumps]), ["review", null, [], [], [], [], []]);
  assert.equal(callouts.at(-1).length, 4);
});

test("a page URL naming a diff line other than a stop's selects nothing and jumps nowhere", async () => {
  for (const hash of ["#diff-abc123R7", "#r123456", "#discussion_r98765"]) {
    const { renders, emphasized, centered, jumps, fileJumps } = loadContent({ review: WALK_REVIEW, hash });
    await settle();
    assert.deepEqual(plain([renders.at(-1).state.selectedStop, emphasized.filter((nodes) => nodes !== null), centered, jumps, fileJumps]), [null, [], [], [], []], hash);
  }
});

test("a fragment that names no diff line does not make the load jump", async () => {
  const { jumps, fileJumps } = loadContent({ review: WALK_REVIEW, hash: "#files_bucket" });
  await settle();
  assert.deepEqual([jumps, fileJumps], [[], []]);
});

test("choosing a stop in the list goes to it and makes it the current stop", async () => {
  const { renders, jumps, revealed, emphasized } = loadContent({ review: WALK_REVIEW });
  await settle();
  jumps.length = 0;
  revealed.length = 0;
  await renders.at(-1).handlers.onSelectStop(3);
  assert.deepEqual(jumps.map((jump) => jump.slice(0, 3)), [["src/ui.js", "R", 30]]);
  assert.deepEqual(revealed, [3]);
  assert.deepEqual(plain([renders.at(-1).state.selectedStop, emphasized.at(-1)]), [3, ["a"]]);
});

test("a reload lands in the walkthrough with nothing selected, whatever was selected before, and nothing is remembered", async () => {
  const first = loadContent({ review: WALK_REVIEW });
  await settle();
  await first.renders.at(-1).handlers.onSelectStop(3);
  first.diagramHandlers.at(-1).onNode("b");
  await settle();
  await first.renders.at(-1).handlers.onMode("files");
  assert.deepEqual(plain(first.stored), {});
  const again = loadContent({ review: WALK_REVIEW, stored: first.stored });
  await settle();
  assert.deepEqual(plain([again.renders.at(-1).state.mode, again.renders.at(-1).state.selectedStop, again.emphasized.at(-1), again.centered]), ["review", null, null, []]);
});

test("every action that focuses a box centres the diagram on it", async () => {
  const { renders, callouts, centered, diagramHandlers } = loadContent({ review: WALK_REVIEW });
  await settle();
  assert.deepEqual(plain(centered), []);
  diagramHandlers.at(-1).onNode("b");
  await settle();
  assert.deepEqual(plain(centered), [["b"]]);
  await renders.at(-1).handlers.onSelectStop(2);
  assert.deepEqual(plain(centered.at(-1)), ["c"]);
  const { onGo, stops } = callouts.at(-1)[0].render();
  await onGo(stops[2]);
  assert.deepEqual(plain(centered.at(-1)), ["a"]);
  await renders.at(-1).handlers.onMode("files");
  assert.deepEqual(plain(centered.at(-1)), ["a"]);
});

test("every way into a stop zooms the diagram to it, and a click on a diagram box only pans", async () => {
  const { renders, callouts, centeredWith, diagramHandlers } = loadContent({ review: WALK_REVIEW });
  await settle();
  assert.deepEqual(plain(centeredWith), []);
  await renders.at(-1).handlers.onSelectStop(3);
  const { onGo, stops } = callouts.at(-1)[0].render();
  await onGo(stops[3]);
  await onGo(stops[0]);
  assert.deepEqual(plain(centeredWith), [{ zoom: true }, { zoom: true }, { zoom: true }]);
  centeredWith.length = 0;
  diagramHandlers.at(-1).onNode("b");
  await settle();
  assert.deepEqual(plain(centeredWith), [{ zoom: false }]);
});

test("opening a stop's anchor zooms to it", async () => {
  const linked = loadContent({ review: WALK_REVIEW, hash: "#diff-src/api.js" });
  await settle();
  assert.deepEqual(plain([linked.centered, linked.centeredWith]), [[["b"]], [{ zoom: true }]]);
});

test("the diagram's Reset clears the selection and keeps the pane's mode: nothing selected and no box marked", async () => {
  const { renders, callouts, emphasized, lineEvents, diagramHandlers } = loadContent({ review: WALK_REVIEW });
  await settle();
  diagramHandlers.at(-1).onNode("c");
  await settle();
  await renders.at(-1).handlers.onSelectStop(2);
  assert.deepEqual(renders.at(-1).state.selectedStop, 2);

  lineEvents.length = 0;
  const shownBefore = callouts.length;
  diagramHandlers.at(-1).onReset();
  await settle();
  const { state } = renders.at(-1);
  assert.deepEqual([state.mode, state.selectedStop], ["review", null]);
  assert.equal(emphasized.at(-1), null);
  assert.deepEqual(lineEvents.slice(0, 2), ["cancelJump", "clearLineTarget"]);
  assert.equal(callouts.length > shownBefore, true);
});

test("Reset leaves a mode of GitHub's own tree in place", async () => {
  const { renders, emphasized, diagramHandlers } = loadContent({ review: WALK_REVIEW });
  await settle();
  diagramHandlers.at(-1).onNode("b");
  await settle();
  await renders.at(-1).handlers.onMode("files");
  assert.equal(renders.at(-1).state.mode, "files");
  assert.equal(emphasized.at(-1), null);
  diagramHandlers.at(-1).onReset();
  await settle();
  assert.equal(renders.at(-1).state.mode, "files");
  diagramHandlers.at(-1).onNode("b");
  await settle();
  assert.deepEqual(plain(emphasized.at(-1)), ["b"]);
});

const NO_STOP_REVIEW = {
  ...WALK_REVIEW,
  nodes: { ...WALK_REVIEW.nodes, b: { ...WALK_REVIEW.nodes.b, stops: [] } },
  walkthrough: WALK_REVIEW.walkthrough.filter((stop) => stop.node !== "b"),
};

test("a diagram box click goes to the first stop on that box, jumping again on every click", async () => {
  const { jumps, diagramHandlers, renders, revealed } = loadContent({ review: WALK_REVIEW });
  await settle();
  for (const click of [1, 2]) {
    jumps.length = 0;
    diagramHandlers.at(-1).onNode("a");
    await settle();
    assert.deepEqual(jumps, [["src/ui.js", "R", 4, undefined]], `click ${click}`);
    assert.deepEqual([renders.at(-1).state.selectedStop, revealed.at(-1)], [1, 1]);
  }
});

test("a box with files and no stop scrolls to its first file header and marks it", async () => {
  const { jumps, fileJumps, diagramHandlers, renders, scrolled, boxes, emphasized } = loadContent({ review: NO_STOP_REVIEW });
  await settle();
  jumps.length = 0;
  diagramHandlers.at(-1).onNode("b");
  await settle();
  assert.deepEqual([jumps, fileJumps, scrolled], [[], [], ["src/api.js"]]);
  assert.deepEqual(plain([boxes.at(-1), emphasized.at(-1)]), [["src/api.js"], ["b"]]);
  assert.deepEqual([renders.at(-1).state.selectedStop, renders.at(-1).state.stops.map((stop) => stop.node)], [null, ["a", "c", "a"]]);
});

test("a box with a stop after a stop-less one clears the current stop only when it has none", async () => {
  const { diagramHandlers, renders } = loadContent({ review: NO_STOP_REVIEW });
  await settle();
  await renders.at(-1).handlers.onSelectStop(1);
  assert.equal(renders.at(-1).state.selectedStop, 1);
  diagramHandlers.at(-1).onNode("b");
  await settle();
  assert.equal(renders.at(-1).state.selectedStop, null);
  diagramHandlers.at(-1).onNode("c");
  await settle();
  assert.equal(renders.at(-1).state.selectedStop, 2);
});

test("a context box, which covers no file, and a box the review does not list do nothing", async () => {
  const { jumps, scrolled, diagramHandlers, renders } = loadContent({ review: WALK_REVIEW });
  await settle();
  const before = renders.length;
  jumps.length = 0;
  diagramHandlers.at(-1).onNode("d");
  diagramHandlers.at(-1).onNode("zzz");
  await settle();
  assert.deepEqual([jumps, scrolled, renders.length], [[], [], before]);
});

test("the sidebar's state and handlers are the stops and the mode", async () => {
  const { renders } = loadContent({ review: WALK_REVIEW });
  await settle();
  assert.deepEqual(Object.keys(renders.at(-1).handlers).sort(), ["onFileSet", "onJudged", "onMode", "onPaneOwner", "onSelectChunk", "onSelectFileInChunk", "onSelectStop", "onTestsMode"]);
});

const SET_REVIEW = {
  ...WALK_REVIEW,
  file_sets: { contract: ["src/api.js", "api.json"], data: [] },
};

test("the chips are All with the page's changed-file count and each non-empty set, and the whole tree shows until one is chosen", async () => {
  const { renders, filters } = loadContent({ review: SET_REVIEW, pagePaths: ["p1", "p2", "p3", "p4", "p5"] });
  await settle();
  assert.deepEqual(plain(renders.at(-1).state.chips), [
    { id: "all", label: "All", count: 9 },
    { id: "contract", label: "API", count: 2 },
  ]);
  assert.equal(renders.at(-1).state.fileSet, null);
  assert.equal(filters.at(-1), null);
});

test("choosing a chip narrows the pane and the tree to the set without moving the diagram, and All restores them", async () => {
  const { renders, filters, centered, jumps, fileJumps } = loadContent({ review: SET_REVIEW });
  await settle();
  await renders.at(-1).handlers.onSelectStop(1);
  centered.length = 0;
  jumps.length = 0;
  await renders.at(-1).handlers.onFileSet("contract");
  assert.deepEqual(plain(renders.at(-1).state.fileSet), { id: "contract", paths: ["src/api.js", "api.json"] });
  assert.deepEqual(plain(filters.at(-1)), ["src/api.js", "api.json"]);
  assert.deepEqual([centered, jumps, fileJumps, renders.at(-1).state.selectedStop], [[], [], [], 1]);
  await renders.at(-1).handlers.onFileSet("all");
  assert.equal(renders.at(-1).state.fileSet, null);
  assert.equal(filters.at(-1), null);
});

test("switching the mode keeps the chip and its filter", async () => {
  const { renders, filters } = loadContent({ review: SET_REVIEW });
  await settle();
  await renders.at(-1).handlers.onFileSet("contract");
  await renders.at(-1).handlers.onMode("review");
  assert.equal(renders.at(-1).state.fileSet.id, "contract");
  assert.deepEqual(plain(filters.at(-1)), ["src/api.js", "api.json"]);
  await renders.at(-1).handlers.onMode("files");
  assert.equal(renders.at(-1).state.fileSet.id, "contract");
  assert.deepEqual(plain(filters.at(-1)), ["src/api.js", "api.json"]);
});

test("selecting a stop in a file the chip hides puts the chip back on All, and a stop in the set keeps it", async () => {
  const { renders, filters } = loadContent({ review: SET_REVIEW });
  await settle();
  await renders.at(-1).handlers.onFileSet("contract");
  await renders.at(-1).handlers.onSelectStop(4);
  assert.equal(renders.at(-1).state.fileSet.id, "contract");
  assert.deepEqual(plain(filters.at(-1)), ["src/api.js", "api.json"]);
  await renders.at(-1).handlers.onSelectStop(1);
  assert.equal(renders.at(-1).state.fileSet, null);
  assert.equal(filters.at(-1), null);
});

const CHUNK_HEAD = "c".repeat(40);
const CHUNK_REVIEW = {
  ...WALK_REVIEW,
  head_sha: CHUNK_HEAD,
  chunks: [
    {
      i: 1,
      title: "Screen and table",
      summary: "s",
      risk: "low",
      risk_reason: "",
      depends_on: [],
      hunks: [
        { id: "h1", path: "src/ui.js", change: "modified", old: [4, 3], new: [4, 5] },
        { id: "h2", path: "db/V1.sql", change: "added", old: [0, 0], new: [1, 6] },
      ],
    },
    { i: 2, title: "Old endpoint goes", summary: "s", risk: "high", risk_reason: "r", depends_on: [1], hunks: [{ id: "h3", path: "src/old.js", change: "deleted", old: [1, 20], new: [0, 0] }] },
    { i: 3, title: "Pure deletion", summary: "s", risk: "medium", risk_reason: "", depends_on: [], hunks: [{ id: "h4", path: "src/ui.js", change: "modified", old: [40, 2], new: [39, 0] }] },
  ],
};
const JUDGED_KEY = `prf-judged:forge.example/acme/widgets#7@${CHUNK_HEAD}`;

async function loadChunks(options = {}) {
  const loaded = loadContent({ review: CHUNK_REVIEW, ...options });
  await settle();
  return loaded;
}

test("selecting a chunk shows the chunks tab, narrows the page to the chunk's lines and lands on its callout above the file", async () => {
  const { renders, hunkFilters, filters, jumps, fileJumps, callouts, revealed, emphasized } = await loadChunks();
  await renders.at(-1).handlers.onSelectChunk(1);
  const { state } = renders.at(-1);
  assert.deepEqual([state.mode, state.selectedChunk, state.selectedStop, state.chunks.length], ["chunks", 1, null, 3]);
  assert.deepEqual(plain(hunkFilters.at(-1)), [
    { path: "src/ui.js", side: "R", start: 4, count: 5 },
    { path: "src/ui.js", side: "L", start: 4, count: 3 },
    { path: "db/V1.sql", side: "R", start: 1, count: 6 },
  ]);
  assert.equal(filters.at(-1), null);
  assert.deepEqual([jumps, fileJumps], [[], [["src/ui.js"]]]);
  assert.deepEqual(callouts.at(-1).map((entry) => [entry.key, entry.anchor, entry.file]), [["chunk:1", "diff-src/ui.js", true]]);
  assert.deepEqual([revealed.at(-1), emphasized.at(-1)], ["chunk 1", null]);
});

test("a deleted file, and a hunk with no new lines, narrow to old lines and put the callout above their file", async () => {
  const { renders, hunkFilters, fileJumps, callouts } = await loadChunks();
  await renders.at(-1).handlers.onSelectChunk(2);
  assert.deepEqual(plain(hunkFilters.at(-1)), [{ path: "src/old.js", side: "L", start: 1, count: 20 }]);
  assert.deepEqual(callouts.at(-1).map((entry) => entry.anchor), ["diff-src/old.js"]);
  await renders.at(-1).handlers.onSelectChunk(3);
  assert.deepEqual(plain(hunkFilters.at(-1)), [{ path: "src/ui.js", side: "L", start: 40, count: 2 }]);
  assert.deepEqual(fileJumps, [["src/old.js"], ["src/ui.js"]]);
});

test("the chunk callout's buttons open a chunk, and a chunk number that does not exist does nothing", async () => {
  const { renders, callouts, fileJumps } = await loadChunks();
  await renders.at(-1).handlers.onSelectChunk(1);
  const { onGo, chunks, judged } = callouts.at(-1)[0].render();
  assert.deepEqual([chunks.length, judged], [3, false]);
  await onGo(2);
  assert.deepEqual(plain(fileJumps.at(-1)), ["src/old.js"]);
  assert.equal(renders.at(-1).state.selectedChunk, 2);
  const shown = fileJumps.length;
  await onGo(99);
  assert.deepEqual([fileJumps.length, renders.at(-1).state.selectedChunk], [shown, 2]);
});

test("a file in the selected chunk jumps to its first hunk there, leaving the tab and the filter as they are", async () => {
  const { renders, hunkFilters, jumps } = await loadChunks();
  await renders.at(-1).handlers.onSelectChunk(1);
  const filter = hunkFilters.at(-1);
  const shown = jumps.length;
  await renders.at(-1).handlers.onSelectFileInChunk(1, "db/V1.sql");
  assert.deepEqual(jumps.slice(shown).map((jump) => jump.slice(0, 3)), [["db/V1.sql", "R", 1]]);
  assert.deepEqual([renders.at(-1).state.mode, renders.at(-1).state.selectedChunk, hunkFilters.at(-1) === filter], ["chunks", 1, true]);
});

test("a file of a chunk with no new lines in its first hunk there lands on the old side, and a path the chunk does not touch does nothing", async () => {
  const { renders, jumps } = await loadChunks();
  await renders.at(-1).handlers.onSelectChunk(3);
  const shown = jumps.length;
  await renders.at(-1).handlers.onSelectFileInChunk(3, "src/ui.js");
  assert.deepEqual(jumps.slice(shown).map((jump) => jump.slice(0, 3)), [["src/ui.js", "L", 40]]);
  await renders.at(-1).handlers.onSelectFileInChunk(3, "src/other.js");
  assert.equal(jumps.length, shown + 1);
});

test("a file of another chunk selects that chunk first, narrowing the page, then jumps to the file's first hunk", async () => {
  const { renders, hunkFilters, jumps, fileJumps } = await loadChunks();
  await renders.at(-1).handlers.onSelectChunk(1);
  await renders.at(-1).handlers.onSelectFileInChunk(2, "src/old.js");
  assert.deepEqual([renders.at(-1).state.mode, renders.at(-1).state.selectedChunk], ["chunks", 2]);
  assert.deepEqual(plain(hunkFilters.at(-1)), [{ path: "src/old.js", side: "L", start: 1, count: 20 }]);
  assert.deepEqual(fileJumps, [["src/ui.js"], ["src/old.js"]]);
  assert.deepEqual(jumps.map((jump) => jump.slice(0, 3)), [["src/old.js", "L", 1]]);
});

test("every mode other than chunks clears the hunk filter, and the chunks tab applies the selected chunk's again", async () => {
  const { renders, hunkFilters, filters, callouts } = await loadChunks();
  assert.equal(hunkFilters.at(-1), null);
  await renders.at(-1).handlers.onSelectChunk(1);
  await renders.at(-1).handlers.onMode("review");
  assert.equal(hunkFilters.at(-1), null);
  assert.equal(callouts.at(-1).length, 4);
  await renders.at(-1).handlers.onMode("chunks");
  assert.equal(hunkFilters.at(-1).length, 3);
  assert.deepEqual(callouts.at(-1).map((entry) => entry.key), ["chunk:1"]);
  await renders.at(-1).handlers.onMode("files");
  assert.deepEqual([hunkFilters.at(-1), callouts.at(-1).length], [null, 0]);
  await renders.at(-1).handlers.onMode("chunks");
  await renders.at(-1).handlers.onSelectStop(2);
  assert.deepEqual([renders.at(-1).state.mode, hunkFilters.at(-1), filters.at(-1)], ["review", null, null]);
});

test("the chunks tab with no chunk selected filters nothing and shows no callout", async () => {
  const { renders, hunkFilters, filters, callouts } = await loadChunks();
  await renders.at(-1).handlers.onMode("chunks");
  assert.deepEqual([renders.at(-1).state.mode, renders.at(-1).state.selectedChunk, hunkFilters.at(-1), filters.at(-1), callouts.at(-1)], ["chunks", null, null, null, []]);
});

test("selecting a box leaves the chunks tab and its hunk filter", async () => {
  const { renders, hunkFilters, diagramHandlers } = await loadChunks();
  await renders.at(-1).handlers.onSelectChunk(1);
  assert.equal(hunkFilters.at(-1).length, 3);
  diagramHandlers.at(-1).onNode("b");
  await settle();
  assert.deepEqual([renders.at(-1).state.mode, hunkFilters.at(-1)], ["review", null]);
});

test("selecting a chunk clears the stop, the chip and the box", async () => {
  const { renders, emphasized } = await loadChunks();
  await renders.at(-1).handlers.onSelectStop(1);
  await renders.at(-1).handlers.onSelectChunk(2);
  assert.deepEqual([renders.at(-1).state.selectedStop, renders.at(-1).state.fileSet, emphasized.at(-1)], [null, null, null]);
});

test("judging a chunk is kept in this browser for the PR's head, and read back on the next load", async () => {
  const first = await loadChunks();
  assert.deepEqual([...first.renders.at(-1).state.judged], []);
  await first.renders.at(-1).handlers.onJudged(2, true);
  await first.renders.at(-1).handlers.onJudged(1, true);
  assert.deepEqual([...first.renders.at(-1).state.judged].sort(), [1, 2]);
  assert.deepEqual(JSON.parse(first.local[JUDGED_KEY]), [1, 2]);
  await first.renders.at(-1).handlers.onJudged(2, false);
  assert.deepEqual(JSON.parse(first.local[JUDGED_KEY]), [1]);
  assert.deepEqual(plain(first.stored), {});
  const again = await loadChunks({ local: first.local });
  assert.deepEqual([...again.renders.at(-1).state.judged], [1]);
  const newHead = await loadChunks({ local: first.local, review: { ...CHUNK_REVIEW, head_sha: "d".repeat(40) } });
  assert.deepEqual([...newHead.renders.at(-1).state.judged], []);
});

test("an unreadable judged list is an empty one, and only chunk numbers are read from it", async () => {
  const garbled = await loadChunks({ local: { [JUDGED_KEY]: "{not json" } });
  assert.deepEqual([...garbled.renders.at(-1).state.judged], []);
  const wrong = await loadChunks({ local: { [JUDGED_KEY]: '{"a":1}' } });
  assert.deepEqual([...wrong.renders.at(-1).state.judged], []);
  const mixed = await loadChunks({ local: { [JUDGED_KEY]: '[1,"x",2.5,3]' } });
  assert.deepEqual([...mixed.renders.at(-1).state.judged], [1, 3]);
});

test("a run with no chunks passes none and has no chunk callout", async () => {
  const { renders, callouts } = loadContent({ review: WALK_REVIEW });
  await settle();
  await renders.at(-1).handlers.onMode("files");
  assert.deepEqual(plain(renders.at(-1).state.chunks), []);
  assert.deepEqual(plain(callouts.at(-1)), []);
});

const TESTS_KEY = "prf-tests-mode";
const TESTS_REVIEW = {
  ...CHUNK_REVIEW,
  file_sets: { contract: [], data: [], tests: ["db/V1.sql", "src/old.js"] },
  chunks: [
    ...CHUNK_REVIEW.chunks,
    {
      i: 4,
      title: "Test then code",
      summary: "s",
      risk: "low",
      risk_reason: "",
      depends_on: [],
      hunks: [
        { id: "h5", path: "db/V1.sql", change: "modified", old: [10, 2], new: [10, 3] },
        { id: "h6", path: "src/api.js", change: "modified", old: [5, 1], new: [5, 2] },
      ],
    },
  ],
};

async function loadTests(options = {}) {
  const loaded = loadContent({ review: TESTS_REVIEW, ...options });
  await settle();
  await loaded.renders.at(-1).handlers.onMode("files");
  return loaded;
}

test("the Tests mode starts at all, shows every file and passes the review's test files to the pane", async () => {
  const { renders, excluded, filters, hunkFilters } = await loadTests();
  assert.deepEqual([renders.at(-1).state.tests, renders.at(-1).state.testsMode], [["db/V1.sql", "src/old.js"], "all"]);
  assert.deepEqual([plain(excluded.at(-1)), filters.at(-1), hunkFilters.at(-1)], [null, null, null]);
});

test("a review with no test files lists none and shows every file whatever the stored mode", async () => {
  const { renders, excluded, filters } = loadContent({ review: WALK_REVIEW, local: { [TESTS_KEY]: "only" } });
  await settle();
  assert.deepEqual([renders.at(-1).state.tests, renders.at(-1).state.testsMode, plain(excluded.at(-1)), filters.at(-1)], [[], "all", null, null]);
  await renders.at(-1).handlers.onTestsMode("hide");
  assert.deepEqual([renders.at(-1).state.testsMode, plain(excluded.at(-1))], ["all", null]);
});

test("the Tests mode is saved as its string, read back on the next load, and an unknown value is ignored", async () => {
  const first = await loadTests();
  await first.renders.at(-1).handlers.onTestsMode("hide");
  assert.equal(first.local[TESTS_KEY], "hide");
  await first.renders.at(-1).handlers.onTestsMode("only");
  assert.equal(first.local[TESTS_KEY], "only");
  await first.renders.at(-1).handlers.onTestsMode("bogus");
  assert.deepEqual([first.local[TESTS_KEY], first.renders.at(-1).state.testsMode], ["only", "only"]);
  await first.renders.at(-1).handlers.onTestsMode("all");
  assert.equal(first.local[TESTS_KEY], "all");
  const again = await loadTests({ local: { [TESTS_KEY]: "hide" } });
  assert.deepEqual([again.renders.at(-1).state.testsMode, plain(again.excluded.at(-1))], ["hide", ["db/V1.sql", "src/old.js"]]);
  const garbled = await loadTests({ local: { [TESTS_KEY]: "nope" } });
  assert.equal(garbled.renders.at(-1).state.testsMode, "all");
});

test("hiding tests in Files excludes the test files; the walkthrough excludes nothing whatever the mode", async () => {
  const { renders, excluded, filters } = await loadTests();
  await renders.at(-1).handlers.onTestsMode("hide");
  assert.deepEqual([plain(excluded.at(-1)), filters.at(-1)], [["db/V1.sql", "src/old.js"], null]);
  await renders.at(-1).handlers.onSelectStop(2);
  assert.deepEqual([renders.at(-1).state.mode, renders.at(-1).state.testsMode, plain(excluded.at(-1)), filters.at(-1)], ["review", "hide", null, null]);
  await renders.at(-1).handlers.onMode("files");
  assert.deepEqual(plain(excluded.at(-1)), ["db/V1.sql", "src/old.js"]);
  await renders.at(-1).handlers.onTestsMode("all");
  assert.equal(excluded.at(-1), null);
});

const KINDS_REVIEW = {
  ...TESTS_REVIEW,
  file_sets: { contract: [], data: [], tests: ["db/V1.sql", "src/old.js", "src/api.integration.test.js", "m/src/testFixtures/java/p/Support.java"] },
};

test("Unit excludes the integration tests from the page and Integration the unit tests, and neither excludes a fixture", async () => {
  const { renders, excluded, filters } = await loadTests({ review: KINDS_REVIEW });
  await renders.at(-1).handlers.onTestsMode("unit");
  assert.deepEqual([renders.at(-1).state.testsMode, plain(excluded.at(-1)), filters.at(-1)], ["unit", ["src/api.integration.test.js"], null]);
  await renders.at(-1).handlers.onTestsMode("integration");
  assert.deepEqual([renders.at(-1).state.testsMode, plain(excluded.at(-1)), filters.at(-1)], ["integration", ["db/V1.sql", "src/old.js"], null]);
  await renders.at(-1).handlers.onTestsMode("hide");
  assert.deepEqual(plain(excluded.at(-1)), KINDS_REVIEW.file_sets.tests);
  await renders.at(-1).handlers.onTestsMode("all");
  assert.equal(excluded.at(-1), null);
});

test("Files counts the distinct files the mode excludes among the page's diff blocks and the brief's paths", async () => {
  const pagePaths = ["m/src/test/java/p/ExtraTest.java", "m/src/integrationTest/java/p/ExtraIT.java", "web/other.js", "db/V1.sql"];
  const { renders } = await loadTests({ review: KINDS_REVIEW, pagePaths });
  const hidden = async (mode) => {
    await renders.at(-1).handlers.onTestsMode(mode);
    return renders.at(-1).state.hiddenFiles;
  };
  assert.deepEqual([await hidden("all"), await hidden("hide"), await hidden("unit"), await hidden("integration"), await hidden("only")], [0, 6, 2, 3, 3]);
});

test("a test in a JVM test source set is a test for the page's filter even when file_sets.tests does not list it", async () => {
  const jvm = "m/src/test/java/p/FooTest.java";
  const review = { ...KINDS_REVIEW, chunks: [...KINDS_REVIEW.chunks, { i: 5, title: "JVM", summary: "s", risk: "low", risk_reason: "", depends_on: [], hunks: [{ id: "h9", path: jvm, change: "modified", old: [1, 1], new: [1, 1] }] }] };
  const { renders, excluded, filters } = await loadTests({ review });
  await renders.at(-1).handlers.onTestsMode("hide");
  assert.equal(plain(excluded.at(-1)).includes(jvm), true);
  await renders.at(-1).handlers.onTestsMode("integration");
  assert.equal(plain(excluded.at(-1)).includes(jvm), true);
  await renders.at(-1).handlers.onTestsMode("unit");
  assert.equal(plain(excluded.at(-1)).includes(jvm), false);
  await renders.at(-1).handlers.onTestsMode("only");
  assert.equal(plain(filters.at(-1)).includes(jvm), true);
});

test("Unit and Integration are saved and read back as their strings", async () => {
  const first = await loadTests();
  await first.renders.at(-1).handlers.onTestsMode("integration");
  assert.equal(first.local[TESTS_KEY], "integration");
  const again = await loadTests({ local: { [TESTS_KEY]: "unit" } });
  assert.equal(again.renders.at(-1).state.testsMode, "unit");
});

test("showing only tests in Files narrows the page to the test files; nothing is excluded", async () => {
  const { renders, excluded, filters } = await loadTests();
  await renders.at(-1).handlers.onTestsMode("only");
  assert.deepEqual(plain([filters.at(-1), excluded.at(-1)]), [["db/V1.sql", "src/old.js"], null]);
  await renders.at(-1).handlers.onSelectStop(1);
  assert.deepEqual([renders.at(-1).state.mode, filters.at(-1), plain(excluded.at(-1))], ["review", null, null]);
  await renders.at(-1).handlers.onMode("files");
  assert.deepEqual(plain(filters.at(-1)), ["db/V1.sql", "src/old.js"]);
  await renders.at(-1).handlers.onTestsMode("all");
  assert.equal(filters.at(-1), null);
});

test("the walkthrough applies only the file set, whatever Tests mode is stored", async () => {
  const review = { ...TESTS_REVIEW, file_sets: { contract: ["db/V1.sql", "src/api.js"], data: [], tests: ["db/V1.sql", "src/old.js"] } };
  for (const stored of ["all", "hide", "only"]) {
    const { renders, filters, excluded, hunkFilters } = await loadTests({ review, local: { [TESTS_KEY]: stored } });
    await renders.at(-1).handlers.onMode("review");
    assert.deepEqual([renders.at(-1).state.mode, filters.at(-1), plain(excluded.at(-1)), hunkFilters.at(-1)], ["review", null, null, null]);
    await renders.at(-1).handlers.onFileSet("contract");
    assert.deepEqual([plain(filters.at(-1)), plain(excluded.at(-1))], [["db/V1.sql", "src/api.js"], null]);
  }
});

test("a file set and the Tests mode both apply", async () => {
  const review = { ...TESTS_REVIEW, file_sets: { contract: ["db/V1.sql", "src/api.js"], data: [], tests: ["db/V1.sql", "src/old.js"] } };
  const { renders, filters, excluded } = await loadTests({ review });
  await renders.at(-1).handlers.onFileSet("contract");
  await renders.at(-1).handlers.onTestsMode("only");
  assert.deepEqual(plain(filters.at(-1)), ["db/V1.sql"]);
  await renders.at(-1).handlers.onTestsMode("hide");
  assert.deepEqual([filters.at(-1), plain(excluded.at(-1))], [["db/V1.sql", "src/api.js"], ["db/V1.sql", "src/old.js"]]);
});

test("the chunks tab drops the hidden files' ranges and puts the callout above the first shown file", async () => {
  const { renders, hunkFilters, excluded, callouts, fileJumps } = await loadTests();
  await renders.at(-1).handlers.onTestsMode("hide");
  await renders.at(-1).handlers.onSelectChunk(1);
  assert.deepEqual(plain(hunkFilters.at(-1)), [
    { path: "src/ui.js", side: "R", start: 4, count: 5 },
    { path: "src/ui.js", side: "L", start: 4, count: 3 },
  ]);
  assert.deepEqual(plain(excluded.at(-1)), ["db/V1.sql", "src/old.js"]);
  await renders.at(-1).handlers.onSelectChunk(4);
  assert.deepEqual(plain(hunkFilters.at(-1)), [
    { path: "src/api.js", side: "R", start: 5, count: 2 },
    { path: "src/api.js", side: "L", start: 5, count: 1 },
  ]);
  assert.deepEqual(callouts.at(-1).map((entry) => [entry.key, entry.anchor]), [["chunk:4", "diff-src/api.js"]]);
  assert.deepEqual(fileJumps.at(-1), ["src/api.js"]);
});

test("the chunk callout is anchored again when the Tests mode changes", async () => {
  const { renders, callouts } = await loadTests();
  await renders.at(-1).handlers.onSelectChunk(4);
  assert.equal(callouts.at(-1)[0].anchor, "diff-db/V1.sql");
  await renders.at(-1).handlers.onTestsMode("hide");
  assert.equal(callouts.at(-1)[0].anchor, "diff-src/api.js");
  await renders.at(-1).handlers.onTestsMode("only");
  assert.equal(callouts.at(-1)[0].anchor, "diff-db/V1.sql");
  assert.deepEqual(plain(renders.at(-1).state.mode), "chunks");
});

test("a chunk whose files are all kept out by the mode is shown whole, with its callout", async () => {
  const { renders, hunkFilters, excluded, callouts } = await loadTests();
  await renders.at(-1).handlers.onTestsMode("hide");
  await renders.at(-1).handlers.onSelectChunk(2);
  assert.deepEqual(plain(hunkFilters.at(-1)), [{ path: "src/old.js", side: "L", start: 1, count: 20 }]);
  assert.deepEqual(plain(excluded.at(-1)), ["db/V1.sql"]);
  assert.deepEqual(callouts.at(-1).map((entry) => entry.anchor), ["diff-src/old.js"]);
  await renders.at(-1).handlers.onTestsMode("only");
  await renders.at(-1).handlers.onSelectChunk(3);
  assert.deepEqual(plain(hunkFilters.at(-1)), [{ path: "src/ui.js", side: "L", start: 40, count: 2 }]);
  assert.equal(excluded.at(-1), null);
});

test("a chunk's callout is above the file the page lists first, not the one its hunks list first", async () => {
  const { renders, callouts, fileJumps } = await loadChunks({ pageOrder: ["db/V1.sql", "src/ui.js"] });
  await renders.at(-1).handlers.onSelectChunk(1);
  assert.deepEqual(callouts.at(-1).map((entry) => [entry.key, entry.anchor, entry.file]), [["chunk:1", "diff-db/V1.sql", true]]);
  assert.deepEqual(fileJumps, [["db/V1.sql"]]);
});

test("a chunk's callout skips the files the Tests mode hides, even when the page lists them first", async () => {
  const { renders, callouts, fileJumps } = await loadTests({ pageOrder: ["db/V1.sql", "src/api.js"] });
  await renders.at(-1).handlers.onSelectChunk(4);
  assert.equal(callouts.at(-1)[0].anchor, "diff-db/V1.sql");
  await renders.at(-1).handlers.onTestsMode("hide");
  assert.deepEqual([callouts.at(-1)[0].anchor, callouts.at(-1)[0].file], ["diff-src/api.js", true]);
  await renders.at(-1).handlers.onSelectChunk(4);
  assert.deepEqual(fileJumps.at(-1), ["src/api.js"]);
  await renders.at(-1).handlers.onSelectChunk(2);
  assert.deepEqual([callouts.at(-1)[0].anchor, fileJumps.at(-1)], ["diff-src/old.js", ["src/old.js"]]);
});

test("showing only tests keeps a chunk's test hunks and drops the rest", async () => {
  const { renders, hunkFilters, excluded } = await loadTests();
  await renders.at(-1).handlers.onTestsMode("only");
  await renders.at(-1).handlers.onSelectChunk(1);
  assert.deepEqual(plain(hunkFilters.at(-1)), [{ path: "db/V1.sql", side: "R", start: 1, count: 6 }]);
  assert.equal(excluded.at(-1), null);
});

const WIDTH = "--prf-callout-width";

test("the callout width is measured from every stop when the walkthrough is shown, and is left alone in Files mode", async () => {
  const widths = { 1: 400.2, 2: 612.4, 3: 530, 4: 480 };
  const { renders, properties, measuring } = loadContent({ review: WALK_REVIEW, cardWidth: (card) => widths[card.stop.i] });
  await settle();
  assert.deepEqual(properties, { [WIDTH]: "613px" });
  const [host] = measuring.appended;
  assert.deepEqual(
    [measuring.appended.length, measuring.removed, host.style, host.children.map((card) => [card.stop.i, card.style.width])],
    [1, [host], { position: "absolute", visibility: "hidden", left: "-10000px", top: "0" }, [[1, "max-content"], [2, "max-content"], [3, "max-content"], [4, "max-content"]]],
  );
  await renders.at(-1).handlers.onMode("files");
  assert.deepEqual([properties, measuring.measured], [{ [WIDTH]: "613px" }, 4]);
});

test("the width is not measured again for a refresh that leaves the shown set as it was", async () => {
  const { renders, measuring } = loadContent({ review: WALK_REVIEW, cardWidth: () => 500 });
  await settle();
  await renders.at(-1).handlers.onMode("review");
  await renders.at(-1).handlers.onSelectStop(2);
  await renders.at(-1).handlers.onFileSet("all");
  assert.deepEqual([measuring.appended.length, measuring.measured], [1, 4]);
});

test("a mode switch measures the layers, and the layers' own widths count, not the stops'", async () => {
  const { renders, properties } = loadContent({ review: CHUNK_REVIEW, cardWidth: (card) => (card.stop ? 900 : 500 + card.chunk.i * 10) });
  await settle();
  await renders.at(-1).handlers.onMode("review");
  assert.equal(properties[WIDTH], "900px");
  await renders.at(-1).handlers.onSelectChunk(1);
  assert.equal(properties[WIDTH], "530px");
});

test("every layer is measured, not only the selected one", async () => {
  const { renders, properties, measuring } = loadContent({ review: CHUNK_REVIEW, cardWidth: (card) => (card.chunk ? [0, 520, 700, 610][card.chunk.i] : 0) });
  await settle();
  await renders.at(-1).handlers.onMode("files");
  const before = measuring.measured;
  await renders.at(-1).handlers.onSelectChunk(1);
  assert.deepEqual([properties[WIDTH], measuring.measured - before], ["700px", 3]);
});

test("changing the Tests mode builds the layer callouts again and measures them again", async () => {
  let wide = 640;
  const { renders, properties, measuring } = loadContent({ review: TESTS_REVIEW, cardWidth: () => wide });
  await settle();
  await renders.at(-1).handlers.onSelectChunk(1);
  assert.equal(properties[WIDTH], "640px");
  const before = measuring.appended.length;
  wide = 555;
  await renders.at(-1).handlers.onTestsMode("hide");
  assert.deepEqual([properties[WIDTH], measuring.appended.length - before], ["555px", 1]);
});

test("a mode with no callouts leaves the width as it was", async () => {
  const { renders, properties } = loadContent({ review: { ...WALK_REVIEW, walkthrough: [] }, cardWidth: () => 500 });
  await settle();
  await renders.at(-1).handlers.onMode("review");
  assert.deepEqual(properties, {});
});

const record = ({ target = {}, added = [], removed = [] } = {}) => ({ target, addedNodes: added, removedNodes: removed });
const structural = { structural: true };
const decoration = {};

test("a refresh draws the list inside page.quietly", async () => {
  const { renders } = loadContent({ review: WALK_REVIEW });
  await settle();
  assert.equal(renders.length > 0 && renders.every((render) => render.quiet), true);
});

async function refreshesAfter(records) {
  const { renders, changes } = loadContent({ review: WALK_REVIEW });
  await settle();
  const before = renders.length;
  changes.at(-1)(records);
  await wait(250);
  return renders.length - before;
}

test("a hover toolbar the host adds or removes inside a cell schedules no refresh", async () => {
  assert.equal(await refreshesAfter([record({ added: [decoration] }), record({ removed: [decoration] })]), 0);
});

test("rows, diff blocks or tree rows the host adds or removes schedule one refresh", async () => {
  assert.equal(await refreshesAfter([record({ added: [decoration] }), record({ added: [structural] })]), 1);
  assert.equal(await refreshesAfter([record({ removed: [structural] })]), 1);
});

test("the host dropping one of our panels schedules a refresh, and a change inside our own element does not", async () => {
  const ours = { owned: true };
  assert.equal(await refreshesAfter([record({ removed: [ours] })]), 1);
  assert.equal(await refreshesAfter([record({ target: ours, removed: [ours], added: [structural] })]), 0);
});

test("structural nodes that are ours schedule no refresh", async () => {
  assert.equal(await refreshesAfter([record({ added: [{ structural: true, owned: true }] })]), 0);
});

test("with the pane handed to the host, nothing of the brief is drawn but the off bar, and the page's filters and callouts are cleared", async () => {
  const { renders, bars, callouts, filters, hunkFilters, excluded, diagramHandlers, diagramRemoved, lineEvents } = loadContent({ review: WALK_REVIEW, owner: "host" });
  await settle();
  assert.deepEqual([renders.length, diagramHandlers.length, bars.length], [0, 0, 1]);
  assert.deepEqual(plain(bars[0].counts), { stops: 4, layers: 0 });
  assert.deepEqual(plain([callouts.at(-1), filters.at(-1), hunkFilters.at(-1), excluded.at(-1)]), [[], null, null, null]);
  assert.equal(diagramRemoved.length > 0, true);
  assert.equal(lineEvents.includes("clearLineTarget"), true);
});

test("the off bar's Show gives the pane back to the brief and keeps that choice", async () => {
  const { renders, bars, ownerSaved, callouts } = loadContent({ review: WALK_REVIEW, owner: "host" });
  await settle();
  bars.at(-1).onShow();
  await settle();
  assert.deepEqual(ownerSaved, ["brief"]);
  assert.deepEqual([renders.at(-1).state.mode, callouts.at(-1).length], ["review", 4]);
});

test("the panel's switch hands the pane to the host, keeps the choice and leaves only the off bar", async () => {
  const { renders, bars, ownerSaved, callouts, filters } = loadContent({ review: WALK_REVIEW });
  await settle();
  assert.equal(bars.length, 0);
  renders.at(-1).handlers.onPaneOwner("host");
  await settle();
  assert.deepEqual([ownerSaved, bars.length, plain(callouts.at(-1)), filters.at(-1)], [["host"], 1, [], null]);
});

test("a change of the stored owner in another tab, or by the shortcut, is applied here without being saved again", async () => {
  const { renders, bars, ownerChanges, ownerSaved, callouts } = loadContent({ review: WALK_REVIEW });
  await settle();
  const drawn = renders.length;
  ownerChanges.at(-1)("brief");
  await settle();
  assert.equal(renders.length, drawn);
  ownerChanges.at(-1)("host");
  await settle();
  assert.deepEqual([bars.length, plain(callouts.at(-1)), ownerSaved], [1, [], []]);
  ownerChanges.at(-1)("brief");
  await settle();
  assert.deepEqual([renders.length > drawn, callouts.at(-1).length], [true, 4]);
});

test("a PR with no brief draws nothing and gets no off bar, whoever owns the pane", async () => {
  for (const owner of ["brief", "host"]) {
    const { bars, renders, callouts, diagramHandlers, output } = loadContent({ review: null, owner });
    await settle();
    assert.deepEqual([bars.length, renders.length, callouts.length, diagramHandlers.length, output], [0, 0, 0, 0, []], owner);
  }
});

test("the conversation page reads no review and draws nothing", async () => {
  const { reviewArgs, renders, bars, output } = loadContent({ view: "conversation", review: WALK_REVIEW });
  await settle();
  assert.deepEqual([reviewArgs, renders, bars, output], [[], [], [], []]);
});

test("a files page asks for its PR's review", async () => {
  const { reviewArgs } = loadContent({ review: WALK_REVIEW });
  await settle();
  assert.deepEqual(plain(reviewArgs), [["acme", "widgets", 7]]);
});

test("the pane opens in the walkthrough for a brief with stops, else in its layers, else in the host's own files", async () => {
  const opened = async (review) => {
    const { renders } = loadContent({ review });
    await settle();
    return renders.at(-1).state.mode;
  };
  assert.deepEqual([await opened(CHUNK_REVIEW), await opened({ ...CHUNK_REVIEW, walkthrough: [] }), await opened({ ...WALK_REVIEW, walkthrough: [] })], ["review", "chunks", "files"]);
});
