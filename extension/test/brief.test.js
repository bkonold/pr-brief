const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const githubPage = require("../github_page.js");
const forgejoPage = require("../forgejo_page.js");
const briefText = require("../brief_text.js");
const runControl = require("../run_control.js");
const { buildBrief, buildCard, cardHtml, isStale } = require("../brief.js");

const FILES_URL = "http://forge.example/acme/widgets/pulls/7/files";

function row(name, files, extra = "") {
  const cells = files
    .map((file) => `<tr><td><code title="src">src</code><br><a href="https://github.com/acme/widgets/pull/7/files#diff-${file}"><strong>${file}.js</strong></a> +1/-0</td></tr>`)
    .join("");
  return `<tr><td>1</td><td><strong>${name}</strong><br><sub>start <a href="https://github.com/acme/widgets/pull/7/changes#diff-${files[0]}R12" title="src/${files[0]}.js">${files[0]}.js:12</a></sub>${extra}</td><td>read</td><td>why</td><td><table>${cells}</table></td></tr>`;
}

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
  'Legend: <span style="display:inline-block;width:14px;background:#fff"></span> changed step',
  "",
  "<details open> <summary><h3> Review order</h3></summary>",
  "",
  `<table class="review-order"><thead><tr><th>#</th><th>Chunk</th><th>Review</th><th>Why</th><th>Files</th></tr></thead><tbody>${row("First chunk", ["alpha", "beta"])}${row("Second chunk", ["gamma"])}</tbody></table>`,
  "",
  "</details>",
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
  const { html, legend } = briefText.renderBody(bodyHtml(hostile), FILES_URL);
  for (const text of [html, legend]) {
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
  const { html, legend } = briefText.renderBody(bodyHtml(), FILES_URL);
  assert.doesNotMatch(html, /Example title|mermaid|flowchart|Diagram Walkthrough|pr-agent-generated|Legend/);
  assert.match(html, /<h3><strong>PR Type<\/strong><\/h3>/);
  assert.match(html, /<li>Adds <code>thing<\/code> to the pipeline\n<ul>\n<li>nested <strong>point<\/strong>/);
  assert.match(legend, /^Legend: <span style="display:inline-block; width:14px; background:#fff"><\/span> changed step$/);
});

test("each chunk's file list is a closed details headed by its file count", () => {
  const { html } = briefText.renderBody(bodyHtml(), FILES_URL);
  const lists = html.match(/<details class="files">.*?<\/details>/gs);
  assert.equal(lists.length, 2);
  assert.match(lists[0], /^<details class="files"><summary>2 files<\/summary><table>.*alpha\.js.*beta\.js.*<\/table><\/details>$/s);
  assert.match(lists[1], /<summary>1 file<\/summary>/);
  assert.doesNotMatch(html, /<details[^>]*\bopen\b/);
  assert.equal(html.match(/<table>/g).length, 2);
});

test("each chunk's start is a closed Start here details that keeps the rewritten link and the quote", () => {
  const withQuote = MARKDOWN.replace(row("First chunk", ["alpha", "beta"]), row("First chunk", ["alpha", "beta"], "<br><code>int total = 0;</code>"));
  const { html } = briefText.renderBody(bodyHtml(withQuote), FILES_URL);
  const starts = html.match(/<details class="start">.*?<\/details>/gs);
  assert.equal(starts.length, 2);
  assert.equal(
    starts[0],
    '<details class="start"><summary>Start here</summary><sub><a href="http://forge.example/acme/widgets/pulls/7/files#diff-alphaR12" title="src/alpha.js">alpha.js:12</a></sub><br><code>int total = 0;</code></details>',
  );
  assert.equal(
    starts[1],
    '<details class="start"><summary>Start here</summary><sub><a href="http://forge.example/acme/widgets/pulls/7/files#diff-gammaR12" title="src/gamma.js">gamma.js:12</a></sub></details>',
  );
  assert.match(html, /<strong>First chunk<\/strong><details class="start">/);
  assert.doesNotMatch(html, /<sub>start /);
  assert.doesNotMatch(html, /<details class="start"[^>]*\bopen\b/);
});

test("a chunk with no start is left alone", () => {
  const cell = '<td>1</td><td><strong>No start</strong></td><td>read</td>';
  const table = `<table class="review-order"><tbody><tr>${cell}</tr></tbody></table>`;
  assert.equal(briefText.foldStarts(table), table);
  assert.equal(briefText.foldStarts("<p>no table</p>"), "<p>no table</p>");
});

test("the review order's own details is not open either", () => {
  const { html } = briefText.renderBody(bodyHtml(), FILES_URL);
  assert.match(html, /<details> <summary><h3> Review order<\/h3><\/summary>/);
});

