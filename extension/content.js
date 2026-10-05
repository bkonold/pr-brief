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

  // Whether a Generate button may be offered: false only when the server says it will not start runs for this
  // repository. A server that cannot be asked (down, wrong token) still gets the button, so the failure can be shown.
  function mayGenerate(status) {
    return status.ok ? status.allowed !== false : true;
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
    const canGenerate = mayGenerate(status);
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
          const fresh = await source.loadBrief(pr.owner, pr.repo, pr.pr, target.key);
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

  function storageKey(pr) {
    return `prFocus:${pr.owner}/${pr.repo}#${pr.pr}`;
  }

  function readSaved(pr) {
    try {
      return JSON.parse(sessionStorage.getItem(storageKey(pr)) ?? "{}") ?? {};
    } catch {
      return {};
    }
  }

  function save(session) {
    try {
      sessionStorage.setItem(storageKey(session.pr), JSON.stringify({ mode: session.mode, selectedN: session.selectedN, variant: session.review?.variant }));
    } catch {
      // The choice just isn't remembered.
    }
  }

  // MutationObserver bursts coalesce into one refresh through the single pending timer.
  function schedule(delay) {
    clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      if (!live()) return;
      start();
      refresh({ scroll: false });
    }, delay);
  }

  function selectedChunk(session) {
    return session.mode === "review" ? (session.review.chunks.find((c) => c.n === session.selectedN) ?? null) : null;
  }

  // The paths outside the selected chunk whose diffs are shown with it because a line in its row was clicked.
  function revealedPaths(session) {
    return session.reveal?.n === session.selectedN ? [...session.reveal.paths] : [];
  }

  function extraFiles(session) {
    const listed = new Set(session.review.chunks.flatMap((chunk) => chunk.files.map((file) => file.path)));
    return [...page.fileBlocks().keys()].filter((path) => !listed.has(path)).map((path) => ({ path }));
  }

  async function refresh({ scroll }) {
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
    const chunk = selectedChunk(session);
    const result = await focus.apply(chunk, { scroll, extra: revealedPaths(session) });
    if (result.stale || current !== session) return;
    renderDiagram(session, chunk);
    focus.markBox(session.activeBox?.paths ?? []);
    page.restoreLineTarget();
    page.showCallouts(session.mode === "review" ? session.callouts : []);

    const waited = Date.now() - session.startedAt;
    const noBlocks = page.fileBlocks().size === 0;
    if (noBlocks && waited < LOAD_GRACE_MS) schedule(LOAD_GRACE_MS - waited + SETTLE_MS);
    tree.render(
      session.review,
      {
        mode: session.mode,
        order: session.order,
        selectedN: session.selectedN,
        expanded: session.expanded,
        extras: extraFiles(session),
        activeFiles: new Set(session.activeBox?.paths ?? []),
        pageSha: page.headSha(),
        note: noBlocks && waited >= LOAD_GRACE_MS ? NO_BLOCKS_NOTE : null,
      },
      handlersFor(session),
    );
  }

  // Without a selected chunk, whether in "GitHub tree" mode or with nothing chosen, every node is shown.
  function renderDiagram(session, chunk) {
    if (!session.review.diagramSvg) {
      diagram.remove();
      return;
    }
    diagram.render(session.review.diagramSvg, { onNode: (nodeId) => selectNode(session, nodeId), onReset: () => resetReview(session) });
    diagram.emphasize(chunk ? (chunk.nodes ?? null) : null);
    diagram.setActive(session.activeBox?.id ?? null);
  }

  // Ends any line jump in progress, which would otherwise scroll to its line when the row finally loads, and
  // clears the outlined line. Every selection started from the list or the diagram calls it.
  function leaveLine() {
    page.cancelJump();
    page.clearLineTarget();
  }

  // The active state: the file whose row and header are marked, and the diagram box clicked to get there, if any.
  function activation(path, boxId = null) {
    return { id: boxId, paths: [path] };
  }

  // Lands the file's header below the sticky chrome and then, together, flashes its list row and its header.
  async function landOnFile(session, path) {
    if (current !== session) return;
    await focus.scrollTo(path);
    if (current !== session || !live() || session.activeBox?.paths[0] !== path) return;
    tree.flashRows();
    focus.announceBox([path]);
  }

  // Forgets the active selection and everything shown for it: the diagram tint and the diff header bars.
  function deactivate(session) {
    session.activeBox = null;
    focus.clearBox();
    diagram.setActive(null);
  }

  // A start with no line names only a file.
  function isFileStart(start) {
    return start.line == null;
  }

  // The anchor a start's callout and link use: the line's, else the file's diff id.
  function startAnchor(start) {
    return isFileStart(start) ? page.fileAnchor(start.path) : page.lineAnchor(start.path, start.side, start.line);
  }

  // Runs the jump to `chunk`'s start: for a line, its diff scrolls into view and the line is highlighted with its
  // callout; for a file, the file's diff scrolls to its callout above the header.
  async function jumpToStart(session, chunk, options) {
    if (current !== session || !live()) return;
    const { path, side, line } = chunk.start;
    if (isFileStart(chunk.start)) await page.jumpToFile(path, options);
    else await page.jumpToLine(path, side, line, options);
  }

  // The callouts of the review's starts, one per chunk that has one: each is built when its place is found, and its
  // buttons select a chunk as a click on that chunk in the list would, without the pulse: the reader is already
  // following the callouts, so nothing needs finding.
  async function calloutsFor(session) {
    const { chunks } = session.review;
    const anchors = await Promise.all(chunks.map((chunk) => (chunk.start ? startAnchor(chunk.start) : null)));
    return chunks.flatMap((chunk, index) =>
      anchors[index]
        ? [
            {
              key: chunk.n,
              anchor: anchors[index],
              ...(isFileStart(chunk.start) ? { file: true } : {}),
              render: () => tree.startCallout(chunk, chunks, (target) => selectChunk(session, target, null, { pulse: false }), diagram.titleOf),
            },
          ]
        : [],
    );
  }

  // Focuses the diffs on the chunk, opens it in the list, makes its start file (else its first) the active one and
  // jumps to its start line or start file; a chunk with no start lands on its first file's header instead. `boxId` is the diagram
  // box the selection came from, which pulses once the jump has landed. Selecting the open chunk again jumps again.
  // `jump` passes on to the line jump, e.g. `{ pulse: false }`. Every selection moves the diagram to follow the chunk's boxes.
  async function selectChunk(session, chunk, boxId = null, jump = undefined) {
    const path = chunk.start?.path ?? chunk.files[0]?.path;
    await change(
      session,
      () => {
        leaveLine();
        deactivate(session);
        session.mode = "review";
        session.selectedN = chunk.n;
        session.expanded = new Set([chunk.n]);
        if (path) session.activeBox = activation(path, boxId);
      },
      { scroll: false },
    );
    if (current !== session || !live()) return;
    centerDiagram(chunk);
    tree.revealGroup(chunk.n);
    if (chunk.start) await jumpToStart(session, chunk, jump);
    else if (path) await landOnFile(session, path);
    if (boxId && current === session && live() && session.activeBox?.id === boxId) diagram.pulse(boxId);
  }

  // Puts the review back as it was when it loaded: no chunk selected, every row collapsed, every file shown, and no
  // line or box marked. The saved selection is cleared with it.
  function resetReview(session) {
    return change(
      session,
      () => {
        leaveLine();
        deactivate(session);
        session.mode = "review";
        session.selectedN = null;
        session.expanded = new Set();
        session.reveal = null;
      },
      { scroll: false },
    );
  }

  // Moves the diagram to follow the boxes of the chunk that was just focused (see createCanvas in diagram.js); a chunk
  // with no boxes leaves it be.
  function centerDiagram(chunk) {
    diagram.centerOn(chunk.nodes ?? []);
  }

  // A box selects the first chunk, in list order, that lists it, as a click on that chunk would. A box no chunk lists
  // does nothing.
  function selectNode(session, nodeId) {
    const chunk = tree.chunkOfNode(session.review.chunks, session.order, nodeId);
    if (chunk) selectChunk(session, chunk, nodeId);
  }

  function change(session, update, options) {
    if (current !== session || !live()) return Promise.resolve();
    update();
    save(session);
    return refresh(options);
  }

  function handlersFor(session) {
    const allKeys = () => [...session.review.chunks.map((chunk) => chunk.n), tree.EXTRA_KEY];
    return {
      onMode: (mode) =>
        change(
          session,
          () => {
            leaveLine();
            deactivate(session);
            session.mode = mode;
          },
          { scroll: false },
        ),
      onToggleGroup: (key) =>
        change(session, () => (session.expanded.has(key) ? session.expanded.delete(key) : session.expanded.add(key)), { scroll: false }),
      onSelectChunk: (n) => selectChunk(session, session.review.chunks.find((chunk) => chunk.n === n)),
      // The start file's diff is hidden while another chunk is focused, so that chunk is focused first. The chunk is
      // also opened in the list, where its start button is.
      onJumpToStart: async (n) => {
        const chunk = session.review.chunks.find((candidate) => candidate.n === n);
        if (!chunk?.start) return;
        const refocus = session.selectedN !== null && session.selectedN !== n;
        if (refocus || !session.expanded.has(n)) {
          await change(
            session,
            () => {
              if (refocus) {
                deactivate(session);
                session.selectedN = n;
              }
              session.expanded = new Set([n]);
            },
            { scroll: false },
          );
        }
        if (current !== session || !live()) return;
        centerDiagram(chunk);
        await jumpToStart(session, chunk);
      },
      // A contract or data line in a chunk's row selects that chunk and jumps to the line's place in the diff, without the
      // pulse. The line may be in the spec, which belongs to another chunk, so its file is shown with this one.
      onJumpToLine: async (n, line) => {
        const chunk = session.review.chunks.find((candidate) => candidate.n === n);
        if (!chunk) return;
        const outside = !chunk.files.some((file) => file.path === line.path);
        await change(
          session,
          () => {
            leaveLine();
            if (session.selectedN === n) {
              session.expanded.add(n);
            } else {
              deactivate(session);
              session.mode = "review";
              session.selectedN = n;
              session.expanded = new Set([n]);
            }
            if (outside) {
              if (session.reveal?.n !== n) session.reveal = { n, paths: new Set() };
              session.reveal.paths.add(line.path);
            }
          },
          { scroll: false },
        );
        if (current !== session || !live()) return;
        centerDiagram(chunk);
        if (line.line == null) await page.jumpToFile(line.path, { pulse: false });
        else await page.jumpToLine(line.path, line.side, line.line, { pulse: false });
      },
      // A file row selects its chunk without the chunk's own scroll, lands that file's header below the sticky chrome
      // and makes the file active: its row and header get the box bar and the header flashes.
      onSelectFile: async (n, path) => {
        await change(
          session,
          () => {
            leaveLine();
            deactivate(session);
            session.selectedN = n;
            if (n !== null) session.expanded.add(n);
            session.activeBox = activation(path);
          },
          { scroll: false },
        );
        if (current !== session || !live()) return;
        const chunk = session.review.chunks.find((candidate) => candidate.n === n);
        if (chunk) centerDiagram(chunk);
        await landOnFile(session, path);
      },
      onOrder: (order) => change(session, () => (session.order = order), { scroll: false }),
      onExpandAll: () => change(session, () => (session.expanded = new Set(allKeys())), { scroll: false }),
      onCollapseAll: () => change(session, () => (session.expanded = new Set()), { scroll: false }),
    };
  }

  function owned(node) {
    return tree.owns(node) || diagram.owns(node) || page.ownsLine(node);
  }

  // A link to a chunk's start, such as the PR brief card's, carries the anchor of that line or file in the URL fragment.
  // Opening the files page on it does what the chunk's "Start here" button does. Any other fragment is left to the page.
  async function jumpToLinkedStart(session) {
    const wanted = location.hash.slice(1);
    if (!wanted.startsWith("diff-") || !session?.review || !live()) return;
    for (const chunk of session.review.chunks) {
      const { start } = chunk;
      if (start && (await startAnchor(start)) === wanted) {
        if (current === session && live()) handlersFor(session).onJumpToStart(chunk.n);
        return;
      }
    }
  }

  // A PR with no run: the list's place holds one line that generates the brief, then follows the run. When it is done
  // the page's review is loaded again and the full list takes the line's place.
  async function offerGenerate(pr, key, token) {
    const target = runTarget(pr);
    const status = await source.runStatus(target);
    if (!live() || token !== loadToken) return;
    if (!mayGenerate(status)) {
      current = null;
      return;
    }
    const session = { key, pr, startedAt: Date.now() };
    const setView = (view) => {
      if (current !== session || !live()) return;
      session.line.view = view;
      refresh({ scroll: false });
    };
    session.line = {
      view: { kind: "none" },
      controller: runControl.create({
        source,
        run: target,
        on: {
          running: (view) => setView({ kind: "running", ...view }),
          error: (view) => setView({ kind: "error", ...view }),
          idle: () => setView({ kind: "none" }),
          done: () => retry(session),
        },
      }),
    };
    current = session;
    stopObserving = page.onChange(onMutations);
    refresh({ scroll: false });
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
    focus.apply(null);
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
    const key = storageKey(pr);
    if (current?.key === key) return;
    teardown();
    current = { key };

    const token = loadToken;
    const review = await source.loadReview(pr.owner, pr.repo, pr.pr, undefined, page.runKey(pr));
    if (!live()) return;
    if (token === loadToken && review?.error === "server") {
      current = { key, pr, offline: review.baseUrl, startedAt: Date.now() };
      stopObserving = page.onChange(onMutations);
      refresh({ scroll: false });
      return;
    }
    if (token === loadToken && !review) {
      await offerGenerate(pr, key, token);
      return;
    }
    if (token !== loadToken || !review) return;
    const saved = readSaved(pr);
    const selectedN = saved.variant === review.variant && review.chunks.some((c) => c.n === saved.selectedN) ? saved.selectedN : null;
    current = {
      key,
      pr,
      review,
      mode: saved.mode === "github" ? "github" : "review",
      selectedN,
      order: tree.defaultOrder(review),
      expanded: new Set([selectedN ?? tree.orderChunks(review.chunks, tree.defaultOrder(review))[0]?.n]),
      startedAt: Date.now(),
      callouts: [],
    };
    const session = current;
    session.callouts = await calloutsFor(session);
    if (current !== session || !live()) return;
    stopObserving = page.onChange(onMutations);
    refresh({ scroll: selectedN !== null }).then(() => jumpToLinkedStart(current));
  }

  stopNavigating = page.onNavigate(start);
  start();
})();
