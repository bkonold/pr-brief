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
      this.textContent = this.children.map((child) => (typeof child === "string" ? child : child.textContent)).join("");
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
    const next = byClass(card, "prf-callout-next")[0];
    assert.deepEqual([next.tag, next.textContent, next.title], ["button", "Next \u2193", "Back to the screen"]);
    for (const button of [next, previous]) button.listeners.click();
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
    tag: slot.tag,
    text: slot.textContent,
    title: slot.title ?? null,
    tabindex: slot.attributes.tabindex ?? null,
    disabled: slot.disabled ?? false,
  }));
}

test("the callout keeps a Previous slot over a Next slot on the first, a middle and the last stop, a missing one hidden and inert", () => {
  globalThis.document = fakeDom();
  try {
    const gone = [];
    const shown = STOPS.map((stop) => navSlots(stopCallout(stop, STOPS, (target) => gone.push(target.i), NODES)));
    for (const [prevSlot, nextSlot] of shown) {
      assert.deepEqual([prevSlot.classes.includes("prf-callout-prev"), nextSlot.classes.includes("prf-callout-next")], [true, true]);
      assert.deepEqual([prevSlot.tag, nextSlot.tag, nextSlot.text], ["button", "button", "Next \u2193"]);
    }
    const [first, middle, last] = shown;
    assert.deepEqual([first[0].hidden, first[1].hidden], [true, false]);
    assert.deepEqual([middle[0].hidden, middle[1].hidden], [false, false]);
    assert.deepEqual([last[0].hidden, last[1].hidden], [false, true]);
    assert.deepEqual(first[0], { classes: ["prf-callout-prev", "prf-callout-empty"], hidden: true, ariaHidden: "true", inert: true, tag: "button", text: "\u2191 Previous", title: null, tabindex: "-1", disabled: true });
    assert.deepEqual([last[1].ariaHidden, last[1].inert, last[1].tabindex, last[1].disabled, last[1].title], ["true", true, "-1", true, null]);
    assert.deepEqual([middle[0].ariaHidden, middle[0].inert, middle[0].tabindex, middle[0].disabled], [null, false, null, false]);
    assert.deepEqual([middle[1].ariaHidden, middle[1].text, middle[1].title, middle[1].tabindex], [null, "Next \u2193", "Back to the screen", null]);
    assert.deepEqual([first[1].text, first[1].title, last[0].text, last[0].title], ["Next \u2193", STOPS[1].title, "\u2191 Previous", STOPS[1].title]);
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
    assert.deepEqual([prevSlot.text, nextSlot.text], ["\u2191 Previous", "Next \u2193"]);
  } finally {
    delete globalThis.document;
  }
});

