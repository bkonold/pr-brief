const test = require("node:test");
const assert = require("node:assert/strict");

const { createHash } = require("node:crypto");

const githubPage = require("../github_page.js");
const forgejoPage = require("../forgejo_page.js");
const { chooseAdapter } = require("../page.js");
const { prFromUrl, pullFromUrl, lineAnchor, stickyOffset, startDistance, landingDelta, calloutDelta, holdPlace, correctLanding } = githubPage;
const { staleMessage, revealTarget } = require("../tree.js");
const { nodeIdOf, edgeEnds, unsafeAttribute, clampWidth, defaultWidth, widestBox, captionFor, walkScale } = require("../diagram.js");

test("prFromUrl matches the changes and files pages", () => {
  const expected = { owner: "example-org", repo: "example-repo", pr: 42, view: "files" };
  assert.deepEqual(prFromUrl({ pathname: "/example-org/example-repo/pull/42/changes" }), expected);
  assert.deepEqual(prFromUrl({ pathname: "/example-org/example-repo/pull/42/files" }), expected);
  assert.deepEqual(prFromUrl({ pathname: "/example-org/example-repo/pull/42/changes/abc..def" }), expected);
  assert.deepEqual(prFromUrl("https://github.com/example-org/example-repo/pull/42/files?w=1#diff-abc"), expected);
});

test("prFromUrl rejects other pages", () => {
  assert.equal(prFromUrl({ pathname: "/o/r/pull/1/commits" }), null);
  assert.equal(prFromUrl({ pathname: "/o/r/pull/1/changesfoo" }), null);
  assert.equal(prFromUrl({ pathname: "/o/r/issues/1/files" }), null);
});

test("pullFromUrl matches any pull request page", () => {
  assert.deepEqual(pullFromUrl({ pathname: "/o/r/pull/7" }), { owner: "o", repo: "r", pr: 7 });
  assert.deepEqual(pullFromUrl({ pathname: "/o/r/pull/7/commits" }), { owner: "o", repo: "r", pr: 7 });
  assert.equal(pullFromUrl({ pathname: "/o/r/pulls" }), null);
});

test("staleMessage reports only a known, different head", () => {
  const sha = "a1b2c3d4e5f60718293a4b5c6d7e8f90abcdef01";
  const other = "1".repeat(40);
  assert.equal(staleMessage({ head_sha: sha }, sha.toUpperCase()), null);
  assert.equal(staleMessage({ head_sha: sha }, null), null);
  assert.equal(
    staleMessage({ head_sha: sha }, other),
    "Review was generated for a1b2c3d; the PR has newer commits. Focus still works by path.",
  );
});

test("lineAnchor joins the diff block id with the side and line", async () => {
  const path = "api/src/main/java/com/example/Foo.java";
  const id = `diff-${createHash("sha256").update(path).digest("hex")}`;
  assert.equal(await lineAnchor(path, "R", 42), `${id}R42`);
  assert.equal(await lineAnchor(path, "L", 7), `${id}L7`);
});

test("loadReview returns null once the extension context is gone", async () => {
  const runtime = { id: "abc", sendMessage: async () => ({ schema: 2 }) };
  globalThis.chrome = { runtime };
  const source = require("../source.js");
  assert.equal(source.alive(), true);
  assert.deepEqual(await source.loadReview("o", "r", 1), { schema: 2 });

  runtime.sendMessage = () => {
    throw new Error("Extension context invalidated.");
  };
  assert.equal(await source.loadReview("o", "r", 1), null);

  runtime.id = undefined;
  assert.equal(source.alive(), false);
  assert.equal(await source.loadReview("o", "r", 1), null);
  delete globalThis.chrome;
});

test("nodeIdOf reads Mermaid's flowchart node ids, including underscores and dashes", () => {
  assert.equal(nodeIdOf("pr-diagram-flowchart-A-0"), "A");
  assert.equal(nodeIdOf("pr-diagram-flowchart-item_list-12"), "item_list");
  assert.equal(nodeIdOf("pr-diagram-flowchart-ui-api-3"), "ui-api");
  assert.equal(nodeIdOf("pr-diagram-L_A_B_0"), null);
  assert.equal(nodeIdOf(null), null);
});

test("edgeEnds resolves both nodes of an edge id from the known node ids", () => {
  const ids = new Set(["A", "B", "item_list", "list", "list_item"]);
  assert.deepEqual(edgeEnds("L_A_B_0", ids), ["A", "B"]);
  assert.deepEqual(edgeEnds("L_item_list_list_item_2", ids), ["item_list", "list_item"]);
  assert.deepEqual(edgeEnds("L_list_A_1", ids), ["list", "A"]);
  assert.equal(edgeEnds("L_A_Z_0", ids), null);
  assert.equal(edgeEnds("flowchart-A-0", ids), null);
});

test("edgeEnds matches every edge of a rendered run diagram", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const runs = path.join(__dirname, "..", "..", "runs");
  if (!fs.existsSync(runs)) return;
  const file = fs.readdirSync(runs).map((pr) => path.join(runs, pr, "one_path_risk_chunked_v15", "diagram.svg")).find(fs.existsSync);
  if (!file) return;
  const svg = fs.readFileSync(file, "utf8");
  const ids = new Set([...svg.matchAll(/id="[^"]*?(flowchart-[^"]+-\d+)"/g)].map((m) => nodeIdOf(m[1])));
  const edges = [...svg.matchAll(/data-edge="true"[^>]*data-id="([^"]+)"|data-id="([^"]+)"[^>]*data-edge="true"/g)].map((m) => m[1] ?? m[2]);
  assert.ok(ids.size > 0);
  for (const edge of edges) assert.ok(edgeEnds(edge, ids), edge);
});

test("unsafeAttribute flags event handlers and javascript links only", () => {
  assert.equal(unsafeAttribute("onclick", "x()"), true);
  assert.equal(unsafeAttribute("onmouseover", ""), true);
  assert.equal(unsafeAttribute("xlink:href", " javascript:alert(1)"), true);
  assert.equal(unsafeAttribute("href", "JavaScript:alert(1)"), true);
  assert.equal(unsafeAttribute("href", "#a"), false);
  assert.equal(unsafeAttribute("class", "node"), false);
  assert.equal(unsafeAttribute("data-id", "L_A_B_0"), false);
});

test("without a box to size by, the default width is a fifth of the viewport and never below 220px", () => {
  assert.equal(defaultWidth(1680), 336);
  assert.equal(defaultWidth(1000), 220);
  assert.equal(defaultWidth(1100), 220);
  assert.equal(defaultWidth(2560), 512);
  assert.equal(defaultWidth(300), 220);
  assert.equal(defaultWidth(undefined), 220);
  assert.equal(defaultWidth(1680, 0), 336);
});

test("defaultWidth is the width at which the walkthrough zoom is 1:1 for the widest box with its halo, in whole pixels", () => {
  assert.equal(defaultWidth(1440, 340), 414);
  assert.equal(defaultWidth(1512, 340), 414);
  assert.equal(defaultWidth(2560, 340), 414);
  assert.equal(defaultWidth(1680, 340), 414);
  assert.equal(defaultWidth(1680, 340.2), 415);
  assert.equal(defaultWidth(1680, 100), 220);
});

test("a panel of the default width draws the widest box at exactly 100% in the walkthrough", () => {
  for (const box of [240, 340, 341.5, 500]) {
    const viewport = { w: defaultWidth(2560, box) - 14 };
    assert.equal(walkScale({ w: box + 20 }, viewport), 1);
  }
});

test("defaultWidth never takes more than 40% of the viewport, and never less than 220px", () => {
  assert.equal(defaultWidth(1000, 340), 400);
  assert.equal(defaultWidth(900, 340), 360);
  assert.equal(defaultWidth(700, 340), 280);
  assert.equal(defaultWidth(500, 340), 220);
});

