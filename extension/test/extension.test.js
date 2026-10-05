const test = require("node:test");
const assert = require("node:assert/strict");

const { createHash } = require("node:crypto");

const githubPage = require("../github_page.js");
const forgejoPage = require("../forgejo_page.js");
const { chooseAdapter } = require("../page.js");
const { prFromUrl, pullFromUrl, lineAnchor, stickyOffset, startDistance, landingDelta, centeringDelta, correctLanding } = githubPage;
const { staleMessage, groupByFolder, orderChunks, revealTarget, startCard, readFirstReason } = require("../tree.js");
const { nodeIdOf, edgeEnds, unsafeAttribute, clampWidth, legendKinds } = require("../diagram.js");
const { keepSelection } = require("../variants.js");
const { fileBadges, targetOfNode, boxTitle } = require("../boxes.js");

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

test("groupByFolder names each shared folder once and keeps the file order", () => {
  const dir = "web/app/routes/_layout.items.$itemType.$slot";
  const files = [{ path: `${dir}/route.tsx` }, { path: `${dir}/route.test.tsx` }, { path: `${dir}/utils.ts` }];
  assert.deepEqual(groupByFolder(files), [{ folder: dir, files }]);
});

test("groupByFolder starts a new run when the folder changes, even for a folder seen before", () => {
  const files = [{ path: "a/x/route.tsx" }, { path: "a/y/route.tsx" }, { path: "a/x/utils.ts" }, { path: "a/x/more.ts" }, { path: "README.md" }];
  assert.deepEqual(
    groupByFolder(files).map(({ folder, files: run }) => [folder, run.map((file) => file.path)]),
    [
      ["a/x", ["a/x/route.tsx"]],
      ["a/y", ["a/y/route.tsx"]],
      ["a/x", ["a/x/utils.ts", "a/x/more.ts"]],
      ["", ["README.md"]],
    ],
  );
  assert.deepEqual(groupByFolder([]), []);
});

test("orderChunks sorts by review level, keeps ties in order and puts Unchunked after skim", () => {
  const chunk = (n, name, review) => ({ n, name, review });
  const ordered = orderChunks([
    chunk(1, "A", "read"),
    chunk(2, "B", "skim"),
    chunk(3, "C", "read carefully"),
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

test("chooseVariant keeps the stored default when the PR has a run for it, else the first listed", async () => {
  const { chooseVariant } = await import("../choose_variant.js");
  const listed = [{ variant: "v10" }, { variant: "v11a" }, { variant: "v11d" }];
  assert.equal(chooseVariant("v11a", listed), "v11a");
  assert.equal(chooseVariant("v9", listed), "v10");
  assert.equal(chooseVariant("v9", []), "v9");
  assert.equal(chooseVariant("v9", undefined), "v9");
});

test("keepSelection follows the selected chunk by name into the new variant", () => {
  const before = { chunks: [{ n: 1, name: "Item list screen" }, { n: 2, name: "Migration" }] };
  const after = { chunks: [{ n: 1, name: "Migration" }, { n: 2, name: "Item list screen" }, { n: 3, name: "SDK" }] };
  assert.equal(keepSelection(before, 1, after), 2);
  assert.equal(keepSelection(before, 2, after), 1);
  assert.equal(keepSelection(before, 2, { chunks: [{ n: 1, name: "Other" }] }), null);
  assert.equal(keepSelection(before, null, after), null);
  assert.equal(keepSelection(before, 9, after), null);
});

const BOX_REVIEW = {
  chunks: [
    { n: 1, name: "API", files: [{ path: "a/Controller.java" }, { path: "a/Service.java" }] },
    { n: 2, name: "Screen", files: [{ path: "web/route.tsx" }] },
  ],
  nodes: [
    { id: "ctl", number: 1, files: ["a/Controller.java"] },
    { id: "svc", number: 2, files: ["a/Service.java", "a/Controller.java"] },
    { id: "ui", number: 3, files: ["web/route.tsx"] },
    { id: "repo", number: 4, files: [] },
    { id: "lane", number: null, files: ["web/route.tsx"] },
  ],
};

test("fileBadges lists each file's box numbers in ascending order", () => {
  assert.deepEqual([...fileBadges(BOX_REVIEW)], [
    ["a/Controller.java", [1, 2]],
    ["a/Service.java", [2]],
    ["web/route.tsx", [3]],
  ]);
  assert.equal(fileBadges({ chunks: [] }).size, 0);
});

test("targetOfNode names a box's first file and its chunk, and nothing for context boxes", () => {
  assert.deepEqual(targetOfNode(BOX_REVIEW, "svc"), { path: "a/Service.java", n: 1 });
  assert.deepEqual(targetOfNode(BOX_REVIEW, "ui"), { path: "web/route.tsx", n: 2 });
  assert.equal(targetOfNode(BOX_REVIEW, "repo"), null);
  assert.equal(targetOfNode(BOX_REVIEW, "missing"), null);
  assert.equal(targetOfNode({ chunks: BOX_REVIEW.chunks }, "ctl"), null);
});

test("legendKinds lists only the styles a diagram uses, then the selection state and the lanes note", () => {
  assert.deepEqual(legendKinds({ plain: 3, save: 0, context: 0, clusters: 0 }), ["changed", "selected"]);
  assert.deepEqual(legendKinds({ plain: 3, save: 1, context: 2, clusters: 0 }), ["changed", "save", "context", "selected"]);
  assert.deepEqual(legendKinds({ plain: 0, save: 2, context: 1, clusters: 3 }), ["save", "context", "selected", "layers"]);
  assert.deepEqual(legendKinds({ plain: 2, save: 0, context: 1, skim: 2, clusters: 0 }), ["changed", "context", "skim", "selected"]);
});

test("classifyFetch tells a down server from a missing review", async () => {
  const { classifyFetch } = await import("../classify.js");
  assert.equal(classifyFetch(undefined, new TypeError("Failed to fetch")), "server");
  assert.equal(classifyFetch({ ok: false, status: 404 }, undefined), "none");
  assert.equal(classifyFetch({ ok: true, status: 200 }, undefined), "ok");
});

test("boxTitle takes the first line of a label without its box number", () => {
  assert.equal(boxTitle("3 · Call item API\nApi: new item client methods"), "Call item API");
  assert.equal(boxTitle("12 · Regenerated SDK<br/>client.ts"), "Regenerated SDK");
  assert.equal(boxTitle("  \n 4 · Contributor guide \nCONTRIBUTING.md"), "Contributor guide");
  assert.equal(boxTitle("Open form or list\nroute"), "Open form or list");
  assert.equal(boxTitle(""), "");
  assert.equal(boxTitle(undefined), "");
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

test("startCard says which line to read first and what kind of line it is", () => {
  const path = "api/src/main/java/com/example/util/ReportHelper.java";
  const added = startCard({ path, side: "R", line: 14, text: "String normalized = reportId.strip();" });
  assert.deepEqual(added, {
    heading: "Read this line first",
    location: "ReportHelper.java:14",
    kind: "added or unchanged line",
    code: "String normalized = reportId.strip();",
    path,
    hint: "Click to jump",
  });
  assert.equal(startCard({ path: "a.ts", side: "L", line: 3, text: "x" }).kind, "removed line");
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
    for (const member of ["prFromUrl", "runKey", "headSha", "fileBlocks", "diffEntries", "entryFor", "scrollToElement", "fileHeaderOf", "jumpToLine", "clearLineTarget", "restoreLineTarget", "ownsLine", "cancelJump", "diagramHost", "treeHost", "descriptionHost", "filesUrl", "onChange", "onNavigate"]) {
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