test("backtick spans in why to stop here render as code", () => {
  globalThis.document = fakeDom();
  try {
    const card = stopCallout({ ...STOPS[0], why: "`validateRequest` calls this; check slot rules." }, STOPS, () => {}, NODES);
    const reason = byClass(card, "prf-callout-reason")[0];
    const code = reason.children.filter((child) => child.tag === "code");
    assert.deepEqual(code.map((element) => element.textContent), ["validateRequest"]);
    assert.equal(reason.textContent.includes("`"), false);
    assert.equal(walk(reason).filter((element) => element.tag === "code").length, 1);
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
    assert.equal(list.children[0].textContent, `${WALK_STOPS.length} stops, in reading order`);
    assert.equal(list.children[0].title, "Read the change in this order. A stop opens its lines in the diff and lights its box in the diagram.");
    assert.equal(stopList({ stops: WALK_STOPS.slice(0, 1), selectedStop: null }, {}).children[0].textContent, "1 stop, in reading order");
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

test("the chips sit on the filter line under the mode toggle, mark the chosen one and choose a set when clicked", () => {
  const { bar, filters } = require("../tree.js");
  globalThis.document = fakeDom();
  globalThis.prFocus.page = { treeLabel: "Files" };
  try {
    const chips = [{ id: "all", label: "All", count: 9 }, { id: "contract", label: "API", count: 4 }];
    const chosen = [];
    const element = filters({ mode: "github", chips, fileSet: { id: "contract" } }, { onFileSet: (id) => chosen.push(id) });
    const buttons = byClass(element, "prf-chip");
    assert.deepEqual(buttons.map((chip) => byClass(chip, "prf-chip-count")[0].textContent), ["9", "4"]);
    assert.deepEqual(buttons.map((chip) => chip.attributes["aria-pressed"]), ["false", "true"]);
    assert.equal(element.className, "prf-filters");
    assert.deepEqual(element.children.map((child) => child.className), ["prf-chips"]);
    assert.deepEqual(bar({ mode: "github", chips }, { onMode() {} }).children.map((child) => child.className), ["prf-modes"]);
    for (const chip of buttons) chip.listeners.click();
    assert.deepEqual(chosen, ["all", "contract"]);
    assert.equal(filters({ mode: "github", chips: [] }, {}), null);
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

function fakeBlocks(ids) {
  const blocks = ids.map((id) => ({ id, hidden: false, classList: { toggle(name, on) { blocks.find((block) => block.id === id).hidden = on; } } }));
  globalThis.document = { querySelectorAll: (selector) => (selector === "block" ? blocks : []) };
  return blocks;
}

function withBlocks(ids, body) {
  return async () => {
    const blocks = fakeBlocks(ids);
    try {
      await body(blocks);
    } finally {
      delete globalThis.document;
    }
  };
}

test("filterFiles hides the tree's file rows outside the set and a directory left empty, and shows them all for null", withBlocks([], async () => {
  const tree = fakeTree(["#diff-a", "#diff-b", "https://host/pull/1/files#diff-c"]);
  const page = filePage({ blockSelector: "block", treeHost: () => tree.host, treeFileSelector: "file", treeDirSelector: "dir", diffId: async (path) => `diff-${path}` });
  await page.filterFiles(["a", "c"]);
  assert.deepEqual(tree.files.map((row) => row.hidden), [false, true, false]);
  assert.equal(tree.dir.hidden, false);
  await page.filterFiles(["b"]);
  assert.deepEqual(tree.files.map((row) => row.hidden), [true, false, true]);
  await page.filterFiles(["zzz"]);
  assert.equal(tree.dir.hidden, true);
  await page.filterFiles(null);
  assert.deepEqual([...tree.files, tree.dir].map((row) => row.hidden), [false, false, false, false]);
}));

test("filterFiles is applied again to rows the host re-rendered, without asking for the ids again", withBlocks([], async () => {
  const tree = fakeTree(["#diff-a", "#diff-b"]);
  let asked = 0;
  const page = filePage({ blockSelector: "block", treeHost: () => tree.host, treeFileSelector: "file", diffId: async (path) => (asked += 1, `diff-${path}`) });
  await page.filterFiles(["a"]);
  for (const row of tree.files) row.hidden = false;
  await page.filterFiles(["a"]);
  assert.deepEqual(tree.files.map((row) => row.hidden), [false, true]);
  assert.equal(asked, 1);
}));

test("a tree row with no diff link is left showing, and a page with no tree is left alone", withBlocks([], async () => {
  const tree = fakeTree([null, "#diff-b"]);
  const page = filePage({ blockSelector: "block", treeHost: () => tree.host, treeFileSelector: "file", diffId: async (path) => `diff-${path}` });
  await page.filterFiles(["a"]);
  assert.deepEqual(tree.files.map((row) => row.hidden), [false, true]);
  await filePage({ blockSelector: "block", treeHost: () => null, treeFileSelector: "file", diffId: async (path) => path }).filterFiles(["a"]);
}));

test("filterFiles hides the diff blocks outside the set, with or without a tree, and shows them all for null", withBlocks(["diff-a", "diff-b", "diff-c"], async (blocks) => {
  const page = filePage({ blockSelector: "block", treeHost: () => null, diffId: async (path) => `diff-${path}` });
  await page.filterFiles(["a", "c"]);
  assert.deepEqual(blocks.map((block) => block.hidden), [false, true, false]);
  await page.filterFiles(["b"]);
  assert.deepEqual(blocks.map((block) => block.hidden), [true, false, true]);
  await page.filterFiles(null);
  assert.deepEqual(blocks.map((block) => block.hidden), [false, false, false]);
}));

test("a diff block that appears after the filter was set is hidden when the filter is applied again", withBlocks(["diff-a"], async (blocks) => {
  const tree = fakeTree(["#diff-a", "#diff-b"]);
  let asked = 0;
  const page = filePage({ blockSelector: "block", treeHost: () => tree.host, treeFileSelector: "file", diffId: async (path) => (asked += 1, `diff-${path}`) });
  await page.filterFiles(["a"]);
  assert.deepEqual(blocks.map((block) => block.hidden), [false]);
  const later = fakeBlocks(["diff-a", "diff-b"]);
  await page.filterFiles(["a"]);
  assert.deepEqual(later.map((block) => block.hidden), [false, true]);
  assert.equal(asked, 1);
}));

const CHUNKS = [
  { i: 1, title: "Entities take identity", summary: "Moves `id` into the constructor.", risk: "low", risk_reason: "", depends_on: [], hunks: [{ id: "h1", path: "a.js", change: "modified", old: [1, 2], new: [1, 3] }] },
  { i: 2, title: "Callers follow", summary: "Callers use it.", risk: "high", risk_reason: "Touches the `upload` path.", depends_on: [1, 3], hunks: [{ id: "h2", path: "b.js", change: "modified", old: [4, 2], new: [4, 2] }, { id: "h3", path: "c.js", change: "added", old: [0, 0], new: [1, 9] }] },
  { i: 3, title: "Tests", summary: "", risk: "medium", risk_reason: "", depends_on: [], hunks: [] },
];

test("chunksOf is the review's chunks, and none for a review made before chunks", () => {
  const { chunksOf } = require("../tree.js");
  assert.deepEqual(chunksOf({ chunks: CHUNKS }), CHUNKS);
  assert.deepEqual(chunksOf({}), []);
});

test("the chunks filter line counts the chunks and how many are judged, singular for one, and the chunk list has no lede", () => {
  const { chunkList, filters } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const lede = (chunks, judged) => byClass(filters({ mode: "chunks", chunks, selectedChunk: null, judged: new Set(judged) }, {}), "prf-lede")[0].textContent;
    assert.equal(lede(CHUNKS, [2]), "3 chunks · 1 judged");
    assert.equal(lede(CHUNKS, []), "3 chunks · 0 judged");
    assert.equal(lede(CHUNKS.slice(0, 1), [1]), "1 chunk · 1 judged");
    assert.equal(lede(CHUNKS, [2, 99]), "3 chunks · 1 judged");
    assert.deepEqual(byClass(chunkList({ chunks: CHUNKS, selectedChunk: null, judged: new Set() }, {}), "prf-lede"), []);
  } finally {
    delete globalThis.document;
  }
});

test("a chunk row shows the number, title, risk and a tick when judged, and marks the current chunk", () => {
  const { chunkList } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const picked = [];
    const list = chunkList({ chunks: CHUNKS, selectedChunk: 2, judged: new Set([1]) }, { onSelectChunk: (i) => picked.push(i) });
    const rows = byClass(list, "prf-chunk");
    assert.deepEqual(
      rows.map((row) => [byClass(row, "prf-num")[0].textContent, byClass(row, "prf-name")[0].textContent, byClass(row, "prf-risk")[0].textContent, byClass(row, "prf-file").length]),
      [["1", "Entities take identity", "low", 0], ["2", "Callers follow", "high", 0], ["3", "Tests", "medium", 0]],
    );
    assert.deepEqual(rows.map((row) => byClass(row, "prf-risk")[0].className), ["prf-risk prf-risk-low", "prf-risk prf-risk-high", "prf-risk prf-risk-medium"]);
    assert.deepEqual(rows.map((row) => byClass(row, "prf-judged-tick").length), [1, 0, 0]);
    const tick = byClass(rows[0], "prf-judged-tick")[0];
    assert.deepEqual([tick.title, tick.textContent, tick.children.map((child) => [child.tag, child.className, child.attributes.width])], ["Judged", "", [["svg", "prf-judged-icon", "16"]]]);
    assert.deepEqual(byClass(rows[0], "prf-head-main")[0].children.map((child) => child.className), ["prf-num", "prf-name", "prf-chunk-meta"]);
    assert.deepEqual(byClass(rows[1], "prf-chunk-meta")[0].children.map((child) => child.className), ["prf-risk prf-risk-high"]);
    assert.deepEqual(rows.map((row) => row.className.split(" ").includes("prf-selected")), [false, true, false]);
    assert.deepEqual(rows.map((row) => byClass(row, "prf-head-main")[0].attributes["aria-current"] ?? null), [null, "step", null]);
    assert.deepEqual(rows.map((row) => row.dataset.chunk), ["1", "2", "3"]);
    for (const row of rows) byClass(row, "prf-head-main")[0].listeners.click();
    assert.deepEqual(picked, [1, 2, 3]);
  } finally {
    delete globalThis.document;
  }
});

test("filesOf groups a chunk's hunks by path, in the order of each path's first hunk", () => {
  const { filesOf } = require("../tree.js");
  const hunk = (id, path) => ({ id, path, change: "modified", old: [1, 1], new: [1, 1] });
  const chunk = { i: 1, hunks: [hunk("h1", "src/b.js"), hunk("h2", "src/a.js"), hunk("h3", "src/b.js"), hunk("h4", "src/b.js")] };
  assert.deepEqual(filesOf(chunk), [
    { path: "src/b.js", hunks: [chunk.hunks[0], chunk.hunks[2], chunk.hunks[3]] },
    { path: "src/a.js", hunks: [chunk.hunks[1]] },
  ]);
  assert.deepEqual(filesOf(CHUNKS[2]), []);
});

test("only the selected chunk's row lists its files, by name with the path as the tooltip, and a click opens the file in the chunk", () => {
  const { chunkList } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const picked = [];
    const chunks = [{ ...CHUNKS[0], hunks: [{ ...CHUNKS[0].hunks[0], path: "src/deep/a.js" }] }, { ...CHUNKS[1], hunks: [...CHUNKS[1].hunks, { id: "h4", path: "b.js", change: "modified", old: [9, 1], new: [9, 1] }] }, CHUNKS[2]];
    const rows = (selectedChunk) => byClass(chunkList({ chunks, selectedChunk, judged: new Set() }, { onSelectFileInChunk: (i, path) => picked.push([i, path]) }), "prf-chunk");
    assert.deepEqual(rows(null).map((row) => byClass(row, "prf-chunk-files").length), [0, 0, 0]);
    assert.deepEqual(rows(2).map((row) => byClass(row, "prf-chunk-files").length), [0, 1, 0]);
    const files = byClass(rows(2)[1], "prf-chunk-file");
    assert.deepEqual(
      files.map((file) => [byClass(file, "prf-chunk-file-name")[0].textContent, file.title]),
      [["b.js", "b.js"], ["c.js", "c.js"]],
    );
    const nested = byClass(rows(1)[0], "prf-chunk-file");
    assert.deepEqual(nested.map((file) => [byClass(file, "prf-chunk-file-name")[0].textContent, file.title]), [["a.js", "src/deep/a.js"]]);
    assert.equal(byClass(rows(3)[2], "prf-chunk-files")[0].children.length, 0);
    for (const file of files) file.listeners.click();
    nested[0].listeners.click();
    assert.deepEqual(picked, [[2, "b.js"], [2, "c.js"], [1, "src/deep/a.js"]]);
  } finally {
    delete globalThis.document;
  }
});

test("a chunk callout names the chunk, its risk and why, its summary and what it needs, which go", () => {
  const { chunkCallout } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const went = [];
    const card = chunkCallout(CHUNKS[1], CHUNKS, (i) => went.push(i), () => {});
    const head = byClass(card, "prf-callout-head")[0];
    assert.deepEqual(head.children.map((child) => child.className), ["prf-callout-icon", "prf-callout-where", "prf-callout-sep", "prf-callout-name"]);
    assert.deepEqual([head.children[1].tag, head.children[1].textContent, head.children[3].textContent], ["strong", "Chunk 2 of 3", "Callers follow"]);
    const risk = byClass(card, "prf-callout-risk")[0];
    assert.deepEqual([byClass(risk, "prf-risk")[0].textContent, byClass(risk, "prf-callout-reason-text")[0].textContent, byClass(risk, "code").length], ["high", "Touches the upload path.", 0]);
    assert.equal(walk(risk).filter((element) => element.tag === "code")[0].textContent, "upload");
    assert.equal(byClass(card, "prf-callout-reason")[0].textContent, "Callers use it.");
    const needs = byClass(card, "prf-callout-needs")[0];
    assert.equal(needs.textContent, "Needs 1, 3");
    const buttons = byClass(needs, "prf-callout-need");
    assert.deepEqual(buttons.map((element) => element.textContent), ["1", "3"]);
    for (const element of buttons) element.listeners.click();
    assert.deepEqual(went, [1, 3]);
  } finally {
    delete globalThis.document;
  }
});

test("a chunk callout leaves out the risk line, the summary and Needs when the chunk has none", () => {
  const { chunkCallout } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const card = chunkCallout({ ...CHUNKS[2], risk: undefined }, CHUNKS, () => {}, () => {});
    assert.deepEqual([byClass(card, "prf-callout-risk").length, byClass(card, "prf-callout-reason").length, byClass(card, "prf-callout-needs").length], [0, 0, 0]);
    const first = chunkCallout({ ...CHUNKS[0], risk_reason: "" }, CHUNKS, () => {}, () => {});
    assert.deepEqual([byClass(first, "prf-risk").length, byClass(first, "prf-callout-reason-text").length], [1, 0]);
  } finally {
    delete globalThis.document;
  }
});

test("a chunk callout keeps its Previous and Next slots, hiding the missing one, and each goes to that chunk", () => {
  const { chunkCallout } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const slots = (chunk) => {
      const went = [];
      const card = chunkCallout(chunk, CHUNKS, (i) => went.push(i), () => {});
      const [back, next] = [byClass(card, "prf-callout-prev")[0], byClass(card, "prf-callout-next")[0]];
      back.listeners.click();
      next.listeners.click();
      return { texts: [back.textContent, next.textContent], inert: [back.disabled ?? false, next.disabled ?? false], titles: [back.title ?? null, next.title ?? null], went };
    };
    assert.deepEqual(slots(CHUNKS[0]), { texts: ["↑ Previous", "Next ↓"], inert: [true, false], titles: [null, "Callers follow"], went: [2] });
    assert.deepEqual(slots(CHUNKS[1]), { texts: ["↑ Previous", "Next ↓"], inert: [false, false], titles: ["Entities take identity", "Tests"], went: [1, 3] });
    assert.deepEqual(slots(CHUNKS[2]), { texts: ["↑ Previous", "Next ↓"], inert: [false, true], titles: ["Callers follow", null], went: [2] });
  } finally {
    delete globalThis.document;
  }
});

