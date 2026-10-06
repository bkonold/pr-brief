const test = require("node:test");
const assert = require("node:assert/strict");

const { createHash } = require("node:crypto");

const githubPage = require("../github_page.js");
const forgejoPage = require("../forgejo_page.js");
const { chooseAdapter } = require("../page.js");
const { prFromUrl, pullFromUrl, lineAnchor, stickyOffset, startDistance, landingDelta, centeringDelta, correctLanding } = githubPage;
const { staleMessage, ambiguousNames, levelLabel, normalizeLevel, chunkLabels, orderChunks, chunkOfNode, revealTarget, readFirstReason } = require("../tree.js");
const { nodeIdOf, edgeEnds, unsafeAttribute, clampWidth, legendKinds } = require("../diagram.js");

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

test("ambiguousNames lists the basenames that more than one file shares", () => {
  const files = [{ path: "a/x/route.tsx" }, { path: "a/y/route.tsx" }, { path: "a/x/utils.ts" }, { path: "README.md" }];
  assert.deepEqual([...ambiguousNames(files)], ["route.tsx"]);
  assert.equal(ambiguousNames([{ path: "a/x.ts" }, { path: "b/y.ts" }]).size, 0);
  assert.equal(ambiguousNames([]).size, 0);
});

test("levelLabel names the effort level and reads the older read carefully as verify", () => {
  assert.equal(levelLabel("verify"), "verify");
  assert.equal(levelLabel("read"), "read");
  assert.equal(levelLabel("skim"), "skim");
  assert.equal(levelLabel("read carefully"), "verify");
});

test("normalizeLevel falls back to read for a missing or unknown word", () => {
  assert.equal(normalizeLevel("Read  Carefully"), "verify");
  assert.equal(normalizeLevel(undefined), "read");
  assert.equal(normalizeLevel("careful"), "read");
});

test("chunkLabels lists the known labels in display order and none for a review without labels", () => {
  assert.deepEqual(chunkLabels({ labels: ["generated", "logic", "breaking", "bogus", "data"] }), ["logic", "breaking", "data", "generated"]);
  assert.deepEqual(chunkLabels({ labels: [] }), []);
  assert.deepEqual(chunkLabels({}), []);
});

