(() => {
  const { page, source, commentSource, runControl, focus, tree, diagram, brief, alive } = globalThis.prFocus;
  if (!page) return;

  const SETTLE_MS = 150;
  const LOAD_GRACE_MS = 5000;
  const BRIEF_WAIT_MS = 250;
  const NO_BLOCKS_NOTE = `Couldn't find ${page.name}'s diff blocks; selectors may need updating`;

  let current = null;
  let loadToken = 0;
  let timer = null;
  let stopObserving = null;
  let stopNavigating = null;
  let shutDown = false;
  let briefState = null;
  let briefToken = 0;

  // The PR brief card, on the conversation page: { key, card, stop }. `card` stays null while the run loads. There is
  // one card per page; it is moved back above the description whenever the page drops or moves it, never built twice.
  function placeBrief() {
    const host = briefState?.card ? page.descriptionHost() : null;
    if (host && (briefState.card.nextElementSibling !== host || !briefState.card.isConnected)) host.before(briefState.card);
  }

  function unmountBrief() {
    briefToken += 1;
    briefState?.stop?.();
    briefState?.card?.remove();
    briefState = null;
  }

  // What the run server is asked about a PR: which host, repository and run folder.
  function runTarget(pr) {
    return { host: page.hostId, owner: pr.owner, repo: pr.repo, pr: pr.pr, key: page.runKey(pr) };
  }

  // The card is drawn for the PR's run when it has one, else as a bar offering to generate it. A run in progress
  // on the server, left by an earlier visit, is followed from where it is. A page with no brief comment yet, where
  // generating is not possible, is waited on: the lookup is repeated once the document has changed and settled.
  async function mountBrief(pr) {
    const key = `${pr.owner}/${pr.repo}#${pr.pr}`;
    if (briefState?.key === key) return;
    unmountBrief();
    const token = briefToken;
    const state = { key, card: null, stop: null };
    briefState = state;
    const target = runTarget(pr);
    const [run, status, pageSha] = await Promise.all([
      source.loadBrief(pr.owner, pr.repo, pr.pr, target.key),
      source.runStatus(target),
      page.currentHeadSha(pr),
    ]);
    if (!live() || token !== briefToken) return;
    const canGenerate = runControl.mayGenerate(status);
    if (!run && !canGenerate) {
      waitForBrief(state, pr);
      return;
    }

    let current = run;
    const baseView = () => (current ? { kind: "brief", ...current, runSha: current.headSha, pageSha, canGenerate } : { kind: "none", canGenerate });
    const controller = runControl.create({
      source,
      run: target,
      on: {
        running: (view) => card.show({ kind: "running", ...view }),
        error: (view) => card.show({ kind: "error", ...view }),
        idle: () => card.show(baseView()),
        done: async () => {
          const fresh = await source.loadBrief(pr.owner, pr.repo, pr.pr, target.key, { server: true });
          if (!live() || token !== briefToken) return;
          if (fresh) current = fresh;
          card.show(fresh ? baseView() : { kind: "error", message: "The run finished, but its brief could not be loaded" });
        },
      },
    });
    const card = brief.buildCard({
      key: target.key,
      filesUrl: page.filesUrl(pr),
      onAction: (action) => (action === "cancel" ? controller.cancel() : controller.generate()),
    });
    card.show(baseView());
    state.card = card;
    const stopChange = page.onChange(placeBrief);
    state.stop = () => {
      controller.stop();
      stopChange();
    };
    placeBrief();
    if (status.ok && status.state === "running") controller.adopt(status);
  }

  // Waits for the brief comment to reach the page: once the document has changed and settled, the lookup runs again
  // if a "Brief data" block is now in it. The wait ends with the next mount or unmount.
  function waitForBrief(state, pr) {
    let pending = null;
    const stopChange = page.onChange(() => {
      clearTimeout(pending);
      pending = setTimeout(() => {
        if (briefState !== state || !live()) return;
        if (commentSource && !commentSource.extractPayload(document)) return;
        state.stop();
        briefState = null;
        mountBrief(pr);
      }, BRIEF_WAIT_MS);
    });
    state.stop = () => {
      clearTimeout(pending);
      stopChange();
    };
  }

  function sessionKey(pr) {
    return `${pr.owner}/${pr.repo}#${pr.pr}`;
  }

  // MutationObserver bursts coalesce into one refresh through the single pending timer.
  function schedule(delay) {
    clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      if (!live()) return;
      start();
      refresh();
    }, delay);
  }

  function refresh() {
    const session = current;
    if (session?.offline && live()) {
      tree.renderServerNote(session.offline, { onRetry: () => retry(session) });
      return;
    }
    if (session?.line && live()) {
      tree.renderGenerateLine(session.line.view, { onGenerate: () => session.line.controller.generate(), onCancel: () => session.line.controller.cancel() });
      return;
    }
    if (!session?.review || !live()) return;
    renderDiagram(session);
    focus.markBox(session.activeBox?.paths ?? []);
    page.restoreLineTarget();
    page.showCallouts(calloutsShown(session));
    const fileSet = tree.fileSetOf(session.review, session.fileSet);
    const mode = testsMode(session);
    const exempt = exemptPaths(session);
    if (session.mode === "chunks") {
      const chunk = selectedChunkOf(session);
      page.filterFiles(null);
      page.filterHunks(chunk ? chunkRanges(session, chunk) : null);
      page.excludeFiles(mode === "hide" ? session.tests.filter((path) => !exempt.has(path)) : null);
    } else {
      page.filterFiles(mode === "only" ? onlyTestPaths(session, fileSet, exempt) : (fileSet?.paths ?? null));
      page.filterHunks(null);
      page.excludeFiles(mode === "hide" ? session.tests.filter((path) => !exempt.has(path)) : null);
    }

    const waited = Date.now() - session.startedAt;
    const noBlocks = page.fileBlocks().size === 0;
    if (noBlocks && waited < LOAD_GRACE_MS) schedule(LOAD_GRACE_MS - waited + SETTLE_MS);
    tree.render(
      session.review,
      {
        mode: session.mode,
        stops: session.stops,
        selectedStop: session.selectedStop,
        chunks: session.chunks,
        selectedChunk: session.selectedChunk,
        judged: session.judged,
        pageSha: page.headSha(),
        chips: tree.fileChips(session.review, page.changedFileCount()),
        fileSet,
        tests: session.tests,
        testsMode: mode,
        note: noBlocks && waited >= LOAD_GRACE_MS ? NO_BLOCKS_NOTE : null,
      },
      handlersFor(session),
    );
  }

  // Without a selected box, whether in "Files" mode or with nothing chosen, every node is shown.
  function renderDiagram(session) {
    if (!session.review.diagramSvg) {
      diagram.remove();
      return;
    }
    diagram.render(session.review.diagramSvg, { onNode: (nodeId) => selectNode(session, nodeId), onReset: () => resetReview(session) });
    diagram.emphasize(session.mode === "review" && session.selectedNode ? [session.selectedNode] : null);
  }

  // Ends any line jump in progress, which would otherwise scroll to its line when the row finally loads, and
  // clears the outlined line. Every selection started from the list or the diagram calls it.
  function leaveLine() {
    page.cancelJump();
    page.clearLineTarget();
  }

  // The active state: the file whose row and header are marked.
  function activation(path) {
    return { paths: [path] };
  }

  // Lands the file's header below the sticky chrome and then announces it.
  async function landOnFile(session, path) {
    if (current !== session) return;
    await focus.scrollTo(path);
    if (current !== session || !live() || session.activeBox?.paths[0] !== path) return;
    focus.announceBox([path]);
  }

  // Forgets the active selection and everything shown for it: the diff header bars.
  function deactivate(session) {
    session.activeBox = null;
    focus.clearBox();
  }

  // A stop with no line names only a file.
  function isFileStop(stop) {
    return stop.line == null;
  }

  // The anchor a stop's callout and link use: the line's, else the file's diff id.
  function stopAnchor(stop) {
    return isFileStop(stop) ? page.fileAnchor(stop.path) : page.lineAnchor(stop.path, stop.side, stop.line);
  }

  // Runs the jump to a stop: for a line, its diff scrolls into view and the line is highlighted with its callout; for a
  // file, the file's diff scrolls to its callout above the header.
  async function jumpToStop(session, stop, options) {
    if (current !== session || !live()) return;
    if (isFileStop(stop)) await page.jumpToFile(stop.path, options);
    else await page.jumpToLine(stop.path, stop.side, stop.line, options);
  }

  // The callouts of the walkthrough, one per stop that has a place in the diff: each is built when its place is found,
  // and its buttons open a stop as a click on it in the list would, without the pulse: the reader is already following
  // the callouts, so nothing needs finding.
  async function calloutsFor(session) {
    const { stops, review } = session;
    const anchors = await Promise.all(stops.map(stopAnchor));
    return stops.flatMap((stop, index) =>
      anchors[index]
        ? [
            {
              key: stop.i,
              anchor: anchors[index],
              ...(isFileStop(stop) ? { file: true } : {}),
              render: () => tree.stopCallout(stop, stops, (target) => selectStop(session, target, { pulse: false }), review.nodes, (other) => isExcluded(session, other.path)),
            },
          ]
        : [],
    );
  }

  // The callouts of the chunks, one per chunk, each at its first hunk's first line: each is built when its place is found.
  // Its buttons open a chunk, and its checkbox records the chunk as judged.
  async function chunkCalloutsFor(session) {
    const { chunks } = session;
    const targets = chunks.map((chunk) => chunkTarget(session, chunk));
    const anchors = await Promise.all(targets.map((target) => (target ? page.lineAnchor(target.path, target.side, target.line) : null)));
    return chunks.flatMap((chunk, index) =>
      anchors[index]
        ? [
            {
              key: `chunk:${chunk.i}`,
              anchor: anchors[index],
              render: () => tree.chunkCallout(chunk, chunks, (i) => selectChunk(session, i, { pulse: false }), (i, on) => setJudged(session, i, on), session.judged.has(chunk.i)),
            },
          ]
        : [],
    );
  }

  // What the page shows over the diff: the stops' callouts in the walkthrough, the selected chunk's in the chunks tab. A
  // stop's callout is built again when the Tests mode changes, since its Previous and Next pass over the stops that mode hides.
  function calloutsShown(session) {
    if (session.mode === "review") return session.callouts.map((entry) => ({ ...entry, version: testsMode(session) }));
    if (session.mode !== "chunks") return [];
    return session.chunkCallouts.filter((entry) => entry.key === `chunk:${session.selectedChunk}`);
  }

  function selectedChunkOf(session) {
    return session.chunks.find((chunk) => chunk.i === session.selectedChunk) ?? null;
  }

  // The first line a chunk shows: its first shown hunk's first new line, or, for a hunk with no new lines (a deleted
  // file, a pure deletion), its first old line; null for a chunk with no hunks.
  function chunkTarget(session, chunk) {
    const hunk = shownHunks(session, chunk)[0];
    return hunk ? hunkTarget(hunk) : null;
  }

  // The hunks of a chunk the Tests mode leaves in view. A chunk whose hunks are all kept out is shown whole instead, so
  // that opening it still shows its callout and its lines.
  function shownHunks(session, chunk) {
    const kept = chunk.hunks.filter((hunk) => !isExcluded(session, hunk.path));
    return kept.length > 0 ? kept : chunk.hunks;
  }

  // The first line a hunk shows: its first new line, or its first old line when it has no new lines.
  function hunkTarget(hunk) {
    return hunk.new[1] > 0 ? { path: hunk.path, side: "R", line: hunk.new[0] } : { path: hunk.path, side: "L", line: hunk.old[0] };
  }

  // The lines the page is narrowed to for a chunk: each hunk's new lines on the right and its old lines on the left, so
  // that removed lines stay.
  function rangesOf(chunk) {
    return chunk.hunks.flatMap(({ path, old: before, new: after }) => [
      ...(after[1] > 0 ? [{ path, side: "R", start: after[0], count: after[1] }] : []),
      ...(before[1] > 0 ? [{ path, side: "L", start: before[0], count: before[1] }] : []),
    ]);
  }

  // The lines the page is narrowed to for a chunk: its shown hunks' ranges.
  function chunkRanges(session, chunk) {
    return rangesOf({ hunks: shownHunks(session, chunk) });
  }

  // The chunks the reader has judged, kept in this browser per PR head: the viewer's own marks, not part of the review.
  function judgedKey(session) {
    const { pr, review } = session;
    return `prf-judged:${location.host}/${pr.owner}/${pr.repo}#${pr.pr}@${review.head_sha}`;
  }

  function loadJudged(session) {
    try {
      const stored = JSON.parse(localStorage.getItem(judgedKey(session)) ?? "[]");
      return new Set(Array.isArray(stored) ? stored.filter(Number.isInteger) : []);
    } catch {
      return new Set();
    }
  }

  function saveJudged(session) {
    try {
      localStorage.setItem(judgedKey(session), JSON.stringify([...session.judged].sort((a, b) => a - b)));
    } catch {
      // The marks stay for this page's life when storage is unavailable.
    }
  }

  function setJudged(session, i, on) {
    return change(session, () => {
      if (on) session.judged.add(i);
      else session.judged.delete(i);
      saveJudged(session);
    });
  }

  const TESTS_MODE_KEY = "prf-tests-mode";
  const TESTS_MODES = ["all", "hide", "only"];

  // The Tests switch's mode is the reader's preference across PRs, kept in this browser.
  function loadTestsMode() {
    try {
      const stored = localStorage.getItem(TESTS_MODE_KEY);
      return TESTS_MODES.includes(stored) ? stored : "all";
    } catch {
      return "all";
    }
  }

  function saveTestsMode(mode) {
    try {
      localStorage.setItem(TESTS_MODE_KEY, mode);
    } catch {
      // The mode stays for this page's life when storage is unavailable.
    }
  }

  // The mode in effect: a review with no test files shows every file whatever the preference.
  function testsMode(session) {
    return session.tests.length > 0 ? session.testsMode : "all";
  }

  // Whether the Tests mode keeps a file out of view: a test file when tests are hidden, any other file when only tests show.
  function isExcluded(session, path) {
    const mode = testsMode(session);
    if (mode === "all") return false;
    return session.tests.includes(path) === (mode === "hide");
  }

  // The files the mode must keep in view although it would not: in the walkthrough, the selected stop's file and the
  // active one, so that a stop or a box can always be opened; in the chunks tab, the files of a selected chunk that
  // is shown whole.
  function exemptPaths(session) {
    const paths = new Set();
    if (session.mode === "chunks") {
      const chunk = selectedChunkOf(session);
      if (chunk && chunk.hunks.every((hunk) => isExcluded(session, hunk.path))) for (const hunk of chunk.hunks) paths.add(hunk.path);
      return paths;
    }
    if (session.mode !== "review") return paths;
    const stop = session.stops.find((candidate) => candidate.i === session.selectedStop);
    if (stop) paths.add(stop.path);
    for (const path of session.activeBox?.paths ?? []) paths.add(path);
    return paths;
  }

  // The files shown in "only" mode: the PR's test files, and the exempt ones, within the file set when one is chosen.
  function onlyTestPaths(session, fileSet, exempt) {
    const wanted = new Set([...session.tests, ...exempt]);
    return (fileSet?.paths ?? [...wanted]).filter((path) => wanted.has(path));
  }

  // Changes the mode, saves it and builds the chunk callouts again, whose places depend on which hunks it keeps in view.
  async function setTestsMode(session, mode) {
    if (current !== session || !live() || !TESTS_MODES.includes(mode)) return;
    session.testsMode = mode;
    saveTestsMode(mode);
    session.chunkCallouts = await chunkCalloutsFor(session);
    return change(session, () => {});
  }

  // Each selection takes the next number, so that a selection a later one has overtaken stops before it jumps: clicking
  // Previous or Next quickly ends at the last stop clicked.
  function startSelection(session) {
    session.selection += 1;
    return session.selection;
  }

  // A selection in a file the chip hides shows every file again, so the target can be seen.
  function showFileOf(session, path) {
    const fileSet = tree.fileSetOf(session.review, session.fileSet);
    if (fileSet && !fileSet.paths.includes(path)) session.fileSet = "all";
  }

  // Makes the stop's file the active one, gives the stop's box the diagram's halo and jumps to the stop's line, or to its
  // file's header when the stop has no line. A stop on no box selects no box. `scroll: false` leaves the diff where it
  // is, so only the box, the list and the highlight follow. The diagram zooms to the stop's box, except with `zoom: false`,
  // which a click on the box itself passes so that it only pans; any other option, e.g. `{ pulse: false }`, passes on to the
  // jump.
  async function selectStop(session, stop, { scroll = true, zoom = true, ...jump } = {}) {
    const mine = startSelection(session);
    await change(session, () => {
      showFileOf(session, stop.path);
      leaveLine();
      deactivate(session);
      session.mode = "review";
      session.selectedStop = stop.i;
      session.selectedNode = stop.node ?? null;
      session.activeBox = activation(stop.path);
    });
    if (current !== session || !live() || session.selection !== mine) return;
    if (stop.node) diagram.centerOn([stop.node], { zoom });
    tree.revealStop(stop.i);
    if (scroll) await jumpToStop(session, stop, Object.keys(jump).length ? jump : undefined);
  }

  // Opens a chunk: the tab shows chunks, no stop or box is selected, and the page narrows to the chunk's hunks. The view
  // lands on the chunk's first line, where its callout is. `jump` options pass on to that jump; the callout's buttons
  // pass `{ pulse: false }`, as a stop's do.
  async function selectChunk(session, i, jump) {
    const chunk = session.chunks.find((candidate) => candidate.i === i);
    if (!chunk) return;
    const mine = startSelection(session);
    await change(session, () => {
      leaveLine();
      deactivate(session);
      session.mode = "chunks";
      session.selectedChunk = chunk.i;
      session.selectedStop = null;
      session.selectedNode = null;
      session.fileSet = "all";
    });
    if (current !== session || !live() || session.selection !== mine) return;
    tree.revealChunk(chunk.i);
    const target = chunkTarget(session, chunk);
    if (target) await page.jumpToLine(target.path, target.side, target.line, jump);
  }

  // Lands on a file's first hunk of a chunk. A chunk that is not the selected one is opened first, which narrows the page;
  // the selected chunk's filter and the tab stay as they are.
  async function jumpInChunk(session, i, path) {
    if (session.selectedChunk !== i) await selectChunk(session, i);
    if (current !== session || !live() || session.selectedChunk !== i) return;
    const hunk = session.chunks.find((chunk) => chunk.i === i)?.hunks.find((candidate) => candidate.path === path);
    if (!hunk) return;
    const target = hunkTarget(hunk);
    await page.jumpToLine(target.path, target.side, target.line);
  }

  // Clears the selection: no box or stop selected and no line or box marked. The pane's mode stays as it is.
  function resetReview(session) {
    return change(
      session,
      () => {
        leaveLine();
        deactivate(session);
        session.selectedNode = null;
        session.selectedStop = null;
      },
    );
  }

  // A box goes to the first stop on it; a box with no stop but with files is marked and scrolled to its first file's
  // header instead. A context box, which covers no file, and an id the review does not list do nothing. Selecting the
  // same box again jumps again.
  async function selectNode(session, nodeId) {
    const box = session.review.nodes[nodeId];
    if (!box) return;
    const stop = session.stops.find((candidate) => candidate.i === box.stops[0]);
    if (stop) {
      await selectStop(session, stop, { zoom: false });
      return;
    }
    const path = box.files[0];
    if (!path) return;
    await selectFile(session, path, nodeId);
  }

  // Marks a file active with no stop selected, and lands its header below the sticky chrome. `nodeId` is the box the file
  // is selected through, if any.
  async function selectFile(session, path, nodeId = null) {
    const mine = startSelection(session);
    await change(session, () => {
      showFileOf(session, path);
      leaveLine();
      deactivate(session);
      session.mode = "review";
      session.selectedStop = null;
      session.selectedNode = nodeId;
      session.activeBox = activation(path);
    });
    if (current !== session || !live() || session.selection !== mine) return;
    if (nodeId) diagram.centerOn([nodeId]);
    await landOnFile(session, path);
  }

  function change(session, update) {
    if (current !== session || !live()) return Promise.resolve();
    update();
    return refresh();
  }

  function handlersFor(session) {
    return {
      onMode: (mode) =>
        change(
          session,
          () => {
            leaveLine();
            deactivate(session);
            session.mode = mode;
          },
        ),
      onSelectStop: (i) => selectStop(session, session.stops.find((stop) => stop.i === i)),
      onSelectChunk: (i) => selectChunk(session, i),
      onSelectFileInChunk: (i, path) => jumpInChunk(session, i, path),
      onJudged: (i, on) => setJudged(session, i, on),
      onFileSet: (id) => change(session, () => (session.fileSet = id)),
      onTestsMode: (mode) => setTestsMode(session, mode),
    };
  }

  function owned(node) {
    return tree.owns(node) || diagram.owns(node) || page.ownsLine(node);
  }

  // A link to a stop, such as the PR brief card's, carries the anchor of that line or file in the URL fragment. Opening
  // the files page on it goes to that stop. Any other fragment is left to the page.
  async function stopLinkedBy(session, wanted) {
    for (const stop of session.stops) {
      if ((await stopAnchor(stop)) === wanted) return stop;
    }
    return null;
  }

  // What the page shows on load: nothing is selected, and the diff stays where GitHub put it. A URL fragment that names
  // a stop's diff line opens that stop, as a click on it would.
  async function selectLinkedStop(session) {
    if (!session?.review || !live()) return;
    const wanted = location.hash.slice(1);
    const linked = wanted.startsWith("diff-") ? await stopLinkedBy(session, wanted) : null;
    if (current !== session || !live()) return;
    if (linked) selectStop(session, linked);
  }

  // A PR with no run: the list's place holds one line that generates the brief, then follows the run. When it is done
  // the page's review is loaded again and the full list takes the line's place.
  // `idleKind` is "old" when the PR has a run written by an older version, which the line asks to re-run.
  async function offerGenerate(pr, key, token, idleKind = "none") {
    const target = runTarget(pr);
    const status = await source.runStatus(target);
    if (!live() || token !== loadToken) return;
    if (!runControl.mayGenerate(status)) {
      current = null;
      return;
    }
    const session = { key, pr, startedAt: Date.now() };
    const setView = (view) => {
      if (current !== session || !live()) return;
      session.line.view = view;
      refresh();
    };
    session.line = {
      view: { kind: idleKind },
      controller: runControl.create({
        source,
        run: target,
        on: {
          running: (view) => setView({ kind: "running", ...view }),
          error: (view) => setView({ kind: "error", ...view }),
          idle: () => setView({ kind: idleKind }),
          done: () => retry(session),
        },
      }),
    };
    current = session;
    stopObserving = page.onChange(onMutations);
    refresh();
    if (status.ok && status.state === "running") session.line.controller.adopt(status);
  }

  // Fetches the review again and mounts the full list when the server is back; otherwise the note returns.
  function retry(session) {
    if (current !== session || !live()) return;
    teardown();
    start();
  }

  function causedByTree(record) {
    const added = [...record.addedNodes];
    return owned(record.target) || (added.length > 0 && record.removedNodes.length === 0 && added.every(owned));
  }

  function onMutations(records) {
    if (!live()) return;
    if (!records.every(causedByTree)) schedule(SETTLE_MS);
  }

  function teardown() {
    loadToken += 1;
    clearTimeout(timer);
    timer = null;
    stopObserving?.();
    stopObserving = null;
    page.cancelJump();
    page.clearLineTarget();
    page.filterFiles(null);
    page.filterHunks(null);
    page.excludeFiles(null);
    focus.clearBox();
    tree.remove();
    diagram.remove();
    current?.line?.controller.stop();
    current = null;
  }

  // After a reload the old copy of this script stays in the open tab with no way to reach the
  // extension, so it removes everything it added and stops listening.
  function shutdown() {
    shutDown = true;
    unmountBrief();
    teardown();
    stopNavigating?.();
    stopNavigating = null;
  }

  function live() {
    if (shutDown) return false;
    if (alive()) return true;
    shutdown();
    return false;
  }

  async function start() {
    if (!live()) return;
    const pr = page.prFromUrl(location);
    if (pr?.view === "conversation") {
      if (current || stopObserving) teardown();
      await mountBrief(pr);
      return;
    }
    unmountBrief();
    if (!pr) {
      if (current || stopObserving) teardown();
      return;
    }
    const key = sessionKey(pr);
    if (current?.key === key) return;
    teardown();
    current = { key };

    const token = loadToken;
    const review = await source.loadReview(pr.owner, pr.repo, pr.pr, page.runKey(pr));
    if (!live()) return;
    if (token === loadToken && review?.error === "server") {
      current = { key, pr, offline: review.baseUrl, startedAt: Date.now() };
      stopObserving = page.onChange(onMutations);
      refresh();
      return;
    }
    if (token === loadToken && (!review || review.error === "old")) {
      await offerGenerate(pr, key, token, review ? "old" : "none");
      return;
    }
    if (token !== loadToken || !review) return;
    current = {
      key,
      pr,
      review,
      mode: "github",
      selectedNode: null,
      startedAt: Date.now(),
      stops: tree.stopsOf(review),
      selectedStop: null,
      chunks: tree.chunksOf(review),
      selectedChunk: null,
      judged: new Set(),
      fileSet: "all",
      tests: tree.testsOf(review),
      testsMode: loadTestsMode(),
      selection: 0,
      callouts: [],
      chunkCallouts: [],
    };
    const session = current;
    session.judged = loadJudged(session);
    session.callouts = await calloutsFor(session);
    session.chunkCallouts = await chunkCalloutsFor(session);
    if (current !== session || !live()) return;
    stopObserving = page.onChange(onMutations);
    refresh();
    selectLinkedStop(current);
  }

  stopNavigating = page.onNavigate(start);
  start();
})();