test("widestBox is the widest node's own rectangle, in diagram units", () => {
  const node = (width) => ({ querySelector: () => (width === null ? null : { getAttribute: () => width }) });
  const svg = (...nodes) => ({ querySelectorAll: () => nodes });
  assert.equal(widestBox(svg(node("300"), node("340"), node("320"))), 340);
  assert.equal(widestBox(svg(node(null), node("150.5"))), 150.5);
  assert.equal(widestBox(svg(node(null))), 0);
  assert.equal(widestBox(svg()), 0);
});

test("clampWidth keeps the panel between 220px and 65% of the viewport", () => {
  assert.equal(clampWidth(400, 1680), 400);
  assert.equal(clampWidth(100, 1680), 220);
  assert.equal(clampWidth(2000, 1680), 1092);
  assert.equal(clampWidth(1092.4, 1680), 1092);
  assert.equal(clampWidth(500, 1000), 500);
  assert.equal(clampWidth(900, 1000), 650);
  assert.equal(clampWidth(300, 200), 220);
  assert.equal(clampWidth(NaN, 1680), 336);
  assert.equal(clampWidth(NaN, 800), 220);
  assert.equal(clampWidth(undefined, 1680), 336);
});

test("captionFor explains the dashed boxes only when the diagram has one", () => {
  const svgWith = (context) => ({ querySelector: (selector) => (selector === "g.node.context" && context ? {} : null) });
  assert.equal(captionFor(svgWith(true)), "Dashed boxes are unchanged context");
  assert.equal(captionFor(svgWith(false)), "");
});

test("classifyFetch tells a down server from a missing review", async () => {
  const { classifyFetch } = await import("../classify.js");
  assert.equal(classifyFetch(undefined, new TypeError("Failed to fetch")), "server");
  assert.equal(classifyFetch({ ok: false, status: 404 }, undefined), "none");
  assert.equal(classifyFetch({ ok: true, status: 200 }, undefined), "ok");
});

test("stickyOffset is the lowest stuck edge over the diff column", () => {
  const column = { left: 300, right: 900 };
  const header = { top: 0, height: 60, left: 0, right: 1400 };
  const toolbar = { top: 60, height: 44, left: 280, right: 920 };
  const tree = { top: 104, height: 800, left: 0, right: 280 };
  const diagram = { top: 0, height: 900, left: 920, right: 1200 };
  const footer = { top: 700, height: 48, left: 0, right: 1400 };
  assert.equal(stickyOffset([header, toolbar, tree, diagram, footer], column, 300), 104);
  assert.equal(stickyOffset([header], column, 300), 60);
  assert.equal(stickyOffset([tree, diagram, footer], column, 300), 0);
  assert.equal(stickyOffset([{ ...header, height: 0 }], column, 300), 0);
  assert.equal(stickyOffset([], column, 300), 0);
});

test("startDistance measures the entry against the sticky offset, wherever its sticky header is", () => {
  assert.equal(startDistance(1984, 104), 1880);
  assert.equal(startDistance(-300, 104), -404);
  assert.equal(startDistance(104, 104), 0);
});

test("revealTarget scrolls the list only when the span is not fully visible", () => {
  const view = { scrollTop: 100, height: 400 };
  assert.equal(revealTarget({ ...view, top: 150, bottom: 450 }), null);
  assert.equal(revealTarget({ ...view, top: 100, bottom: 500 }), null);
  assert.equal(revealTarget({ ...view, top: 450, bottom: 600 }), 208);
  assert.equal(revealTarget({ ...view, top: 20, bottom: 120 }), 12);
  assert.equal(revealTarget({ ...view, top: 2, bottom: 60, scrollTop: 40 }), 0);
  assert.equal(revealTarget({ ...view, top: 700, bottom: 1300 }), 692);
});

test("landingDelta asks for a correction only beyond one pixel", () => {
  assert.equal(landingDelta(60, 60), 0);
  assert.equal(landingDelta(61, 60), 0);
  assert.equal(landingDelta(59.4, 60), 0);
  assert.equal(landingDelta(854, 60), 794);
  assert.equal(landingDelta(-12, 60), -72);
});

test("correctLanding nudges until the entry is in place, then stops", async () => {
  let top = 300;
  const nudges = [];
  const settled = await correctLanding({
    idle: async () => {},
    delta: () => top - 60,
    nudge: (distance) => {
      nudges.push(distance);
      top -= distance;
    },
    isCurrent: () => true,
  });
  assert.equal(settled, true);
  assert.deepEqual(nudges, [240]);
});

test("correctLanding stops at once when a newer scroll has taken over", async () => {
  let token = 1;
  const nudges = [];
  const settled = await correctLanding({
    idle: async () => {
      token = 2;
    },
    delta: () => 500,
    nudge: (distance) => nudges.push(distance),
    isCurrent: () => token === 1,
  });
  assert.equal(settled, false);
  assert.deepEqual(nudges, []);
});

test("correctLanding gives up after its passes when the entry keeps moving", async () => {
  let nudged = 0;
  const settled = await correctLanding({ idle: async () => {}, delta: () => 50, nudge: () => (nudged += 1), isCurrent: () => true, passes: 3 });
  assert.equal(settled, false);
  assert.equal(nudged, 3);
});

const LIMITS = { scrollTop: 2000, scrollMax: 9000 };

test("calloutDelta puts a callout 16px below the sticky chrome and asks for no correction within a pixel", () => {
  assert.equal(calloutDelta(1000, 104, LIMITS), 880);
  assert.equal(calloutDelta(-300, 104, LIMITS), -420);
  assert.equal(calloutDelta(120, 104, LIMITS), 0);
  assert.equal(calloutDelta(121, 104, LIMITS), 0);
  assert.equal(calloutDelta(122.5, 104, LIMITS), 2.5);
});

test("calloutDelta places a line stop and a file stop alike: the sticky chrome plus the file header, then 16px", () => {
  const chrome = 60;
  const header = 44;
  const place = (calloutTop) => calloutDelta(calloutTop, chrome + header, LIMITS);
  assert.equal(place(chrome + header + 16), 0);
  assert.equal(place(700), 700 - 120);
});

test("calloutDelta lands as close as it can near the top and the bottom of the page", () => {
  assert.equal(calloutDelta(1000, 104, { scrollTop: 8900, scrollMax: 9000 }), 100);
  assert.equal(calloutDelta(1000, 104, { scrollTop: 9000, scrollMax: 9000 }), 0);
  assert.equal(calloutDelta(-90, 104, { scrollTop: 40, scrollMax: 9000 }), -40);
  assert.equal(calloutDelta(-90, 104, { scrollTop: 0, scrollMax: 9000 }), 0);
});

function fakeHold({ delta }) {
  const log = { nudges: [], observing: 0, listening: 0 };
  let layoutChanged = null;
  let userInput = null;
  const release = holdPlace({
    delta,
    nudge: (distance) => log.nudges.push(distance),
    observe: (callback) => {
      layoutChanged = callback;
      log.observing += 1;
      return () => (log.observing -= 1);
    },
    onInput: (callback) => {
      userInput = callback;
      log.listening += 1;
      return () => (log.listening -= 1);
    },
  });
  return { log, release, shift: () => layoutChanged(), input: () => userInput() };
}

test("holdPlace nudges the target back when the layout shifts, and not when it is already in place", () => {
  let off = 0;
  const hold = fakeHold({ delta: () => off });
  hold.shift();
  off = 120;
  hold.shift();
  off = 0;
  hold.shift();
  assert.deepEqual(hold.log.nudges, [120]);
  assert.deepEqual([hold.log.observing, hold.log.listening], [1, 1]);
});