test("links into the files view point at this host's files view and keep their fragment", () => {
  const { html } = briefText.renderBody(bodyHtml(), FILES_URL);
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
    assert.match(diagramBox[1], /^<figure class="diagram">.*<svg viewBox="0 0 10 10">.*<p class="legend">Legend:.*<\/figure>$/s);
    const at = (needle) => shadow.indexOf(needle);
    assert.ok(at("Second point") < at('<details class="diagram-box">'), "the diagram follows the description's bullets");
    assert.ok(at('<details class="diagram-box">') < at("Review order"), "the diagram precedes the review order");
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
function loadContent({ run, status = { ok: true, state: "idle", allowed: true }, hostPresent = true, pageSha = null, view = "conversation", review = null }) {
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
  const emphasized = [];
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
      cancelJump() {},
      clearLineTarget() {},
      fileBlocks: () => new Map(),
      headSha: () => null,
      restoreLineTarget() {},
      ownsLine: () => false,
      jumpToLine: async (...args) => jumps.push(args.slice(0, 3)),
    },
    boxes: require("../boxes.js"),
    source: {
      loadBrief: async () => run,
      loadReview: async () => review,
      runStatus: async (target) => (calls.push(["status", target]), status),
      startRun: async (target) => (calls.push(["start", target]), { ok: true, key: target.key, state: "running" }),
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
      orderChunks: require("../tree.js").orderChunks,
      defaultOrder: require("../tree.js").defaultOrder,
      EXTRA_KEY: "extra",
      render: (shownReview, state, handlers) => renders.push({ review: shownReview, state, handlers }),
      renderGenerateLine: (shown, handlers) => lines.push({ shown, handlers }),
      readFirstReason: require("../tree.js").readFirstReason,
      flashRows() {},
      revealGroup() {},
      remove() {},
      owns: () => false,
    },
    focus: { apply: async () => ({}), clearBox() {}, markBox() {}, scrollTo: async () => {}, announceBox() {}, owns: () => false },
    diagram: {
      render() {},
      emphasize: (nodes) => emphasized.push(nodes),
      setActive() {},
      titleOf: () => "",
      pulse() {},
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
  const context = { prFocus, location: { href: "x", hash: "" }, console: consoleSpy, setTimeout: unref(setTimeout), clearTimeout, setInterval: unref(setInterval), clearInterval, Date, Promise };
  context.globalThis = context;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../content.js"), "utf8"), context);
  return { log, built, navigations, output, calls, lines, renders, jumps, emphasized };
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

test("a files page whose repository the server will not run shows no line", async () => {
  const { lines } = loadContent({ run: null, view: "files", status: { ok: true, state: "idle", allowed: false } });
  await settle();
  assert.deepEqual(lines, []);
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

function ranked(n, name, risk, files = ["alpha"]) {
  return `<tr data-flow="${n}" data-risk="${risk}"><td>${n}<br><sub>step ${n}</sub></td><td><strong>${name}</strong></td><td>read</td><td>why</td><td><table>${files
    .map((file) => `<tr><td><a href="https://github.com/acme/widgets/pull/7/files#diff-${file}">${file}.js</a></td></tr>`)
    .join("")}</table></td></tr>`;
}

const ORDER_ROWS = [ranked(1, "Screen", 0), ranked(2, "Endpoint", 1, ["beta", "gamma"]), ranked(3, "Table", 2), ranked(4, "Tests", 0), ranked(5, "Unchunked", -1)];
const ORDER_MARKDOWN = [
  "# T",
  "",
  "### **Description**",
  "text",
  "",
  "___",
  "",
  "<details open> <summary><h3> Review order</h3></summary>",
  "",
  `<table class="review-order"><thead><tr><th>#</th><th>Chunk</th></tr></thead><tbody>${ORDER_ROWS.join("")}</tbody></table>`,
  "",
  "</details>",
  "",
].join("\n");
const names = (html) => [...html.matchAll(/<tr data-flow="\d+" data-risk="-?\d+"><td>\d+<br><sub>[^<]*<\/sub><\/td><td><strong>([^<]*)</g)].map((match) => match[1]);

test("orderRows puts the chunks in flow order, or by risk with ties in flow order and the catch-all last", () => {
  const html = briefText.renderBody(bodyHtml(ORDER_MARKDOWN), FILES_URL).html;
  assert.deepEqual(names(briefText.orderRows(html, "flow")), ["Screen", "Endpoint", "Table", "Tests", "Unchunked"]);
  assert.deepEqual(names(briefText.orderRows(html, "risk")), ["Table", "Endpoint", "Screen", "Tests", "Unchunked"]);
});

test("orderRows moves a row with its nested file list whole and leaves the rest of the html alone", () => {
  const html = briefText.renderBody(bodyHtml(ORDER_MARKDOWN), FILES_URL).html;
  const risk = briefText.orderRows(html, "risk");
  assert.equal(risk.length, html.length);
  assert.ok(risk.startsWith(html.slice(0, html.indexOf("<tr data-flow"))));
  assert.ok(risk.endsWith(html.slice(html.lastIndexOf("</tbody>"))));
  const endpoint = /<tr data-flow="2"[^]*?<\/details><\/td><\/tr>/.exec(risk)[0];
  assert.match(endpoint, /2 files<\/summary>.*diff-beta.*diff-gamma/s);
  assert.equal(briefText.orderRows(risk, "flow"), html);
});

test("html with no ranked rows is returned as it is in either order", () => {
  const html = briefText.renderBody(bodyHtml(), FILES_URL).html;
  assert.equal(briefText.hasOrders(html), false);
  assert.equal(briefText.orderRows(html, "risk"), html);
  assert.equal(briefText.orderRows("<p>none</p>", "flow"), "<p>none</p>");
});

test("the rank attributes survive sanitizing while event handlers on the same row do not", () => {
  const html = briefText.sanitize('<tr data-flow="2" onclick="x()" data-risk="1" data-evil="y"><td>a</td></tr>');
  assert.equal(html, '<tr data-flow="2" data-risk="1"><td>a</td></tr>');
});

test("a review order with ranks opens in flow order with an Order switch, and the risk view reorders it", () => {
  const view = { kind: "brief", variant: "v16", bodyHtml: bodyHtml(ORDER_MARKDOWN), diagramSvg: null };
  const flow = cardHtml(view, CARD);
  assert.deepEqual(names(flow), ["Screen", "Endpoint", "Table", "Tests", "Unchunked"]);
  assert.match(flow, /<\/summary><div class="order-switch">Order: <button class="link" type="button" data-action="order:flow" aria-pressed="true">by flow<\/button> \| <button class="link" type="button" data-action="order:risk" aria-pressed="false">by risk<\/button><\/div>/);
  const risk = cardHtml({ ...view, order: "risk" }, CARD);
  assert.deepEqual(names(risk), ["Table", "Endpoint", "Screen", "Tests", "Unchunked"]);
  assert.match(risk, /data-action="order:risk" aria-pressed="true"/);
});

test("a run without ranks shows no Order switch", () => {
  const html = cardHtml({ kind: "brief", variant: "v15", bodyHtml: bodyHtml(), diagramSvg: null }, CARD);
  assert.doesNotMatch(html, /order-switch|order:/);
});

test("the Contract and data block renders as a list of links into the files view, with its fragments kept", () => {
  const markdown = [
    "# T",
    "",
    "### **Description**",
    "text",
    "",
    "___",
    "",
    "### **Contract and data**",
    '<ul class="contract">',
    '<li><a href="https://github.com/acme/widgets/pull/7/files#diff-abcR40"><code>GET /widgets</code></a> · <a href="https://github.com/acme/widgets/pull/7/files#diff-abcR41"><strong>size now required</strong></a></li>',
    '<li><a href="https://github.com/acme/widgets/pull/7/files#diff-defR3"><code>orders</code></a> <sub>table</sub> · <a href="https://github.com/acme/widgets/pull/7/files#diff-defR3">CREATE TABLE</a></li>',
    "</ul>",
    "",
    "<sub>Database changes not checked</sub>",
    "",
    "___",
    "",
  ].join("\n");
  const html = cardHtml({ kind: "brief", variant: "v16", bodyHtml: bodyHtml(markdown), diagramSvg: null }, CARD);
  assert.match(html, /<h3><strong>Contract and data<\/strong><\/h3>\s*<ul class="contract">/);
  assert.match(html, /<a href="http:\/\/forge\.example\/acme\/widgets\/pulls\/7\/files#diff-abcR40"><code>GET \/widgets<\/code><\/a>/);
  assert.match(html, /<strong>size now required<\/strong>/);
  assert.match(html, /<code>orders<\/code><\/a> <sub>table<\/sub>/);
  assert.match(html, /<sub>Database changes not checked<\/sub>/);
});

function interactiveDocument() {
  const order = { innerHTML: "", opened: false };
  const details = { get open() { return order.opened; }, setAttribute: () => { order.opened = true; } };
  order.querySelector = () => details;
  const handlers = [];
  const document = {
    order,
    handlers,
    createElement: () => ({
      attributes: {},
      setAttribute(name, value) {
        this.attributes[name] = value;
      },
      attachShadow() {
        this.shadow = {
          innerHTML: "",
          addEventListener: (type, handler) => handlers.push(handler),
          querySelector: (selector) => (selector === ".order" ? order : null),
        };
        return this.shadow;
      },
    }),
  };
  const click = (action) => {
    let prevented = false;
    const target = { closest: () => ({ getAttribute: () => action }) };
    for (const handler of handlers) handler({ target, preventDefault: () => (prevented = true) });
    return prevented;
  };
  return { document, click };
}

test("the Order buttons reorder the open review order in place and never reach onAction", () => {
  const { document, click } = interactiveDocument();
  globalThis.document = document;
  try {
    const actions = [];
    const host = buildCard({ key: "fj-7", filesUrl: FILES_URL, onAction: (action) => actions.push(action) });
    host.show({ kind: "brief", variant: "v16", bodyHtml: bodyHtml(ORDER_MARKDOWN), diagramSvg: null });
    document.order.opened = true;
    assert.equal(click("order:risk"), true);
    assert.deepEqual(names(document.order.innerHTML), ["Table", "Endpoint", "Screen", "Tests", "Unchunked"]);
    assert.equal(document.order.opened, true);
    click("order:flow");
    assert.deepEqual(names(document.order.innerHTML), ["Screen", "Endpoint", "Table", "Tests", "Unchunked"]);
    click("generate");
    assert.deepEqual(actions, ["generate"]);
    host.show({ kind: "brief", variant: "v16", bodyHtml: bodyHtml(ORDER_MARKDOWN), diagramSvg: null });
    assert.deepEqual(names(host.shadow.innerHTML), ["Screen", "Endpoint", "Table", "Tests", "Unchunked"]);
  } finally {
    delete globalThis.document;
  }
});

const STEP_REVIEW = {
  schema: 2,
  repo: "acme/widgets",
  pr: 7,
  variant: "v16",
  diagramSvg: "<svg></svg>",
  chunks: [
    { n: 1, name: "Screen", step: "UI", review: "skim", why: "w", nodes: ["a"], files: [{ path: "src/ui.js" }], start: { path: "src/ui.js", side: "R", line: 4, text: "x" } },
    { n: 2, name: "Endpoint", step: "API", review: "read", why: "w", nodes: ["b"], files: [{ path: "src/api.js" }], start: { path: "src/api.js", side: "R", line: 9, text: "y" } },
    { n: 3, name: "Table", step: "Database", review: "read carefully", why: "w", nodes: ["c"], files: [{ path: "db/V1.sql" }], start: { path: "db/V1.sql", side: "R", line: 2, text: "z" } },
  ],
};

test("a files page opens in flow order when the run has steps, and the switch reorders the list", async () => {
  const { renders } = loadContent({ run: null, view: "files", review: STEP_REVIEW });
  await settle();
  const names = (render) => require("../tree.js").orderChunks(render.review.chunks, render.state.order).map((chunk) => chunk.name);
  assert.equal(renders.at(-1).state.order, "flow");
  assert.deepEqual(names(renders.at(-1)), ["Screen", "Endpoint", "Table"]);
  renders.at(-1).handlers.onOrder("risk");
  await settle();
  assert.equal(renders.at(-1).state.order, "risk");
  assert.deepEqual(names(renders.at(-1)), ["Table", "Endpoint", "Screen"]);
  assert.equal(renders.at(-1).state.selectedN, null);
});

test("a run with no steps opens by risk and its switch is not offered", async () => {
  const withoutSteps = { ...STEP_REVIEW, chunks: STEP_REVIEW.chunks.map(({ step, ...chunk }) => chunk) };
  const { renders } = loadContent({ run: null, view: "files", review: withoutSteps });
  await settle();
  assert.equal(renders.at(-1).state.order, "risk");
  assert.equal(require("../tree.js").hasSteps(withoutSteps.chunks), false);
});

test("a chunk's start jump and the diagram highlight work in both orders", async () => {
  const { renders, jumps, emphasized } = loadContent({ run: null, view: "files", review: STEP_REVIEW });
  await settle();
  for (const order of ["flow", "risk"]) {
    renders.at(-1).handlers.onOrder(order);
    await settle();
    const { handlers } = renders.at(-1);
    jumps.length = 0;
    await handlers.onJumpToStart(3);
    assert.deepEqual(jumps, [["db/V1.sql", "R", 2]]);
    await handlers.onSelectChunk(2);
    assert.deepEqual(emphasized.at(-1), ["b"]);
    assert.equal(renders.at(-1).state.order, order);
    await renders.at(-1).handlers.onSelectChunk(2);
    assert.deepEqual(emphasized.at(-1), null);
  }
});
