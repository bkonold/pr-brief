(() => {
  const { page, source, runControl, boxes, focus, tree, diagram, brief, alive } = globalThis.prFocus;
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
    const result = await focus.apply(chunk, { scroll });
    if (result.stale || current !== session) return;
    renderDiagram(session, chunk);
    focus.markBox(session.activeBox?.paths ?? []);
    page.restoreLineTarget();

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
    diagram.render(session.review.diagramSvg, { onNode: (nodeId) => (session.review.nodes ? selectBox(session, nodeId) : selectNode(session, nodeId)) });
    diagram.emphasize(chunk ? (chunk.nodes ?? null) : null);
    diagram.setActive(session.activeBox?.id ?? null);
  }

  // Ends any line jump in progress, which would otherwise scroll to its line when the row finally loads, and
  // clears the outlined line. Every selection started from the list or the diagram calls it.
  function leaveLine() {
    page.cancelJump();
    page.clearLineTarget();
  }

  // The active state of a single file: no box id, number or title, so no label is shown for it.
  function fileActivation(path) {
    return { id: null, number: null, paths: [path], title: "" };
  }

  // Lands the file's header below the sticky chrome and then, together, flashes its list row and its header.
  async function landOnFile(session, path) {
    if (current !== session) return;
    await focus.scrollTo(path);
    if (current !== session || !live() || session.activeBox?.paths[0] !== path) return;
    tree.flashRows();
    focus.announceBox([path], null);
  }

  // Forgets the active box and everything shown for it: the diagram tint, the diff header bars and the label.
  function deactivate(session) {
    session.activeBox = null;
    focus.clearBox();
    diagram.setActive(null);
  }

  // With the box-to-file mapping, a box selects the chunk that holds its first file, makes the box the active
  // one and scrolls to that file's header. Once the scroll has landed, the box, its files' headers and its
  // list rows pulse once and the first header is labelled. A box that covers no file does nothing.
  async function selectBox(session, nodeId) {
    const target = boxes.targetOfNode(session.review, nodeId);
    if (!target) return;
    const box = session.review.nodes.find((node) => node.id === nodeId);
    await change(
      session,
      () => {
        session.mode = "review";
        if (session.selectedN !== target.n) session.expanded = new Set([target.n]);
        session.expanded.add(target.n);
        session.selectedN = target.n;
        leaveLine();
        deactivate(session);
        session.activeBox = { id: nodeId, number: box.number, paths: box.files, title: diagram.titleOf(nodeId) };
      },
      { scroll: false },
    );
    if (current !== session) return;
    tree.revealGroup(target.n);
    await focus.scrollTo(target.path);
    if (current !== session || !live() || session.activeBox?.id !== nodeId) return;
    const { number, title, paths } = session.activeBox;
    diagram.pulse(nodeId);
    focus.announceBox(paths, number == null ? title : `Box ${number} · ${title}`);
  }

  // Without it, a box selects the first chunk, in list order, that touches it; the diff doesn't scroll.
  function selectNode(session, nodeId) {
    const owner = tree.orderChunks(session.review.chunks, session.order).find((chunk) => chunk.nodes?.includes(nodeId));
    if (!owner || (session.mode === "review" && session.selectedN === owner.n)) return;
    change(
      session,
      () => {
        leaveLine();
        session.mode = "review";
        session.selectedN = owner.n;
        session.expanded = new Set([owner.n]);
      },
      { scroll: false },
    ).then(() => {
      if (current === session && live()) tree.revealGroup(owner.n);
    });
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
      // Selecting a chunk lands its first listed file and makes it the active file, as a click on its row would.
      onSelectChunk: async (n) => {
        const unselect = session.selectedN === n;
        const first = unselect ? undefined : session.review.chunks.find((chunk) => chunk.n === n)?.files[0]?.path;
        await change(
          session,
          () => {
            leaveLine();
            deactivate(session);
            session.selectedN = unselect ? null : n;
            if (unselect) session.expanded.add(n);
            else session.expanded = new Set([n]);
            if (first) session.activeBox = fileActivation(first);
          },
          { scroll: false },
        );
        if (first) await landOnFile(session, first);
      },
      // The start file's diff is hidden while another chunk is focused, so that chunk is focused first.
      onJumpToStart: async (n) => {
        const chunk = session.review.chunks.find((candidate) => candidate.n === n);
        const start = chunk?.start;
        if (!start) return;
        if (session.selectedN !== null && session.selectedN !== n) {
          await change(
            session,
            () => {
              deactivate(session);
              session.selectedN = n;
              session.expanded = new Set([n]);
            },
            { scroll: false },
          );
        }
        if (current === session) await page.jumpToLine(start.path, start.side, start.line, (dismiss) => tree.startCallout(chunk, dismiss));
      },
      // A file row selects its chunk without the chunk's own scroll, lands that file's header below the sticky chrome
      // and makes the file active: its row and header get the box bar and the header flashes, without a label.
      onSelectFile: async (n, path) => {
        await change(
          session,
          () => {
            leaveLine();
            deactivate(session);
            session.selectedN = n;
            if (n !== null) session.expanded.add(n);
            session.activeBox = fileActivation(path);
          },
          { scroll: false },
        );
        await landOnFile(session, path);
      },
      onOrder: (order) => change(session, () => (session.order = order), { scroll: false }),
      onExpandAll: () => change(session, () => (session.expanded = new Set(allKeys())), { scroll: false }),
      onCollapseAll: () => change(session, () => (session.expanded = new Set()), { scroll: false }),
    };
  }

  function owned(node) {
    return tree.owns(node) || diagram.owns(node) || focus.owns(node) || page.ownsLine(node);
  }

  // A link to a chunk's start line, such as the PR brief card's, carries that line's anchor in the URL fragment.
  // Opening the files page on it does what the ↳ button does. Any other fragment is left to the page.
  async function jumpToLinkedStart(session) {
    const wanted = location.hash.slice(1);
    if (!wanted.startsWith("diff-") || !session?.review || !live()) return;
    for (const chunk of session.review.chunks) {
      const { start } = chunk;
      if (start && (await page.lineAnchor(start.path, start.side, start.line)) === wanted) {
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
    };
    stopObserving = page.onChange(onMutations);
    refresh({ scroll: selectedN !== null }).then(() => jumpToLinkedStart(current));
  }

  stopNavigating = page.onNavigate(start);
  start();
})();