test("holdPlace stops watching at the user's first input, so a later shift is left alone", () => {
  const hold = fakeHold({ delta: () => 80 });
  hold.input();
  assert.deepEqual([hold.log.observing, hold.log.listening], [0, 0]);
  hold.shift();
  assert.deepEqual(hold.log.nudges, []);
});

test("holdPlace can be released by the page, and releasing twice stops nothing twice", () => {
  const hold = fakeHold({ delta: () => 80 });
  hold.release();
  hold.release();
  hold.input();
  assert.deepEqual([hold.log.observing, hold.log.listening], [0, 0]);
  hold.shift();
  assert.deepEqual(hold.log.nudges, []);
});

test("chooseAdapter picks the adapter that serves the host and none for any other", () => {
  const adapters = [githubPage, forgejoPage];
  assert.equal(chooseAdapter("github.com", adapters), githubPage);
  assert.equal(chooseAdapter("localhost:3300", adapters), forgejoPage);
  assert.equal(chooseAdapter("localhost:3000", adapters), null);
  assert.equal(chooseAdapter("gist.github.com", adapters), null);
  assert.equal(chooseAdapter(undefined, adapters), null);
  assert.equal(chooseAdapter("github.com", [undefined, forgejoPage]), null);
});

test("each adapter names itself and its tree for the interface", () => {
  assert.deepEqual([githubPage.name, githubPage.treeLabel], ["GitHub", "Files"]);
  assert.deepEqual([forgejoPage.name, forgejoPage.treeLabel], ["Forgejo", "Files"]);
  for (const page of [githubPage, forgejoPage]) {
    for (const member of ["prFromUrl", "runKey", "headSha", "fileBlocks", "entryFor", "scrollToElement", "fileHeaderOf", "jumpToLine", "clearLineTarget", "restoreLineTarget", "showCallouts", "ownsLine", "cancelJump", "diagramHost", "treeHost", "descriptionHost", "filesUrl", "onChange", "onNavigate"]) {
      assert.equal(typeof page[member], "function", `${page.name}.${member}`);
    }
  }
});

test("a GitHub pull request's runs are keyed by its number", () => {
  assert.equal(githubPage.runKey(prFromUrl({ pathname: "/example-org/example-repo/pull/42/changes" })), "42");
});

test("a Forgejo files page maps to the fj- run key", () => {
  const url = { pathname: "/acme/widgets/pulls/7/files" };
  assert.deepEqual(forgejoPage.prFromUrl(url), { owner: "acme", repo: "widgets", pr: 7, view: "files" });
  assert.equal(forgejoPage.runKey(forgejoPage.prFromUrl(url)), "fj-7");
  assert.equal(forgejoPage.runKey(forgejoPage.prFromUrl("http://localhost:3300/acme/widgets/pulls/120/files?style=unified#diff-abc")), "fj-120");
});

test("a Forgejo URL that is neither a files nor a conversation page maps to nothing", () => {
  assert.equal(forgejoPage.prFromUrl({ pathname: "/acme/widgets/pulls/7/commits" }), null);
  assert.equal(forgejoPage.prFromUrl({ pathname: "/acme/widgets/pulls/7/filesfoo" }), null);
  assert.equal(forgejoPage.prFromUrl({ pathname: "/acme/widgets/pull/7/files" }), null);
  assert.equal(forgejoPage.prFromUrl({ pathname: "/acme/widgets/issues/7/files" }), null);
  assert.deepEqual(forgejoPage.pullFromUrl({ pathname: "/acme/widgets/pulls/7/commits" }), { owner: "acme", repo: "widgets", pr: 7 });
  assert.equal(prFromUrl({ pathname: "/acme/widgets/pulls/7/files" }), null);
});

test("a Forgejo line anchor is the sha1 of the path plus the side and line", async () => {
  const path = "services/billing/Invoice.kt";
  const id = `diff-${createHash("sha1").update(path).digest("hex")}`;
  assert.equal(await forgejoPage.lineAnchor(path, "R", 42), `${id}R42`);
  assert.equal(await forgejoPage.lineAnchor(path, "L", 7), `${id}L7`);
});

test("loadReview sends the run key with the PR number, defaulting to the number", async () => {
  const sent = [];
  globalThis.chrome = { runtime: { id: "abc", sendMessage: async (message) => (sent.push(message), null) } };
  const source = require("../source.js");
  await source.loadReview("acme", "widgets", 7, "fj-7");
  await source.loadReview("o", "r", 9);
  assert.equal(sent[0].key, "fj-7");
  assert.equal(sent[0].pr, 7);
  assert.equal(sent[1].key, "9");
  delete globalThis.chrome;
});

test("the run server calls go through the background script with the run's host, repository and key", async () => {
  const sent = [];
  globalThis.chrome = { runtime: { id: "abc", sendMessage: async (message) => (sent.push(message), { ok: true, state: "running" }) } };
  const source = require("../source.js");
  const run = { host: "forgejo", owner: "acme", repo: "widgets", pr: 7, key: "fj-7" };
  assert.deepEqual(await source.startRun(run), { ok: true, state: "running" });
  await source.runStatus(run);
  await source.cancelRun(run);
  assert.deepEqual(sent.map((message) => message.type), ["startRun", "runStatus", "cancelRun"]);
  assert.ok(sent.every((message) => message.host === "forgejo" && message.key === "fj-7" && message.pr === 7));
  globalThis.chrome = { runtime: { id: "abc", sendMessage: async () => Promise.reject(new Error("gone")) } };
  assert.equal((await source.startRun(run)).problem, "error");
  delete globalThis.chrome;
  assert.equal((await source.startRun(run)).problem, "error");
});

test("each adapter names its host for the run server", () => {
  assert.deepEqual([githubPage.hostId, forgejoPage.hostId], ["github", "forgejo"]);
});

test("the head sha is read from the page on any view of the PR it was loaded for, and asked of the host when the page has none", async () => {
  const { createPage } = require("../page_common.js");
  const saved = globalThis.location;
  const SHA = "a".repeat(40);
  const FETCHED = "b".repeat(40);
  const spec = (shown) => ({
    origin: "https://forge.example",
    changesPage: /^\/([^/]+)\/([^/]+)\/pull\/(\d+)\/files$/,
    pullPage: /^\/([^/]+)\/([^/]+)\/pull\/(\d+)/,
    conversationPage: /^\/([^/]+)\/([^/]+)\/pull\/(\d+)\/?$/,
    hostId: "forgejo",
    readHeadSha: () => shown,
    fetchHeadSha: async (pr) => (pr.pr === 3 ? FETCHED : null),
  });
  try {
    globalThis.location = { pathname: "/o/r/pull/3" };
    const shown = createPage(spec(SHA));
    assert.equal(shown.headSha(), SHA);
    assert.equal(await shown.currentHeadSha({ owner: "o", repo: "r", pr: 3 }), SHA);
    globalThis.location = { pathname: "/o/r/pull/4" };
    assert.equal(shown.headSha(), null);
    globalThis.location = { pathname: "/o/r/pull/3" };
    const silent = createPage(spec(null));
    assert.equal(silent.headSha(), null);
    assert.equal(await silent.currentHeadSha({ owner: "o", repo: "r", pr: 3 }), FETCHED);
    assert.equal(await silent.currentHeadSha({ owner: "o", repo: "r", pr: 9 }), null);
  } finally {
    globalThis.location = saved;
    if (saved === undefined) delete globalThis.location;
  }
});

