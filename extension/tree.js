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
  // Octicons' check, 16-unit filled.
  const CHECK_ICON = "M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.751.751 0 0 1 .018-1.042.751.751 0 0 1 1.042-.018L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0Z";
  // Three stacked layers, filled.
  const LAYERS_ICON = "M8 1 15 4.5 8 8 1 4.5ZM1 7.4 8 10.9 15 7.4V8.9L8 12.4 1 8.9ZM1 10.4 8 13.9 15 10.4V11.9L8 15.4 1 11.9Z";
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

  // The review's layers, in order: review.json's `chunks`, absent on a run made before layers existed.
  function chunksOf(review) {
    return review.chunks ?? [];
  }

  const FILE_SET_LABELS = { contract: "API", data: "Data" };

  // The chips that pick which files the pane lists: "All" with the PR's changed-file count, then each of the review's
  // file sets that has files. A run with no such set, or an older run that has none, gets no chips. `changed` is how
  // many files the page shows as changed; the "All" count is never smaller than a set it contains.
  function fileChips(review, changed = 0) {
    const sets = review.file_sets ?? {};
    const sized = Object.keys(FILE_SET_LABELS).filter((id) => (sets[id] ?? []).length > 0);
    if (sized.length === 0) return [];
    const all = Math.max(changed, ...sized.map((id) => sets[id].length));
    return [{ id: "all", label: "All", count: all }, ...sized.map((id) => ({ id, label: FILE_SET_LABELS[id], count: sets[id].length }))];
  }

  // The PR's test files, as full paths: review.json's `file_sets.tests`, absent on a run made before it existed.
  function testsOf(review) {
    return review.file_sets?.tests ?? [];
  }

  // The file set a chip selects: { id, paths, lines } with the review's contract or data lines of that set; null for "All"
  // and for a set the review does not have.
  function fileSetOf(review, id) {
    const paths = Object.hasOwn(FILE_SET_LABELS, id) ? review.file_sets?.[id] : null;
    return paths?.length ? { id, paths, lines: review[id] ?? [] } : null;
  }

  function baseName(path) {
    return path.slice(path.lastIndexOf("/") + 1);
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
    if (stop.why) {
      const reason = make("div", "prf-callout-reason");
      reason.append(...messageNodes(stop.why));
      main.append(make("div", "prf-callout-label", "Why stop here"), reason);
    }
    card.append(main);

    const nav = make("div", "prf-callout-nav");
    const at = stops.findIndex((other) => other.i === stop.i);
    const previous = stops[at - 1];
    const following = stops[at + 1];
    const back = button(previous ? "prf-callout-prev" : "prf-callout-prev prf-callout-empty", "↑ Previous", () => previous && onGo(previous));
    if (previous) back.title = previous.title;
    else inertSlot(back);
    const next = button(following ? "prf-callout-next" : "prf-callout-next prf-callout-empty", "Next \u2193", () => following && onGo(following));
    if (following) next.title = following.title;
    else inertSlot(next);
    nav.append(back, next);
    card.append(nav);
    return card;
  }

  function modeToggle(state, handlers) {
    const toggle = make("div", "prf-modes");
    const modes = [["review", "Walkthrough", LIST_ORDERED_ICON]];
    if (state.chunks?.length) modes.push(["chunks", "Layers", LAYERS_ICON]);
    modes.push(["github", ns.page.treeLabel, DIRECTORY_ICON]);
    for (const [mode, label, icon] of modes) {
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

  const TESTS_MODES = ["all", "hide", "only"];
  const TESTS_CHOICES = [["all", "all"], ["hide", "hidden"], ["only", "only"]];

  // Whether the Tests control keeps `path` out of view: a test file while tests are hidden, any other file while only
  // tests are shown.
  function isExcludedByTests(state, path) {
    if (state.testsMode === "hide") return (state.tests ?? []).includes(path);
    if (state.testsMode === "only") return !(state.tests ?? []).includes(path);
    return false;
  }

  // The label "Tests" and one choice per mode, all, hidden or only, of which files the page shows: all of them, all but
  // the test files, or only the test files. The choice in effect is pressed; a click picks its mode directly.
  function testsControl(state, handlers) {
    const mode = TESTS_MODES.includes(state.testsMode) ? state.testsMode : "all";
    const control = make("span", "prf-tests");
    control.append(make("span", "prf-tests-label", "Tests"));
    TESTS_CHOICES.forEach(([value, label], index) => {
      const choice = button("prf-tests-choice", label, () => handlers.onTestsMode(value));
      choice.setAttribute("aria-pressed", String(mode === value));
      if (index > 0) control.append(make("span", "prf-tests-sep", "\u00b7"));
      control.append(choice);
    });
    return control;
  }

  // The line under the toggle: the file chips in "Walkthrough" and "Files" or the layer count in "Layers" at its left,
  // and in "Files" and "Layers" the Tests control, when the review has test files, at its right. Null when the line
  // would be empty.
  function filters(state, handlers) {
    const line = make("div", "prf-filters");
    if (state.mode === "chunks") line.append(chunksLede(state));
    else if (state.chips?.length) line.append(chipRow(state, handlers));
    if (state.mode !== "review" && state.tests?.length) line.append(testsControl(state, handlers));
    return line.children.length > 0 ? line : null;
  }

  function bar(state, handlers) {
    const element = make("div", "prf-bar");
    element.append(modeToggle(state, handlers));
    return element;
  }

  // One row per stop: its number and its title. The current stop is marked.
  function stopRow(stop, state, handlers) {
    const current = stop.i === state.selectedStop;
    const main = button("prf-head-main", undefined, () => handlers.onSelectStop(stop.i));
    if (current) main.setAttribute("aria-current", "step");
    const title = make("span", "prf-title");
    title.append(make("span", "prf-name", stop.title));
    if (state.fileSet) title.append(fileName(stop.path));
    main.append(make("span", "prf-num", String(stop.i)), title);
    const header = make("div", "prf-head");
    header.append(main);
    const element = make("section", "prf-group prf-stop");
    element.classList.toggle("prf-selected", current);
    element.dataset.stop = String(stop.i);
    element.append(header);
    return element;
  }

  function fileName(path) {
    const element = make("span", "prf-file", baseName(path));
    element.title = path;
    return element;
  }

  // The line above the stops, counting them; its tooltip says what the list is for.
  const LEDE_HELP = "Read the change in this order. A stop opens its lines in the diff and lights its box in the diagram.";

  function ledeOf(count) {
    const lede = make("p", "prf-lede", `${count} ${count === 1 ? "stop" : "stops"}, in reading order`);
    lede.title = LEDE_HELP;
    return lede;
  }

  // The stops in walkthrough order, under the lede. With a file set selected, only the stops whose file is in the set;
  // a set with no such stop says so in place of the list.
  function stopList(state, handlers) {
    const list = make("div", "prf-groups");
    const files = state.fileSet ? new Set(state.fileSet.paths) : null;
    const stops = files ? state.stops.filter((stop) => files.has(stop.path)) : state.stops;
    if (stops.length === 0) {
      const message = files ? `No stops on ${FILE_SET_LABELS[state.fileSet.id]} files.` : "This run has no stops to walk through.";
      list.append(make("p", "prf-banner", message));
    } else {
      list.append(ledeOf(stops.length));
    }
    for (const stop of stops) list.append(stopRow(stop, state, handlers));
    return list;
  }

  function riskPill(risk) {
    return make("span", `prf-risk prf-risk-${risk}`, risk);
  }

  // The files a layer touches, each with its hunks in the layer's order, listed in the order of each file's first hunk.
  function filesOf(chunk) {
    const files = new Map();
    for (const hunk of chunk.hunks) {
      if (!files.has(hunk.path)) files.set(hunk.path, { path: hunk.path, hunks: [] });
      files.get(hunk.path).hunks.push(hunk);
    }
    return [...files.values()];
  }

  const JVM_FOLDER = /^(?:(.+?)\/)?src\/([^/]+)\/(?:java|kotlin|scala|groovy|resources)\/(.+)$/;

  function dirOf(path) {
    const slash = path.lastIndexOf("/");
    return slash < 0 ? "/" : path.slice(0, slash);
  }

  function jvmFolderOf(dir) {
    const match = JVM_FOLDER.exec(dir);
    return match ? { module: match[1] ?? "", set: match[2], segments: match[3].split("/") } : null;
  }

  // How many leading segments every list shares, leaving each list at least one segment.
  function sharedSegments(lists) {
    const cap = Math.min(...lists.map((segments) => segments.length)) - 1;
    let count = 0;
    while (count < cap && lists.every((segments) => segments[count] === lists[0][count])) count++;
    return count;
  }

  function jvmLabel(folder, segments, withModule) {
    const head = [withModule ? folder.module : "", folder.set === "main" ? "" : folder.set].filter(Boolean).join(" ");
    return head ? `${head} \u203a ${segments.join("/")}` : segments.join("/");
  }

  // The layer's files grouped by folder, folders in the order of their first hunk, each as { dir, label, files }.
  // `reviewPaths` is every path in the review. A JVM source folder (<module>/src/<set>/<lang>/<package>) is labelled
  // by module, source set and package, minus the package prefix all the review's JVM folders share. A layer of
  // several folders drops what they all share: the module when every folder is JVM in one module, otherwise the
  // leading directories common to non-JVM folders when none is JVM.
  function folderGroups(chunk, reviewPaths) {
    const groups = new Map();
    for (const file of filesOf(chunk)) {
      const dir = dirOf(file.path);
      if (!groups.has(dir)) groups.set(dir, { dir, label: dir, files: [] });
      groups.get(dir).files.push(file);
    }
    const jvmPackages = [...new Set(reviewPaths.map(dirOf))].map((dir) => jvmFolderOf(dir)?.segments).filter(Boolean);
    const prefix = jvmPackages.length ? sharedSegments(jvmPackages) : 0;
    const folders = [...groups.values()].map((group) => ({ group, jvm: jvmFolderOf(group.dir) }));
    const several = folders.length > 1;
    const allJvm = folders.every(({ jvm }) => jvm);
    const withModule = !(several && allJvm && new Set(folders.map(({ jvm }) => jvm.module)).size === 1);
    for (const { group, jvm } of folders) {
      if (jvm) group.label = jvmLabel(jvm, jvm.segments.slice(prefix), withModule);
    }
    if (several && folders.every(({ jvm }) => !jvm)) {
      const lists = folders.map(({ group }) => (group.dir === "/" ? [] : group.dir.split("/")));
      const drop = sharedSegments(lists);
      for (const [index, { group }] of folders.entries()) group.label = lists[index].slice(drop).join("/") || group.dir;
    }
    return [...groups.values()];
  }

  // The layer's files under one muted line per folder (its full directory as the tooltip), each file a button with its
  // full path as the tooltip. A file the Tests control keeps out of view is struck through, and so is a folder line
  // whose files all are.
  function chunkFiles(chunk, state, handlers) {
    const list = make("div", "prf-chunk-files");
    const reviewPaths = state.chunks.flatMap((other) => other.hunks.map((hunk) => hunk.path));
    for (const { dir, label, files } of folderGroups(chunk, reviewPaths)) {
      const group = make("div", "prf-chunk-group");
      const folder = make("div", "prf-chunk-folder", label);
      folder.title = dir;
      const excluded = files.map(({ path }) => isExcludedByTests(state, path));
      const buttons = files.map(({ path }, index) => {
        const file = button("prf-chunk-file", undefined, () => handlers.onSelectFileInChunk(chunk.i, path));
        file.classList.toggle("prf-dimmed", excluded[index]);
        file.title = path;
        file.append(make("span", "prf-chunk-file-name", baseName(path)));
        return file;
      });
      folder.classList.toggle("prf-dimmed", excluded.every(Boolean));
      group.append(folder, ...buttons);
      list.append(group);
    }
    return list;
  }

  // One row per layer, on one line: its number and title, then at the end its risk and a tick once it is judged. The
  // current layer is marked and, as the only one, lists the files it touches under its title.
  function chunkRow(chunk, state, handlers) {
    const current = chunk.i === state.selectedChunk;
    const main = button("prf-head-main", undefined, () => handlers.onSelectChunk(chunk.i));
    if (current) main.setAttribute("aria-current", "step");
    const meta = make("span", "prf-chunk-meta");
    if (chunk.risk) meta.append(riskPill(chunk.risk));
    if (state.judged?.has(chunk.i)) {
      const tick = make("span", "prf-judged-tick");
      tick.title = "Judged";
      tick.append(filledIcon(CHECK_ICON, 16, "prf-judged-icon"));
      meta.append(tick);
    }
    main.append(make("span", "prf-num", String(chunk.i)), make("span", "prf-name", chunk.title), meta);
    const header = make("div", "prf-head");
    header.append(main);
    const element = make("section", "prf-group prf-chunk");
    element.classList.toggle("prf-selected", current);
    element.dataset.chunk = String(chunk.i);
    element.append(header);
    if (current) element.append(chunkFiles(chunk, state, handlers));
    return element;
  }

  // The line counting the layers and how many are judged.
  function chunksLede(state) {
    const judged = state.chunks.filter((chunk) => state.judged?.has(chunk.i)).length;
    return make("p", "prf-lede", `${state.chunks.length} ${state.chunks.length === 1 ? "layer" : "layers"} \u00b7 ${judged} judged`);
  }

  // The layers in order.
  function chunkList(state, handlers) {
    const list = make("div", "prf-groups");
    for (const chunk of state.chunks) list.append(chunkRow(chunk, state, handlers));
    return list;
  }

  // The card shown above a layer's first line in the diff: which layer of how many this is and its title, its risk and
  // why, what it summarises, the layers it builds on (each a button that opens that layer), and, in a column beside
  // them, buttons to the previous and the next layer, each in a slot that is kept, hidden, when there is no such
  // layer, with a Judged checkbox under them. `onGo(i)` opens a layer by its number, `onJudged(i, checked)` records the checkbox, and `judged`
  // is whether the layer is judged already.
  function chunkCallout(chunk, chunks, onGo, onJudged, judged = false) {
    const card = make("div", "prf-callout");
    const main = make("div", "prf-callout-main");
    const head = make("div", "prf-callout-head");
    head.append(
      outlineIcon(ROUTE_ICON, 18, "prf-callout-icon"),
      make("strong", "prf-callout-where", `Layer ${chunk.i} of ${chunks.length}`),
      outlineIcon(CHEVRON_ICON, 14, "prf-callout-sep"),
      make("span", "prf-callout-name", chunk.title),
    );
    main.append(head);
    if (chunk.risk) {
      const risk = make("div", "prf-callout-risk");
      risk.append(riskPill(chunk.risk));
      if (chunk.risk_reason) {
        const reason = make("span", "prf-callout-reason-text");
        reason.append(...messageNodes(chunk.risk_reason));
        risk.append(reason);
      }
      main.append(risk);
    }
    if (chunk.summary) {
      const summary = make("div", "prf-callout-reason");
      summary.append(...messageNodes(chunk.summary));
      main.append(summary);
    }
    if (chunk.depends_on?.length) {
      const needs = make("div", "prf-callout-needs");
      needs.append("Needs ");
      chunk.depends_on.forEach((n, index) => {
        if (index > 0) needs.append(", ");
        needs.append(button("prf-callout-need", String(n), () => onGo(n)));
      });
      main.append(needs);
    }
    const label = make("label", "prf-callout-judged");
    const box = make("input");
    box.type = "checkbox";
    box.checked = judged;
    box.addEventListener("change", () => onJudged(chunk.i, box.checked));
    label.append(box, make("span", undefined, "Judged"));
    card.append(main);

    const nav = make("div", "prf-callout-nav");
    const at = chunks.findIndex((other) => other.i === chunk.i);
    const previous = chunks[at - 1];
    const following = chunks[at + 1];
    const back = button(previous ? "prf-callout-prev" : "prf-callout-prev prf-callout-empty", "\u2191 Previous", () => previous && onGo(previous.i));
    if (previous) back.title = previous.title;
    else inertSlot(back);
    const next = button(following ? "prf-callout-next" : "prf-callout-next prf-callout-empty", "Next \u2193", () => following && onGo(following.i));
    if (following) next.title = following.title;
    else inertSlot(next);
    nav.append(back, next, label);
    card.append(nav);
    return card;
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

  // state: { mode: "review" | "chunks" | "github", stops, selectedStop, chunks, selectedChunk, judged, pageSha, note, chips,
  // fileSet, tests, testsMode }, `judged` being a Set of layer numbers, `tests` the PR's test files' paths and `testsMode`
  // "all" | "hide" | "only", which of the PR's files the Tests control shows in "Files" and "Layers"
  // handlers: onMode(mode), onSelectStop(i), onSelectChunk(i), onSelectFileInChunk(i, path), onFileSet(id), onTestsMode(mode)
  function render(review, state, handlers) {
    const mount = mountPoint();
    if (!mount) return;
    const { root, host } = mount;
    const reviewMode = state.mode === "review";
    const listMode = reviewMode || state.mode === "chunks";
    const scrolled = root.querySelector(".prf-groups")?.scrollTop ?? 0;
    root.classList.toggle("prf-review", listMode);
    host.classList.toggle(HOST_HIDDEN, listMode);

    root.replaceChildren(bar(state, handlers));
    const filterLine = filters(state, handlers);
    if (filterLine) root.append(filterLine);
    const stale = staleMessage(review, state.pageSha);
    if (stale) root.append(make("p", "prf-banner", stale));
    if (state.note) root.append(make("p", "prf-banner", state.note));
    if (listMode) {
      root.append(reviewMode ? stopList(state, handlers) : chunkList(state, handlers));
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

  // Scrolls the list, and only it, so the row matching `selector` shows. Smooth unless the user prefers reduced motion.
  function revealRow(selector) {
    const list = document.querySelector(`#${ROOT_ID} .prf-groups`);
    const element = list?.querySelector(selector);
    if (!element) return;
    const base = list.getBoundingClientRect().top - list.scrollTop;
    const row = element.getBoundingClientRect();
    const target = revealTarget({ scrollTop: list.scrollTop, height: list.clientHeight, top: row.top - base, bottom: row.bottom - base });
    if (target === null) return;
    const reduced = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    list.scrollTo({ top: target, behavior: reduced ? "instant" : "smooth" });
  }

  function revealStop(i) {
    revealRow(`.prf-stop[data-stop="${i}"]`);
  }

  function revealChunk(i) {
    revealRow(`.prf-chunk[data-chunk="${i}"]`);
  }

  function remove() {
    document.getElementById(ROOT_ID)?.remove();
    ns.page.treeHost()?.classList.remove(HOST_HIDDEN);
  }

  function owns(node) {
    const element = node?.nodeType === 1 ? node : node?.parentElement;
    return Boolean(element?.closest(`#${ROOT_ID}`));
  }

  ns.tree = { render, renderServerNote, renderGenerateLine, revealStop, revealChunk, revealTarget, stopsOf, chunksOf, filesOf, folderGroups, fileChips, fileSetOf, testsOf, stopCallout, chunkCallout, bar, filters, stopList, chunkRow, chunkList, remove, owns, staleMessage };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.tree;
