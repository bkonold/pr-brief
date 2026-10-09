const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const githubPage = require("../github_page.js");
const forgejoPage = require("../forgejo_page.js");
const briefText = require("../brief_text.js");
const tree = require("../tree.js");
const runControl = require("../run_control.js");
const { buildBrief, buildCard, cardHtml, isStale } = require("../brief.js");

const FILES_URL = "http://forge.example/acme/widgets/pulls/7/files";

const MARKDOWN = [
  "# Example title",
  "",
  "<!-- pr-agent-generated -->",
  "### **PR Type**",
  "Enhancement",
  "",
  "___",
  "",
  "### **Description**",
  "- Adds `thing` to the pipeline",
  "  - nested **point**",
  "",
  "- Second point",
  "",
  "___",
  "",
  "### Diagram Walkthrough",
  "",
  "```mermaid",
  "flowchart TD",
  '  a["1 · Step"]',
  "```",
  "",
  "Dashed boxes are unchanged context",
  "",
  "___",
  "",
].join("\n");

function bodyHtml(markdown = MARKDOWN) {
  return `<!doctype html><html><head><title>t</title><style>body{}</style></head><body><article id="out"></article>
<script src="https://cdn.example/marked.min.js"></script>
<script>
 const md = ${JSON.stringify(markdown).replace(/<\//g, "<\\/")};
 document.getElementById('out').innerHTML = marked.parse(md);
</script></body></html>`;
}

test("a GitHub conversation page maps to the conversation view and a files page to the files view", () => {
  const { prFromUrl } = githubPage;
  const base = { owner: "example-org", repo: "example-repo", pr: 5 };
  assert.deepEqual(prFromUrl({ pathname: "/example-org/example-repo/pull/5" }), { ...base, view: "conversation" });
  assert.deepEqual(prFromUrl("https://github.com/example-org/example-repo/pull/5/?x=1#issuecomment-9"), { ...base, view: "conversation" });
  assert.deepEqual(prFromUrl({ pathname: "/example-org/example-repo/pull/5/files" }), { ...base, view: "files" });
  assert.deepEqual(prFromUrl({ pathname: "/example-org/example-repo/pull/5/changes" }), { ...base, view: "files" });
  assert.equal(prFromUrl({ pathname: "/example-org/example-repo/pull/5/commits" }), null);
  assert.equal(prFromUrl({ pathname: "/example-org/example-repo/pulls/5" }), null);
  assert.equal(prFromUrl({ pathname: "/example-org/example-repo/issues/5" }), null);
});

test("a Forgejo conversation page maps to the conversation view and a files page to the files view", () => {
  const { prFromUrl } = forgejoPage;
  const base = { owner: "acme", repo: "widgets", pr: 7 };
  assert.deepEqual(prFromUrl({ pathname: "/acme/widgets/pulls/7" }), { ...base, view: "conversation" });
  assert.deepEqual(prFromUrl("http://localhost:3300/acme/widgets/pulls/7#issuecomment-3"), { ...base, view: "conversation" });
  assert.deepEqual(prFromUrl({ pathname: "/acme/widgets/pulls/7/files" }), { ...base, view: "files" });
  assert.equal(prFromUrl({ pathname: "/acme/widgets/pulls/7/commits" }), null);
  assert.equal(prFromUrl({ pathname: "/acme/widgets/pull/7" }), null);
});

test("each adapter builds the files view URL of a PR", () => {
  assert.equal(githubPage.filesUrl({ owner: "o", repo: "r", pr: 5 }), "https://github.com/o/r/pull/5/files");
  assert.equal(forgejoPage.filesUrl({ owner: "acme", repo: "widgets", pr: 7 }), "http://localhost:3300/acme/widgets/pulls/7/files");
});