test("GitHub's head sha not shown by the page is read from the PR's conversation page, then asked of the run server", async () => {
  const SHA = "c".repeat(40);
  const FROM_SERVER = "d".repeat(40);
  const asked = [];
  const fetched = [];
  const embedded = (text) => ({ querySelector: () => (text === null ? null : { textContent: text }) });
  let conversation = embedded(`{"pullRequest":{"headSha":"${SHA}"}}`);
  const saved = { source: globalThis.prFocus.source, commentSource: globalThis.prFocus.commentSource, location: globalThis.location };
  const pr = { owner: "acme", repo: "widgets", pr: 7 };
  try {
    globalThis.location = { pathname: "/acme/widgets/pull/7/commits" };
    globalThis.prFocus.commentSource = { fetchConversation: async (url) => (fetched.push(url), conversation) };
    globalThis.prFocus.source = { headSha: async (run) => (asked.push(run), FROM_SERVER) };
    assert.equal(githubPage.headSha(), null);
    assert.equal(await githubPage.currentHeadSha(pr), SHA);
    assert.deepEqual([fetched, asked], [["https://github.com/acme/widgets/pull/7"], []]);

    conversation = embedded(null);
    assert.equal(await githubPage.currentHeadSha(pr), FROM_SERVER);
    assert.deepEqual(asked, [{ host: "github", owner: "acme", repo: "widgets", pr: 7, key: "7" }]);

    conversation = null;
    globalThis.prFocus.source = { headSha: async () => null };
    assert.equal(await githubPage.currentHeadSha(pr), null);
    delete globalThis.prFocus.source;
    assert.equal(await githubPage.currentHeadSha(pr), null);

    fetched.length = 0;
    globalThis.location = { pathname: "/acme/widgets/pull/7" };
    assert.equal(await githubPage.currentHeadSha(pr), null);
    assert.deepEqual(fetched, []);
  } finally {
    globalThis.prFocus.source = saved.source;
    globalThis.prFocus.commentSource = saved.commentSource;
    globalThis.location = saved.location;
    if (saved.location === undefined) delete globalThis.location;
  }
});

test("each adapter gives the PR's conversation page and knows when the page is it", () => {
  const saved = globalThis.location;
  try {
    assert.equal(githubPage.conversationUrl({ owner: "acme", repo: "widgets", pr: 7 }), "https://github.com/acme/widgets/pull/7");
    assert.equal(forgejoPage.conversationUrl({ owner: "acme", repo: "widgets", pr: 7 }), "http://localhost:3300/acme/widgets/pulls/7");
    globalThis.location = { pathname: "/acme/widgets/pull/7" };
    assert.equal(githubPage.isConversationPage(), true);
    assert.equal(githubPage.isConversationPage({ owner: "Acme", repo: "widgets", pr: 7 }), true);
    assert.equal(githubPage.isConversationPage({ owner: "acme", repo: "widgets", pr: 8 }), false);
    assert.equal(githubPage.isConversationPage({ owner: "acme", repo: "other", pr: 7 }), false);
    globalThis.location = { pathname: "/acme/widgets/pull/7/files" };
    assert.equal(githubPage.isConversationPage(), false);
    globalThis.location = { pathname: "/acme/widgets/pulls/7" };
    assert.equal(forgejoPage.isConversationPage({ owner: "acme", repo: "widgets", pr: 7 }), true);
    delete globalThis.location;
    assert.equal(forgejoPage.isConversationPage(), false);
  } finally {
    globalThis.location = saved;
    if (saved === undefined) delete globalThis.location;
  }
});

const { stopsOf, stopCallout } = require("../tree.js");

const NODES = {
  screen: { title: "Screen", files: ["a.js"], stops: [1, 3] },
  endpoint: { title: "Endpoint", files: [], stops: [] },
  table: { title: "Table", files: ["b.js"], stops: [2] },
};

const STOPS = [
  { i: 1, title: "List is built", why: "Where the list is built.", path: "a.js", side: "R", line: 4, node: "screen" },
  { i: 2, title: "Query filters by owner", why: "Check the owner filter survives.", path: "b.js", side: "R", line: 9, node: "table" },
  { i: 3, title: "Back to the screen", why: "The result renders here.", path: "a.js", side: "R", line: 30, node: "screen" },
];

function fakeDom() {
  class Element {
    constructor(tag) {
      Object.assign(this, { tag, className: "", textContent: "", children: [], listeners: {}, attributes: {}, dataset: {} });
      this.classList = {
        add: (name) => (this.className = `${this.className} ${name}`.trim()),
        toggle: (name, on) => on && this.classList.add(name),
      };
    }
    get firstChild() {
      return this.children[0];
    }
    append(...nodes) {
      this.children.push(...nodes);
    }
    setAttribute(name, value) {
      this.attributes[name] = value;
    }
    addEventListener(name, listener) {
      this.listeners[name] = listener;
    }
  }
  return { createElement: (tag) => new Element(tag), createElementNS: (_ns, tag) => new Element(tag) };
}

const walk = (element) => [element, ...(element.children ?? []).filter((child) => typeof child === "object").flatMap(walk)];
const byClass = (root, name) => walk(root).filter((element) => element.className.split(" ").includes(name));

test("a stop callout names the stop, its box and title, why to stop here, and its previous and next stops, which go", () => {
  globalThis.document = fakeDom();
  try {
    const gone = [];
    const card = stopCallout(STOPS[1], STOPS, (stop) => gone.push(stop.i), NODES);
    const head = byClass(card, "prf-callout-head")[0];
    assert.deepEqual(head.children.map((child) => child.className), ["prf-callout-icon", "prf-callout-where", "prf-callout-sep", "prf-callout-name"]);
    assert.equal(head.children[1].tag, "strong");
    assert.equal(head.children[1].textContent, "Stop 2 of 3 \u00b7 Table");
    assert.equal(head.children[3].textContent, "Query filters by owner");
    assert.equal(byClass(card, "prf-callout-label")[0].textContent, "Why stop here");
    assert.equal(byClass(card, "prf-callout-reason")[0].textContent, "Check the owner filter survives.");
    const previous = byClass(card, "prf-callout-prev")[0];
    assert.deepEqual([previous.textContent, previous.title], ["\u2191 Previous", "List is built"]);
    assert.equal(byClass(card, "prf-callout-nav-label")[0].textContent, "Next");
    assert.deepEqual(byClass(card, "prf-callout-go").map((button) => button.textContent), ["Back to the screen \u2193"]);
    for (const button of [...byClass(card, "prf-callout-go"), previous]) button.listeners.click();
    assert.deepEqual(gone, [3, 1]);
  } finally {
    delete globalThis.document;
  }
});

function navSlots(card) {
  const nav = byClass(card, "prf-callout-nav")[0];
  return nav.children.map((slot) => ({
    classes: slot.className.split(" "),
    hidden: slot.className.split(" ").includes("prf-callout-empty"),
    ariaHidden: slot.attributes["aria-hidden"] ?? null,
    inert: slot.inert ?? false,
    buttons: walk(slot).filter((element) => element.tag === "button").map((element) => ({ text: element.textContent, tabindex: element.attributes.tabindex ?? null, disabled: element.disabled ?? false })),
    caption: byClass(slot, "prf-callout-nav-label")[0]?.textContent ?? null,
  }));
}

