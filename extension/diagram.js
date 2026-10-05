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

  const MIN_SCALE = 0.25;
  const MAX_SCALE = 4;
  const ZOOM_STEP = 1.25;
  const FIT_MARGIN = 8;
  const DRAG_THRESHOLD = 4;
  const WHEEL_ZOOM_RATE = 0.0025;
  const WHEEL_ZOOM_CAP = 100;
  const GLIDE_MS = 200;
  const FALLBACK_SIZE = { w: 300, h: 200 };
  const LINE_PIXELS = 16;
  const PAGE_PIXELS = 400;

  function clampScale(scale) {
    return Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale));
  }

  // The diagram's natural size in its own units: its viewBox, else absolute width and height attributes.
  function contentSize(viewBox, width, height) {
    const box = String(viewBox ?? "").trim().split(/[\s,]+/).map(Number);
    if (box.length === 4 && box.every(Number.isFinite) && box[2] > 0 && box[3] > 0) return { w: box[2], h: box[3] };
    const w = /^\s*[\d.]+(px)?\s*$/.test(width ?? "") ? parseFloat(width) : NaN;
    const h = /^\s*[\d.]+(px)?\s*$/.test(height ?? "") ? parseFloat(height) : NaN;
    return w > 0 && h > 0 ? { w, h } : { ...FALLBACK_SIZE };
  }

  // The view (scale, plus the translation of the diagram's top-left corner in viewport pixels) that fits the
  // diagram's width to the viewport with a margin, top-aligned and horizontally centred.
  function fitView(content, viewport, margin = FIT_MARGIN) {
    const scale = clampScale((viewport.w - 2 * margin) / content.w);
    return { scale, x: (viewport.w - content.w * scale) / 2, y: margin };
  }

  // The view after zooming to `scale` with the viewport point (px, py) staying put.
  function zoomAround(view, scale, px, py) {
    const next = clampScale(scale);
    const ratio = next / view.scale;
    return { scale: next, x: px - (px - view.x) * ratio, y: py - (py - view.y) * ratio };
  }

  // One zoom-button step: a quarter larger (direction > 0) or the reverse.
  function stepScale(scale, direction) {
    return clampScale(direction > 0 ? scale * ZOOM_STEP : scale / ZOOM_STEP);
  }

  // Keeps part of the diagram visible: a diagram edge can be panned to the middle of the viewport, no further. A
  // diagram shorter than half the viewport still rests at the fit margin.
  function clampView(view, content, viewport) {
    const clampAxis = (offset, size, span) => Math.max(Math.min(span / 2 - size, FIT_MARGIN), Math.min(span / 2, offset));
    return {
      scale: view.scale,
      x: clampAxis(view.x, content.w * view.scale, viewport.w),
      y: clampAxis(view.y, content.h * view.scale, viewport.h),
    };
  }

  // The view that centres `rect` (a box's bounds in diagram units) in the viewport. The zoom stays unless the rect
  // is larger than the viewport inside the fit margin, in which case it drops to the largest zoom at which the rect
  // fits. The result keeps clampView's limits.
  function centerView(view, rect, content, viewport, margin = FIT_MARGIN) {
    const fits = Math.min((viewport.w - 2 * margin) / rect.w, (viewport.h - 2 * margin) / rect.h);
    const scale = clampScale(Math.min(view.scale, fits));
    return clampView(
      { scale, x: viewport.w / 2 - (rect.x + rect.w / 2) * scale, y: viewport.h / 2 - (rect.y + rect.h / 2) * scale },
      content,
      viewport,
    );
  }

  function wheelUnit(event) {
    return event.deltaMode === 1 ? LINE_PIXELS : event.deltaMode === 2 ? PAGE_PIXELS : 1;
  }

  // The scale multiplier for a wheel event: smooth for a trackpad's small deltas (a pinch arrives as ctrl + wheel)
  // and bounded for a mouse wheel's notches.
  function wheelZoomFactor(event) {
    const delta = Math.max(-WHEEL_ZOOM_CAP, Math.min(WHEEL_ZOOM_CAP, event.deltaY * wheelUnit(event)));
    return Math.exp(-delta * WHEEL_ZOOM_RATE);
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
  let canvas = null;
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

  const LEVEL_CLASSES = ":not(.lv-verify):not(.lv-read):not(.lv-skim)";
  const PLAIN = `g.node:not(.save):not(.context):not(.skim)${LEVEL_CLASSES}`;
  const LANES = 'g.cluster:not([id$="-also"])';
  const SHAPES = "rect, polygon, path, circle, ellipse";
  const LEGEND_LABELS = {
    changed: "Changed step",
    verify: "Verify",
    read: "Read",
    skim: "Skim",
    save: "Writes data",
    context: "Unchanged context",
    selected: "Selected chunk",
    layers: "Columns are code layers",
  };

  // The legend entries a diagram needs, given how many boxes of each style it has: only the styles it uses, plus
  // the extension's own "selected chunk" state, and a note when the boxes are grouped in lanes.
  function legendKinds({ plain, save, context, verify = 0, read = 0, skim = 0, clusters }) {
    return [
      ...(plain > 0 ? ["changed"] : []),
      ...(verify > 0 ? ["verify"] : []),
      ...(read > 0 ? ["read"] : []),
      ...(skim > 0 ? ["skim"] : []),
      ...(save > 0 ? ["save"] : []),
      ...(context > 0 ? ["context"] : []),
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
      return { fill: style.fill, stroke: style.stroke, width: parseFloat(style.strokeWidth), dashed: style.strokeDasharray !== "none" };
    };
    const swatches = {
      changed: look(PLAIN),
      verify: look("g.node.lv-verify"),
      read: look("g.node.lv-read"),
      skim: look("g.node.lv-skim") ?? look("g.node.skim"),
      save: look("g.node.save"),
      context: look("g.node.context"),
    };
    const counts = {
      plain: copy.querySelectorAll(PLAIN).length,
      verify: copy.querySelectorAll("g.node.lv-verify").length,
      read: copy.querySelectorAll("g.node.lv-read").length,
      skim: copy.querySelectorAll("g.node.lv-skim, g.node.skim").length,
      save: copy.querySelectorAll("g.node.save").length,
      context: copy.querySelectorAll("g.node.context").length,
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
          if (look.width > 0) swatch.style.borderWidth = `${look.width}px`;
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

  // The pan-and-zoom canvas: `svg` is absolutely positioned in `viewport` and moved by a translate + scale
  // transform. The view is a { scale, x, y } in viewport pixels; `fitted` keeps it matched to the viewport width
  // until the user zooms or pans. Any wheel event, pinch included, zooms around the pointer and never scrolls the
  // page, a drag anywhere pans, and a press that stays under DRAG_THRESHOLD is a click on the box under it.
  // `centerOn` pans to a box list or a rect with a short glide, which any wheel or press interrupts; while the
  // viewport is hidden (the panel is collapsed) it remembers the latest target and centres on it once the viewport
  // has a size again.
  function createCanvas(viewport, svg, { onNode, onView }) {
    const content = contentSize(svg.getAttribute("viewBox"), svg.getAttribute("width"), svg.getAttribute("height"));
    svg.style.width = `${content.w}px`;
    svg.style.height = `${content.h}px`;
    let view = { scale: 1, x: 0, y: 0 };
    let fitted = true;
    let drag = null;
    let glideFrame = null;
    let pending = null;

    const size = () => ({ w: viewport.clientWidth, h: viewport.clientHeight });

    function paint() {
      svg.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.scale})`;
      onView(view);
    }

    function show(next, isFit) {
      view = clampView(next, content, size());
      fitted = isFit;
      paint();
    }

    function fit() {
      if (size().w <= 0) return;
      show(fitView(content, size()), true);
    }

    function zoomTo(scale, px = size().w / 2, py = size().h / 2) {
      show(zoomAround(view, scale, px, py), false);
    }

    function cancelGlide() {
      if (glideFrame === null) return;
      cancelAnimationFrame(glideFrame);
      glideFrame = null;
    }

    function glide(target) {
      cancelGlide();
      if (!globalThis.requestAnimationFrame || globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
        show(target, false);
        return;
      }
      const from = view;
      let start = null;
      const step = (now) => {
        start ??= now;
        const progress = Math.min(1, (now - start) / GLIDE_MS);
        const eased = 1 - (1 - progress) ** 3;
        const mix = (a, b) => a + (b - a) * eased;
        show({ scale: mix(from.scale, target.scale), x: mix(from.x, target.x), y: mix(from.y, target.y) }, false);
        glideFrame = progress < 1 ? requestAnimationFrame(step) : null;
      };
      glideFrame = requestAnimationFrame(step);
    }

    // The bounds of the listed boxes in diagram units, or null when none is drawn.
    function boundsOf(ids) {
      const wanted = new Set(ids);
      const origin = svg.getBoundingClientRect();
      let box = null;
      for (const group of svg.querySelectorAll("g.node")) {
        if (!wanted.has(nodeIdOf(group.id))) continue;
        const r = group.getBoundingClientRect();
        box = box
          ? { left: Math.min(box.left, r.left), top: Math.min(box.top, r.top), right: Math.max(box.right, r.right), bottom: Math.max(box.bottom, r.bottom) }
          : { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
      }
      if (!box) return null;
      return {
        x: (box.left - origin.left) / view.scale,
        y: (box.top - origin.top) / view.scale,
        w: (box.right - box.left) / view.scale,
        h: (box.bottom - box.top) / view.scale,
      };
    }

    // `target` is a list of box ids or a { x, y, w, h } rect in diagram units. An empty list leaves the canvas as it
    // is, and drops any target waiting for the viewport to be shown.
    function centerOn(target) {
      const ids = Array.isArray(target) ? target : null;
      if (ids?.length === 0) {
        pending = null;
        return;
      }
      if (size().w <= 0) {
        pending = target;
        return;
      }
      pending = null;
      const rect = ids ? boundsOf(ids) : target;
      if (rect) glide(centerView(view, rect, content, size()));
    }

    function pointInViewport(event) {
      const rect = viewport.getBoundingClientRect();
      return { x: event.clientX - rect.left - viewport.clientLeft, y: event.clientY - rect.top - viewport.clientTop };
    }

    function onWheel(event) {
      event.preventDefault();
      cancelGlide();
      const { x, y } = pointInViewport(event);
      zoomTo(view.scale * wheelZoomFactor(event), x, y);
    }

    function endDrag(event, activate) {
      if (!drag || drag.id !== event.pointerId) return;
      const finished = drag;
      drag = null;
      viewport.classList.remove("prd-panning");
      if (activate && !finished.moved && finished.nodeId) onNode(finished.nodeId);
    }

    function onPointerDown(event) {
      if (event.button !== 0) return;
      cancelGlide();
      const group = event.target.closest?.("g.node");
      const nodeId = group && !group.classList.contains("context") ? nodeIdOf(group.id) : null;
      try {
        viewport.setPointerCapture(event.pointerId);
      } catch {
        // Without capture the drag still works while the pointer stays over the viewport.
      }
      drag = { id: event.pointerId, x: event.clientX, y: event.clientY, from: view, moved: false, nodeId };
      event.preventDefault();
    }

    function onPointerMove(event) {
      if (!drag || drag.id !== event.pointerId) return;
      const dx = event.clientX - drag.x;
      const dy = event.clientY - drag.y;
      if (!drag.moved && Math.hypot(dx, dy) > DRAG_THRESHOLD) {
        drag.moved = true;
        viewport.classList.add("prd-panning");
      }
      if (drag.moved) show({ ...drag.from, x: drag.from.x + dx, y: drag.from.y + dy }, false);
    }

    const resizeObserver = globalThis.ResizeObserver
      ? new ResizeObserver(() => {
          if (size().w <= 0) return;
          cancelGlide();
          if (fitted) fit();
          else show(view, false);
          if (pending) centerOn(pending);
        })
      : null;
    resizeObserver?.observe(viewport);

    viewport.addEventListener("wheel", onWheel, { passive: false });
    viewport.addEventListener("pointerdown", onPointerDown);
    viewport.addEventListener("pointermove", onPointerMove);
    viewport.addEventListener("pointerup", (event) => endDrag(event, true));
    viewport.addEventListener("pointercancel", (event) => endDrag(event, false));
    paint();

    return {
      fit,
      actualSize: () => zoomTo(1),
      zoomIn: () => zoomTo(stepScale(view.scale, 1)),
      zoomOut: () => zoomTo(stepScale(view.scale, -1)),
      centerOn,
      destroy() {
        cancelGlide();
        resizeObserver?.disconnect();
      },
    };
  }

  function zoomControls() {
    const group = make("div", "prd-zoom");
    const button = (className, text, label) => {
      const element = make("button", className, text);
      element.type = "button";
      element.setAttribute("aria-label", label);
      element.title = label;
      return element;
    };
    const out = button("prd-zoom-out", "−", "Zoom out");
    const percent = button("prd-zoom-percent", "100%", "Reset to 100%");
    const zoomIn = button("prd-zoom-in", "+", "Zoom in");
    const fit = button("prd-zoom-fit", "Fit", "Fit the diagram to the pane width");
    const reset = button("prd-zoom-reset", "↺", "Reset");
    group.append(out, percent, zoomIn, fit, reset);
    return { group, out, percent, zoomIn, fit, reset };
  }

  // The Reset button's click: fits the canvas to the pane, then lets the host put the rest of the review back.
  function resetAction(canvasOf, handlers) {
    return () => {
      canvasOf().fit();
      handlers.onReset?.();
    };
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
    const zoom = zoomControls();
    const header = make("div", "prd-header");
    header.append(make("span", "prd-title", "Change diagram"), make("span", "prd-rail-label", "Diagram"), zoom.group, chevron);

    const cardElement = make("div", "prd-card prd-viewport");
    cardElement.append(svg);
    canvas = createCanvas(cardElement, svg, {
      onNode: handlers.onNode,
      onView: ({ scale }) => {
        zoom.percent.textContent = `${Math.round(scale * 100)}%`;
        zoom.out.disabled = scale <= MIN_SCALE;
        zoom.zoomIn.disabled = scale >= MAX_SCALE;
      },
    });
    zoom.out.addEventListener("click", () => canvas.zoomOut());
    zoom.zoomIn.addEventListener("click", () => canvas.zoomIn());
    zoom.percent.addEventListener("click", () => canvas.actualSize());
    zoom.fit.addEventListener("click", () => canvas.fit());
    zoom.reset.addEventListener("click", resetAction(() => canvas, handlers));
    panel.classList.toggle("prd-collapsed", collapsed);
    panel.append(resizeHandle(panel), header, cardElement, buildLegend(legend));
    setWidth(panel, panelWidth);
    return panel;
  }

  // Docks the diagram as the leftmost pane, right before the host's file pane in its own flex row, so the file
  // pane and the diff column narrow to make room. Safe to call repeatedly: it re-mounts only when the panel is
  // gone. handlers: { onNode(nodeId), onReset() }; the Reset button refits the canvas and then calls onReset.
  function render(svgText, handlers) {
    const host = ns.page.diagramHost();
    if (!host) return;
    if (!root?.isConnected || shownText !== svgText) {
      const svg = parseSvg(svgText);
      if (!svg) return;
      canvas?.destroy();
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

  // Pans the canvas so the boxes are centred in the pane (see createCanvas). Does nothing without a diagram.
  function centerOn(nodeIds) {
    canvas?.centerOn(nodeIds);
  }

  // The title of a box: the bold first line of its label, without the box number; "" for an unknown box or one the
  // diagram draws without a title.
  function titleOf(nodeId) {
    return found?.nodes.get(nodeId)?.querySelector(".nodeLabel .t")?.textContent.trim() ?? "";
  }

  function remove() {
    canvas?.destroy();
    root?.remove();
    root = card = found = shownText = canvas = null;
    emphasis = null;
    activeNode = null;
  }

  function owns(node) {
    const element = node?.nodeType === 1 ? node : node?.parentElement;
    return Boolean(element?.closest(`#${ROOT_ID}`));
  }

  readStoredWidth();

  ns.diagram = { resetAction, zoomControls, render, emphasize, setActive, centerOn, titleOf, pulse, remove, owns, nodeIdOf, edgeEnds, unsafeAttribute, clampWidth, legendKinds, clampScale, contentSize, fitView, zoomAround, stepScale, clampView, centerView, wheelZoomFactor, createCanvas };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.diagram;
