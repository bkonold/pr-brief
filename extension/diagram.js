(() => {
  const ns = (globalThis.prFocus ??= {});
  const ROOT_ID = "pr-focus-diagram";
  const COLLAPSED_KEY = "prFocus:diagramCollapsed";
  const ON = "prd-on";
  const OFF = "prd-off";
  const NODE_ID = /flowchart-(.+)-\d+$/;
  const EDGE_ID = /^L_(.+)_\d+$/;
  const WIDTH_KEY = "diagramWidth";
  const DEFAULT_WIDTH = 280;
  const MIN_WIDTH = 220;
  const MAX_VIEWPORT_SHARE = 0.65;

  // A usable panel width for this viewport: at least MIN_WIDTH, at most MAX_VIEWPORT_SHARE of the viewport.
  function clampWidth(width, viewportWidth) {
    if (!Number.isFinite(width)) return DEFAULT_WIDTH;
    return Math.round(Math.max(MIN_WIDTH, Math.min(width, viewportWidth * MAX_VIEWPORT_SHARE)));
  }

  // Mermaid names a node's group `<svg id>-flowchart-<nodeId>-<index>`.
  function nodeIdOf(elementId) {
    return NODE_ID.exec(elementId ?? "")?.[1] ?? null;
  }

  // Mermaid names an edge `L_<from>_<to>_<index>`. Node ids may contain underscores, so the ends are found by
  // matching known node ids.
  function edgeEnds(edgeId, nodeIds) {
    const rest = EDGE_ID.exec(edgeId ?? "")?.[1];
    if (!rest) return null;
    for (const from of nodeIds) {
      const to = rest.startsWith(`${from}_`) ? rest.slice(from.length + 1) : null;
      if (to !== null && nodeIds.has(to)) return [from, to];
    }
    return null;
  }

  function unsafeAttribute(name, value) {
    return /^on/i.test(name) || (/(^|:)href$/i.test(name) && /^\s*javascript:/i.test(value));
  }

  // The SVG as an element of this document, without scripts, event handlers or javascript: links; null when it
  // doesn't parse.
  function parseSvg(svgText) {
    const parsed = new DOMParser().parseFromString(svgText, "image/svg+xml");
    const root = parsed.documentElement;
    if (root.localName !== "svg" || parsed.querySelector("parsererror")) return null;
    for (const script of root.querySelectorAll("script")) script.remove();
    for (const element of [root, ...root.querySelectorAll("*")]) {
      for (const { name, value } of [...element.attributes]) {
        if (unsafeAttribute(name, value)) element.removeAttribute(name);
      }
    }
    return document.importNode(root, true);
  }

  // The svg's emphasizable parts: node groups by id, and edges with the nodes they join.
  function index(svg) {
    const nodes = new Map();
    for (const group of svg.querySelectorAll("g.node")) {
      const id = nodeIdOf(group.id);
      if (id) nodes.set(id, group);
    }
    const ids = new Set(nodes.keys());
    const edges = [];
    for (const element of svg.querySelectorAll("[data-id]")) {
      const ends = edgeEnds(element.getAttribute("data-id"), ids);
      if (ends) edges.push({ element: element.localName === "path" ? element : (element.closest(".edgeLabel") ?? element), ends });
    }
    return { nodes, edges };
  }

  // null restores; an empty list dims the whole diagram a little, for a chunk that isn't on it.
  function applyEmphasis(card, found, ids) {
    card.classList.toggle("prd-none", Array.isArray(ids) && ids.length === 0);
    const active = new Set(ids ?? []);
    const mark = (element, on) => {
      element.classList.toggle(ON, ids !== null && on);
      element.classList.toggle(OFF, ids !== null && ids.length > 0 && !on);
    };
    for (const [id, group] of found.nodes) mark(group, active.has(id));
    for (const { element, ends } of found.edges) mark(element, ends.every((end) => active.has(end)));
  }

  const SVG_NS = "http://www.w3.org/2000/svg";
  const ACTIVE = "prd-active";
  const GEOMETRY = ["x", "y", "width", "height", "rx", "ry"];

  let root = null;
  let card = null;
  let found = null;
  let shownText = null;
  let emphasis = null;
  let activeNode = null;
  let overlay = null;
  let closeOverlayOnEscape = null;
  let panelWidth = DEFAULT_WIDTH;
  let legend = [];

  // The remembered width is read once when the script loads, so it is usually known before the first render.
  function readStoredWidth() {
    if (!ns.alive?.() || !globalThis.chrome?.storage?.local) return;
    chrome.storage.local
      .get(WIDTH_KEY)
      .then((stored) => {
        if (stored[WIDTH_KEY] === undefined) return;
        panelWidth = clampWidth(Number(stored[WIDTH_KEY]), innerWidth);
        root?.style.setProperty("--prd-width", `${panelWidth}px`);
      })
      .catch(() => {});
  }

  function storeWidth(width) {
    if (!ns.alive?.() || !globalThis.chrome?.storage?.local) return;
    chrome.storage.local.set({ [WIDTH_KEY]: width }).catch(() => {});
  }

  function setWidth(panel, width) {
    panelWidth = clampWidth(width, innerWidth);
    panel.style.setProperty("--prd-width", `${panelWidth}px`);
  }

  // Dragging the right edge rightwards widens the panel, and the file pane and diff column, its flex siblings,
  // narrow to match.
  function resizeHandle(panel) {
    const handle = make("div", "prd-handle");
    handle.title = "Drag to resize; double-click to reset";
    let drag = null;
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      handle.setPointerCapture(event.pointerId);
      drag = { x: event.clientX, width: panel.getBoundingClientRect().width };
      panel.classList.add("prd-dragging");
      event.preventDefault();
    });
    handle.addEventListener("pointermove", (event) => {
      if (drag) setWidth(panel, drag.width + event.clientX - drag.x);
    });
    const end = () => {
      if (!drag) return;
      drag = null;
      panel.classList.remove("prd-dragging");
      storeWidth(panelWidth);
    };
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
    handle.addEventListener("dblclick", () => {
      setWidth(panel, DEFAULT_WIDTH);
      storeWidth(panelWidth);
    });
    return handle;
  }

  const PLAIN = "g.node:not(.save):not(.context):not(.skim)";
  const LANES = 'g.cluster:not([id$="-also"])';
  const SHAPES = "rect, polygon, path, circle, ellipse";
  const LEGEND_LABELS = {
    changed: "Changed step",
    save: "Writes data",
    context: "Unchanged context",
    skim: "Skim, off the path",
    selected: "Selected chunk",
    layers: "Columns are code layers",
  };

  // The legend entries a diagram needs, given how many boxes of each style it has: only the styles it uses, plus
  // the extension's own "selected chunk" state, and a note when the boxes are grouped in lanes.
  function legendKinds({ plain, save, context, skim = 0, clusters }) {
    return [
      ...(plain > 0 ? ["changed"] : []),
      ...(save > 0 ? ["save"] : []),
      ...(context > 0 ? ["context"] : []),
      ...(skim > 0 ? ["skim"] : []),
      "selected",
      ...(clusters > 0 ? ["layers"] : []),
    ];
  }

  // The look of one kind of box as the page draws it, read from a throwaway copy of the diagram so the live
  // boxes' emphasis doesn't leak into the swatch.
  function sampleSwatches(svg) {
    const measure = make("div", "prd-card prd-measure");
    const copy = svg.cloneNode(true);
    for (const element of copy.querySelectorAll(".prd-on, .prd-off")) element.classList.remove("prd-on", "prd-off");
    measure.append(copy);
    document.body.append(measure);
    const look = (selector) => {
      const shape = copy.querySelector(`${selector} > :is(${SHAPES})`);
      if (!shape) return null;
      const style = getComputedStyle(shape);
      return { fill: style.fill, stroke: style.stroke, dashed: style.strokeDasharray !== "none" };
    };
    const swatches = { changed: look(PLAIN), save: look("g.node.save"), context: look("g.node.context"), skim: look("g.node.skim") };
    const counts = {
      plain: copy.querySelectorAll(PLAIN).length,
      save: copy.querySelectorAll("g.node.save").length,
      context: copy.querySelectorAll("g.node.context").length,
      skim: copy.querySelectorAll("g.node.skim").length,
      clusters: copy.querySelectorAll(LANES).length,
    };
    measure.remove();
    return legendKinds(counts).map((kind) => ({ kind, label: LEGEND_LABELS[kind], look: swatches[kind] ?? null }));
  }

  function buildLegend(entries) {
    const list = make("ul", "prd-legend");
    for (const { kind, label, look } of entries) {
      const item = make("li", undefined, label);
      if (kind !== "layers") {
        const swatch = make("span", `prd-swatch prd-swatch-${kind}`);
        if (look) {
          swatch.style.background = look.fill;
          swatch.style.borderColor = look.stroke;
          swatch.style.borderStyle = look.dashed ? "dashed" : "solid";
        }
        item.prepend(swatch);
      }
      list.append(item);
    }
    return list;
  }

  function readCollapsed() {
    try {
      return sessionStorage.getItem(COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  }

  function writeCollapsed(collapsed) {
    try {
      sessionStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      // The state just isn't remembered.
    }
  }

  function make(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function closeOverlay() {
    overlay?.remove();
    overlay = null;
    if (closeOverlayOnEscape) document.removeEventListener("keydown", closeOverlayOnEscape, true);
    closeOverlayOnEscape = null;
  }

  function openOverlay() {
    closeOverlay();
    overlay = make("div", "prd-overlay");
    overlay.append(make("div", "prd-overlay-card"));
    overlay.firstChild.append(card.querySelector("svg").cloneNode(true), buildLegend(legend));
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) closeOverlay();
    });
    closeOverlayOnEscape = (event) => {
      if (event.key === "Escape") closeOverlay();
    };
    document.addEventListener("keydown", closeOverlayOnEscape, true);
    document.body.append(overlay);
  }

  function build(svg, handlers, collapsed) {
    const panel = make("aside", "prd-panel");
    panel.id = ROOT_ID;
    const chevron = make("button", "prd-chevron");
    chevron.type = "button";
    const showToggle = (isCollapsed) => {
      chevron.textContent = isCollapsed ? "›" : "‹";
      chevron.setAttribute("aria-expanded", String(!isCollapsed));
      chevron.setAttribute("aria-label", isCollapsed ? "Expand change diagram" : "Collapse change diagram");
    };
    showToggle(collapsed);
    chevron.addEventListener("click", () => {
      const next = !panel.classList.contains("prd-collapsed");
      writeCollapsed(next);
      panel.classList.toggle("prd-collapsed", next);
      showToggle(next);
    });
    const header = make("div", "prd-header");
    header.append(make("span", "prd-title", "Change diagram"), make("span", "prd-rail-label", "Diagram"), chevron);

    const cardElement = make("div", "prd-card");
    cardElement.title = "Click to enlarge";
    cardElement.append(svg);
    cardElement.addEventListener("click", (event) => {
      const group = event.target.closest?.("g.node");
      const nodeId = group ? nodeIdOf(group.id) : null;
      if (group?.classList.contains("context")) return;
      if (nodeId) handlers.onNode(nodeId);
      else openOverlay();
    });
    panel.classList.toggle("prd-collapsed", collapsed);
    panel.append(resizeHandle(panel), header, cardElement, buildLegend(legend));
    setWidth(panel, panelWidth);
    return panel;
  }

  // Docks the diagram as the leftmost pane, right before the host's file pane in its own flex row, so the file
  // pane and the diff column narrow to make room. Safe to call repeatedly: it re-mounts only when the panel is
  // gone. handlers: { onNode(nodeId) }.
  function render(svgText, handlers) {
    const host = ns.page.diagramHost();
    if (!host) return;
    if (!root?.isConnected || shownText !== svgText) {
      const svg = parseSvg(svgText);
      if (!svg) return;
      root?.remove();
      legend = sampleSwatches(svg);
      root = build(svg, handlers, readCollapsed());
      card = root.querySelector(".prd-card");
      found = index(svg);
      shownText = svgText;
      applyEmphasis(card, found, emphasis);
      applyActive();
    }
    root.style.top = host.top;
    root.style.setProperty("--prd-top", host.top);
    root.style.order = host.order;
    const anchor = host.pane ?? host.content;
    if (root.nextElementSibling !== anchor) anchor.before(root);
  }

  function emphasize(nodeIds) {
    emphasis = nodeIds ?? null;
    if (card && found) applyEmphasis(card, found, emphasis);
  }

  function applyActive() {
    if (!found) return;
    for (const [id, group] of found.nodes) group.classList.toggle(ACTIVE, id === activeNode);
  }

  // The box clicked last: it keeps a tint, stronger than the chunk highlight, until another is set or null clears it.
  function setActive(nodeId) {
    activeNode = nodeId ?? null;
    applyActive();
  }

  // A short stroke-width swell with an accent tint over the box, drawn as a transient copy of its outline so it
  // isn't overridden by the highlight's own stroke. Skipped under reduced motion.
  function pulse(nodeId) {
    const group = found?.nodes.get(nodeId);
    const shape = group?.querySelector(":scope > rect");
    if (!shape || globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const copy = document.createElementNS(SVG_NS, "rect");
    copy.setAttribute("class", "prd-pulse");
    for (const name of GEOMETRY) if (shape.hasAttribute(name)) copy.setAttribute(name, shape.getAttribute(name));
    copy.addEventListener("animationend", () => copy.remove(), { once: true });
    shape.after(copy);
  }

  function remove() {
    closeOverlay();
    root?.remove();
    root = card = found = shownText = null;
    emphasis = null;
    activeNode = null;
  }

  function owns(node) {
    const element = node?.nodeType === 1 ? node : node?.parentElement;
    return Boolean(element?.closest(`#${ROOT_ID}, .prd-overlay`));
  }

  readStoredWidth();

  ns.diagram = { render, emphasize, setActive, pulse, remove, owns, nodeIdOf, edgeEnds, unsafeAttribute, clampWidth, legendKinds };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.diagram;