test("orderChunks sorts by review level, keeps ties in order and puts Unchunked after skim", () => {
  const chunk = (n, name, review) => ({ n, name, review });
  const ordered = orderChunks([
    chunk(1, "A", "read"),
    chunk(2, "B", "skim"),
    chunk(3, "C", "verify"),
    chunk(4, "Unchunked", "read"),
    chunk(5, "D", "skim"),
    chunk(6, "E", "read carefully"),
    chunk(7, "F", "read"),
  ]);
  assert.deepEqual(ordered.map((c) => c.n), [3, 6, 1, 7, 2, 5, 4]);
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

test("clampWidth keeps the panel between 220px and 65% of the viewport", () => {
  assert.equal(clampWidth(400, 1680), 400);
  assert.equal(clampWidth(100, 1680), 220);
  assert.equal(clampWidth(2000, 1680), 1092);
  assert.equal(clampWidth(1092.4, 1680), 1092);
  assert.equal(clampWidth(500, 1000), 500);
  assert.equal(clampWidth(900, 1000), 650);
  assert.equal(clampWidth(300, 200), 220);
  assert.equal(clampWidth(NaN, 1680), 280);
  assert.equal(clampWidth(undefined, 1680), 280);
});

const OLD_AND_NEW = [{ variant: "v10" }, { variant: "v11b" }, { variant: "v15" }, { variant: "v16" }];

test("chooseVariant takes this visit's pick first", async () => {
  const { chooseVariant } = await import("../choose_variant.js");
  const config = { default_variant: "v16", variants: ["v16"] };
  assert.equal(chooseVariant("v10", config, OLD_AND_NEW), "v10");
});

test("chooseVariant ignores a pick the PR has no run for and takes the server's default", async () => {
  const { chooseVariant } = await import("../choose_variant.js");
  const config = { default_variant: "v16", variants: ["v16"] };
  assert.equal(chooseVariant("v9", config, OLD_AND_NEW), "v16");
  assert.equal(chooseVariant(undefined, config, OLD_AND_NEW), "v16");
});

test("chooseVariant takes the newest active variant when the PR lacks the server's default", async () => {
  const { chooseVariant } = await import("../choose_variant.js");
  const config = { default_variant: "v16", variants: ["v11b", "v15", "v16"] };
  assert.equal(chooseVariant(undefined, config, [{ variant: "v10" }, { variant: "v11b" }, { variant: "v15" }]), "v15");
  assert.equal(chooseVariant(undefined, config, [{ variant: "v15" }, { variant: "v11b" }]), "v15");
});

test("chooseVariant takes the newest variant the PR has when none of them is active", async () => {
  const { chooseVariant } = await import("../choose_variant.js");
  const config = { default_variant: "v16", variants: ["v16"] };
  assert.equal(chooseVariant(undefined, config, [{ variant: "v10" }, { variant: "v9" }, { variant: "v11b" }]), "v11b");
});

test("chooseVariant takes the newest variant the PR has when the server's config is unavailable", async () => {
  const { chooseVariant } = await import("../choose_variant.js");
  assert.equal(chooseVariant(undefined, null, OLD_AND_NEW), "v16");
  assert.equal(chooseVariant(undefined, null, [{ variant: "v9" }, { variant: "v10" }]), "v10");
  assert.equal(chooseVariant("v10", null, OLD_AND_NEW), "v10");
});

test("chooseVariant orders versions by number and treats a longer name as newer", async () => {
  const { newest } = await import("../choose_variant.js");
  assert.equal(newest(["x_v9", "x_v10", "x_v11b"]), "x_v11b");
  assert.equal(newest(["x_v15", "x_v15_nocontext", "x_v14"]), "x_v15_nocontext");
  assert.equal(newest([]), undefined);
});

test("chooseVariant without a variants list falls back to the pick, then the server's default", async () => {
  const { chooseVariant } = await import("../choose_variant.js");
  const config = { default_variant: "v16", variants: ["v16"] };
  assert.equal(chooseVariant("v10", config, []), "v10");
  assert.equal(chooseVariant(undefined, config, undefined), "v16");
  assert.equal(chooseVariant(undefined, config, null), "v16");
  assert.equal(chooseVariant(undefined, null, []), undefined);
});

test("the switcher lists only variants that are active and present, in the PR's order", async () => {
  const { switcherVariants } = await import("../choose_variant.js");
  const config = { default_variant: "v16", variants: ["v16", "v15", "v14"] };
  assert.deepEqual(switcherVariants(OLD_AND_NEW, config).map((entry) => entry.variant), ["v15", "v16"]);
});

const NODE_CHUNKS = [
  { n: 1, name: "Screen", step: "UI", review: "skim", nodes: ["ui", "shared"] },
  { n: 2, name: "Endpoint", step: "API", review: "verify", nodes: ["api", "shared"] },
  { n: 3, name: "Notes", review: "read" },
];

test("chunkOfNode picks the first chunk in the displayed order that lists the box", () => {
  assert.equal(chunkOfNode(NODE_CHUNKS, "flow", "shared").n, 1);
  assert.equal(chunkOfNode(NODE_CHUNKS, "risk", "shared").n, 2);
  assert.equal(chunkOfNode(NODE_CHUNKS, "risk", "ui").n, 1);
  assert.equal(chunkOfNode(NODE_CHUNKS, "risk", "missing"), null);
});

test("legendKinds lists only the styles a diagram uses, then the selection state and the lanes note", () => {
  assert.deepEqual(legendKinds({ plain: 3, save: 0, context: 0, clusters: 0 }), ["changed", "selected"]);
  assert.deepEqual(legendKinds({ plain: 3, save: 1, context: 2, clusters: 0 }), ["changed", "save", "context", "selected"]);
  assert.deepEqual(legendKinds({ plain: 0, save: 2, context: 1, clusters: 3 }), ["save", "context", "selected", "layers"]);
  assert.deepEqual(legendKinds({ plain: 2, save: 0, context: 1, skim: 2, clusters: 0 }), ["changed", "skim", "context", "selected"]);
  assert.deepEqual(legendKinds({ plain: 0, save: 1, context: 0, verify: 1, read: 2, skim: 1, clusters: 0 }), ["verify", "read", "skim", "save", "selected"]);
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

test("readFirstReason prefers the start line's reason and falls back to the chunk's", () => {
  const start = { path: "a.ts", side: "R", line: 3, text: "x" };
  assert.equal(readFirstReason({ why: "Every user's reports.", start: { ...start, why: "Check the owner filter survives." } }), "Check the owner filter survives.");
  assert.equal(readFirstReason({ why: "Every user's reports.", start }), "Every user's reports.");
  assert.equal(readFirstReason({ why: "Every user's reports.", start: { ...start, why: "   " } }), "Every user's reports.");
  assert.equal(readFirstReason({ why: "", start }), "");
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

test("centeringDelta is the distance from a row's middle to the window's middle, 0 within tolerance", () => {
  assert.equal(centeringDelta({ top: 1000, height: 20 }, 800), 610);
  assert.equal(centeringDelta({ top: -500, height: 20 }, 800), -890);
  assert.equal(centeringDelta({ top: 390, height: 20 }, 800), 0);
  assert.equal(centeringDelta({ top: 394, height: 20 }, 800), 0);
  assert.equal(centeringDelta({ top: 396, height: 20 }, 800), 6);
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
  assert.deepEqual([githubPage.name, githubPage.treeLabel], ["GitHub", "GitHub tree"]);
  assert.deepEqual([forgejoPage.name, forgejoPage.treeLabel], ["Forgejo", "Forgejo tree"]);
  for (const page of [githubPage, forgejoPage]) {
    for (const member of ["prFromUrl", "runKey", "headSha", "fileBlocks", "diffEntries", "entryFor", "scrollToElement", "fileHeaderOf", "jumpToLine", "clearLineTarget", "restoreLineTarget", "showCallouts", "ownsLine", "cancelJump", "diagramHost", "treeHost", "descriptionHost", "filesUrl", "onChange", "onNavigate"]) {
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
  await source.loadReview("acme", "widgets", 7, undefined, "fj-7");
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

test("GitHub's conversation page, which embeds no head sha, asks the run server for it", async () => {
  const SHA = "c".repeat(40);
  const asked = [];
  const saved = globalThis.prFocus.source;
  const savedLocation = globalThis.location;
  const pr = { owner: "acme", repo: "widgets", pr: 7 };
  try {
    globalThis.location = { pathname: "/acme/widgets/pull/7" };
    globalThis.prFocus.source = { headSha: async (run) => (asked.push(run), SHA) };
    assert.equal(githubPage.headSha(), null);
    assert.equal(await githubPage.currentHeadSha(pr), SHA);
    assert.deepEqual(asked, [{ host: "github", owner: "acme", repo: "widgets", pr: 7, key: "7" }]);
    globalThis.prFocus.source = { headSha: async () => null };
    assert.equal(await githubPage.currentHeadSha(pr), null);
    delete globalThis.prFocus.source;
    assert.equal(await githubPage.currentHeadSha(pr), null);
  } finally {
    globalThis.prFocus.source = saved;
    globalThis.location = savedLocation;
    if (savedLocation === undefined) delete globalThis.location;
  }
});

const { hasSteps, defaultOrder } = require("../tree.js");

test("orderChunks in flow order keeps review.json's order and puts Unchunked last", () => {
  const chunks = [
    { n: 1, name: "Screen", review: "skim", step: "UI" },
    { n: 2, name: "Table", review: "verify", step: "Database" },
    { n: 3, name: "Unchunked", review: "read" },
    { n: 4, name: "Config", review: "read" },
  ];
  assert.deepEqual(orderChunks(chunks, "flow").map((chunk) => chunk.name), ["Screen", "Table", "Config", "Unchunked"]);
  assert.deepEqual(orderChunks(chunks, "risk").map((chunk) => chunk.name), ["Table", "Config", "Screen", "Unchunked"]);
  assert.deepEqual(orderChunks(chunks), orderChunks(chunks, "risk"));
});

test("a run opens in flow order only when its chunks have steps", () => {
  assert.equal(hasSteps([{ name: "A" }, { name: "B", step: "API" }]), true);
  assert.equal(hasSteps([{ name: "A" }]), false);
  assert.equal(defaultOrder({ chunks: [{ name: "A", step: "UI" }] }), "flow");
  assert.equal(defaultOrder({ chunks: [{ name: "A" }] }), "risk");
});

const { nextOf, prevOf, startCallout } = require("../tree.js");

const FLOW_CHUNKS = [
  { n: 1, name: "Screen", next: [2, 3], why: "Every user's reports.", start: { path: "a.js", side: "R", line: 1, why: "Where the list is built." } },
  { n: 2, name: "Endpoint", next: [3], why: "w" },
  { n: 3, name: "Table", next: [], why: "w" },
];

test("nextOf names the chunks in next, and prevOf the chunk numbered one lower", () => {
  assert.deepEqual(nextOf(FLOW_CHUNKS, FLOW_CHUNKS[0]).map((chunk) => chunk.n), [2, 3]);
  assert.deepEqual(nextOf(FLOW_CHUNKS, FLOW_CHUNKS[2]), []);
  assert.equal(prevOf(FLOW_CHUNKS, FLOW_CHUNKS[1]).n, 1);
  assert.equal(prevOf(FLOW_CHUNKS, FLOW_CHUNKS[0]), null);
});

test("without next, nextOf falls back to the chunk with the next higher number", () => {
  const old = FLOW_CHUNKS.map(({ next, ...chunk }) => chunk);
  assert.deepEqual(nextOf(old, old[0]).map((chunk) => chunk.n), [2]);
  assert.deepEqual(nextOf([old[2], old[0]], old[0]).map((chunk) => chunk.n), [3]);
  assert.deepEqual(nextOf(old, old[2]), []);
});

test("nextOf skips a number no chunk has", () => {
  assert.deepEqual(nextOf(FLOW_CHUNKS, { n: 1, next: [9, 2] }).map((chunk) => chunk.n), [2]);
});

function fakeDom() {
  class Element {
    constructor(tag) {
      Object.assign(this, { tag, className: "", textContent: "", children: [], listeners: {}, attributes: {} });
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

test("a start callout shows the chunk, the reason, its next buttons and the previous one, which jump", () => {
  globalThis.document = fakeDom();
  try {
    const gone = [];
    const card = startCallout(FLOW_CHUNKS[1], FLOW_CHUNKS, (chunk) => gone.push(chunk.n));
    assert.equal(byClass(card, "prf-callout-chunk")[0].textContent, "2 · Endpoint");
    assert.equal(byClass(card, "prf-callout-label")[0].textContent, "Why the LLM picked this");
    assert.deepEqual(byClass(card, "prf-callout-go").map((button) => button.textContent), ["3 · Table ↓"]);
    assert.deepEqual([byClass(card, "prf-callout-prev")[0].textContent, byClass(card, "prf-callout-prev")[0].title], ["↑ Previous", "1 · Screen"]);
    for (const button of [...byClass(card, "prf-callout-go"), ...byClass(card, "prf-callout-prev")]) button.listeners.click();
    assert.deepEqual(gone, [3, 1]);
  } finally {
    delete globalThis.document;
  }
});

const BOXED_CHUNKS = [
  { n: 1, name: "Screen", next: [2], why: "w", nodes: ["a"] },
  { n: 2, name: "Endpoint", next: [3], why: "w", nodes: ["b", "b2"] },
  { n: 3, name: "Table", next: [], why: "w", nodes: ["c"] },
];
const BOX_TITLES = { a: "List items", b: "Fetch items", c: "Store items" };
const titleOf = (nodeId) => BOX_TITLES[nodeId] ?? "";

test("a start callout's header is the box title in bold, a chevron, then the chunk name, and its buttons use box titles", () => {
  globalThis.document = fakeDom();
  try {
    const gone = [];
    const card = startCallout(BOXED_CHUNKS[1], BOXED_CHUNKS, (chunk) => gone.push(chunk.n), titleOf);
    const head = byClass(card, "prf-callout-head")[0];
    assert.deepEqual(head.children.map((child) => child.className), ["prf-callout-icon", "prf-callout-chunk", "prf-callout-sep", "prf-callout-name"]);
    assert.equal(head.children[1].tag, "strong");
    assert.equal(head.children[1].textContent, "2 · Fetch items");
    assert.equal(head.children[3].textContent, "Endpoint");
    assert.deepEqual(byClass(card, "prf-callout-go").map((button) => button.textContent), ["3 · Store items ↓"]);
    const previous = byClass(card, "prf-callout-prev")[0];
    assert.deepEqual([previous.textContent, previous.title], ["↑ Previous", "1 · List items"]);
    for (const button of [...byClass(card, "prf-callout-go"), previous]) button.listeners.click();
    assert.deepEqual(gone, [3, 1]);
  } finally {
    delete globalThis.document;
  }
});

test("a chunk with no box or no title for its box keeps the bold number and chunk name, with no chevron", () => {
  globalThis.document = fakeDom();
  try {
    const noBox = startCallout({ ...BOXED_CHUNKS[1], nodes: [] }, BOXED_CHUNKS, () => {}, titleOf);
    assert.deepEqual(byClass(noBox, "prf-callout-head")[0].children.map((child) => child.className), ["prf-callout-icon", "prf-callout-chunk"]);
    assert.equal(byClass(noBox, "prf-callout-chunk")[0].textContent, "2 · Endpoint");
    const untitled = startCallout(BOXED_CHUNKS[1], BOXED_CHUNKS, () => {}, () => "");
    assert.equal(byClass(untitled, "prf-callout-chunk")[0].textContent, "2 · Endpoint");
    assert.deepEqual(byClass(untitled, "prf-callout-sep"), []);
    assert.deepEqual(byClass(untitled, "prf-callout-go").map((button) => button.textContent), ["3 · Table ↓"]);
    assert.equal(byClass(untitled, "prf-callout-prev")[0].title, "1 · Screen");
  } finally {
    delete globalThis.document;
  }
});

test("a start callout uses the start line's reason, lists every next chunk and has no previous button on the first chunk", () => {
  globalThis.document = fakeDom();
  try {
    const card = startCallout(FLOW_CHUNKS[0], FLOW_CHUNKS, () => {});
    assert.equal(byClass(card, "prf-callout-reason")[0].textContent, "Where the list is built.");
    assert.deepEqual(byClass(card, "prf-callout-go").map((button) => button.textContent), ["2 · Endpoint ↓", "3 · Table ↓"]);
    assert.deepEqual(byClass(card, "prf-callout-prev"), []);
  } finally {
    delete globalThis.document;
  }
});

test("the last chunk's callout says Last step and offers no next button", () => {
  globalThis.document = fakeDom();
  try {
    const card = startCallout(FLOW_CHUNKS[2], FLOW_CHUNKS, () => {});
    assert.equal(byClass(card, "prf-callout-nav-label")[0].textContent, "Last step");
    assert.deepEqual(byClass(card, "prf-callout-go"), []);
    assert.deepEqual([byClass(card, "prf-callout-prev")[0].textContent, byClass(card, "prf-callout-prev")[0].title], ["↑ Previous", "2 · Endpoint"]);
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

test("a start callout for a file start reads the start's reason and keeps its next and previous buttons", () => {
  globalThis.document = fakeDom();
  try {
    const fileStart = { path: "b.js", side: null, line: null, why: "Open this file first." };
    const chunks = FLOW_CHUNKS.map((chunk) => (chunk.n === 2 ? { ...chunk, start: fileStart } : chunk));
    const card = startCallout(chunks[1], chunks, () => {});
    assert.equal(byClass(card, "prf-callout-reason")[0].textContent, "Open this file first.");
    assert.deepEqual(byClass(card, "prf-callout-go").map((button) => button.textContent), ["3 · Table ↓"]);
    assert.equal(byClass(card, "prf-callout-prev")[0].title, "1 · Screen");
  } finally {
    delete globalThis.document;
  }
});

test("a file row ends with its added and removed line counts, a zero side left out, and none when there are no lines", () => {
  globalThis.document = fakeDom();
  try {
    const { fileRow } = require("../tree.js");
    const countsOf = (file) => {
      const row = fileRow(file, () => {}).children[0];
      return byClass(row, "prf-file-counts").map((counts) => [row.children.at(-1) === counts, counts.children.map((side) => [side.className, side.textContent])]);
    };
    assert.deepEqual(countsOf({ path: "a/x.js", additions: 12, deletions: 3 }), [[true, [["prf-add", "+12"], ["prf-del", "\u22123"]]]]);
    assert.deepEqual(countsOf({ path: "a/x.js", additions: 12, deletions: 0 }), [[true, [["prf-add", "+12"]]]]);
    assert.deepEqual(countsOf({ path: "a/x.js", additions: 0, deletions: 4 }), [[true, [["prf-del", "\u22124"]]]]);
    assert.deepEqual(countsOf({ path: "a/x.js", additions: 0, deletions: 0 }), []);
    assert.deepEqual(countsOf({ path: "a/x.js" }), []);
  } finally {
    delete globalThis.document;
  }
});

test("a chunk's Contract and Data blocks list each line with its impact chip above its files, and a click reports the line", () => {
  const { changeBlocks, impactChip } = require("../tree.js");
  globalThis.document = fakeDom();
  try {
    const chunk = {
      n: 2,
      contract: [
        { impact: "callers must change", text: "`size` now required", path: "api/openapi.json", side: "R", line: 40 },
        { impact: "additive", text: "new `GET /items`", path: "api/openapi.json", side: "R", line: 52 },
      ],
      data: [{ impact: null, text: "DO block in V9.sql", path: "db/V9.sql", side: "R", line: 3 }],
    };
    const clicked = [];
    const blocks = changeBlocks(chunk, (line) => clicked.push(line.line));
    assert.deepEqual(blocks.map((block) => block.className), ["prf-lines prf-lines-contract", "prf-lines prf-lines-data"]);
    assert.deepEqual(blocks.map((block) => byClass(block, "prf-lines-title")[0].textContent), ["Contract", "Data"]);
    const chips = byClass(blocks[0], "prf-impact");
    assert.deepEqual(chips.map((chip) => [chip.className, chip.textContent]), [["prf-impact prf-impact-0", "callers must change"], ["prf-impact prf-impact-2", "additive"]]);
    assert.deepEqual(byClass(blocks[1], "prf-impact"), []);
    assert.deepEqual(byClass(blocks[0], "prf-line-text")[0].children.map((part) => part.tag ?? part), ["code", " now required"]);
    const rows = byClass(blocks[0], "prf-line");
    assert.equal(rows[0].title, "openapi.json:40");
    rows[1].listeners.click();
    assert.deepEqual(clicked, [52]);
    assert.equal(impactChip("consumers may break", ["callers must change", "consumers may break"]).className, "prf-impact prf-impact-1");
    assert.equal(impactChip("rewrites rows", ["destructive", "rewrites rows", "additive"]).className, "prf-impact prf-impact-1");
    assert.equal(impactChip("x", ["a"]), null);
    assert.deepEqual(changeBlocks({ n: 1 }, () => {}), []);
    assert.deepEqual(changeBlocks({ n: 1, contract: [] }, () => {}), []);
  } finally {
    delete globalThis.document;
  }
});

test("a chunk's change line is its change and where as one line, or the whole text when the run has no such parts", () => {
  const { changeBlocks, lineText } = require("../tree.js");
  assert.equal(lineText({ change: "`+ productType` required param", on: "`GET /rows`", text: "long sentence" }), "`+ productType` required param · `GET /rows`");
  assert.equal(lineText({ change: "DO block", on: "", text: "DO block in V9.sql" }), "DO block");
  assert.equal(lineText({ text: "`size` now required" }), "`size` now required");
  globalThis.document = fakeDom();
  try {
    const chunk = { n: 1, contract: [{ impact: "callers must change", text: "sentence", change: "`+ kind` required param", on: "`GET /rows`", reaches: "request", path: "api/openapi.json", side: "R", line: 4 }] };
    const [block] = changeBlocks(chunk, () => {});
    const parts = byClass(block, "prf-line-text")[0].children.map((part) => part.tag ?? part);
    assert.deepEqual(parts, ["code", " required param · ", "code"]);
    assert.equal(byClass(block, "prf-line").length, 1);
  } finally {
    delete globalThis.document;
  }
});

function fakeHeader() {
  const classes = new Set();
  return { classes, classList: { add: (name) => classes.add(name), remove: (name) => classes.delete(name) } };
}

test("focus offers no way to hide a diff, and markChunk tints only the chunk's headers without touching any diff", async () => {
  const focus = require("../focus.js");
  assert.deepEqual(Object.keys(focus).sort(), ["announceBox", "clearBox", "markBox", "markChunk", "scrollTo"]);
  const headers = new Map([["a.js", fakeHeader()], ["b.js", fakeHeader()], ["c.js", fakeHeader()]]);
  const saved = { document: globalThis.document, page: globalThis.prFocus.page, alive: globalThis.prFocus.alive };
  globalThis.prFocus.alive = () => true;
  globalThis.prFocus.page = {
    fileBlocks: () => new Map(),
    entryFor: async (path) => (headers.has(path) ? path : null),
    entryOf: () => null,
    fileHeaderOf: (entry) => headers.get(entry) ?? null,
  };
  globalThis.document = { querySelectorAll: () => [...headers.values()].filter((header) => header.classes.has("prf-chunk-mark")) };
  try {
    const marked = () => [...headers].filter(([, header]) => header.classes.has("prf-chunk-mark")).map(([path]) => path);
    await focus.markChunk({ files: [{ path: "a.js" }, { path: "b.js" }] });
    assert.deepEqual(marked(), ["a.js", "b.js"]);
    await focus.markChunk({ files: [{ path: "b.js" }, { path: "c.js" }, { path: "not-loaded.js" }] });
    assert.deepEqual(marked(), ["b.js", "c.js"]);
    await focus.markChunk(null);
    assert.deepEqual(marked(), []);
  } finally {
    globalThis.document = saved.document;
    globalThis.prFocus.page = saved.page;
    globalThis.prFocus.alive = saved.alive;
    if (saved.document === undefined) delete globalThis.document;
  }
});

test("a newer markChunk wins over an older one that is still looking for its headers", async () => {
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
  globalThis.document = { querySelectorAll: () => [...headers.values()].filter((header) => header.classes.has("prf-chunk-mark")) };
  try {
    const older = focus.markChunk({ files: [{ path: "a.js" }] });
    const newer = focus.markChunk({ files: [{ path: "b.js" }] });
    gates.get("b.js")();
    await newer;
    gates.get("a.js")();
    await older;
    assert.deepEqual([...headers].filter(([, header]) => header.classes.has("prf-chunk-mark")).map(([path]) => path), ["b.js"]);
  } finally {
    globalThis.document = saved.document;
    globalThis.prFocus.page = saved.page;
    globalThis.prFocus.alive = saved.alive;
    if (saved.document === undefined) delete globalThis.document;
  }
});