test("the callout keeps a Previous slot over a Next slot on the first, a middle and the last stop, a missing one hidden and inert", () => {
  globalThis.document = fakeDom();
  try {
    const gone = [];
    const shown = STOPS.map((stop) => navSlots(stopCallout(stop, STOPS, (target) => gone.push(target.i), NODES)));
    for (const [prevSlot, nextSlot] of shown) {
      assert.deepEqual([prevSlot.classes.includes("prf-callout-prev"), nextSlot.classes.includes("prf-callout-next")], [true, true]);
      assert.equal(nextSlot.caption, "Next");
    }
    const [first, middle, last] = shown;
    assert.deepEqual([first[0].hidden, first[1].hidden], [true, false]);
    assert.deepEqual([middle[0].hidden, middle[1].hidden], [false, false]);
    assert.deepEqual([last[0].hidden, last[1].hidden], [false, true]);
    assert.deepEqual(first[0], { classes: ["prf-callout-prev", "prf-callout-empty"], hidden: true, ariaHidden: "true", inert: true, buttons: [{ text: "\u2191 Previous", tabindex: "-1", disabled: true }], caption: null });
    assert.deepEqual([last[1].ariaHidden, last[1].inert, last[1].buttons.map((button) => [button.tabindex, button.disabled])], ["true", true, [["-1", true]]]);
    assert.deepEqual([middle[0].ariaHidden, middle[0].inert, middle[0].buttons[0].tabindex, middle[0].buttons[0].disabled], [null, false, null, false]);
    assert.deepEqual([middle[1].ariaHidden, middle[1].buttons.map((button) => [button.text, button.tabindex])], [null, [["Back to the screen \u2193", null]]]);
    assert.deepEqual([first[1].buttons[0].text, last[0].buttons[0].text], [`${STOPS[1].title} \u2193`, "\u2191 Previous"]);
  } finally {
    delete globalThis.document;
  }
});

test("a hidden slot's placeholder goes nowhere when clicked, and the real buttons keep going", () => {
  globalThis.document = fakeDom();
  try {
    const gone = [];
    const first = stopCallout(STOPS[0], STOPS, (target) => gone.push(target.i), NODES);
    for (const button of walk(first).filter((element) => element.tag === "button")) button.listeners.click();
    assert.deepEqual(gone, [2]);
    gone.length = 0;
    const last = stopCallout(STOPS[2], STOPS, (target) => gone.push(target.i), NODES);
    for (const button of walk(last).filter((element) => element.tag === "button")) button.listeners.click();
    assert.deepEqual(gone, [2]);
  } finally {
    delete globalThis.document;
  }
});

test("a single stop has two hidden slots and keeps the column", () => {
  globalThis.document = fakeDom();
  try {
    const only = [STOPS[0]];
    const [prevSlot, nextSlot] = navSlots(stopCallout(only[0], only, () => {}, NODES));
    assert.deepEqual([prevSlot.hidden, nextSlot.hidden, prevSlot.ariaHidden, nextSlot.ariaHidden], [true, true, "true", "true"]);
    assert.deepEqual([prevSlot.buttons[0].text, nextSlot.caption], ["\u2191 Previous", "Next"]);
  } finally {
    delete globalThis.document;
  }
});

test("a stop on no box or with no reason leaves the box and the reason out of its callout", () => {
  globalThis.document = fakeDom();
  try {
    const card = stopCallout({ ...STOPS[0], node: null, why: "" }, STOPS, () => {}, NODES);
    assert.equal(byClass(card, "prf-callout-where")[0].textContent, "Stop 1 of 3");
    assert.deepEqual(byClass(card, "prf-callout-reason"), []);
    assert.deepEqual(byClass(card, "prf-callout-label"), []);
  } finally {
    delete globalThis.document;
  }
});

test("a run shows its walkthrough's stops as given, even when there are none", () => {
  assert.deepEqual(stopsOf({ nodes: NODES, walkthrough: STOPS }), STOPS);
  assert.deepEqual(stopsOf({ nodes: NODES, walkthrough: [] }), []);
});

const WALK_STOPS = [
  { i: 1, title: "List is built", why: "w", path: "a.js", side: "R", line: 4, node: "screen" },
  { i: 2, title: "Query filters", why: "w", path: "b.js", side: "R", line: 9, node: "endpoint" },
  { i: 3, title: "Docs", why: "w", path: "c.md", side: null, line: null, node: null },
];

test("a walkthrough row shows the stop's number and its title, and marks the current stop", () => {
  const { stopList } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const picked = [];
    const list = stopList({ stops: WALK_STOPS, selectedStop: 2 }, { onSelectStop: (i) => picked.push(i) });
    const rows = byClass(list, "prf-stop");
    assert.deepEqual(
      rows.map((row) => [byClass(row, "prf-num")[0].textContent, byClass(row, "prf-name")[0].textContent]),
      [["1", "List is built"], ["2", "Query filters"], ["3", "Docs"]],
    );
    assert.deepEqual(rows.map((row) => row.className.split(" ").includes("prf-selected")), [false, true, false]);
    assert.deepEqual(rows.map((row) => byClass(row, "prf-head-main")[0].attributes["aria-current"] ?? null), [null, "step", null]);
    for (const row of rows) byClass(row, "prf-head-main")[0].listeners.click();
    assert.deepEqual(picked, [1, 2, 3]);
  } finally {
    delete globalThis.document;
  }
});

test("the walkthrough list opens with a line saying what the stops are for", () => {
  const { stopList } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const list = stopList({ stops: WALK_STOPS, selectedStop: null }, {});
    assert.equal(list.children[0].className, "prf-lede");
    assert.equal(
      list.children[0].textContent,
      "Read the change in this order. A stop opens its lines in the diff and lights its box in the diagram.",
    );
  } finally {
    delete globalThis.document;
  }
});

test("a run with no stops has no lede line", () => {
  const { stopList } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const list = stopList({ stops: [], selectedStop: null }, {});
    assert.deepEqual(byClass(list, "prf-lede"), []);
  } finally {
    delete globalThis.document;
  }
});

test("a run with no stops says so instead of listing rows", () => {
  const { stopList } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const list = stopList({ stops: [], selectedStop: null }, {});
    assert.deepEqual(byClass(list, "prf-stop"), []);
    assert.match(byClass(list, "prf-banner")[0].textContent, /no stops/);
  } finally {
    delete globalThis.document;
  }
});

function fakeTable(anchors) {
  const rows = [];
  class Row {
    constructor(className = "") {
      Object.assign(this, { className, dataset: {}, children: [], colSpan: 1 });
      this.classList = { contains: (name) => this.className.split(" ").includes(name) };
    }
    get previousElementSibling() {
      return rows[rows.indexOf(this) - 1] ?? null;
    }
    get nextElementSibling() {
      return rows[rows.indexOf(this) + 1] ?? null;
    }
    append(...nodes) {
      this.children.push(...nodes);
    }
    before(node) {
      rows.splice(rows.indexOf(this), 0, node);
    }
    remove() {
      if (rows.includes(this)) rows.splice(rows.indexOf(this), 1);
    }
  }
  const lines = new Map(anchors.map((anchor) => [anchor, new Row("line")]));
  rows.push(...lines.values());
  const classes = (selector) => rows.filter((row) => row.className.split(" ").includes(selector.slice(1)));
  globalThis.document = { createElement: () => new Row(), querySelectorAll: classes };
  const addLine = (anchor) => {
    lines.set(anchor, new Row("line"));
    rows.push(lines.get(anchor));
  };
  return { rows, lines, addLine, findRow: (anchor) => lines.get(anchor) ?? null, callouts: () => classes(".prf-callout-row") };
}

function calloutPage(table) {
  return require("../page_common.js").createPage({ findRow: table.findRow });
}

test("showCallouts puts one callout row directly above each start line and changes nothing when called again", () => {
  const table = fakeTable(["a", "b"]);
  try {
    const page = calloutPage(table);
    const built = [];
    const entries = ["a", "b"].map((anchor) => ({ key: anchor, anchor, render: () => (built.push(anchor), { anchor }) }));
    page.showCallouts(entries);
    page.showCallouts(entries);
    assert.deepEqual(table.rows.map((row) => row.dataset.key ?? "line"), ["a", "line", "b", "line"]);
    assert.deepEqual(built, ["a", "b"]);
    assert.equal(table.callouts()[0].nextElementSibling, table.lines.get("a"));
  } finally {
    delete globalThis.document;
  }
});