test("a chunk callout's Judged checkbox starts as the chunk is and reports each change", () => {
  const { chunkCallout } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const reported = [];
    const box = (judged) => walk(chunkCallout(CHUNKS[0], CHUNKS, () => {}, (i, on) => reported.push([i, on]), judged)).find((element) => element.tag === "input");
    assert.deepEqual([box(false).checked, box(true).checked, box(false).type], [false, true, "checkbox"]);
    const live = box(false);
    live.checked = true;
    live.listeners.change();
    live.checked = false;
    live.listeners.change();
    assert.deepEqual(reported, [[1, true], [1, false]]);
    const card = chunkCallout(CHUNKS[0], CHUNKS, () => {}, () => {});
    assert.equal(byClass(card, "prf-callout-judged")[0].textContent, "Judged");
    assert.deepEqual(byClass(card, "prf-callout-nav")[0].children.map((child) => child.className), ["prf-callout-prev prf-callout-empty", "prf-callout-next", "prf-callout-judged"]);
    assert.deepEqual(byClass(byClass(card, "prf-callout-main")[0], "prf-callout-judged"), []);
  } finally {
    delete globalThis.document;
  }
});

test("the mode toggle offers Chunks between the walkthrough and the host's tree only for a review with chunks, and the chunks tab has no chip row", () => {
  const { bar } = require("../tree.js");
  globalThis.document = fakeDom();
  globalThis.prFocus.page = { treeLabel: "Files" };
  try {
    const chips = [{ id: "all", label: "All", count: 9 }, { id: "contract", label: "API", count: 4 }];
    const labels = (state) => byClass(bar(state, { onMode() {} }), "prf-mode").map((choice) => choice.children[1].textContent);
    assert.deepEqual(labels({ mode: "github", chips: [], chunks: CHUNKS }), ["Walkthrough", "Chunks", "Files"]);
    assert.deepEqual(labels({ mode: "github", chips: [], chunks: [] }), ["Walkthrough", "Files"]);
    assert.deepEqual(labels({ mode: "github", chips: [] }), ["Walkthrough", "Files"]);
    const modes = [];
    const element = bar({ mode: "chunks", chips, chunks: CHUNKS }, { onMode: (mode) => modes.push(mode) });
    const choices = byClass(element, "prf-mode");
    assert.deepEqual(choices.map((choice) => choice.attributes["aria-pressed"]), ["false", "true", "false"]);
    for (const choice of choices) choice.listeners.click();
    assert.deepEqual(modes, ["review", "chunks", "github"]);
    assert.deepEqual(element.children.map((child) => child.className), ["prf-modes"]);
    assert.deepEqual(bar({ mode: "review", chips, chunks: CHUNKS, tests: ["a.test.js"] }, {}).children.map((child) => child.className), ["prf-modes"]);
  } finally {
    delete globalThis.document;
    delete globalThis.prFocus.page;
  }
});

