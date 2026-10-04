(() => {
  const { githubPage, source, variants, boxes, focus, tree, diagram, alive } = globalThis.prFocus;

  const SETTLE_MS = 150;
  const LOAD_GRACE_MS = 5000;
  const NO_BLOCKS_NOTE = "Couldn't find GitHub's diff blocks; selectors may need updating";

  let current = null;
  let loadToken = 0;
  let timer = null;
  let stopObserving = null;
  let stopNavigating = null;
  let shutDown = false;

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
    return [...githubPage.fileBlocks().keys()].filter((path) => !listed.has(path)).map((path) => ({ path }));
  }

  async function refresh({ scroll }) {
    const session = current;
    if (session?.offline && live()) {
      tree.renderServerNote(session.offline, { onRetry: () => retry(session) });
      return;
    }
    if (!session?.review || !live()) return;
    const chunk = selectedChunk(session);
    const result = await focus.apply(chunk, { scroll });
    if (result.stale || current !== session) return;
    renderDiagram(session, chunk);
    focus.markBox(session.activeBox?.paths ?? []);
    githubPage.restoreLineTarget();

    const waited = Date.now() - session.startedAt;
    const noBlocks = githubPage.fileBlocks().size === 0;
    if (noBlocks && waited < LOAD_GRACE_MS) schedule(LOAD_GRACE_MS - waited + SETTLE_MS);
    tree.render(
      session.review,
      {
        mode: session.mode,
        selectedN: session.selectedN,
        expanded: session.expanded,
        extras: extraFiles(session),
        badges: boxes.fileBadges(session.review),
        activeFiles: new Set(session.activeBox?.paths ?? []),
        pageSha: githubPage.headSha(),
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
    githubPage.cancelJump();
    githubPage.clearLineTarget();
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
    tree.flashBadges();
    focus.announceBox(paths, number == null ? title : `Box ${number} · ${title}`);
  }

  // Without it, a box selects the first chunk, in list order, that touches it; the diff doesn't scroll.
  function selectNode(session, nodeId) {
    const owner = tree.orderChunks(session.review.chunks).find((chunk) => chunk.nodes?.includes(nodeId));
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
        if (current === session) await githubPage.jumpToLine(start.path, start.side, start.line, (dismiss) => tree.startCallout(chunk, dismiss));
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
      onSwitchVariant: (variant) => switchVariant(session, variant),
      onExpandAll: () => change(session, () => (session.expanded = new Set(allKeys())), { scroll: false }),
      onCollapseAll: () => change(session, () => (session.expanded = new Set()), { scroll: false }),
    };
  }

  function owned(node) {
    return tree.owns(node) || diagram.owns(node) || focus.owns(node) || githubPage.ownsLine(node);
  }

  // Loads another variant's review in place. The selected chunk stays selected when the new variant has a chunk
  // of the same name; otherwise the selection and the focus are cleared.
  async function switchVariant(session, variant) {
    if (current !== session || !live() || variant === session.review.variant) return;
    session.switching = (session.switching ?? 0) + 1;
    const mine = session.switching;
    await source.saveVariant(variant);
    const review = await source.loadReview(session.pr.owner, session.pr.repo, session.pr.pr, variant);
    if (current !== session || !live() || mine !== session.switching) return;
    if (review && !review.error) {
      leaveLine();
      deactivate(session);
      const kept = variants.keepSelection(session.review, session.selectedN, review);
      session.selectedN = kept;
      session.expanded = new Set([kept ?? tree.orderChunks(review.chunks)[0]?.n]);
      session.review = review;
      save(session);
    }
    refresh({ scroll: false });
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
    githubPage.cancelJump();
    githubPage.clearLineTarget();
    focus.apply(null);
    focus.clearBox();
    tree.remove();
    diagram.remove();
    current = null;
  }

  // After a reload the old copy of this script stays in the open tab with no way to reach the
  // extension, so it removes everything it added and stops listening.
  function shutdown() {
    shutDown = true;
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
    const pr = githubPage.prFromUrl(location);
    if (!pr) {
      if (current || stopObserving) teardown();
      return;
    }
    const key = storageKey(pr);
    if (current?.key === key) return;
    teardown();
    current = { key };

    const token = loadToken;
    const review = await source.loadReview(pr.owner, pr.repo, pr.pr);
    if (!live()) return;
    if (token === loadToken && review?.error === "server") {
      current = { key, pr, offline: review.baseUrl, startedAt: Date.now() };
      stopObserving = githubPage.onChange(onMutations);
      refresh({ scroll: false });
      return;
    }
    if (token !== loadToken || !review) {
      if (token === loadToken) current = null;
      return;
    }
    const saved = readSaved(pr);
    const selectedN = saved.variant === review.variant && review.chunks.some((c) => c.n === saved.selectedN) ? saved.selectedN : null;
    current = {
      key,
      pr,
      review,
      mode: saved.mode === "github" ? "github" : "review",
      selectedN,
      expanded: new Set([selectedN ?? tree.orderChunks(review.chunks)[0]?.n]),
      startedAt: Date.now(),
    };
    stopObserving = githubPage.onChange(onMutations);
    refresh({ scroll: selectedN !== null });
  }

  stopNavigating = githubPage.onNavigate(start);
  start();
})();