test("showCallouts skips a start line that has not loaded and adds its callout once the row appears", () => {
  const table = fakeTable(["a"]);
  try {
    const page = calloutPage(table);
    const entries = [{ key: 1, anchor: "a", render: () => ({}) }, { key: 2, anchor: "late", render: () => ({}) }];
    page.showCallouts(entries);
    assert.equal(table.callouts().length, 1);
    table.addLine("late");
    page.showCallouts(entries);
    assert.deepEqual(table.rows.map((row) => row.dataset.key ?? "line"), ["1", "line", "2", "line"]);
  } finally {
    delete globalThis.document;
  }
});

test("showCallouts replaces a callout the host dropped and removes callouts that are no longer wanted", () => {
  const table = fakeTable(["a", "b"]);
  try {
    const page = calloutPage(table);
    const entries = ["a", "b"].map((anchor) => ({ key: anchor, anchor, render: () => ({}) }));
    page.showCallouts(entries);
    table.callouts()[0].remove();
    page.showCallouts(entries);
    assert.deepEqual(table.rows.map((row) => row.dataset.key ?? "line"), ["a", "line", "b", "line"]);
    page.showCallouts(entries.slice(1));
    assert.deepEqual(table.rows.map((row) => row.dataset.key ?? "line"), ["line", "b", "line"]);
    page.showCallouts([]);
    assert.deepEqual(table.callouts(), []);
  } finally {
    delete globalThis.document;
  }
});

function fakeEntries(ids) {
  class Node {
    constructor(className = "") {
      this.classes = new Set(className.split(" ").filter(Boolean));
      this.dataset = {};
      this.children = [];
      this.parent = null;
      this.classList = {
        contains: (name) => this.classes.has(name),
        add: (...names) => names.forEach((name) => this.classes.add(name)),
        remove: (...names) => names.forEach((name) => this.classes.delete(name)),
      };
    }
    set className(value) {
      this.classes = new Set(value.split(" ").filter(Boolean));
    }
    get className() {
      return [...this.classes].join(" ");
    }
    get firstElementChild() {
      return this.children[0] ?? null;
    }
    get nextElementSibling() {
      return this.parent?.children[this.parent.children.indexOf(this) + 1] ?? null;
    }
    append(...nodes) {
      for (const node of nodes) {
        node.parent = this;
        this.children.push(node);
      }
    }
    prepend(node) {
      node.parent = this;
      this.children.unshift(node);
    }
    remove() {
      if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1);
      this.parent = null;
    }
    getBoundingClientRect() {
      return { top: 0, height: 0, bottom: 0, left: 0, right: 0 };
    }
    addEventListener() {}
    querySelector(selector) {
      return this.all().find((node) => node !== this && node.classes?.has(selector.slice(1))) ?? null;
    }
    all() {
      return [this, ...this.children.flatMap((child) => child.all?.() ?? [])];
    }
  }
  const root = new Node();
  const entries = new Map(ids.map((id) => [id, new Node("entry")]));
  for (const [id, entry] of entries) {
    entry.dataset.id = id;
    const header = new Node("file-header");
    header.dataset.path = id;
    entry.append(header);
    root.append(entry);
  }
  const matching = (selector) => {
    const wanted = selector.split(",").map((part) => part.trim().slice(1));
    return root.all().filter((node) => wanted.some((name) => node.classes.has(name)));
  };
  globalThis.document = {
    createElement: () => new Node(),
    getElementById: (id) => entries.get(id) ?? null,
    querySelectorAll: matching,
    querySelector: () => null,
    createTreeWalker: () => ({ nextNode: () => null }),
    body: root,
    documentElement: { scrollHeight: 5000 },
  };
  globalThis.NodeFilter = { SHOW_ELEMENT: 1, FILTER_ACCEPT: 1, FILTER_SKIP: 3, FILTER_REJECT: 2 };
  globalThis.innerHeight = 800;
  globalThis.scrollY = 0;
  globalThis.scrollBy = () => {};
  const done = () => {
    for (const name of ["document", "NodeFilter", "innerHeight", "scrollY", "scrollBy"]) delete globalThis[name];
  };
  return { root, entries, callouts: () => matching(".prf-callout-row"), done };
}

function filePage(extra = {}) {
  return require("../page_common.js").createPage({
    findRow: () => null,
    entryOf: (block) => block,
    diffId: async (path) => path,
    fileHeaderSelector: ".file-header",
    stickySkip: ".none",
    contentSelector: ".content",
    ...extra,
  });
}

const fileEntry = (key, anchor, built = []) => ({ key, anchor, file: true, render: () => (built.push(anchor), { key }) });

test("showCallouts puts a file callout as the first child of its file's entry, above the header, once", () => {
  const dom = fakeEntries(["a", "b"]);
  try {
    const page = filePage();
    const built = [];
    const entries = [fileEntry(1, "a", built), fileEntry(2, "b", built)];
    page.showCallouts(entries);
    page.showCallouts(entries);
    assert.deepEqual(built, ["a", "b"]);
    assert.equal(dom.callouts().length, 2);
    for (const [id, entry] of dom.entries) {
      assert.deepEqual(entry.children.map((child) => child.className), ["prf-callout-row prf-callout-file", "file-header"], id);
    }
    assert.equal(dom.entries.get("a").children[0].dataset.anchor, "a");
    assert.equal(page.fileHeaderOf(dom.entries.get("a")).className, "file-header");
  } finally {
    dom.done();
  }
});

test("a file callout waits for its diff to load, comes back when the host drops it, and goes when no longer wanted", () => {
  const dom = fakeEntries(["a"]);
  try {
    const page = filePage();
    const entries = [fileEntry(1, "a"), fileEntry(2, "late")];
    page.showCallouts(entries);
    assert.equal(dom.callouts().length, 1);
    dom.entries.get("a").children[0].remove();
    page.showCallouts(entries);
    assert.equal(dom.entries.get("a").children.length, 2);
    page.showCallouts([]);
    assert.deepEqual(dom.callouts(), []);
    assert.equal(dom.entries.get("a").children.length, 1);
  } finally {
    dom.done();
  }
});

test("a file callout and a line callout can be shown together without disturbing each other", () => {
  const dom = fakeEntries(["a"]);
  try {
    const page = filePage();
    const entries = [fileEntry(1, "a"), { key: 2, anchor: "line", render: () => ({}) }];
    page.showCallouts(entries);
    page.showCallouts(entries);
    assert.deepEqual(dom.callouts().map((callout) => callout.dataset.key), ["1"]);
  } finally {
    dom.done();
  }
});

test("jumpToFile marks the file callout as the target and pulses it, and a jump without the pulse only marks it", async () => {
  const dom = fakeEntries(["a", "b"]);
  try {
    const page = filePage();
    page.showCallouts([fileEntry(1, "a"), fileEntry(2, "b")]);
    const [first, second] = dom.callouts();
    assert.equal(await page.jumpToFile("a"), true);
    assert.deepEqual([first.classes.has("prf-line-target"), first.classes.has("prf-pulse")], [true, true]);
    assert.deepEqual([second.classes.has("prf-line-target"), second.classes.has("prf-pulse")], [false, false]);
    assert.equal(await page.jumpToFile("b", { pulse: false }), true);
    assert.deepEqual([first.classes.has("prf-line-target"), first.classes.has("prf-pulse")], [false, false]);
    assert.deepEqual([second.classes.has("prf-line-target"), second.classes.has("prf-pulse")], [true, false]);
    page.clearLineTarget();
    assert.equal(second.classes.has("prf-line-target"), false);
  } finally {
    dom.done();
  }
});