function fakeDiff(blockIds) {
  class Row {
    constructor(lines = [], extra = {}) {
      Object.assign(this, { lines, hunk: false, callout: false, hidden: false, ...extra });
      this.classList = {
        contains: (name) => name === "prf-callout-row" && this.callout,
        add: () => (this.hidden = true),
        remove: () => (this.hidden = false),
        toggle: (_name, on) => (this.hidden = Boolean(on)),
      };
    }
  }
  const line = (...pairs) => new Row(pairs.map(([side, number]) => ({ side, line: number })));
  const blocks = blockIds.map((id) => {
    const block = { id, fileHidden: false, rows: [], classList: { toggle: (_name, on) => (block.fileHidden = Boolean(on)) } };
    block.querySelectorAll = (selector) => (selector === "tr" ? block.rows : []);
    return block;
  });
  const all = () => blocks.flatMap((block) => block.rows);
  globalThis.document = { querySelectorAll: (selector) => (selector === "block" ? blocks : selector === ".prf-hunk-hidden" ? all().filter((row) => row.hidden) : []) };
  return { blocks, Row, line };
}

function hunkPage(extra = {}) {
  return filePage({
    blockSelector: "block",
    treeHost: () => null,
    diffId: async (path) => `diff-${path}`,
    rowLines: (row) => row.lines,
    hunkRow: (row) => row.hunk,
    ...extra,
  });
}

