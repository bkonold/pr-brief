const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const githubPage = require("../github_page.js");
const forgejoPage = require("../forgejo_page.js");
const briefText = require("../brief_text.js");
const { buildBrief } = require("../brief.js");

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
// is a recording element, and a source that answers with `run`.
function loadContent({ run, hostPresent = true }) {
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
  const prFocus = {
    page: {
      name: "Fake",
      prFromUrl: () => ({ owner: "acme", repo: "widgets", pr: 7, view: "conversation" }),
      runKey: (pr) => `fj-${pr.pr}`,
      filesUrl: () => FILES_URL,
      descriptionHost: () => (hostPresent ? description : null),
      onNavigate: (callback) => (navigations.push(callback), () => {}),
      onChange: () => () => {},
    },
    source: { loadBrief: async () => run },
    brief: {
      buildBrief: (options) => {
        built.push(options);
        return { isConnected: true, nextElementSibling: null, remove() {}, placed: 0 };
      },
    },
    tree: {},
    alive: () => true,
  };
  const output = [];
  const consoleSpy = { log: (...a) => output.push(a), warn: (...a) => output.push(a), error: (...a) => output.push(a), info: (...a) => output.push(a), debug: (...a) => output.push(a) };
  const context = { prFocus, location: { href: "x" }, console: consoleSpy, setTimeout, clearTimeout, Date };
  context.globalThis = context;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../content.js"), "utf8"), context);
  return { log, built, navigations, output };
}

const settle = () => new Promise((resolve) => setImmediate(resolve));

test("nothing is built, placed or logged when the PR has no run", async () => {
  const { built, log, output } = loadContent({ run: null });
  await settle();
  assert.deepEqual([built, log, output], [[], [], []]);
});

test("one card is built for a run, however many times the page announces a navigation", async () => {
  const { built, log, navigations } = loadContent({ run: { variant: "v1", bodyHtml: "<p>x</p>", diagramSvg: null } });
  await settle();
  for (const navigate of navigations) {
    navigate();
    navigate();
  }
  await settle();
  assert.equal(built.length, 1);
  assert.deepEqual({ ...built[0] }, { key: "fj-7", variant: "v1", bodyHtml: "<p>x</p>", diagramSvg: null, filesUrl: FILES_URL });
  assert.deepEqual(log, ["placed"]);
});

test("the card waits for the description to exist before it is placed", async () => {
  const { built, log } = loadContent({ run: { variant: "v1", bodyHtml: "<p>x</p>", diagramSvg: null }, hostPresent: false });
  await settle();
  assert.equal(built.length, 1);
  assert.deepEqual(log, []);
});
