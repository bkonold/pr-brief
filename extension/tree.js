(() => {
  const ns = (globalThis.prFocus ??= {});
  const ROOT_ID = "pr-focus-tree";
  const HOST_HIDDEN = "prf-tree-hidden";
  const SHORT_SHA = 7;
  const SVG_NS = "http://www.w3.org/2000/svg";
  // Octicons' list-ordered and file-directory, 16-unit filled paths.
  const LIST_ORDERED_ICON =
    "M5 3.25a.75.75 0 0 1 .75-.75h8.5a.75.75 0 0 1 0 1.5h-8.5A.75.75 0 0 1 5 3.25Zm0 5a.75.75 0 0 1 .75-.75h8.5a.75.75 0 0 1 0 1.5h-8.5A.75.75 0 0 1 5 8.25Zm0 5a.75.75 0 0 1 .75-.75h8.5a.75.75 0 0 1 0 1.5h-8.5a.75.75 0 0 1-.75-.75ZM.924 10.32a.5.5 0 0 1-.851-.525l.001-.001.001-.002.002-.004.007-.011c.097-.144.215-.273.348-.384.228-.19.588-.392 1.068-.392.468 0 .858.181 1.126.484.259.294.377.673.377 1.038 0 .987-.686 1.495-1.156 1.845l-.047.035c-.303.225-.522.4-.654.597h1.357a.5.5 0 0 1 0 1H.5a.5.5 0 0 1-.5-.5c0-1.005.692-1.52 1.167-1.875l.035-.025c.531-.396.8-.625.8-1.078a.57.57 0 0 0-.128-.376C1.806 10.068 1.695 10 1.5 10a.658.658 0 0 0-.429.163.835.835 0 0 0-.144.153ZM2.003 2.5V6h.503a.5.5 0 0 1 0 1H.5a.5.5 0 0 1 0-1h.503V3.308l-.28.14a.5.5 0 0 1-.446-.895l1.003-.5a.5.5 0 0 1 .723.447Z";
  const DIRECTORY_ICON =
    "M0 2.75C0 1.784.784 1 1.75 1H5c.55 0 1.07.26 1.4.7l.9 1.2a.25.25 0 0 0 .2.1h6.75c.966 0 1.75.784 1.75 1.75v8.5A1.75 1.75 0 0 1 14.25 15H1.75A1.75 1.75 0 0 1 0 13.25Zm1.75-.25a.25.25 0 0 0-.25.25v10.5c0 .138.112.25.25.25h12.5a.25.25 0 0 0 .25-.25v-8.5a.25.25 0 0 0-.25-.25H7.5c-.55 0-1.07-.26-1.4-.7l-.9-1.2a.25.25 0 0 0-.2-.1Z";
  const CHEVRON_ICON = "M6 3.5L10.5 8 6 12.5";
  const ROUTE_ICON = "M2 12.5a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0-3 0M11 3.5a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0-3 0M3.5 11v-1.5a2 2 0 0 1 2-2h5a2 2 0 0 0 2-2V5";
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

  // A 16-unit icon filled with the current text colour.
  function filledIcon(d, size, className) {
    const svg = svgIcon(d, size, className);
    svg.firstChild.setAttribute("fill", "currentColor");
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

  // The walkthrough's stops, in reading order: review.json's `walkthrough`.
  function stopsOf(review) {
    return review.walkthrough;
  }

  const FILE_SET_LABELS = { contract: "Contract", data: "Data" };

  // The chips that narrow the host's file tree to a set of files: "All" with the PR's changed-file count, then each of the review's
  // file sets that has files. A run with no such set, or an older run that has none, gets no chips. `changed` is how
  // many files the page shows as changed; the "All" count is never smaller than a set it contains.
  function fileChips(review, changed = 0) {
    const sets = review.file_sets ?? {};
    const sized = Object.keys(FILE_SET_LABELS).filter((id) => (sets[id] ?? []).length > 0);
    if (sized.length === 0) return [];
    const all = Math.max(changed, ...sized.map((id) => sets[id].length));
    return [{ id: "all", label: "All", count: all }, ...sized.map((id) => ({ id, label: FILE_SET_LABELS[id], count: sets[id].length }))];
  }

  // The file set a chip selects: { id, paths }; null for "All" and for a set the review does not have.
  function fileSetOf(review, id) {
    const paths = Object.hasOwn(FILE_SET_LABELS, id) ? review.file_sets?.[id] : null;
    return paths?.length ? { id, paths } : null;
  }

  // Keeps an empty slot of the callout's nav column in the layout so the other slot stays where it is, while the slot
  // can't be seen, focused, clicked or announced. `control` is the button inside it, when the slot is not itself one.
  function inertSlot(slot, control = slot) {
    slot.setAttribute("aria-hidden", "true");
    slot.inert = true;
    control.setAttribute("tabindex", "-1");
    control.disabled = true;
  }

  // The card shown above a stop's line, or above its file's header, in the diff: which stop of how many this is, the
  // diagram box it belongs to and its title, why to stop here, and, in a column beside them, buttons to the previous and
  // the next stop, each in a slot that is kept, hidden, when there is no such stop. `onGo(stop)` opens a stop; `nodes`
  // is review.json's `nodes`, which names the box a stop belongs to.
  function stopCallout(stop, stops, onGo, nodes = {}) {
    const card = make("div", "prf-callout");
    const main = make("div", "prf-callout-main");
    const head = make("div", "prf-callout-head");
    head.append(outlineIcon(ROUTE_ICON, 18, "prf-callout-icon"));
    const box = nodes[stop.node];
    head.append(
      make("strong", "prf-callout-where", `Stop ${stop.i} of ${stops.length}${box ? ` · ${box.title}` : ""}`),
      outlineIcon(CHEVRON_ICON, 14, "prf-callout-sep"),
      make("span", "prf-callout-name", stop.title),
    );
    main.append(head);
    if (stop.why) main.append(make("div", "prf-callout-label", "Why stop here"), make("div", "prf-callout-reason", stop.why));
    card.append(main);

    const nav = make("div", "prf-callout-nav");
    const at = stops.findIndex((other) => other.i === stop.i);
    const previous = stops[at - 1];
    const following = stops[at + 1];
    const back = button(previous ? "prf-callout-prev" : "prf-callout-prev prf-callout-empty", "↑ Previous", () => previous && onGo(previous));
    if (previous) back.title = previous.title;
    else inertSlot(back);
    const next = make("div", following ? "prf-callout-next" : "prf-callout-next prf-callout-empty");
    const buttons = make("div", "prf-callout-targets");
    buttons.append(button("prf-callout-go", following ? `${following.title} ↓` : "↓", () => following && onGo(following)));
    next.append(make("span", "prf-callout-nav-label", "Next"), buttons);
    if (!following) inertSlot(next, buttons.children[0]);
    nav.append(back, next);
    card.append(nav);
    return card;
  }

  function modeToggle(state, handlers) {
    const toggle = make("div", "prf-modes");
    for (const [mode, label, icon] of [["review", "Walkthrough", LIST_ORDERED_ICON], ["github", ns.page.treeLabel, DIRECTORY_ICON]]) {
      const choice = button("prf-mode", undefined, () => handlers.onMode(mode));
      choice.append(filledIcon(icon, 14, "prf-mode-icon"), make("span", undefined, label));
      choice.setAttribute("aria-pressed", String(state.mode === mode));
      toggle.append(choice);
    }
    return toggle;
  }

  function chipRow(state, handlers) {
    const selected = state.fileSet?.id ?? "all";
    const row = make("div", "prf-chips");
    for (const chip of state.chips) {
      const element = button("prf-chip", undefined, () => handlers.onFileSet(chip.id));
      element.append(make("span", undefined, chip.label), make("span", "prf-chip-count", String(chip.count)));
      element.setAttribute("aria-pressed", String(selected === chip.id));
      row.append(element);
    }
    return row;
  }

  function bar(state, handlers) {
    const element = make("div", "prf-bar");
    element.append(modeToggle(state, handlers));
    if (state.chips?.length) element.append(chipRow(state, handlers));
    return element;
  }

  // One row per stop: its number and its title. The current stop is marked.
  function stopRow(stop, state, handlers) {
    const current = stop.i === state.selectedStop;
    const main = button("prf-head-main", undefined, () => handlers.onSelectStop(stop.i));
    if (current) main.setAttribute("aria-current", "step");
    const title = make("span", "prf-title");
    title.append(make("span", "prf-name", stop.title));
    main.append(make("span", "prf-num", String(stop.i)), title);
    const header = make("div", "prf-head");
    header.append(main);
    const element = make("section", "prf-group prf-stop");
    element.classList.toggle("prf-selected", current);
    element.dataset.stop = String(stop.i);
    element.append(header);
    return element;
  }

  function stopList(state, handlers) {
    const list = make("div", "prf-groups");
    if (state.stops.length === 0) list.append(make("p", "prf-banner", "This run has no stops to walk through."));
    for (const stop of state.stops) list.append(stopRow(stop, state, handlers));
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

  // state: { mode: "review" | "github", stops, selectedStop, pageSha, note, chips, fileSet }
  // handlers: onMode(mode), onSelectStop(i), onFileSet(id)
  function render(review, state, handlers) {
    const mount = mountPoint();
    if (!mount) return;
    const { root, host } = mount;
    const reviewMode = state.mode === "review";
    const scrolled = root.querySelector(".prf-groups")?.scrollTop ?? 0;
    root.classList.toggle("prf-review", reviewMode);
    host.classList.toggle(HOST_HIDDEN, reviewMode);

    root.replaceChildren(bar(state, handlers));
    const stale = staleMessage(review, state.pageSha);
    if (stale) root.append(make("p", "prf-banner", stale));
    if (state.note) root.append(make("p", "prf-banner", state.note));
    if (reviewMode) {
      root.append(stopList(state, handlers));
      root.querySelector(".prf-groups").scrollTop = scrolled;
    }
  }

  const SERVER_COMMAND = "pd serve";
  const OLD_BRIEF_MESSAGE = "This brief predates v1; re-run it.";

  // The note shown instead of the list while the page server is down. GitHub's own tree stays visible. handlers: onRetry()
  function renderServerNote(baseUrl, handlers) {
    const mount = mountPoint();
    if (!mount) return;
    const { root, host } = mount;
    root.classList.remove("prf-review");
    host.classList.remove(HOST_HIDDEN);
    const note = make("div", "prf-banner prf-offline");
    note.append(make("p", undefined, `pr-brief server isn't running at ${baseUrl}`));
    const command = make("p");
    command.append("Start it with ", make("code", undefined, SERVER_COMMAND));
    note.append(command, button("prf-retry", "Retry", handlers.onRetry));
    root.replaceChildren(note);
  }

  // `text` as nodes, with `code` spans in backticks drawn as <code>.
  function messageNodes(text) {
    return String(text)
      .split(/`([^`]+)`/)
      .map((part, index) => (index % 2 === 1 ? make("code", undefined, part) : part))
      .filter((node) => node !== "");
  }

  // The one line shown in the list's place when the PR has no brief yet, GitHub's own tree staying visible.
  // view: { kind: "none" } | { kind: "old" } | { kind: "running", stage, elapsed } | { kind: "error", message }
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
    } else if (view.kind === "old") {
      line.append(make("span", "prf-generate-text", OLD_BRIEF_MESSAGE), button("prf-retry", "Re-run", handlers.onGenerate));
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

  // Scrolls the review list, and only it, so the row of stop `i` shows. Smooth unless the user prefers reduced motion.
  function revealStop(i) {
    const list = document.querySelector(`#${ROOT_ID} .prf-groups`);
    const element = list?.querySelector(`.prf-stop[data-stop="${i}"]`);
    if (!element) return;
    const base = list.getBoundingClientRect().top - list.scrollTop;
    const row = element.getBoundingClientRect();
    const target = revealTarget({ scrollTop: list.scrollTop, height: list.clientHeight, top: row.top - base, bottom: row.bottom - base });
    if (target === null) return;
    const reduced = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    list.scrollTo({ top: target, behavior: reduced ? "instant" : "smooth" });
  }

  function remove() {
    document.getElementById(ROOT_ID)?.remove();
    ns.page.treeHost()?.classList.remove(HOST_HIDDEN);
  }

  function owns(node) {
    const element = node?.nodeType === 1 ? node : node?.parentElement;
    return Boolean(element?.closest(`#${ROOT_ID}`));
  }

  ns.tree = { render, renderServerNote, renderGenerateLine, revealStop, revealTarget, stopsOf, fileChips, fileSetOf, stopCallout, bar, stopList, remove, owns, staleMessage };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.tree;