test("renderBody drops every script, whether in body.html or in the markdown it renders", () => {
  const hostile = MARKDOWN.replace(
    "Enhancement",
    'Enhancement <script>alert(1)</script><img src=x onerror="alert(2)"><a href="javascript:alert(3)">x</a><a href="jav&#x61;script:alert(4)">y</a><a href="java\tscript:alert(5)">z</a><SCRIPT SRC=//evil.example/x.js></SCRIPT><iframe src="//evil.example"></iframe><p onclick="alert(6)">p</p>',
  );
  const { html, caption } = briefText.renderBody(bodyHtml(hostile), FILES_URL);
  for (const text of [html, caption]) {
    assert.doesNotMatch(text, /<script|<\/script|<iframe|onerror|onclick|javascript:|alert\(/i);
  }
  assert.match(html, /<p>Enhancement/);
  assert.match(html, /<p>p<\/p>/);
});

test("renderBody strips scripts from a body.html that has no markdown string", () => {
  const page = '<html><body><h1>Title</h1><script>alert(1)</script><p onmouseover="x()">kept</p><script src="//cdn.example/a.js"></script></body></html>';
  const { html } = briefText.renderBody(page, FILES_URL);
  assert.equal(html, "<h1>Title</h1><p>kept</p>");
});

test("sanitize in svg mode keeps a diagram's style and drops what can run script", () => {
  const svg = '<svg viewBox="0 0 10 10" onload="x()"><style>#d .n{fill:red}</style><script>alert(1)</script><g class="n"><foreignObject><div>label</div></foreignObject><a xlink:href="javascript:x()"/></g></svg>';
  const clean = briefText.sanitize(svg, "svg");
  assert.match(clean, /<style>#d \.n\{fill:red\}<\/style>/);
  assert.match(clean, /<foreignObject><div>label<\/div><\/foreignObject>/);
  assert.doesNotMatch(clean, /script|onload|javascript:/i);
});

test("renderBody renders the description and leaves the title, the mermaid source and its heading out", () => {
  const { html, caption } = briefText.renderBody(bodyHtml(), FILES_URL);
  assert.doesNotMatch(html, /Example title|mermaid|flowchart|Diagram Walkthrough|pr-agent-generated|Dashed boxes/);
  assert.match(html, /<h3><strong>PR Type<\/strong><\/h3>/);
  assert.match(html, /<li>Adds <code>thing<\/code> to the pipeline\n<ul>\n<li>nested <strong>point<\/strong>/);
  assert.equal(caption, "Dashed boxes are unchanged context");
});

test("links into the files view point at this host's files view and keep their fragment", () => {
  const markdown = '<a href="https://github.com/acme/widgets/pull/7/files#diff-alpha">a</a> <a href="https://github.com/acme/widgets/pull/7/changes#diff-alphaR12">b</a>';
  const { html } = briefText.renderBody(bodyHtml(markdown), FILES_URL);
  assert.match(html, /href="http:\/\/forge\.example\/acme\/widgets\/pulls\/7\/files#diff-alpha"/);
  assert.match(html, /href="http:\/\/forge\.example\/acme\/widgets\/pulls\/7\/files#diff-alphaR12"/);
  assert.doesNotMatch(html, /github\.com/);
  assert.equal(briefText.rewriteLinks('<a href="https://elsewhere.example/x#y">x</a>', FILES_URL), '<a href="https://elsewhere.example/x#y">x</a>');
});

function fakeDocument() {
  const created = [];
  return {
    created,
    createElement(tag) {
      const element = {
        tag,
        attributes: {},
        setAttribute(name, value) {
          this.attributes[name] = value;
        },
        attachShadow() {
          this.shadow = { innerHTML: "" };
          return this.shadow;
        },
      };
      created.push(element);
      return element;
    },
  };
}

const SVG = '<svg viewBox="0 0 10 10"><style>#d{fill:red}</style><g class="node"/></svg>';

test("the card is a closed details that reads and writes no storage", () => {
  const touched = [];
  const trap = (name) => ({ get: () => (touched.push(name), assert.fail(`${name} was used`)) });
  const saved = { document: globalThis.document, chrome: globalThis.chrome };
  Object.defineProperty(globalThis, "localStorage", { configurable: true, ...trap("localStorage") });
  Object.defineProperty(globalThis, "sessionStorage", { configurable: true, ...trap("sessionStorage") });
  globalThis.chrome = { storage: { get sync() { return trap("chrome.storage").get(); } } };
  const document = fakeDocument();
  globalThis.document = document;
  try {
    const host = buildBrief({ key: "fj-7", variant: "v1", bodyHtml: bodyHtml(), diagramSvg: SVG, filesUrl: FILES_URL });
    const shadow = host.shadow.innerHTML;
    assert.equal(host.attributes["data-run"], "fj-7");
    assert.equal(host.attributes["data-variant"], "v1");
    const outer = /<details class="brief"[^>]*>/.exec(shadow)[0];
    assert.equal(outer, '<details class="brief">');
    assert.doesNotMatch(shadow, /<details[^>]*\bopen\b/);
    assert.match(shadow, /<span class="title">PR brief<\/span>/);
    assert.match(shadow, /<span class="badge"[^>]*>local, not posted<\/span>/);
    assert.match(shadow, /<a class="files-link" href="http:\/\/forge\.example\/acme\/widgets\/pulls\/7\/files">Review in files view<\/a>/);
    const diagramBox = /<details class="diagram-box"><summary>Diagram<\/summary>(.*?)<\/details>/s.exec(shadow);
    assert.ok(diagramBox, "the diagram is in its own details headed Diagram");
    assert.match(diagramBox[1], /^<figure class="diagram">.*<svg viewBox="0 0 10 10">.*<p class="caption">Dashed boxes are unchanged context<\/p><\/figure>$/s);
    const at = (needle) => shadow.indexOf(needle);
    assert.ok(at("Second point") < at('<details class="diagram-box">'), "the diagram follows the description's bullets");
    assert.equal(shadow.match(/<details class="diagram-box">/g).length, 1);
    assert.doesNotMatch(shadow, /grid-template-columns/);
    assert.match(shadow, /\.text > ul > li, \.text > ol > li \{ margin-bottom: 1\.5em; \}/);
    assert.doesNotMatch(shadow, /<script/i);
    assert.deepEqual(touched, []);
  } finally {
    delete globalThis.localStorage;
    delete globalThis.sessionStorage;
    globalThis.document = saved.document;
    globalThis.chrome = saved.chrome;
    if (saved.document === undefined) delete globalThis.document;
    if (saved.chrome === undefined) delete globalThis.chrome;
  }
});

test("the card leaves the diagram out when the run has none, or when it is not an svg", () => {
  globalThis.document = fakeDocument();
  try {
    for (const diagramSvg of [null, "", "<html>nope</html>"]) {
      const shadow = buildBrief({ key: "7", variant: "v1", bodyHtml: bodyHtml(), diagramSvg, filesUrl: FILES_URL }).shadow.innerHTML;
      assert.doesNotMatch(shadow, /<figure|<svg|<details class="diagram-box"/);
    }
  } finally {
    delete globalThis.document;
  }
});

// content.js runs on load, so it is loaded into a context of fakes: a conversation page whose description host
// is a recording element, a source that answers with `run` and `status`, and a card that records what it is shown.
function loadContent({ run, status = { ok: true, state: "idle", allowed: true }, hostPresent = true, pageSha = null, view = "conversation", review = null, hash = "", stored = {}, startState = "running" }) {
  const log = [];
  const description = {
    name: "description",
    before(card) {
      log.push("placed");
      card.placed = (card.placed ?? 0) + 1;
    },
  };
  const navigations = [];
  const built = [];
  const calls = [];
  const lines = [];
  const renders = [];
  const jumps = [];
  const fileJumps = [];
  const callouts = [];
  const emphasized = [];
  const centered = [];
  const centeredWith = [];
  const lineEvents = [];
  const diagramHandlers = [];
  const briefArgs = [];
  const revealed = [];
  const boxes = [];
  const scrolled = [];
  const filters = [];
  const prFocus = {
    page: {
      name: "Fake",
      hostId: "forgejo",
      prFromUrl: () => ({ owner: "acme", repo: "widgets", pr: 7, view }),
      runKey: (pr) => `fj-${pr.pr}`,
      filesUrl: () => FILES_URL,
      currentHeadSha: async () => pageSha,
      descriptionHost: () => (hostPresent ? description : null),
      onNavigate: (callback) => (navigations.push(callback), () => {}),
      onChange: () => () => {},
      cancelJump: () => lineEvents.push("cancelJump"),
      clearLineTarget: () => lineEvents.push("clearLineTarget"),
      fileBlocks: () => new Map(),
      headSha: () => null,
      restoreLineTarget() {},
      ownsLine: () => false,
      lineAnchor: async (path, side, line) => `${path}${side}${line}`,
      fileAnchor: async (path) => `diff-${path}`,
      showCallouts: (entries) => callouts.push(entries),
      filterTree: (paths) => filters.push(paths),
      changedFileCount: () => 9,
      jumpToLine: async (...args) => jumps.push(args),
      jumpToFile: async (...args) => fileJumps.push(args),
    },
    source: {
      loadBrief: async (...args) => (briefArgs.push(args), run),
      loadReview: async () => review,
      runStatus: async (target) => (calls.push(["status", target]), status),
      startRun: async (target) => (calls.push(["start", target]), { ok: true, key: target.key, state: startState }),
      cancelRun: async (target) => (calls.push(["cancel", target]), { ok: true, key: target.key, state: "canceled" }),
    },
    runControl: { ...runControl, create: (options) => runControl.create({ ...options, timers: { setTimeout: context.setTimeout, clearTimeout, setInterval: context.setInterval, clearInterval } }) },
    brief: {
      buildCard: (options) => {
        const card = { isConnected: true, nextElementSibling: null, remove() {}, placed: 0, options, shown: [], show: (shown) => card.shown.push(shown) };
        built.push(card);
        return card;
      },
    },
    tree: {
      render: (shownReview, state, handlers) => renders.push({ review: shownReview, state, handlers }),
      renderGenerateLine: (shown, handlers) => lines.push({ shown, handlers }),
      stopsOf: require("../tree.js").stopsOf,
      fileChips: require("../tree.js").fileChips,
      fileSetOf: require("../tree.js").fileSetOf,
      stopCallout: (stop, stops, onGo, nodes) => ({ stop, stops, onGo, nodes }),
      revealStop: (i) => revealed.push(i),
      remove() {},
      owns: () => false,
    },
    focus: { clearBox() {}, markBox: (paths) => boxes.push(paths), scrollTo: async (path) => scrolled.push(path), announceBox() {} },
    diagram: {
      render: (svg, handlers) => diagramHandlers.push(handlers),
      emphasize: (nodes) => emphasized.push(nodes),
      titleOf: (nodeId) => `title of ${nodeId}`,
      centerOn: (nodeIds, options) => (centered.push(nodeIds), centeredWith.push(options)),
      remove() {},
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
  const context = { prFocus, sessionStorage, location: { href: "x", hash }, console: consoleSpy, setTimeout: unref(setTimeout), clearTimeout, setInterval: unref(setInterval), clearInterval, Date, Promise };
  context.globalThis = context;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../content.js"), "utf8"), context);
  return { briefArgs, log, built, navigations, output, calls, lines, renders, jumps, fileJumps, callouts, emphasized, centered, centeredWith, lineEvents, stored, diagramHandlers, revealed, boxes, scrolled, filters };
}

const plain = (value) => JSON.parse(JSON.stringify(value));
const settle = () => new Promise((resolve) => setImmediate(resolve));
const RUN = { variant: "v1", bodyHtml: "<p>x</p>", diagramSvg: null, headSha: "a".repeat(40) };

test("nothing is built, placed or logged when the PR has no run and the server will not run its repository", async () => {
  const { built, log, output } = loadContent({ run: null, status: { ok: true, state: "idle", allowed: false } });
  await settle();
  assert.deepEqual([built, log, output], [[], [], []]);
});

test("a PR with no run gets a card offering to generate, and the click starts a run", async () => {
  const { built, log, calls } = loadContent({ run: null });
  await settle();
  assert.equal(built.length, 1);
  assert.deepEqual(log, ["placed"]);
  assert.deepEqual(plain(built[0].shown), [{ kind: "none", canGenerate: true }]);
  assert.deepEqual({ ...built[0].options, onAction: undefined }, { key: "fj-7", filesUrl: FILES_URL, onAction: undefined });
  built[0].options.onAction("generate");
  await settle();
  assert.deepEqual(plain(calls.at(-1)), ["start", { host: "forgejo", owner: "acme", repo: "widgets", pr: 7, key: "fj-7" }]);
  assert.deepEqual(plain(built[0].shown[1]), { kind: "running", stage: "fetch", elapsed: 0 });
  built[0].options.onAction("cancel");
  await settle();
  assert.equal(calls.at(-1)[0], "cancel");
  assert.deepEqual(plain(built[0].shown.at(-1)), { kind: "none", canGenerate: true });
});

test("with the server down or the token wrong the card is still offered, so the click can say why", async () => {
  for (const status of [{ problem: "server" }, { problem: "token" }]) {
    const { built } = loadContent({ run: null, status });
    await settle();
    assert.deepEqual(plain(built[0].shown), [{ kind: "none", canGenerate: true }]);
    built[0].options.onAction("generate");
  }
});

test("a run in progress on the server is followed when the page opens, and its failure is shown", async () => {
  const { built } = loadContent({ run: null, status: { ok: true, state: "running", stage: "write", elapsed: 41, allowed: true } });
  await settle();
  assert.deepEqual(plain(built[0].shown), [{ kind: "none", canGenerate: true }, { kind: "running", stage: "write", elapsed: 41 }]);
});

test("one card is built for a run, however many times the page announces a navigation", async () => {
  const { built, log, navigations } = loadContent({ run: RUN });
  await settle();
  for (const navigate of navigations) {
    navigate();
    navigate();
  }
  await settle();
  assert.equal(built.length, 1);
  assert.deepEqual({ ...built[0].options, onAction: undefined }, { key: "fj-7", filesUrl: FILES_URL, onAction: undefined });
  assert.deepEqual(plain(built[0].shown), [{ kind: "brief", ...RUN, runSha: RUN.headSha, pageSha: null, canGenerate: true }]);
  assert.deepEqual(log, ["placed"]);
});

test("the card shows the run's head and the page's, so a moved head reads as stale", async () => {
  const { built } = loadContent({ run: RUN, pageSha: "b".repeat(40) });
  await settle();
  const [shown] = built[0].shown;
  assert.deepEqual([shown.runSha, shown.pageSha], ["a".repeat(40), "b".repeat(40)]);
  assert.ok(isStale(shown.runSha, shown.pageSha));
});

test("the card waits for the description to exist before it is placed", async () => {
  const { built, log } = loadContent({ run: RUN, hostPresent: false });
  await settle();
  assert.equal(built.length, 1);
  assert.deepEqual(log, []);
});

test("a files page with no run shows one generate line, and its click starts a run", async () => {
  const { lines, calls } = loadContent({ run: null, view: "files" });
  await settle();
  assert.deepEqual(plain(lines.at(-1).shown), { kind: "none" });
  lines.at(-1).handlers.onGenerate();
  await settle();
  assert.deepEqual(plain(calls.at(-1)), ["start", { host: "forgejo", owner: "acme", repo: "widgets", pr: 7, key: "fj-7" }]);
  assert.deepEqual(plain(lines.at(-1).shown), { kind: "running", stage: "fetch", elapsed: 0 });
});

test("a files page whose run was written by an older version shows one re-run line, and its click starts a run", async () => {
  const { lines, renders, calls } = loadContent({ run: null, view: "files", review: { error: "old", baseUrl: "http://x" } });
  await settle();
  assert.deepEqual([renders, plain(lines.at(-1).shown)], [[], { kind: "old" }]);
  lines.at(-1).handlers.onGenerate();
  await settle();
  assert.deepEqual(plain(calls.at(-1)), ["start", { host: "forgejo", owner: "acme", repo: "widgets", pr: 7, key: "fj-7" }]);
  assert.deepEqual(plain(lines.at(-1).shown), { kind: "running", stage: "fetch", elapsed: 0 });
});

test("a files page whose repository the server will not run shows no line", async () => {
  const { lines } = loadContent({ run: null, view: "files", status: { ok: true, state: "idle", allowed: false } });
  await settle();
  assert.deepEqual(lines, []);
});

const UNSET = { ok: false, problem: "unset" };

test("with no run server set and no brief comment, nothing is built, placed or asked of a server", async () => {
  for (const view of ["conversation", "files"]) {
    const { built, log, output, lines, calls } = loadContent({ run: null, view, status: UNSET });
    await settle();
    assert.deepEqual([built, log, output, lines], [[], [], [], []], view);
    assert.deepEqual(plain(calls), [["status", { host: "forgejo", owner: "acme", repo: "widgets", pr: 7, key: "fj-7" }]], view);
  }
});

test("a brief read from the comment is drawn with no run server set, and without a Generate or Regenerate affordance", async () => {
  const { built } = loadContent({ run: { ...RUN, origin: "comment" }, status: UNSET });
  await settle();
  assert.deepEqual(plain(built[0].shown), [{ kind: "brief", ...RUN, origin: "comment", runSha: RUN.headSha, pageSha: null, canGenerate: false }]);
});

test("a run the local server has just written is read from the server, not from the comment", async () => {
  const { built, briefArgs } = loadContent({ run: { ...RUN, origin: "comment" }, startState: "done" });
  await settle();
  assert.deepEqual(plain(briefArgs), [["acme", "widgets", 7, "fj-7"]]);
  built[0].options.onAction("generate");
  await settle();
  assert.deepEqual(plain(briefArgs.at(-1)), ["acme", "widgets", 7, "fj-7", { server: true }]);
});

const RUN_SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f90abcdef01";
const PAGE_SHA = "9f8e7d6c5b4a39281706f5e4d3c2b1a098765432";
const CARD = { key: "fj-7", filesUrl: FILES_URL };

test("with no run the card is a bar with the badge and a Generate brief button", () => {
  const html = cardHtml({ kind: "none", canGenerate: true }, CARD);
  assert.match(html, /<span class="title">PR brief<\/span><span class="badge"[^>]*>local, not posted<\/span><button class="btn" type="button" data-action="generate">Generate brief<\/button>/);
  assert.doesNotMatch(html, /<details|<ol/);
  assert.doesNotMatch(cardHtml({ kind: "none", canGenerate: false }, CARD), /<button/);
});

test("while a run is going the card shows the elapsed time, the stage pills and a Cancel link", () => {
  const html = cardHtml({ kind: "running", stage: "write", elapsed: 83 }, CARD);
  assert.match(html, /<span class="progress">Writing brief · 1:23<\/span><button class="link" type="button" data-action="cancel">Cancel<\/button>/);
  const pills = [...html.matchAll(/<li class="pill (\w+)">([^<]+)<\/li>/g)].map((match) => [match[2], match[1]]);
  assert.deepEqual(pills, [["Fetch PR", "done"], ["Gather context", "done"], ["Write", "current"], ["Render", "pending"]]);
});

test("a failure shows its message, escaped, with a Retry button", () => {
  const html = cardHtml({ kind: "error", message: "bad <b>line</b> with `pd serve`" }, CARD);
  assert.match(html, /<p class="error" role="alert">bad &lt;b&gt;line&lt;\/b&gt; with <code>pd serve<\/code><\/p>/);
  assert.match(html, /data-action="generate">Retry<\/button>/);
});

const BRIEF = { kind: "brief", variant: "v1", bodyHtml: bodyHtml(), diagramSvg: null, runSha: RUN_SHA, pageSha: RUN_SHA.toUpperCase(), canGenerate: true };
const GENERATE = (label, kind) => `<button class="${kind}" type="button" data-action="generate">${label}</button>`;
const summaryOf = (html) => /<summary>[^]*?<\/summary>/.exec(html)[0];

test("a run for an older head says so and offers a Regenerate button beside the badge", () => {
  const stale = cardHtml({ ...BRIEF, pageSha: PAGE_SHA }, CARD);
  assert.match(stale, /<span class="badge"[^>]*>for a1b2c3d, PR is at 9f8e7d6<\/span><button class="btn" type="button" data-action="generate">Regenerate<\/button><a class="files-link" href="[^"]+">Review in files view<\/a>/);
  assert.equal(summaryOf(stale).match(/Regenerate/g).length, 1);
  assert.match(stale, /<details class="brief">/);
  assert.doesNotMatch(stale, /<details[^>]*\bopen\b/);
});

test("a run for the page's head, or a page whose head is unknown, offers a quiet Regenerate link in the header", () => {
  for (const pageSha of [RUN_SHA.toUpperCase(), null, undefined]) {
    const html = cardHtml({ ...BRIEF, pageSha }, CARD);
    assert.match(html, /<span class="badge"[^>]*>local, not posted<\/span><button class="link quiet" type="button" data-action="generate">Regenerate<\/button><a class="files-link"/);
    assert.ok(summaryOf(html).includes(GENERATE("Regenerate", "link quiet")));
    assert.doesNotMatch(html, /class="btn"/);
  }
  assert.ok(summaryOf(cardHtml({ ...BRIEF, canGenerate: undefined }, CARD)).includes(GENERATE("Regenerate", "link quiet")));
});

test("when generating is not allowed the card shows no Regenerate, stale or not", () => {
  for (const pageSha of [PAGE_SHA, RUN_SHA, null]) {
    const html = cardHtml({ ...BRIEF, pageSha, canGenerate: false }, CARD);
    assert.doesNotMatch(html, /Regenerate|data-action="generate"/);
  }
});

test("a brief read from the PR's comment says so, and offers Regenerate only when a run server is set", () => {
  const posted = { ...BRIEF, origin: "comment", pageSha: null };
  const quiet = cardHtml({ ...posted, canGenerate: true }, CARD);
  assert.match(quiet, /<span class="badge"[^>]*>from the PR's comment<\/span>/);
  assert.ok(summaryOf(quiet).includes(GENERATE("Regenerate", "link quiet")));
  for (const canGenerate of [false, undefined]) {
    const html = cardHtml({ ...posted, canGenerate }, CARD);
    assert.match(html, /<span class="badge"[^>]*>from the PR's comment<\/span><a class="files-link"/);
    assert.doesNotMatch(html, /Regenerate|data-action="generate"/);
  }
  const stale = cardHtml({ ...posted, pageSha: PAGE_SHA, canGenerate: false }, CARD);
  assert.match(stale, /<span class="badge"[^>]*>for a1b2c3d, PR is at 9f8e7d6<\/span><a class="files-link"/);
  assert.doesNotMatch(stale, /Regenerate/);
  assert.match(cardHtml({ ...BRIEF, origin: "server" }, CARD), /local, not posted/);
});

test("clicking Regenerate in the header runs the action and does not toggle the card", () => {
  const listeners = [];
  globalThis.document = {
    createElement: () => ({
      attributes: {},
      setAttribute() {},
      attachShadow() {
        this.shadow = { innerHTML: "", addEventListener: (type, listener) => listeners.push([type, listener]) };
        return this.shadow;
      },
    }),
  };
  try {
    const actions = [];
    const host = buildCard({ ...CARD, onAction: (action) => actions.push(action) });
    for (const pageSha of [RUN_SHA, PAGE_SHA, null]) {
      host.show({ ...BRIEF, pageSha });
      assert.match(summaryOf(host.shadow.innerHTML), /data-action="generate">Regenerate<\/button>/);
    }
    const [[, listener]] = listeners;
    let prevented = 0;
    listener({ target: { closest: (selector) => (selector === "[data-action]" ? { getAttribute: () => "generate" } : null) }, preventDefault: () => (prevented += 1) });
    assert.deepEqual(actions, ["generate"]);
    assert.equal(prevented, 1);
  } finally {
    delete globalThis.document;
  }
});

test("a head that is unknown on either side is never stale", () => {
  assert.equal(isStale(null, PAGE_SHA), false);
  assert.equal(isStale(RUN_SHA, null), false);
  assert.equal(isStale(RUN_SHA, RUN_SHA), false);
  assert.equal(isStale(RUN_SHA, PAGE_SHA), true);
});

test("clicking a button in the card reports its action, and show redraws the card for each view", () => {
  const listeners = [];
  const document = {
    createElement: () => ({
      attributes: {},
      setAttribute(name, value) {
        this.attributes[name] = value;
      },
      attachShadow() {
        this.shadow = { innerHTML: "", addEventListener: (type, listener) => listeners.push([type, listener]) };
        return this.shadow;
      },
    }),
  };
  globalThis.document = document;
  try {
    const actions = [];
    const host = buildCard({ ...CARD, onAction: (action) => actions.push(action) });
    host.show({ kind: "none", canGenerate: true });
    assert.match(host.shadow.innerHTML, /Generate brief/);
    host.show({ kind: "running", stage: "fetch", elapsed: 0 });
    assert.match(host.shadow.innerHTML, /Writing brief · 0:00/);
    host.show({ kind: "brief", variant: "v1", bodyHtml: bodyHtml(), diagramSvg: null });
    assert.equal(host.attributes["data-variant"], "v1");
    assert.equal(listeners.length, 1);
    const [type, listener] = listeners[0];
    assert.equal(type, "click");
    let prevented = 0;
    const click = (action) => listener({ target: { closest: () => (action ? { getAttribute: () => action } : null) }, preventDefault: () => (prevented += 1) });
    click("generate");
    click("cancel");
    click(null);
    assert.deepEqual(actions, ["generate", "cancel"]);
    assert.equal(prevented, 2);
  } finally {
    delete globalThis.document;
  }
});

const V22_MARKDOWN = [
  "# T",
  "",
  '<details class="section">',
  '<summary><strong>Contract</strong> <span class="pill p0"><strong>callers must change</strong></span> <span class="pill p2">additive</span> <span class="muted">3 changes</span></summary>',
  "",
  '<div class="table-wrap">',
  "",
  "| Impact | Side | Change | On | ↗ |",
  "| --- | --- | --- | --- | --- |",
  '| <span class="pill p0"><strong>callers must change</strong></span> | request | <code>+ kind</code> required param | <code>GET /rows</code> | [↗](https://github.com/acme/widgets/pull/7/changes#diff-abcR4) |',
  '| <span class="pill p2">additive</span> | response | <code>+ note</code> optional | 9 schemas: <code>A</code>, <code title="LongSchemaNameThatIsCutInTheMiddleOfItsLetters">LongSchemaNameTh…ItsLetters</code> +6 | [↗](https://github.com/acme/widgets/pull/7/changes#diff-abcR9) |',
  '| <span class="pill p2">additive</span> |  | <code>+ a</code> nullable &#124; x | <code>widgets</code> | [↗](https://github.com/acme/widgets/pull/7/changes#diff-defR3) |',
  "",
  "</div>",
  "",
  "</details>",
  "",
  "___",
  "",
  "### **Data**",
  "No database changes",
  "",
  "### Diagram Walkthrough",
  "",
  "```mermaid",
  "flowchart TD",
  "```",
  "",
].join("\n");

test("a v22 section is one closed details with its name and chips in the summary and one table", () => {
  const html = cardHtml({ kind: "brief", variant: "v22", bodyHtml: bodyHtml(V22_MARKDOWN), diagramSvg: null }, CARD);
  assert.equal((html.match(/<details class="section">/g) ?? []).length, 1);
  assert.doesNotMatch(html, /<details class="section" open/);
  assert.match(html, /<summary><strong>Contract<\/strong> <span class="pill p0"><strong>callers must change<\/strong><\/span> <span class="pill p2">additive<\/span> <span class="muted">3 changes<\/span><\/summary>/);
  assert.equal((html.match(/<table>/g) ?? []).length, 1);
  assert.match(html, /<thead><tr><th>Impact<\/th><th>Side<\/th><th>Change<\/th><th>On<\/th><th>↗<\/th><\/tr><\/thead>/);
  assert.match(html, /<td><span class="pill p0"><strong>callers must change<\/strong><\/span><\/td><td>request<\/td><td><code>\+ kind<\/code> required param<\/td><td><code>GET \/rows<\/code><\/td>/);
  assert.match(html, /<td><a href="http:\/\/forge\.example\/acme\/widgets\/pulls\/7\/files#diff-abcR4">↗<\/a><\/td>/);
  assert.match(html, /<code title="LongSchemaNameThatIsCutInTheMiddleOfItsLetters">LongSchemaNameTh…ItsLetters<\/code>/);
  assert.match(html, /<code>\+ a<\/code> nullable &#124; x/);
  assert.match(html, /<div class="table-wrap">\s*<table>/);
  assert.doesNotMatch(html, /\||class="sub"|group-row|chunk/);
});

test("a v22 brief keeps the diagram after the Data section", () => {
  const svg = '<svg viewBox="0 0 1 1"><g></g></svg>';
  const html = cardHtml({ kind: "brief", variant: "v22", bodyHtml: bodyHtml(V22_MARKDOWN), diagramSvg: svg }, CARD);
  const contract = html.indexOf("<strong>Contract</strong>");
  const data = html.indexOf("<h3><strong>Data</strong></h3>");
  const diagram = html.indexOf('class="diagram-box"');
  assert.ok(contract !== -1 && data > contract && diagram > data, [contract, data, diagram].join());
  assert.equal(html.slice(contract, data).includes("diagram-box"), false);
});

test("renderMarkdown reads a pipe table with an escaped pipe and leaves a lone pipe line as text", () => {
  const { html } = briefText.renderMarkdown(["| a | b |", "| --- | --- |", "| x \\| y | `z` |", "", "| not a table |"].join("\n"));
  assert.match(html, /<table><thead><tr><th>a<\/th><th>b<\/th><\/tr><\/thead><tbody><tr><td>x \| y<\/td><td><code>z<\/code><\/td><\/tr><\/tbody><\/table>/);
  assert.match(html, /<p>\| not a table \|<\/p>/);
});

test("the callouts are shown in the review and removed in the host's own tree view", async () => {
  const { renders, callouts } = loadContent({ run: null, view: "files", review: WALK_REVIEW });
  await settle();
  await renders.at(-1).handlers.onMode("github");
  assert.deepEqual(plain(callouts.at(-1)), []);
  await renders.at(-1).handlers.onMode("review");
  assert.equal(callouts.at(-1).length, 4);
});

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
  const { callouts } = loadContent({ run: null, view: "files", review: WALK_REVIEW });
  await settle();
  assert.deepEqual(
    callouts.at(-1).map((entry) => [entry.key, entry.anchor, entry.file ?? false]),
    [[1, "src/ui.jsR4", false], [2, "db/V1.sqlR2", false], [3, "src/ui.jsR30", false], [4, "diff-src/api.js", true]],
  );
  const { stop, stops, nodes } = callouts.at(-1)[1].render();
  assert.deepEqual([stop.i, stops.length, Object.keys(nodes)], [2, 4, ["a", "b", "c", "d"]]);
});

test("walking the stops with a callout's buttons gives each stop's box the halo and centres on it", async () => {
  const { callouts, jumps, fileJumps, centered, emphasized } = loadContent({ run: null, view: "files", review: WALK_REVIEW });
  await settle();
  jumps.length = 0;
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
  assert.equal(JSON.stringify(fileJumps), JSON.stringify([["src/api.js", { pulse: false }]]));
});

test("a stop on no box selects no box but still jumps there", async () => {
  const outside = { ...WALK_REVIEW, walkthrough: [{ i: 1, title: "Docs", why: "w", path: "docs/readme.md", side: "R", line: 3, node: null }] };
  const { callouts, jumps, renders, emphasized, centered } = loadContent({ run: null, view: "files", review: outside });
  await settle();
  jumps.length = 0;
  await callouts.at(-1)[0].render().onGo(outside.walkthrough[0]);
  assert.equal(JSON.stringify(jumps), JSON.stringify([["docs/readme.md", "R", 3, { pulse: false }]]));
  assert.deepEqual(plain([renders.at(-1).state.selectedStop, emphasized.at(-1), centered]), [1, null, []]);
});

test("clicking Previous or Next quickly ends at the last stop clicked, jumping only there", async () => {
  const { callouts, jumps, emphasized } = loadContent({ run: null, view: "files", review: WALK_REVIEW });
  await settle();
  jumps.length = 0;
  const { onGo, stops } = callouts.at(-1)[0].render();
  await Promise.all([onGo(stops[1]), onGo(stops[2])]);
  assert.equal(JSON.stringify(jumps), JSON.stringify([["src/ui.js", "R", 30, { pulse: false }]]));
  assert.deepEqual(plain(emphasized.at(-1)), ["a"]);
});

test("opening the files page on a stop's diff anchor goes to that stop", async () => {
  const { fileJumps, emphasized } = loadContent({ run: null, view: "files", review: WALK_REVIEW, hash: "#diff-src/api.js" });
  await settle();
  assert.deepEqual(fileJumps, [["src/api.js", undefined]]);
  assert.deepEqual(plain(emphasized.at(-1)), ["b"]);
});

test("the sidebar opens with every stop listed and the first one current", async () => {
  const { renders, emphasized } = loadContent({ run: null, view: "files", review: WALK_REVIEW });
  await settle();
  const { state } = renders.at(-1);
  assert.deepEqual([state.stops.map((stop) => stop.i), state.selectedStop], [[1, 2, 3, 4], 1]);
  assert.deepEqual(Object.keys(state).sort(), ["chips", "fileSet", "mode", "note", "pageSha", "selectedStop", "stops"]);
  assert.deepEqual(plain(emphasized.at(-1)), ["a"]);
});

test("a fresh load selects stop 1 as a click on it would: box, pan, list and a jump to its line", async () => {
  const { renders, emphasized, centered, revealed, jumps, callouts } = loadContent({ run: null, view: "files", review: WALK_REVIEW });
  await settle();
  assert.deepEqual(plain([renders.at(-1).state.selectedStop, emphasized.at(-1), centered, revealed]), [1, ["a"], [["a"]], [1]]);
  assert.deepEqual(jumps, [["src/ui.js", "R", 4, undefined]]);
  assert.equal(callouts.at(-1).length, 4);
});

test("a page URL naming a diff line other than a stop's keeps the diff where it is and only follows stop 1 in the diagram", async () => {
  for (const hash of ["#diff-abc123R7", "#r123456", "#discussion_r98765"]) {
    const { renders, emphasized, centered, jumps, fileJumps } = loadContent({ run: null, view: "files", review: WALK_REVIEW, hash });
    await settle();
    assert.deepEqual(plain([renders.at(-1).state.selectedStop, emphasized.at(-1), centered, jumps, fileJumps]), [1, ["a"], [["a"]], [], []], hash);
  }
});

test("a fragment that names no diff line does not stop the load from jumping to stop 1", async () => {
  const { jumps } = loadContent({ run: null, view: "files", review: WALK_REVIEW, hash: "#files_bucket" });
  await settle();
  assert.equal(jumps.length, 1);
});

test("choosing a stop in the list goes to it and makes it the current stop", async () => {
  const { renders, jumps, revealed, emphasized } = loadContent({ run: null, view: "files", review: WALK_REVIEW });
  await settle();
  jumps.length = 0;
  revealed.length = 0;
  await renders.at(-1).handlers.onSelectStop(3);
  assert.deepEqual(jumps.map((jump) => jump.slice(0, 3)), [["src/ui.js", "R", 30]]);
  assert.deepEqual(revealed, [3]);
  assert.deepEqual(plain([renders.at(-1).state.selectedStop, emphasized.at(-1)]), [3, ["a"]]);
});

test("a reload lands on stop 1 again, whatever was selected before, and nothing is remembered", async () => {
  const first = loadContent({ run: null, view: "files", review: WALK_REVIEW });
  await settle();
  await first.renders.at(-1).handlers.onSelectStop(3);
  first.diagramHandlers.at(-1).onNode("b");
  await settle();
  await first.renders.at(-1).handlers.onMode("github");
  assert.deepEqual(plain(first.stored), {});
  const again = loadContent({ run: null, view: "files", review: WALK_REVIEW, stored: first.stored });
  await settle();
  assert.deepEqual(plain([again.renders.at(-1).state.mode, again.renders.at(-1).state.selectedStop, again.emphasized.at(-1), again.centered]), ["review", 1, ["a"], [["a"]]]);
});

test("every action that focuses a box centres the diagram on it", async () => {
  const { renders, callouts, centered, diagramHandlers } = loadContent({ run: null, view: "files", review: WALK_REVIEW });
  await settle();
  assert.deepEqual(plain(centered), [["a"]]);
  centered.length = 0;
  diagramHandlers.at(-1).onNode("b");
  await settle();
  assert.deepEqual(plain(centered), [["b"]]);
  await renders.at(-1).handlers.onSelectStop(2);
  assert.deepEqual(plain(centered.at(-1)), ["c"]);
  const { onGo, stops } = callouts.at(-1)[0].render();
  await onGo(stops[2]);
  assert.deepEqual(plain(centered.at(-1)), ["a"]);
  await renders.at(-1).handlers.onMode("github");
  assert.deepEqual(plain(centered.at(-1)), ["a"]);
});

test("every way into a stop zooms the diagram to it, and a click on a diagram box only pans", async () => {
  const { renders, callouts, centeredWith, diagramHandlers } = loadContent({ run: null, view: "files", review: WALK_REVIEW });
  await settle();
  assert.deepEqual(plain(centeredWith), [{ zoom: true }]);
  centeredWith.length = 0;
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
  const linked = loadContent({ run: null, view: "files", review: WALK_REVIEW, hash: "#diff-src/api.js" });
  await settle();
  assert.deepEqual(plain([linked.centered, linked.centeredWith]), [[["b"]], [{ zoom: true }]]);
});

test("the diagram's Reset restores the load-time state: nothing selected and no box marked", async () => {
  const { renders, callouts, emphasized, lineEvents, diagramHandlers } = loadContent({ run: null, view: "files", review: WALK_REVIEW });
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

test("Reset also clears a mode of GitHub's own tree", async () => {
  const { renders, emphasized, diagramHandlers } = loadContent({ run: null, view: "files", review: WALK_REVIEW });
  await settle();
  diagramHandlers.at(-1).onNode("b");
  await settle();
  await renders.at(-1).handlers.onMode("github");
  assert.equal(renders.at(-1).state.mode, "github");
  assert.equal(emphasized.at(-1), null);
  diagramHandlers.at(-1).onReset();
  await settle();
  assert.equal(renders.at(-1).state.mode, "review");
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
  const { jumps, diagramHandlers, renders, revealed } = loadContent({ run: null, view: "files", review: WALK_REVIEW });
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
  const { jumps, fileJumps, diagramHandlers, renders, scrolled, boxes, emphasized } = loadContent({ run: null, view: "files", review: NO_STOP_REVIEW });
  await settle();
  jumps.length = 0;
  diagramHandlers.at(-1).onNode("b");
  await settle();
  assert.deepEqual([jumps, fileJumps, scrolled], [[], [], ["src/api.js"]]);
  assert.deepEqual(plain([boxes.at(-1), emphasized.at(-1)]), [["src/api.js"], ["b"]]);
  assert.deepEqual([renders.at(-1).state.selectedStop, renders.at(-1).state.stops.map((stop) => stop.node)], [null, ["a", "c", "a"]]);
});

test("a box with a stop after a stop-less one clears the current stop only when it has none", async () => {
  const { diagramHandlers, renders } = loadContent({ run: null, view: "files", review: NO_STOP_REVIEW });
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
  const { jumps, scrolled, diagramHandlers, renders } = loadContent({ run: null, view: "files", review: WALK_REVIEW });
  await settle();
  const before = renders.length;
  jumps.length = 0;
  diagramHandlers.at(-1).onNode("d");
  diagramHandlers.at(-1).onNode("zzz");
  await settle();
  assert.deepEqual([jumps, scrolled, renders.length], [[], [], before]);
});

test("the sidebar's state and handlers are the stops and the mode", async () => {
  const { renders } = loadContent({ run: null, view: "files", review: WALK_REVIEW });
  await settle();
  assert.deepEqual(Object.keys(renders.at(-1).handlers).sort(), ["onFileSet", "onJump", "onMode", "onSelectFile", "onSelectStop"]);
});

const SET_REVIEW = {
  ...WALK_REVIEW,
  file_sets: { contract: ["src/api.js", "api.json"], data: [] },
  contract: [{ impact: "additive", text: "x", path: "api.json", side: "R", line: 5, source: { path: "src/api.js", side: "R", line: 12 } }],
  data: [],
};

test("the chips are All with the page's changed-file count and each non-empty set, and the whole tree shows until one is chosen", async () => {
  const { renders, filters } = loadContent({ run: null, view: "files", review: SET_REVIEW });
  await settle();
  assert.deepEqual(plain(renders.at(-1).state.chips), [
    { id: "all", label: "All", count: 9 },
    { id: "contract", label: "Contract", count: 2 },
  ]);
  assert.equal(renders.at(-1).state.fileSet, null);
  assert.equal(filters.at(-1), null);
});

test("choosing a chip narrows the pane and the tree to the set without moving the diagram, and All restores them", async () => {
  const { renders, filters, centered, jumps, fileJumps } = loadContent({ run: null, view: "files", review: SET_REVIEW });
  await settle();
  await renders.at(-1).handlers.onSelectStop(1);
  centered.length = 0;
  jumps.length = 0;
  await renders.at(-1).handlers.onFileSet("contract");
  assert.deepEqual(plain(renders.at(-1).state.fileSet), { id: "contract", paths: ["src/api.js", "api.json"], lines: SET_REVIEW.contract });
  assert.deepEqual(plain(filters.at(-1)), ["src/api.js", "api.json"]);
  assert.deepEqual([centered, jumps, fileJumps, renders.at(-1).state.selectedStop], [[], [], [], 1]);
  await renders.at(-1).handlers.onFileSet("all");
  assert.equal(renders.at(-1).state.fileSet, null);
  assert.equal(filters.at(-1), null);
});

test("a no-stop row lands on its file's header and marks it, and a link in the set's table jumps to its line or file", async () => {
  const { renders, scrolled, boxes, jumps, fileJumps } = loadContent({ run: null, view: "files", review: SET_REVIEW });
  await settle();
  await renders.at(-1).handlers.onFileSet("contract");
  await renders.at(-1).handlers.onSelectFile("api.json");
  assert.deepEqual([scrolled, plain(boxes.at(-1)), renders.at(-1).state.selectedStop], [["api.json"], ["api.json"], null]);
  jumps.length = 0;
  await renders.at(-1).handlers.onJump({ path: "src/api.js", side: "R", line: 12 });
  await renders.at(-1).handlers.onJump({ path: "api.json", side: null, line: null });
  assert.deepEqual([jumps, fileJumps], [[["src/api.js", "R", 12, undefined]], [["api.json", undefined]]]);
});