test("filterHunks hides the rows outside the ranges and the hunk header or expand row left standing before a hidden one", async () => {
  const { blocks, Row, line } = fakeDiff(["diff-a", "diff-b"]);
  const [a, b] = blocks;
  a.rows = [
    new Row([], { hunk: true }),
    line(["L", 9], ["R", 10]),
    line(["R", 11]),
    new Row([], { hunk: true }),
    line(["L", 29], ["R", 30]),
    new Row([], { callout: true }),
    new Row([], { hunk: true }),
    line(["R", 50]),
    new Row([]),
  ];
  b.rows = [line(["R", 1])];
  const page = hunkPage();
  await page.filterHunks([{ path: "a", side: "R", start: 10, count: 2 }]);
  assert.deepEqual(a.rows.map((row) => row.hidden), [false, false, false, true, true, false, true, true, false]);
  assert.deepEqual([a.fileHidden, b.fileHidden], [false, true]);
  await page.filterHunks(null);
  assert.deepEqual([...a.rows, ...b.rows].map((row) => row.hidden), new Array(10).fill(false));
  assert.deepEqual([a.fileHidden, b.fileHidden], [false, false]);
});

test("a row is kept when any of its lines is in a range of its own side, so a removed line needs an old-side range", async () => {
  const { blocks, line } = fakeDiff(["diff-a"]);
  blocks[0].rows = [line(["L", 5]), line(["R", 5]), line(["L", 5], ["R", 5]), line(["L", 6]), line(["R", 4]), line(["R", 7])];
  const page = hunkPage();
  await page.filterHunks([{ path: "a", side: "L", start: 5, count: 1 }]);
  assert.deepEqual(blocks[0].rows.map((row) => row.hidden), [false, true, false, true, true, true]);
  await page.filterHunks([{ path: "a", side: "R", start: 5, count: 2 }, { path: "a", side: "L", start: 6, count: 1 }]);
  assert.deepEqual(blocks[0].rows.map((row) => row.hidden), [true, false, false, false, true, true]);
});

test("a row that shows no line and is no hunk row is left alone, with or without hunk detection", async () => {
  const { blocks, Row, line } = fakeDiff(["diff-a"]);
  blocks[0].rows = [new Row([]), line(["R", 99]), new Row([]), new Row([], { hunk: true }), line(["R", 98])];
  await hunkPage().filterHunks([{ path: "a", side: "R", start: 1, count: 1 }]);
  assert.deepEqual(blocks[0].rows.map((row) => row.hidden), [false, true, false, true, true]);
  await hunkPage({ hunkRow: undefined }).filterHunks([{ path: "a", side: "R", start: 1, count: 1 }]);
  assert.deepEqual(blocks[0].rows.map((row) => row.hidden), [false, true, false, false, true]);
});

test("filterHunks is applied again to rows the host rendered since, without asking for the ids again, and a new filter drops the old rows' hiding", async () => {
  const { blocks, Row, line } = fakeDiff(["diff-a", "diff-b"]);
  const [a, b] = blocks;
  a.rows = [line(["R", 1])];
  let asked = 0;
  const page = hunkPage({ diffId: async (path) => (asked += 1, `diff-${path}`) });
  const ranges = [{ path: "a", side: "R", start: 1, count: 1 }];
  await page.filterHunks(ranges);
  a.rows.push(line(["R", 2]), new Row([], { hunk: true }), line(["R", 9]));
  await page.filterHunks(ranges);
  assert.deepEqual(a.rows.map((row) => row.hidden), [false, true, true, true]);
  assert.equal(asked, 1);
  b.rows = [line(["R", 1]), line(["R", 5])];
  await page.filterHunks([{ path: "b", side: "R", start: 1, count: 1 }]);
  assert.deepEqual([a.fileHidden, b.fileHidden, ...b.rows.map((row) => row.hidden), ...a.rows.map((row) => row.hidden)], [true, false, false, true, false, false, false, false]);
});