function scrollingPage(dom, startTop) {
  const state = { top: startTop, layout: [], input: new Map() };
  globalThis.scrollBy = ({ top }) => {
    state.top -= top;
    globalThis.scrollY += top;
  };
  globalThis.addEventListener = (type, handler) => state.input.set(type, handler);
  globalThis.removeEventListener = (type) => state.input.delete(type);
  globalThis.ResizeObserver = class {
    constructor(callback) {
      this.callback = callback;
      this.live = true;
      state.layout.push(this);
    }
    observe() {}
    disconnect() {
      this.live = false;
    }
  };
  state.shift = (by) => {
    state.top += by;
    for (const observer of state.layout) if (observer.live) observer.callback();
  };
  dom.callouts()[0].getBoundingClientRect = () => ({ top: state.top, height: 40, bottom: state.top + 40, left: 0, right: 0 });
  return state;
}

function endScrollingPage() {
  for (const name of ["addEventListener", "removeEventListener", "ResizeObserver"]) delete globalThis[name];
}

test("jumpToFile lands the callout 16px below the sticky chrome and the file header, and holds it as content above shifts", async () => {
  const dom = fakeEntries(["a"]);
  try {
    const page = filePage();
    page.showCallouts([fileEntry(1, "a")]);
    const scrolling = scrollingPage(dom, 900);
    dom.entries.get("a").children[1].getBoundingClientRect = () => ({ top: 0, height: 36, bottom: 36, left: 0, right: 0 });
    assert.equal(await page.jumpToFile("a"), true);
    assert.equal(scrolling.top, 36 + 16);
    scrolling.shift(300);
    assert.equal(scrolling.top, 36 + 16);
    scrolling.shift(-120);
    assert.equal(scrolling.top, 36 + 16);
  } finally {
    endScrollingPage();
    dom.done();
  }
});

test("a held stop is let go at the user's first scroll or click, and by a newer jump or cancelJump", async () => {
  for (const release of [(page, scrolling) => scrolling.input.get("wheel")(), (page, scrolling) => scrolling.input.get("pointerdown")(), (page) => page.cancelJump()]) {
    const dom = fakeEntries(["a"]);
    try {
      const page = filePage();
      page.showCallouts([fileEntry(1, "a")]);
      const scrolling = scrollingPage(dom, 900);
      await page.jumpToFile("a");
      assert.equal(scrolling.top, 16);
      release(page, scrolling);
      scrolling.shift(300);
      assert.equal(scrolling.top, 316);
      assert.equal(scrolling.input.size, 0);
    } finally {
      endScrollingPage();
      dom.done();
    }
  }
});

test("jumpToFile near the end of the page lands as close as the page can scroll and does not keep nudging", async () => {
  const dom = fakeEntries(["a"]);
  try {
    const page = filePage();
    page.showCallouts([fileEntry(1, "a")]);
    const scrolling = scrollingPage(dom, 5000);
    assert.equal(await page.jumpToFile("a"), true);
    assert.equal(scrolling.top, 800);
    assert.equal(globalThis.scrollY, 4200);
    scrolling.shift(0);
    assert.equal(scrolling.top, 800);
  } finally {
    endScrollingPage();
    dom.done();
  }
});

test("restoreLineTarget gives a re-created file callout its target mark back", async () => {
  const dom = fakeEntries(["a"]);
  try {
    const page = filePage();
    const entries = [fileEntry(1, "a")];
    page.showCallouts(entries);
    await page.jumpToFile("a", { pulse: false });
    dom.callouts()[0].remove();
    page.showCallouts(entries);
    assert.equal(dom.callouts()[0].classes.has("prf-line-target"), false);
    page.restoreLineTarget();
    assert.equal(dom.callouts()[0].classes.has("prf-line-target"), true);
  } finally {
    dom.done();
  }
});

test("jumpToFile does nothing for a diff that is not in the page", async () => {
  const dom = fakeEntries(["a"]);
  try {
    const page = filePage();
    page.showCallouts([fileEntry(1, "a")]);
    assert.equal(await page.jumpToFile("missing"), false);
    assert.equal(dom.callouts()[0].classes.has("prf-line-target"), false);
  } finally {
    dom.done();
  }
});

function fakeHeader() {
  const classes = new Set();
  return { classes, classList: { add: (name) => classes.add(name), remove: (name) => classes.delete(name) } };
}

test("focus offers no way to hide a diff, and markBox marks only the active files' headers without touching any diff", async () => {
  const focus = require("../focus.js");
  assert.deepEqual(Object.keys(focus).sort(), ["announceBox", "clearBox", "markBox", "scrollTo"]);
  const headers = new Map([["a.js", fakeHeader()], ["b.js", fakeHeader()], ["c.js", fakeHeader()]]);
  const saved = { document: globalThis.document, page: globalThis.prFocus.page, alive: globalThis.prFocus.alive };
  globalThis.prFocus.alive = () => true;
  globalThis.prFocus.page = {
    fileBlocks: () => new Map(),
    entryFor: async (path) => (headers.has(path) ? path : null),
    entryOf: () => null,
    fileHeaderOf: (entry) => headers.get(entry) ?? null,
  };
  globalThis.document = { querySelectorAll: () => [...headers.values()].filter((header) => header.classes.has("prf-box-active")) };
  try {
    const marked = () => [...headers].filter(([, header]) => header.classes.has("prf-box-active")).map(([path]) => path);
    await focus.markBox(["a.js", "b.js"]);
    assert.deepEqual(marked(), ["a.js", "b.js"]);
    await focus.markBox(["b.js", "c.js", "not-loaded.js"]);
    assert.deepEqual(marked(), ["b.js", "c.js"]);
    await focus.markBox([]);
    assert.deepEqual(marked(), []);
  } finally {
    globalThis.document = saved.document;
    globalThis.prFocus.page = saved.page;
    globalThis.prFocus.alive = saved.alive;
    if (saved.document === undefined) delete globalThis.document;
  }
});

test("a newer markBox wins over an older one that is still looking for its headers", async () => {
  const focus = require("../focus.js");
  const headers = new Map([["a.js", fakeHeader()], ["b.js", fakeHeader()]]);
  const saved = { document: globalThis.document, page: globalThis.prFocus.page, alive: globalThis.prFocus.alive };
  const gates = new Map();
  globalThis.prFocus.alive = () => true;
  globalThis.prFocus.page = {
    fileBlocks: () => new Map(),
    entryFor: (path) => new Promise((resolve) => gates.set(path, () => resolve(path))),
    entryOf: () => null,
    fileHeaderOf: (entry) => headers.get(entry),
  };
  globalThis.document = { querySelectorAll: () => [...headers.values()].filter((header) => header.classes.has("prf-box-active")) };
  try {
    const older = focus.markBox(["a.js"]);
    const newer = focus.markBox(["b.js"]);
    gates.get("b.js")();
    await newer;
    gates.get("a.js")();
    await older;
    assert.deepEqual([...headers].filter(([, header]) => header.classes.has("prf-box-active")).map(([path]) => path), ["b.js"]);
  } finally {
    globalThis.document = saved.document;
    globalThis.prFocus.page = saved.page;
    globalThis.prFocus.alive = saved.alive;
    if (saved.document === undefined) delete globalThis.document;
  }
});

