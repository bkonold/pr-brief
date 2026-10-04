(() => {
  const ns = (globalThis.prFocus ??= {});
  const ROOT_ID = "pr-focus-tree";
  const HOST_HIDDEN = "prf-tree-hidden";
  const EXTRA_KEY = "extra";
  const BADGE_FLASH = "prf-badge-flash";
  const ROW_FLASH = "prf-row-flash";
  const UNCHUNKED = "Unchunked";
  const LOWEST_LEVEL = "skim";
  const WHY_LIMIT = 140;
  const SHORT_SHA = 7;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const LIST_TREE_ICON = "M2.5 3h11M5.5 8h8M5.5 13h8M3 3.5v9.5M3 8h2.5M3 13h2.5";
  const FOLDER_ICON = "M1.75 3.5h4.25l1.5 1.75h6.75v7.5h-12.5z";
  const DIAMOND_ICON = "M8 2l5 6-5 6-5-6z";
  const JUMP_ICON = "M2.5 3v10M5.5 8h8M10 4.5L13.5 8 10 11.5";
  const CARET_ICON = "M4 6l4 4 4-4";
  const FILE_ICON =
    "M2 1.75C2 .784 2.784 0 3.75 0h6.586c.464 0 .909.184 1.237.513l2.914 2.914c.329.328.513.773.513 1.237v9.586A1.75 1.75 0 0 1 13.25 16h-9.5A1.75 1.75 0 0 1 2 14.25Zm1.75-.25a.25.25 0 0 0-.25.25v12.5c0 .138.112.25.25.25h9.5a.25.25 0 0 0 .25-.25V6h-2.75A1.75 1.75 0 0 1 9 4.25V1.5Zm6.75.062V4.25c0 .138.112.25.25.25h2.688l-.011-.013-2.914-2.914-.013-.011Z";

  const LEVEL_ORDER = ["read carefully", "read", "skim"];

  function groupRank(chunk) {
    if (chunk.name === UNCHUNKED) return LEVEL_ORDER.length;
    const rank = LEVEL_ORDER.indexOf(chunk.review);
    return rank === -1 ? LEVEL_ORDER.indexOf("read") : rank;
  }

  function isMuted(chunk) {
    return chunk.review === LOWEST_LEVEL || chunk.name === UNCHUNKED;
  }

  // "read carefully" first, then "read", then "skim", then Unchunked; ties keep review.json's order.
  function orderChunks(chunks) {
    return chunks
      .map((chunk, index) => ({ chunk, index }))
      .sort((a, b) => groupRank(a.chunk) - groupRank(b.chunk) || a.index - b.index)
      .map(({ chunk }) => chunk);
  }

  function folderOf(path) {
    const slash = path.lastIndexOf("/");
    return slash === -1 ? "" : path.slice(0, slash);
  }

  function baseNameOf(path) {
    return path.slice(path.lastIndexOf("/") + 1);
  }

  // The files in their given order, split into runs that share a folder, so each folder is named once above
  // its files. Order is kept, and a folder met again later starts a new run. A file at the repository root has
  // the folder "".
  function groupByFolder(files) {
    const runs = [];
    for (const file of files) {
      const folder = folderOf(file.path);
      if (runs.at(-1)?.folder === folder) runs.at(-1).files.push(file);
      else runs.push({ folder, files: [file] });
    }
    return runs;
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

  function shorten(text, limit) {
    return text.length > limit ? `${text.slice(0, limit - 1).trimEnd()}…` : text;
  }

  function fileIcon() {
    const svg = svgIcon(FILE_ICON, 14, "prf-file-icon");
    svg.setAttribute("fill", "currentColor");
    return svg;
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

  function fileRow(file, onClick, boxes = [], active = false) {
    const item = make("li", "prf-file-item");
    const row = button("prf-file", undefined, onClick);
    row.classList.toggle("prf-file-active", active);
    row.title = file.path;
    row.append(fileIcon(), make("span", "prf-file-name", baseNameOf(file.path)));
    if (boxes.length) {
      const badge = make("span", "prf-box");
      badge.append(outlineIcon(DIAMOND_ICON, 10, "prf-box-icon"), boxes.join(", "));
      badge.title = `Diagram ${boxes.length === 1 ? "box" : "boxes"} ${boxes.join(", ")}`;
      row.append(badge);
    }
    if (file.additions !== undefined) {
      row.append(make("span", "prf-add", `+${file.additions}`), make("span", "prf-del", `−${file.deletions}`));
    }
    item.append(row);
    return item;
  }

  // The rows of a file list, each shared folder named once in a dim header above its files. `rowFor(file)` builds a
  // file's row.
  function fileRows(files, rowFor) {
    const rows = [];
    for (const { folder, files: run } of groupByFolder(files)) {
      if (folder) {
        const header = make("li", "prf-folder");
        header.title = folder;
        header.append(make("bdi", "prf-folder-text", `${folder}/`));
        rows.push(header);
      }
      for (const file of run) rows.push(rowFor(file));
    }
    return rows;
  }

  function group({ key, expanded, selected, muted }, header, files) {
    const element = make("section", "prf-group");
    element.dataset.group = String(key);
    element.classList.toggle("prf-expanded", expanded);
    element.classList.toggle("prf-selected", selected);
    element.classList.toggle("prf-muted", muted);
    element.append(header);
    if (expanded) element.append(files);
    return element;
  }

  function chevron(expanded, onClick) {
    const element = button("prf-chevron", "›", onClick);
    element.setAttribute("aria-expanded", String(expanded));
    element.setAttribute("aria-label", expanded ? "Collapse group" : "Expand group");
    return element;
  }

  const CARD_ID = "pr-focus-start-card";
  const CARD_DELAY_MS = 300;
  const SIDE_KIND = { L: "removed line", R: "added or unchanged line" };

  // What the start-line card says: the diff records a start line as "L" (old file) or "R" (new file) and
  // doesn't tell an added line from a context line on the new side.
  function startCard(start) {
    const basename = start.path.split("/").pop();
    return {
      heading: "Read this line first",
      location: `${basename}:${start.line}`,
      kind: SIDE_KIND[start.side] ?? "line",
      code: start.text,
      path: start.path,
      hint: "Click to jump",
    };
  }

  let card = null;
  let cardTimer = null;
  let cardDismiss = null;

  function hideStartCard() {
    clearTimeout(cardTimer);
    cardTimer = null;
    card?.remove();
    card = null;
    if (cardDismiss) document.removeEventListener("keydown", cardDismiss, true);
    cardDismiss = null;
  }

  // The card sits in the list directly below its chunk's header, pushing the rows under it down, so it never
  // covers the diff.
  function showStartCard(button, start) {
    hideStartCard();
    const model = startCard(start);
    card = make("div", "prf-card");
    card.id = CARD_ID;
    card.setAttribute("role", "tooltip");
    const code = make("div", "prf-card-code", model.code);
    card.append(
      make("div", "prf-card-head", model.heading),
      make("div", "prf-card-loc", `${model.location} · ${model.kind}`),
      code,
      make("div", "prf-card-path", model.path),
      make("div", "prf-card-hint", model.hint),
    );
    button.closest(".prf-head").after(card);
    cardDismiss = (event) => {
      if (event.key === "Escape") hideStartCard();
    };
    document.addEventListener("keydown", cardDismiss, true);
  }

  // Why to read the chunk's start line: the model's reason for that line, else the chunk's own.
  function readFirstReason(chunk) {
    return chunk.start?.why?.trim() || chunk.why || "";
  }

  // The note pinned above the start line in the diff: only the reason, since the row below it already shows the line.
  function startCallout(chunk, onClose) {
    const element = make("div", "prf-callout");
    element.setAttribute("role", "note");
    const close = button("prf-callout-close", "×", onClose);
    close.setAttribute("aria-label", "Dismiss the read-first note");
    element.append(
      outlineIcon(JUMP_ICON, 16, "prf-callout-icon"),
      make("strong", "prf-callout-label", "Read first:"),
      make("span", "prf-callout-reason", readFirstReason(chunk)),
      close,
    );
    return element;
  }

  function startButton(chunk, handlers) {
    const element = button("prf-start", undefined, (event) => {
      event.stopPropagation();
      hideStartCard();
      handlers.onJumpToStart(chunk.n);
    });
    element.append(outlineIcon(JUMP_ICON, 16, "prf-start-icon"));
    element.setAttribute("aria-label", `Jump to the line to read first: ${startCard(chunk.start).location}`);
    element.addEventListener("mouseenter", () => {
      hideStartCard();
      cardTimer = setTimeout(() => showStartCard(element, chunk.start), CARD_DELAY_MS);
    });
    element.addEventListener("focus", () => {
      if (element.matches(":focus-visible")) showStartCard(element, chunk.start);
    });
    element.addEventListener("mouseleave", hideStartCard);
    element.addEventListener("blur", hideStartCard);
    return element;
  }

  function chunkGroup(chunk, state, handlers) {
    const expanded = state.expanded.has(chunk.n);
    const main = button("prf-head-main", undefined, () => handlers.onSelectChunk(chunk.n));
    main.setAttribute("aria-pressed", String(chunk.n === state.selectedN));
    const line = make("span", "prf-line");
    line.append(make("span", "prf-name", `${chunk.n} · ${chunk.name}`), make("span", "prf-count", String(chunk.files.length)));
    if (isMuted(chunk)) line.append(make("span", "prf-tag", chunk.name === UNCHUNKED ? UNCHUNKED : chunk.review));
    const level = make("span", "prf-meta");
    level.append(make("span", `prf-level prf-level-${chunk.review.replace(/\s+/g, "-")}`, chunk.review));
    const why = make("span", "prf-why");
    if (chunk.why) why.append(outlineIcon(DIAMOND_ICON, 10, "prf-why-icon"));
    why.append(make("span", "prf-why-text", shorten(chunk.why ?? "", WHY_LIMIT)));
    why.title = chunk.why ?? "";
    main.append(line, level, why);

    const header = make("div", "prf-head");
    header.append(chevron(expanded, () => handlers.onToggleGroup(chunk.n)), outlineIcon(FOLDER_ICON, 14, "prf-folder-icon"), main);
    if (chunk.start) header.append(startButton(chunk, handlers));
    const files = make("ul", "prf-files");
    files.append(
      ...fileRows(chunk.files, (file) =>
        fileRow(file, () => handlers.onSelectFile(chunk.n, file.path), state.badges?.get(file.path), state.activeFiles?.has(file.path)),
      ),
    );
    return group({ key: chunk.n, expanded, selected: chunk.n === state.selectedN, muted: isMuted(chunk) }, header, files);
  }

  function extraGroup(extras, state, handlers) {
    const expanded = state.expanded.has(EXTRA_KEY);
    const main = button("prf-head-main", undefined, () => handlers.onToggleGroup(EXTRA_KEY));
    const line = make("span", "prf-line");
    line.append(make("span", "prf-name", "Not in review"), make("span", "prf-count", String(extras.length)));
    main.append(line);
    const header = make("div", "prf-head");
    header.append(chevron(expanded, () => handlers.onToggleGroup(EXTRA_KEY)), outlineIcon(FOLDER_ICON, 14, "prf-folder-icon"), main);
    const files = make("ul", "prf-files");
    files.append(...fileRows(extras, (file) => fileRow(file, () => handlers.onSelectFile(null, file.path))));
    return group({ key: EXTRA_KEY, expanded, selected: false, muted: true }, header, files);
  }

  function modeToggle(state, handlers) {
    const toggle = make("div", "prf-modes");
    for (const [mode, label, icon] of [["review", "By review", LIST_TREE_ICON], ["github", "GitHub tree", FOLDER_ICON]]) {
      const choice = button("prf-mode", undefined, () => handlers.onMode(mode));
      choice.append(outlineIcon(icon, 14, "prf-mode-icon"), make("span", undefined, label));
      choice.setAttribute("aria-pressed", String(state.mode === mode));
      toggle.append(choice);
    }
    return toggle;
  }

  // Offered only when the PR has runs for more than one variant.
  function variantSelect(review, handlers) {
    const select = make("select", "prf-variant");
    select.setAttribute("aria-label", "Review variant");
    for (const entry of review.variants) {
      const option = make("option", undefined, entry.label);
      option.value = entry.variant;
      option.title = entry.description ?? "";
      option.selected = entry.variant === review.variant;
      select.append(option);
    }
    select.title = review.variants.find((entry) => entry.variant === review.variant)?.description ?? "";
    select.addEventListener("change", () => handlers.onSwitchVariant(select.value));
    const pill = make("label", "prf-variant-pill");
    pill.append(make("span", "prf-variant-label", "Variant:"), select, outlineIcon(CARET_ICON, 12, "prf-variant-caret"));
    return pill;
  }

  function bar(review, state, handlers) {
    const element = make("div", "prf-bar");
    if (review.variants?.length > 1) element.append(variantSelect(review, handlers));
    element.append(modeToggle(state, handlers));
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
    for (const chunk of orderChunks(review.chunks)) list.append(chunkGroup(chunk, state, handlers));
    if (state.extras.length) list.append(extraGroup(state.extras, state, handlers));
    return list;
  }

  // Our list sits just before GitHub's tree in the same column; GitHub's tree is hidden while ours shows.
  function mountPoint() {
    const host = ns.githubPage.treeHost();
    if (!host) return null;
    let root = document.getElementById(ROOT_ID);
    if (!root) {
      root = make("div", "prf-tree");
      root.id = ROOT_ID;
    }
    if (root.nextElementSibling !== host) host.before(root);
    return { root, host };
  }

  // state: { mode: "review" | "github", selectedN, expanded: Set of chunk numbers and "extra",
  //          extras: [{ path }], pageSha, note, badges: Map of path -> diagram box numbers,
  //          activeFiles: Set of the active box's paths }
  // handlers: onMode(mode), onToggleGroup(key), onSelectChunk(n), onSelectFile(n | null, path),
  //           onJumpToStart(n), onExpandAll(), onCollapseAll(), onSwitchVariant(variant)
  function render(review, state, handlers) {
    const mount = mountPoint();
    if (!mount) return;
    const { root, host } = mount;
    const reviewMode = state.mode === "review";
    hideStartCard();
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

  const SERVER_COMMAND = "python3 -m http.server 8765 --bind 127.0.0.1";

  // The note shown instead of the list while the page server is down. GitHub's own tree stays visible. handlers: onRetry()
  function renderServerNote(baseUrl, handlers) {
    const mount = mountPoint();
    if (!mount) return;
    const { root, host } = mount;
    root.classList.remove("prf-review");
    host.classList.remove(HOST_HIDDEN);
    const note = make("div", "prf-banner prf-offline");
    note.append(make("p", undefined, `pr-describe page server isn't running at ${baseUrl}`));
    const command = make("p");
    command.append("Run ", make("code", undefined, SERVER_COMMAND), " from ~/workspace/pr-describe");
    note.append(command, button("prf-retry", "Retry", handlers.onRetry));
    root.replaceChildren(note);
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

  // Flashes once the box-number badge of every file row of the active box. A re-render during the flash ends it.
  function flashBadges() {
    if (globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    for (const badge of document.querySelectorAll(`#${ROOT_ID} .prf-file-active .prf-box`)) {
      badge.classList.remove(BADGE_FLASH);
      void badge.offsetWidth;
      badge.classList.add(BADGE_FLASH);
      badge.addEventListener("animationend", () => badge.classList.remove(BADGE_FLASH), { once: true });
    }
  }

  function remove() {
    hideStartCard();
    document.getElementById(ROOT_ID)?.remove();
    ns.githubPage.treeHost()?.classList.remove(HOST_HIDDEN);
  }

  function owns(node) {
    const element = node?.nodeType === 1 ? node : node?.parentElement;
    return Boolean(element?.closest(`#${ROOT_ID}`));
  }

  ns.tree = { render, renderServerNote, flashBadges, flashRows, revealGroup, revealTarget, startCard, readFirstReason, startCallout, remove, owns, orderChunks, groupByFolder, staleMessage, EXTRA_KEY };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.tree;
