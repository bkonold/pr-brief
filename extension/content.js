(() => {
  const { page, source, runControl, focus, tree, diagram, brief, alive } = globalThis.prFocus;
  if (!page) return;

  const SETTLE_MS = 150;
  const LOAD_GRACE_MS = 5000;
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
  // on the server, left by an earlier visit, is followed from where it is.
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
    if (!run && !canGenerate) return;

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
    page.showCallouts(session.mode === "review" ? session.callouts : []);
    const fileSet = tree.fileSetOf(session.review, session.fileSet);
    page.filterTree(fileSet?.paths ?? null);

    const waited = Date.now() - session.startedAt;
    const noBlocks = page.fileBlocks().size === 0;
    if (noBlocks && waited < LOAD_GRACE_MS) schedule(LOAD_GRACE_MS - waited + SETTLE_MS);
    tree.render(
      session.review,
      {
        mode: session.mode,
        stops: session.stops,
        selectedStop: session.selectedStop,
        pageSha: page.headSha(),
        chips: tree.fileChips(session.review, page.changedFileCount()),
        fileSet,
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
              render: () => tree.stopCallout(stop, stops, (target) => selectStop(session, target, { pulse: false }), review.nodes),
            },
          ]
        : [],
    );
  }

  // Each selection takes the next number, so that a selection a later one has overtaken stops before it jumps: clicking
  // Previous or Next quickly ends at the last stop clicked.
  function startSelection(session) {
    session.selection += 1;
    return session.selection;
  }

  // Makes the stop's file the active one, gives the stop's box the diagram's halo and jumps to the stop's line, or to its
  // file's header when the stop has no line. A stop on no box selects no box. `scroll: false` leaves the diff where it
  // is, so only the box, the list and the highlight follow. The diagram zooms to the stop's box, except with `zoom: false`,
  // which a click on the box itself passes so that it only pans; any other option, e.g. `{ pulse: false }`, passes on to the
  // jump.
  async function selectStop(session, stop, { scroll = true, zoom = true, ...jump } = {}) {
    const mine = startSelection(session);
    await change(session, () => {
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
      onSelectFile: (path) => selectFile(session, path),
      onFileSet: (id) => change(session, () => (session.fileSet = id)),
      onJump: (loc) => jumpToStop(session, loc),
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
    page.filterTree(null);
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
      fileSet: "all",
      selection: 0,
      callouts: [],
    };
    const session = current;
    session.callouts = await calloutsFor(session);
    if (current !== session || !live()) return;
    stopObserving = page.onChange(onMutations);
    refresh();
    selectLinkedStop(current);
  }

  stopNavigating = page.onNavigate(start);
  start();
})();
