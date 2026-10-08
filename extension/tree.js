(() => {
  const ns = (globalThis.prFocus ??= {});
  const ROOT_ID = "pr-focus-tree";
  const HOST_HIDDEN = "prf-tree-hidden";
  const UNCHUNKED = "Unchunked";
  const SHORT_SHA = 7;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const LIST_TREE_ICON = "M2.5 3h11M5.5 8h8M5.5 13h8M3 3.5v9.5M3 8h2.5M3 13h2.5";
  const FOLDER_ICON = "M1.75 3.5h4.25l1.5 1.75h6.75v7.5h-12.5z";
  const CHEVRON_ICON = "M6 3.5L10.5 8 6 12.5";
  const ROUTE_ICON = "M2 12.5a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0-3 0M11 3.5a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0-3 0M3.5 11v-1.5a2 2 0 0 1 2-2h5a2 2 0 0 0 2-2V5";
  const LEVEL_ORDER = ["verify", "read", "skim"];
  const LEGACY_LEVELS = { "read carefully": "verify" };
  // The effort level a review.json word names: verify, read or skim; the older "read carefully" is verify and an
  // unknown word is read.
  function normalizeLevel(review) {
    const word = String(review ?? "").trim().toLowerCase().replace(/\s+/g, " ");
    const level = LEGACY_LEVELS[word] ?? word;
    return LEVEL_ORDER.includes(level) ? level : "read";
  }

  // The first chunk, in review.json's order, that lists the diagram box `nodeId`; null when none does.
  function chunkOfNode(chunks, nodeId) {
    return chunks.find((chunk) => chunk.nodes?.includes(nodeId)) ?? null;
  }

  function chunkByNumber(chunks, n) {
    return chunks.find((chunk) => chunk.n === n) ?? null;
  }

  function baseNameOf(path) {
    return path.slice(path.lastIndexOf("/") + 1);
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

  // Why to read the chunk's start (its line or file): the model's reason for it, else the chunk's own.
  function readFirstReason(chunk) {
    return chunk.start?.why?.trim() || chunk.why || "";
  }

  // The walkthrough's stops, in reading order: review.json's `walkthrough` when the run has one. A run made before
  // walkthroughs has one stop per chunk that names a start, in chunk order, titled by its file and giving the chunk's
  // reason for starting there.
  function stopsOf(review) {
    if (Array.isArray(review.walkthrough)) return review.walkthrough;
    return review.chunks
      .filter((chunk) => chunk.start)
      .map((chunk, index) => ({
        i: index + 1,
        title: baseNameOf(chunk.start.path),
        why: readFirstReason(chunk),
        path: chunk.start.path,
        side: chunk.start.side ?? null,
        line: chunk.start.line ?? null,
        chunk: chunk.n,
      }));
  }

  // The first stop that lies in chunk `n`; null when the walkthrough never stops there.
  function firstStopOf(stops, n) {
    return stops.find((stop) => stop.chunk === n) ?? null;
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
  // chunk it lies in and its title, why to stop here, and, in a column beside them, buttons to the previous and the next
  // stop, each in a slot that is kept, hidden, when there is no such stop. `onGo(stop)` opens a stop; `chunks` names the chunk a stop lies in.
  function stopCallout(stop, stops, onGo, chunks = []) {
    const card = make("div", "prf-callout");
    const main = make("div", "prf-callout-main");
    const head = make("div", "prf-callout-head");
    head.append(outlineIcon(ROUTE_ICON, 18, "prf-callout-icon"));
    const chunk = chunkByNumber(chunks, stop.chunk);
    head.append(
      make("strong", "prf-callout-chunk", `Stop ${stop.i} of ${stops.length}${chunk ? ` · ${chunk.n} ${chunk.name}` : ""}`),
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
    for (const [mode, label, icon] of [["review", "By review", LIST_TREE_ICON], ["github", ns.page.treeLabel, FOLDER_ICON]]) {
      const choice = button("prf-mode", undefined, () => handlers.onMode(mode));
      choice.append(outlineIcon(icon, 14, "prf-mode-icon"), make("span", undefined, label));
      choice.setAttribute("aria-pressed", String(state.mode === mode));
      toggle.append(choice);
    }
    return toggle;
  }

  function bar(state, handlers) {
    const element = make("div", "prf-bar");
    element.append(modeToggle(state, handlers));
    return element;
  }

  // What names the chunk a stop lies in: its step word, else its name; empty for a stop in no chunk.
  function stopChunkWord(review, stop) {
    const chunk = chunkByNumber(review.chunks, stop.chunk);
    return chunk ? chunk.step || chunk.name : "";
  }

  // One row per stop: its number, its title and the chunk it lies in. The current stop is marked.
  function stopRow(review, stop, state, handlers) {
    const current = stop.i === state.selectedStop;
    const main = button("prf-head-main", undefined, () => handlers.onSelectStop(stop.i));
    if (current) main.setAttribute("aria-current", "step");
    const title = make("span", "prf-title");
    title.append(make("span", "prf-name", stop.title));
    main.append(make("span", "prf-num", String(stop.i)), title, make("span", "prf-level", stopChunkWord(review, stop)));
    const header = make("div", "prf-head");
    header.append(main);
    const element = make("section", "prf-group prf-stop");
    element.classList.toggle("prf-selected", current);
    element.dataset.stop = String(stop.i);
    element.append(header);
    return element;
  }

  function stopList(review, state, handlers) {
    const list = make("div", "prf-groups");
    if (state.stops.length === 0) list.append(make("p", "prf-banner", "This run has no stops to walk through."));
    for (const stop of state.stops) list.append(stopRow(review, stop, state, handlers));
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

  // state: { mode: "review" | "github", stops, selectedStop, pageSha, note }
  // handlers: onMode(mode), onSelectStop(i)
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
      root.append(stopList(review, state, handlers));
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
      .map((part, index) => (index % 2 === 1 ? make("code", undefined, part) : part))
      .filter((node) => node !== "");
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

  ns.tree = { render, renderServerNote, renderGenerateLine, revealStop, revealTarget, readFirstReason, stopsOf, firstStopOf, stopCallout, bar, stopList, remove, owns, chunkOfNode, normalizeLevel, staleMessage };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.tree;