test("the hunk filter takes the place of the file filter while set, tree rows included, and the file filter comes back after it", async () => {
  const { blocks } = fakeDiff(["diff-a", "diff-b", "diff-c"]);
  const tree = fakeTree(["#diff-a", "#diff-b", "#diff-c"]);
  const page = hunkPage({ treeHost: () => tree.host, treeFileSelector: "file", treeDirSelector: "dir" });
  await page.filterFiles(["a", "b"]);
  assert.deepEqual(blocks.map((block) => block.fileHidden), [false, false, true]);
  await page.filterHunks([{ path: "c", side: "R", start: 1, count: 1 }]);
  assert.deepEqual(blocks.map((block) => block.fileHidden), [true, true, false]);
  assert.deepEqual(tree.files.map((row) => row.hidden), [true, true, false]);
  await page.filterHunks(null);
  assert.deepEqual(blocks.map((block) => block.fileHidden), [false, false, true]);
  assert.deepEqual(tree.files.map((row) => row.hidden), [false, false, true]);
});

test("a newer filterHunks call wins over an older one that is still looking up its ids", async () => {
  const { blocks } = fakeDiff(["diff-a", "diff-b"]);
  let release;
  const slow = new Promise((resolve) => (release = resolve));
  const page = hunkPage({ diffId: async (path) => (path === "a" ? (await slow, "diff-a") : "diff-b") });
  const older = page.filterHunks([{ path: "a", side: "R", start: 1, count: 1 }]);
  await page.filterHunks([{ path: "b", side: "R", start: 1, count: 1 }]);
  release();
  await older;
  assert.deepEqual(blocks.map((block) => block.fileHidden), [true, false]);
});

test("a kept diff behind the host's load control is loaded once, and a diff outside the ranges is not", async () => {
  const { blocks } = fakeDiff(["diff-a", "diff-b"]);
  const loaded = [];
  const page = hunkPage({ loadDiff: (id) => (loaded.push(id), true) });
  const ranges = [{ path: "a", side: "R", start: 1, count: 1 }];
  await page.filterHunks(ranges);
  await page.filterHunks(ranges);
  assert.deepEqual(loaded, ["diff-a"]);
  assert.equal(blocks.length, 2);
});

function adapterRows(rows, algorithm) {
  const block = { id: `diff-${createHash(algorithm).update("x").digest("hex")}`, classList: { toggle() {} }, querySelectorAll: (selector) => (selector === "tr" ? rows : []) };
  globalThis.document = {
    querySelectorAll: (selector) => (selector.startsWith("#diff-container") || selector.startsWith("div[id^=") ? [block] : selector === ".prf-hunk-hidden" ? rows.filter((row) => row.hidden) : []),
    querySelector: () => null,
    getElementById: (id) => (id === "prf-forgejo-theme" ? {} : null),
  };
}

function adapterRow(extra) {
  const row = { hidden: false, text: "", ...extra };
  row.textContent = row.text;
  row.classList = { contains: (name) => (row.classes ?? []).includes(name), add: () => (row.hidden = true), remove: () => (row.hidden = false), toggle: (_name, on) => (row.hidden = Boolean(on)) };
  return row;
}

test("GitHub rows give their lines by their line anchors, and a hunk cell's anchor is no line but marks a @@ or expand row", async () => {
  const hash = "f".repeat(64);
  const cell = (anchor) => ({ getAttribute: (name) => (name === "data-line-anchor" ? anchor : null) });
  const code = (...anchors) => adapterRow({ querySelectorAll: () => anchors.map(cell), querySelector: () => null });
  const hunk = (anchor, text) =>
    adapterRow({ text, querySelectorAll: (selector) => (selector.includes(":not(") ? [] : [cell(anchor)]), querySelector: (selector) => (selector === ".diff-hunk-cell" ? {} : null) });
  const rows = [
    hunk(`diff-${hash}R0`, "@@ -1,3 +1,4 @@"),
    code(`diff-${hash}R1`),
    code(`diff-${hash}L2`),
    code(`diff-${hash}R2`),
    hunk(`diff-${hash}R3`, ""),
    hunk(`diff-${hash}R9`, "@@ -9,2 +10,2 @@"),
    code(`diff-${hash}R10`),
    code(`diff-${hash}HL4`),
    adapterRow({ text: "A comment", querySelectorAll: () => [], querySelector: () => null }),
  ];
  adapterRows(rows, "sha256");
  try {
    await githubPage.filterHunks([{ path: "x", side: "R", start: 1, count: 2 }, { path: "x", side: "L", start: 2, count: 1 }]);
    assert.deepEqual(rows.map((row) => row.hidden), [false, false, false, false, true, true, true, false, false]);
  } finally {
    delete globalThis.document;
  }
});