test("loading the diagram script removes the width an earlier version saved and stores nothing", async () => {
  const path = require.resolve("../diagram.js");
  const calls = [];
  const originalChrome = globalThis.chrome;
  const originalPrFocus = globalThis.prFocus;
  const cached = require.cache[path];
  delete require.cache[path];
  globalThis.prFocus = { alive: () => true };
  globalThis.chrome = {
    storage: {
      local: {
        get: async (...args) => (calls.push(["get", ...args]), {}),
        set: async (...args) => (calls.push(["set", ...args]), undefined),
        remove: async (...args) => (calls.push(["remove", ...args]), undefined),
      },
    },
  };
  try {
    require("../diagram.js");
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(calls, [["remove", "diagramWidth"]]);
  } finally {
    delete require.cache[path];
    if (cached) require.cache[path] = cached;
    globalThis.chrome = originalChrome;
    globalThis.prFocus = originalPrFocus;
  }
});

const SETS = { contract: ["a.js", "api.json"], data: [] };

test("fileChips counts all changed files and each set that has files, and shows no chip for an empty set", () => {
  const { fileChips } = require("../tree.js");
  assert.deepEqual(fileChips({ file_sets: { contract: ["a.js", "api.json"], data: ["m.sql"] } }, 9), [
    { id: "all", label: "All", count: 9 },
    { id: "contract", label: "API", count: 2 },
    { id: "data", label: "Data", count: 1 },
  ]);
  assert.deepEqual(fileChips({ file_sets: SETS }, 5).map((chip) => [chip.id, chip.count]), [["all", 5], ["contract", 2]]);
});

test("fileChips gives no chips to a run without a non-empty set, and All never counts fewer files than a set", () => {
  const { fileChips } = require("../tree.js");
  assert.deepEqual(fileChips({}, 9), []);
  assert.deepEqual(fileChips({ file_sets: { contract: [], data: [] } }, 9), []);
  assert.equal(fileChips({ file_sets: SETS }, 0)[0].count, 2);
});

test("fileSetOf is the chosen set with its lines, and nothing for All, an empty set or an unknown name", () => {
  const { fileSetOf } = require("../tree.js");
  const contract = [{ text: "x" }];
  const review = { file_sets: { contract: ["a.js"], data: [] }, contract, data: [] };
  assert.deepEqual(fileSetOf(review, "contract"), { id: "contract", paths: ["a.js"], lines: contract });
  assert.equal(fileSetOf(review, "all"), null);
  assert.equal(fileSetOf(review, "data"), null);
  assert.equal(fileSetOf(review, "toString"), null);
  assert.equal(fileSetOf({}, "contract"), null);
});

test("the chips sit under the mode toggle, mark the chosen one and choose a set when clicked", () => {
  const { bar } = require("../tree.js");
  globalThis.document = fakeDom();
  globalThis.prFocus.page = { treeLabel: "Files" };
  try {
    const chips = [{ id: "all", label: "All", count: 9 }, { id: "contract", label: "API", count: 4 }];
    const chosen = [];
    const element = bar({ mode: "review", chips, fileSet: { id: "contract" } }, { onMode() {}, onFileSet: (id) => chosen.push(id) });
    const buttons = byClass(element, "prf-chip");
    assert.deepEqual(buttons.map((chip) => byClass(chip, "prf-chip-count")[0].textContent), ["9", "4"]);
    assert.deepEqual(buttons.map((chip) => chip.attributes["aria-pressed"]), ["false", "true"]);
    assert.deepEqual(element.children.map((child) => child.className), ["prf-modes", "prf-chips"]);
    for (const chip of buttons) chip.listeners.click();
    assert.deepEqual(chosen, ["all", "contract"]);
    assert.deepEqual(byClass(bar({ mode: "review", chips: [] }, {}), "prf-chips"), []);
  } finally {
    delete globalThis.document;
    delete globalThis.prFocus.page;
  }
});

test("with a set chosen the list is the lede and only the stops on its files, in walkthrough order", () => {
  const { stopList } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const fileSet = { id: "contract", paths: ["c.md", "b.js", "api.json"], lines: [] };
    const list = stopList({ stops: WALK_STOPS, selectedStop: null, fileSet }, { onSelectStop() {} });
    const rows = byClass(list, "prf-stop");
    assert.deepEqual(
      rows.map((row) => [byClass(row, "prf-num")[0].textContent, byClass(row, "prf-name")[0].textContent, byClass(row, "prf-file")[0].textContent]),
      [["2", "Query filters", "b.js"], ["3", "Docs", "c.md"]],
    );
    assert.deepEqual(list.children.map((row) => row.className.split(" ")[0] === "prf-lede" ? "prf-lede" : row.className.split(" ")[1]), ["prf-lede", "prf-stop", "prf-stop"]);
    assert.equal(byClass(list, "prf-nostop").length, 0);
  } finally {
    delete globalThis.document;
  }
});

test("a set with no stop on any of its files lists only a banner naming the set", () => {
  const { stopList } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const list = stopList({ stops: WALK_STOPS, selectedStop: null, fileSet: { id: "contract", paths: ["api.json"], lines: [] } }, { onSelectStop() {} });
    assert.deepEqual(list.children.map((child) => [child.className, child.textContent]), [["prf-banner", "No stops on API files."]]);
  } finally {
    delete globalThis.document;
  }
});

test("a run with no stops lists only the banner for a run with no stops", () => {
  const { stopList } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const list = stopList({ stops: [], selectedStop: null, fileSet: null }, { onSelectStop() {} });
    assert.deepEqual(list.children.map((child) => [child.className, child.textContent]), [["prf-banner", "This run has no stops to walk through."]]);
  } finally {
    delete globalThis.document;
  }
});

function fakeTree(links) {
  class Row {
    constructor(href, ...inside) {
      this.href = href;
      this.inside = inside;
      this.hidden = false;
      this.classList = { toggle: (name, on) => (this.hidden = on), contains: () => this.hidden };
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
  const files = links.map((href) => new Row(href));
  const dir = new Row(null, ...files);
  const host = { querySelectorAll: (selector) => (selector === "file" ? files : selector === "dir" ? [dir] : []) };
  return { files, dir, host };
}

test("filterTree hides the tree's file rows outside the set and a directory left empty, and shows them all for null", async () => {
  const tree = fakeTree(["#diff-a", "#diff-b", "https://host/pull/1/files#diff-c"]);
  const page = filePage({ treeHost: () => tree.host, treeFileSelector: "file", treeDirSelector: "dir", diffId: async (path) => `diff-${path}` });
  await page.filterTree(["a", "c"]);
  assert.deepEqual(tree.files.map((row) => row.hidden), [false, true, false]);
  assert.equal(tree.dir.hidden, false);
  await page.filterTree(["b"]);
  assert.deepEqual(tree.files.map((row) => row.hidden), [true, false, true]);
  await page.filterTree(["zzz"]);
  assert.equal(tree.dir.hidden, true);
  await page.filterTree(null);
  assert.deepEqual([...tree.files, tree.dir].map((row) => row.hidden), [false, false, false, false]);
});

test("filterTree is applied again to rows the host re-rendered, without asking for the ids again", async () => {
  const tree = fakeTree(["#diff-a", "#diff-b"]);
  let asked = 0;
  const page = filePage({ treeHost: () => tree.host, treeFileSelector: "file", diffId: async (path) => (asked += 1, `diff-${path}`) });
  await page.filterTree(["a"]);
  for (const row of tree.files) row.hidden = false;
  await page.filterTree(["a"]);
  assert.deepEqual(tree.files.map((row) => row.hidden), [false, true]);
  assert.equal(asked, 1);
});

test("a tree row with no diff link is left showing, and a page with no tree is left alone", async () => {
  const tree = fakeTree([null, "#diff-b"]);
  const page = filePage({ treeHost: () => tree.host, treeFileSelector: "file", diffId: async (path) => `diff-${path}` });
  await page.filterTree(["a"]);
  assert.deepEqual(tree.files.map((row) => row.hidden), [false, true]);
  await filePage({ treeHost: () => null, treeFileSelector: "file", diffId: async (path) => path }).filterTree(["a"]);
});
