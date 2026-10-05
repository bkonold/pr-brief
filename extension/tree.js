(() => {
  const ns = (globalThis.prFocus ??= {});
  const ROOT_ID = "pr-focus-tree";
  const HOST_HIDDEN = "prf-tree-hidden";
  const EXTRA_KEY = "extra";
  const ROW_FLASH = "prf-row-flash";
  const UNCHUNKED = "Unchunked";
  const LOWEST_LEVEL = "skim";
  const SHORT_SHA = 7;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const LIST_TREE_ICON = "M2.5 3h11M5.5 8h8M5.5 13h8M3 3.5v9.5M3 8h2.5M3 13h2.5";
  const FOLDER_ICON = "M1.75 3.5h4.25l1.5 1.75h6.75v7.5h-12.5z";
  const JUMP_ICON = "M2.5 3v10M5.5 8h8M10 4.5L13.5 8 10 11.5";
  const LEVEL_ORDER = ["read carefully", "read", "skim"];

  function groupRank(chunk) {
    if (chunk.name === UNCHUNKED) return LEVEL_ORDER.length;
    const rank = LEVEL_ORDER.indexOf(chunk.review);
    return rank === -1 ? LEVEL_ORDER.indexOf("read") : rank;
  }

  function isMuted(chunk) {
    return chunk.review === LOWEST_LEVEL || chunk.name === UNCHUNKED;
  }

  // True when the run's chunks carry a `step`, which is what makes review.json's order a flow order worth offering
  // beside the risk order.
  function hasSteps(chunks) {
    return chunks.some((chunk) => chunk.step);
  }

  // The order a review is first shown in: the flow of the change when the run has steps, else by risk.
  function defaultOrder(review) {
    return hasSteps(review.chunks) ? "flow" : "risk";
  }

  // "risk" (the default): "read carefully" first, then "read", then "skim", then Unchunked; ties keep review.json's
  // order. "flow": review.json's order, Unchunked last.
  function orderChunks(chunks, order = "risk") {
    const rank = order === "flow" ? (chunk) => (chunk.name === UNCHUNKED ? 1 : 0) : groupRank;
    return chunks
      .map((chunk, index) => ({ chunk, index }))
      .sort((a, b) => rank(a.chunk) - rank(b.chunk) || a.index - b.index)
      .map(({ chunk }) => chunk);
  }

  function folderOf(path) {
    const slash = path.lastIndexOf("/");
    return slash === -1 ? "" : path.slice(0, slash);
  }

  function baseNameOf(path) {
    return path.slice(path.lastIndexOf("/") + 1);
  }

  // The basenames that more than one of `files` has, so those rows can show their folder to tell them apart.
  function ambiguousNames(files) {
    const seen = new Set();
    const repeated = new Set();
    for (const { path } of files) {
      const name = baseNameOf(path);
      if (seen.has(name)) repeated.add(name);
      seen.add(name);
    }
    return repeated;
  }

  const LEVEL_LABELS = { "read carefully": "careful" };

  // The short word a chunk row shows for its review level.
  function levelLabel(review) {
    return LEVEL_LABELS[review] ?? review;
  }

  function staleMessage(review, pageSha) {
    if (!review.head_sha || !pageSha || review.head_sha.toLowerCase() === pageSha.toLowerCase()) return null;
    return `Review was generated for ${review.head_sha.slice(0, SHORT_SHA)}; the PR has newer commits. Focus still works by path.`;
  }

  function make(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function button(className, text, onClick) {
    const element = make("button", className, text);
    element.type = "button";
    element.addEventListener("click", onClick);
    return element;
  }

  // A 16-unit icon drawn as an outline in the current text colour.
  function outlineIcon(d, size, className) {
    const svg = svgIcon(d, size, className);
    for (const [name, value] of [["fill", "none"], ["stroke", "currentColor"], ["stroke-width", "1.5"], ["stroke-linecap", "round"], ["stroke-linejoin", "round"]]) {
      svg.firstChild.setAttribute(name, value);
    }
    return svg;
  }

  function svgIcon(d, size, className) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("width", String(size));
    svg.setAttribute("height", String(size));
    svg.setAttribute("aria-hidden", "true");
    svg.classList.add(className);
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    svg.append(path);
    return svg;
  }

  // `options.start` marks the chunk's start file; `options.showFolder` adds the folder after a basename that another
  // file in the list shares.
  function fileRow(file, onClick, { active = false, start = false, showFolder = false } = {}) {
    const item = make("li", "prf-file-item");
    const row = button("prf-file", undefined, onClick);
    row.classList.toggle("prf-file-active", active);
    row.classList.toggle("prf-file-start", start);
    row.title = file.path;
    row.append(make("span", "prf-file-name", baseNameOf(file.path)));
    if (showFolder) row.append(make("span", "prf-file-dir", folderOf(file.path)));
    item.append(row);
    return item;
  }

  // The rows of a file list; `optionsFor(file)` gives each row's active and start options.
  function fileRows(files, onSelect, optionsFor = () => ({})) {
    const repeated = ambiguousNames(files);
    return files.map((file) =>
      fileRow(file, () => onSelect(file.path), { ...optionsFor(file), showFolder: repeated.has(baseNameOf(file.path)) }),
    );
  }

  function group({ key, expanded, selected, muted }, header, body) {
    const element = make("section", "prf-group");
    element.dataset.group = String(key);
    element.classList.toggle("prf-expanded", expanded);
    element.classList.toggle("prf-selected", selected);
    element.classList.toggle("prf-muted", muted);
    element.append(header);
    if (expanded) element.append(body);
    return element;
  }

  // Why to read the chunk's start line: the model's reason for that line, else the chunk's own.
  function readFirstReason(chunk) {
    return chunk.start?.why?.trim() || chunk.why || "";
  }

  // The button under an open chunk's files that jumps to the line the model says to read first.
  function startHere(chunk, handlers) {
    const element = button("prf-start-here", undefined, () => handlers.onJumpToStart(chunk.n));
    element.append(outlineIcon(JUMP_ICON, 14, "prf-start-icon"), "Start here");
    element.title = `${baseNameOf(chunk.start.path)}:${chunk.start.line}`;
    return element;
  }

  function chunkGroup(chunk, state, handlers) {
    const expanded = state.expanded.has(chunk.n);
    const main = button("prf-head-main", undefined, () => handlers.onSelectChunk(chunk.n));
    main.setAttribute("aria-pressed", String(chunk.n === state.selectedN));
    main.append(
      make("span", "prf-num", String(chunk.n)),
      make("span", "prf-name", chunk.name),
      make("span", `prf-level prf-level-${chunk.review.replace(/\s+/g, "-")}`, levelLabel(chunk.review)),
    );

    const header = make("div", "prf-head");
    header.append(main);
    const files = make("ul", "prf-files");
    files.append(
      ...fileRows(
        chunk.files,
        (path) => handlers.onSelectFile(chunk.n, path),
        (file) => ({ active: state.activeFiles?.has(file.path), start: file.path === chunk.start?.path }),
      ),
    );
    const body = make("div", "prf-body");
    body.append(files);
    if (chunk.start) body.append(startHere(chunk, handlers));
    return group({ key: chunk.n, expanded, selected: chunk.n === state.selectedN, muted: isMuted(chunk) }, header, body);
  }

  function extraGroup(extras, state, handlers) {
    const expanded = state.expanded.has(EXTRA_KEY);
    const main = button("prf-head-main", undefined, () => handlers.onToggleGroup(EXTRA_KEY));
    main.append(make("span", "prf-name", "Not in review"));
    const header = make("div", "prf-head");
    header.append(main);
    const files = make("ul", "prf-files");
    files.append(...fileRows(extras, (path) => handlers.onSelectFile(null, path)));
    return group({ key: EXTRA_KEY, expanded, selected: false, muted: true }, header, files);
  }

  function modeToggle(state, handlers) {
    const toggle = make("div", "prf-modes");
    for (const [mode, label, icon] of [["review", "By review", LIST_TREE_ICON], ["github", ns.page.treeLabel, FOLDER_ICON]]) {
      const choice = button("prf-mode", undefined, () => handlers.onMode(mode));
      choice.append(outlineIcon(icon, 14, "prf-mode-icon"), make("span", undefined, label));
      choice.setAttribute("aria-pressed", String(state.mode === mode));
      toggle.append(choice);
    }
    return toggle;
  }

  // The "Order: by flow | by risk" switch of the review list. Offered only when the run's chunks have steps.
  function orderSwitch(state, handlers) {
    const element = make("div", "prf-order");
    element.append(make("span", "prf-order-label", "Order:"));
    for (const [order, label] of [["flow", "by flow"], ["risk", "by risk"]]) {
      const choice = button("prf-order-choice", label, () => handlers.onOrder(order));
      choice.setAttribute("aria-pressed", String(state.order === order));
      element.append(choice);
    }
    return element;
  }

  function bar(review, state, handlers) {
    const element = make("div", "prf-bar");
    element.append(modeToggle(state, handlers));
    if (state.mode === "review" && hasSteps(review.chunks)) element.append(orderSwitch(state, handlers));
    if (state.mode === "review") {
      const allOpen = [...review.chunks.map((chunk) => chunk.n), ...(state.extras.length ? [EXTRA_KEY] : [])].every((key) =>
        state.expanded.has(key),
      );
      element.append(
        allOpen ? button("prf-expand", "Collapse all", handlers.onCollapseAll) : button("prf-expand", "Expand all", handlers.onExpandAll),
      );
    }
    return element;
  }

  function groups(review, state, handlers) {
    const list = make("div", "prf-groups");
    for (const chunk of orderChunks(review.chunks, state.order)) list.append(chunkGroup(chunk, state, handlers));
    if (state.extras.length) list.append(extraGroup(state.extras, state, handlers));
    return list;
  }

  // Our list sits just before GitHub's tree in the same column; GitHub's tree is hidden while ours shows.
  function mountPoint() {
    const host = ns.page.treeHost();
    if (!host) return null;
    let root = document.getElementById(ROOT_ID);
    if (!root) {
      root = make("div", "prf-tree");
      root.id = ROOT_ID;
    }
    if (root.nextElementSibling !== host) host.before(root);
    return { root, host };
  }

  // state: { mode: "review" | "github", order: "flow" | "risk", selectedN, expanded: Set of chunk numbers and "extra",
  //          extras: [{ path }], pageSha, note, activeFiles: Set of the active box's paths }
  // handlers: onMode(mode), onToggleGroup(key), onSelectChunk(n), onSelectFile(n | null, path),
  //           onJumpToStart(n), onExpandAll(), onCollapseAll(), onOrder(order)
  function render(review, state, handlers) {
    const mount = mountPoint();
    if (!mount) return;
    const { root, host } = mount;
    const reviewMode = state.mode === "review";
    const scrolled = root.querySelector(".prf-groups")?.scrollTop ?? 0;
    root.classList.toggle("prf-review", reviewMode);
    host.classList.toggle(HOST_HIDDEN, reviewMode);

    root.replaceChildren(bar(review, state, handlers));
    const stale = staleMessage(review, state.pageSha);
    if (stale) root.append(make("p", "prf-banner", stale));
    if (state.note) root.append(make("p", "prf-banner", state.note));
    if (reviewMode) {
      root.append(groups(review, state, handlers));
      root.querySelector(".prf-groups").scrollTop = scrolled;
    }
  }

  const SERVER_COMMAND = "pd serve";

  // The note shown instead of the list while the page server is down. GitHub's own tree stays visible. handlers: onRetry()
  function renderServerNote(baseUrl, handlers) {
    const mount = mountPoint();
    if (!mount) return;
    const { root, host } = mount;
    root.classList.remove("prf-review");
    host.classList.remove(HOST_HIDDEN);
    const note = make("div", "prf-banner prf-offline");
    note.append(make("p", undefined, `pr-describe server isn't running at ${baseUrl}`));
    const command = make("p");
    command.append("Start it with ", make("code", undefined, SERVER_COMMAND));
    note.append(command, button("prf-retry", "Retry", handlers.onRetry));
    root.replaceChildren(note);
  }

  // `text` as nodes, with `code` spans in backticks drawn as <code>.
  function messageNodes(text) {
    return String(text)
      .split(/`([^`]+)`/)
      .map((part, index) => (index % 2 === 1 ? make("code", undefined, part) : part));
  }

  // The one line shown in the list's place when the PR has no brief yet, GitHub's own tree staying visible.
  // view: { kind: "none" } | { kind: "running", stage, elapsed } | { kind: "error", message }
  // handlers: onGenerate(), onCancel()
  function renderGenerateLine(view, handlers) {
    const mount = mountPoint();
    if (!mount) return;
    const { root, host } = mount;
    root.classList.remove("prf-review");
    host.classList.remove(HOST_HIDDEN);
    const line = make("div", "prf-banner prf-offline prf-generate");
    if (view.kind === "running") {
      const stage = ns.runControl.STAGES.find((entry) => entry.id === view.stage)?.label ?? "";
      line.append(make("span", "prf-generate-text", `Writing brief · ${ns.runControl.formatElapsed(view.elapsed)}${stage ? ` · ${stage}` : ""}`), button("prf-retry", "Cancel", handlers.onCancel));
    } else if (view.kind === "error") {
      const text = make("span", "prf-generate-text");
      text.append(...messageNodes(view.message));
      line.append(text, button("prf-retry", "Retry", handlers.onGenerate));
    } else {
      line.append(make("span", "prf-generate-text", "No brief for this PR yet"), button("prf-retry", "Generate brief", handlers.onGenerate));
    }
    root.replaceChildren(line);
  }

  const REVEAL_MARGIN = 8;

  // The scrollTop that brings the span [top, bottom] (in the list's scrolled content coordinates) into a list
  // `height` tall, scrolled to `scrollTop`; null when the span is already fully visible. A span too tall to fit
  // goes with its top near the top of the list.
  function revealTarget({ scrollTop, height, top, bottom, margin = REVEAL_MARGIN }) {
    if (top >= scrollTop && bottom <= scrollTop + height) return null;
    if (bottom - top > height - 2 * margin || top < scrollTop) return Math.max(0, top - margin);
    return bottom + margin - height;
  }

  // Scrolls the review list, and only it, so the group for chunk `n` shows its header and its active file rows.
  // Smooth unless the user prefers reduced motion.
  function revealGroup(n) {
    const list = document.querySelector(`#${ROOT_ID} .prf-groups`);
    const element = list?.querySelector(`.prf-group[data-group="${n}"]`);
    if (!element) return;
    const base = list.getBoundingClientRect().top - list.scrollTop;
    const header = element.querySelector(".prf-head").getBoundingClientRect();
    const rows = [...element.querySelectorAll(".prf-file-active")].map((row) => row.getBoundingClientRect());
    const target = revealTarget({
      scrollTop: list.scrollTop,
      height: list.clientHeight,
      top: header.top - base,
      bottom: Math.max(header.bottom, ...rows.map((rect) => rect.bottom)) - base,
    });
    if (target === null) return;
    const reduced = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    list.scrollTo({ top: target, behavior: reduced ? "instant" : "smooth" });
  }

  // Flashes once the active file rows.
  function flashRows() {
    if (globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    for (const row of document.querySelectorAll(`#${ROOT_ID} .prf-file-active`)) {
      row.classList.remove(ROW_FLASH);
      void row.offsetWidth;
      row.classList.add(ROW_FLASH);
      row.addEventListener("animationend", () => row.classList.remove(ROW_FLASH), { once: true });
    }
  }

  function remove() {
    document.getElementById(ROOT_ID)?.remove();
    ns.page.treeHost()?.classList.remove(HOST_HIDDEN);
  }

  function owns(node) {
    const element = node?.nodeType === 1 ? node : node?.parentElement;
    return Boolean(element?.closest(`#${ROOT_ID}`));
  }

  ns.tree = { render, renderServerNote, renderGenerateLine, flashRows, revealGroup, revealTarget, readFirstReason, remove, owns, orderChunks, hasSteps, defaultOrder, ambiguousNames, levelLabel, staleMessage, EXTRA_KEY };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.tree;