test("Forgejo rows give their lines by the rel of their line-number spans, and a tag-code row stands with the next row", async () => {
  const hash = "e".repeat(40);
  const span = (rel) => ({ getAttribute: (name) => (name === "rel" ? rel : null) });
  const code = (...rels) => adapterRow({ classes: ["add-code"], querySelectorAll: () => rels.map(span) });
  const rows = [
    adapterRow({ classes: ["tag-code"], querySelectorAll: () => [] }),
    code("", `diff-${hash}R3`),
    code(`diff-${hash}L4`, ""),
    adapterRow({ classes: ["tag-code"], querySelectorAll: () => [] }),
    code(`diff-${hash}L40`, `diff-${hash}R41`),
  ];
  adapterRows(rows, "sha1");
  try {
    await forgejoPage.filterHunks([{ path: "x", side: "R", start: 3, count: 1 }, { path: "x", side: "L", start: 4, count: 1 }]);
    assert.deepEqual(rows.map((row) => row.hidden), [false, false, false, true, true]);
  } finally {
    delete globalThis.document;
  }
});

test("testsOf is the review's test files, and none for a review made before they were listed", () => {
  const { testsOf } = require("../tree.js");
  assert.deepEqual(testsOf({ file_sets: { contract: [], data: [], tests: ["a.test.js"] } }), ["a.test.js"]);
  assert.deepEqual(testsOf({ file_sets: { contract: ["a.js"] } }), []);
  assert.deepEqual(testsOf({}), []);
});

function filtersOf(state, handlers = {}) {
  const { filters } = require("../tree.js");
  globalThis.document = fakeDom();
  globalThis.prFocus.page = { treeLabel: "Files" };
  try {
    return filters({ chips: [], ...state }, handlers);
  } finally {
    delete globalThis.document;
    delete globalThis.prFocus.page;
  }
}

function testsControlOf(state, handlers = {}) {
  const line = filtersOf(state, handlers);
  return line ? byClass(line, "prf-tests") : [];
}

test("the filter line holds the chips in the walkthrough and Files, the lede in Chunks, and the Tests control outside the walkthrough", () => {
  const tests = ["a.test.js"];
  const chips = [{ id: "all", label: "All", count: 3 }];
  assert.deepEqual(filtersOf({ mode: "review", chips, tests, chunks: CHUNKS }).children.map((child) => child.className), ["prf-chips"]);
  assert.equal(filtersOf({ mode: "review", chips: [], tests }), null);
  assert.deepEqual(filtersOf({ mode: "github", chips, tests }).children.map((child) => child.className), ["prf-chips", "prf-tests"]);
  assert.deepEqual(filtersOf({ mode: "chunks", chunks: CHUNKS, tests }).children.map((child) => child.className), ["prf-lede", "prf-tests"]);
  assert.deepEqual(filtersOf({ mode: "chunks", chunks: CHUNKS }).children.map((child) => child.className), ["prf-lede"]);
  assert.deepEqual(filtersOf({ mode: "github", chips: [], tests }).children.map((child) => child.className), ["prf-tests"]);
  assert.equal(filtersOf({ mode: "github", chips: [] }), null);
});

test("the Tests control is drawn only when the review has test files, in Files and Chunks, and not in the walkthrough", () => {
  assert.deepEqual(testsControlOf({ mode: "github" }), []);
  assert.deepEqual(testsControlOf({ mode: "github", tests: [] }), []);
  assert.equal(testsControlOf({ mode: "github", tests: ["a.test.js"] }).length, 1);
  assert.equal(testsControlOf({ mode: "chunks", chunks: CHUNKS, tests: ["a.test.js"] }).length, 1);
  assert.deepEqual(testsControlOf({ mode: "review", tests: ["a.test.js"] }), []);
});

test("the Tests control reads Tests all · hidden · only and presses the choice matching the mode, all when there is none", () => {
  const view = (testsMode) => {
    const [control] = testsControlOf({ mode: "github", tests: ["a.test.js"], testsMode });
    const choices = byClass(control, "prf-tests-choice");
    return { text: control.textContent, label: byClass(control, "prf-tests-label")[0].textContent, choices: choices.map((choice) => choice.textContent), pressed: choices.map((choice) => choice.attributes["aria-pressed"]) };
  };
  const text = "Testsall·hidden·only";
  const choices = ["all", "hidden", "only"];
  assert.deepEqual(view("all"), { text, label: "Tests", choices, pressed: ["true", "false", "false"] });
  assert.deepEqual(view("hide"), { text, label: "Tests", choices, pressed: ["false", "true", "false"] });
  assert.deepEqual(view("only"), { text, label: "Tests", choices, pressed: ["false", "false", "true"] });
  assert.deepEqual(view(undefined).pressed, ["true", "false", "false"]);
});

test("clicking a Tests choice sends that mode, whichever is in effect", () => {
  const asked = [];
  const [control] = testsControlOf({ mode: "chunks", chunks: CHUNKS, tests: ["a.test.js"], testsMode: "hide" }, { onTestsMode: (mode) => asked.push(mode) });
  for (const choice of byClass(control, "prf-tests-choice")) choice.listeners.click();
  assert.deepEqual(asked, ["all", "hide", "only"]);
});

test("a stop row is not dimmed by the Tests mode", () => {
  const { stopList } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const stops = [
      { i: 1, title: "Code", why: "", path: "src/a.js", side: "R", line: 1, node: null },
      { i: 2, title: "Test", why: "", path: "src/a.test.js", side: "R", line: 1, node: null },
    ];
    for (const testsMode of ["all", "hide", "only"]) {
      const classes = byClass(stopList({ stops, selectedStop: null, tests: ["src/a.test.js"], testsMode }, {}), "prf-stop").map((row) => row.className);
      assert.deepEqual(classes.filter((name) => name.includes("prf-dimmed")), []);
    }
  } finally {
    delete globalThis.document;
  }
});

test("a chunk's file button is struck through when the Tests mode keeps that file out of view", () => {
  const { chunkList } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const hunk = (id, path) => ({ id, path, change: "modified", old: [1, 1], new: [1, 1] });
    const chunks = [{ i: 1, title: "t", summary: "", risk: "low", depends_on: [], hunks: [hunk("h1", "src/a.js"), hunk("h2", "src/a.test.js")] }];
    const struck = (testsMode) => byClass(chunkList({ chunks, selectedChunk: 1, judged: new Set(), tests: ["src/a.test.js"], testsMode }, {}), "prf-chunk-file").map((file) => file.className.split(" ").includes("prf-dimmed"));
    assert.deepEqual(struck("all"), [false, false]);
    assert.deepEqual(struck("hide"), [false, true]);
    assert.deepEqual(struck("only"), [true, false]);
  } finally {
    delete globalThis.document;
  }
});

test("a stop callout's Previous and Next go to the neighbouring stops, and a slot with none beyond it is hidden", () => {
  globalThis.document = fakeDom();
  try {
    const gone = [];
    const [prevSlot, nextSlot] = navSlots(stopCallout(STOPS[0], STOPS, (target) => gone.push(target.i), NODES));
    assert.deepEqual([prevSlot.hidden, nextSlot.hidden, nextSlot.title], [true, false, STOPS[1].title]);
    const [, lastNext] = navSlots(stopCallout(STOPS[2], STOPS, () => {}, NODES));
    assert.equal(lastNext.hidden, true);
    const card = stopCallout(STOPS[1], STOPS, (target) => gone.push(target.i), NODES);
    for (const button of walk(card).filter((element) => element.tag === "button")) button.listeners.click();
    assert.deepEqual(gone, [1, 3]);
  } finally {
    delete globalThis.document;
  }
});

test("excludeFiles hides the blocks and tree rows of its files, and a directory left with none, whatever the file filter keeps", withBlocks(["diff-a", "diff-b", "diff-c"], async (blocks) => {
  const tree = fakeTree(["#diff-a", "#diff-b", "#diff-c"]);
  const page = filePage({ blockSelector: "block", treeHost: () => tree.host, treeFileSelector: "file", treeDirSelector: "dir", diffId: async (path) => `diff-${path}` });
  await page.excludeFiles(["b"]);
  assert.deepEqual(blocks.map((block) => block.hidden), [false, true, false]);
  assert.deepEqual(tree.files.map((row) => row.hidden), [false, true, false]);
  assert.equal(tree.dir.hidden, false);
  await page.filterFiles(["a", "b"]);
  assert.deepEqual(blocks.map((block) => block.hidden), [false, true, true]);
  assert.deepEqual(tree.files.map((row) => row.hidden), [false, true, true]);
  await page.excludeFiles(["a", "b", "c"]);
  assert.equal(tree.dir.hidden, true);
  await page.excludeFiles(null);
  assert.deepEqual(blocks.map((block) => block.hidden), [false, false, true]);
  await page.filterFiles(null);
  assert.deepEqual([...blocks, ...tree.files, tree.dir].map((item) => item.hidden), new Array(7).fill(false));
}));

test("excludeFiles is applied again on every call and asks for the ids once per set of paths, and a newer call wins", withBlocks(["diff-a", "diff-b"], async (blocks) => {
  let asked = 0;
  const page = filePage({ blockSelector: "block", treeHost: () => null, diffId: async (path) => (asked += 1, `diff-${path}`) });
  await page.excludeFiles(["a"]);
  blocks[0].hidden = false;
  await page.excludeFiles(["a"]);
  assert.deepEqual([blocks[0].hidden, asked], [true, 1]);
  const older = page.excludeFiles(["b"]);
  await page.excludeFiles(["a"]);
  await older;
  assert.deepEqual(blocks.map((block) => block.hidden), [true, false]);
}));

test("an excluded block is hidden even when the hunk filter keeps it, and its rows are left alone", async () => {
  const { blocks, Row, line } = fakeDiff(["diff-a", "diff-b"]);
  blocks[0].rows.push(line(["R", 1]), line(["R", 2]));
  blocks[1].rows.push(line(["R", 1]));
  const page = hunkPage();
  await page.filterHunks([{ path: "a", side: "R", start: 1, count: 1 }, { path: "b", side: "R", start: 1, count: 1 }]);
  assert.deepEqual(blocks.map((block) => block.fileHidden), [false, false]);
  assert.deepEqual(blocks[0].rows.map((row) => row.hidden), [false, true]);
  await page.excludeFiles(["a"]);
  assert.deepEqual(blocks.map((block) => block.fileHidden), [true, false]);
  assert.deepEqual(blocks[0].rows.map((row) => row.hidden), [false, false]);
  await page.excludeFiles(null);
  assert.deepEqual(blocks.map((block) => block.fileHidden), [false, false]);
  assert.deepEqual(blocks[0].rows.map((row) => row.hidden), [false, true]);
  assert.ok(Row);
});
