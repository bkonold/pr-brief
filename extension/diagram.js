(() => {
  const ns = (globalThis.prFocus ??= {});
  const ROOT_ID = "pr-focus-diagram";
  const COLLAPSED_KEY = "prFocus:diagramCollapsed";
  const ON = "prd-on";
  const NODE_ID = /flowchart-(.+)-\d+$/;
  const EDGE_ID = /^L_(.+)_\d+$/;
  const DASHED_EDGE = /\bedge-pattern-(?:dotted|dashed)\b/;
  const WIDTH_KEY = "diagramWidth";
  const DEFAULT_VIEWPORT_SHARE = 0.2;
  const MIN_WIDTH = 220;
  const MAX_DEFAULT_SHARE = 0.4;
  const MAX_VIEWPORT_SHARE = 0.65;
  const PANE_CHROME = 14;

  // The width of a panel nobody has resized: a fifth of the viewport, widened to take the diagram's widest box at 1:1 with
  // its focus halo, BOX_MARGIN on each side and the panel's own chrome, so a focused box is centred rather than pushed
  // against the left edge; but never past MAX_DEFAULT_SHARE of the viewport, and at least MIN_WIDTH. `boxWidth` is 0 when
  // the diagram has no box to size by.
  function defaultWidth(viewportWidth, boxWidth = 0) {
    const share = Math.round(viewportWidth * DEFAULT_VIEWPORT_SHARE) || 0;
    const wanted = boxWidth > 0 ? Math.max(share, Math.ceil(boxWidth) + 2 * (HALO_REACH + BOX_MARGIN) + PANE_CHROME) : share;
    const cap = Math.round(viewportWidth * MAX_DEFAULT_SHARE) || 0;
    return Math.max(MIN_WIDTH, Math.min(wanted, cap));
  }

  // The width of the diagram's widest box in diagram units, which are pixels at 1:1; 0 when it draws none.
  function widestBox(svg) {
    let widest = 0;
    for (const group of svg.querySelectorAll("g.node")) {
      const width = Number(group.querySelector(":scope > rect")?.getAttribute("width"));
      if (Number.isFinite(width) && width > widest) widest = width;
    }
    return widest;
  }

  // A usable panel width for this viewport: at least MIN_WIDTH, at most MAX_VIEWPORT_SHARE of the viewport.
  function clampWidth(width, viewportWidth) {
    if (!Number.isFinite(width)) return defaultWidth(viewportWidth);
    return Math.round(Math.max(MIN_WIDTH, Math.min(width, viewportWidth * MAX_VIEWPORT_SHARE)));
  }

  const MIN_SCALE = 0.25;
  const MAX_SCALE = 4;
  const ZOOM_STEP = 1.25;
  const REST_MARGIN = 8;
  const BOX_MARGIN = 16;
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

  // The view a diagram rests in when nothing has been focused or moved: 1:1, centred horizontally when it fits the viewport
  // and else left-aligned, at the top.
  function restingView(content, viewport) {
    return { scale: 1, x: content.w <= viewport.w ? (viewport.w - content.w) / 2 : REST_MARGIN, y: REST_MARGIN };
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
  // diagram shorter than half the viewport still rests at the rest margin.
  function clampView(view, content, viewport) {
    const clampAxis = (offset, size, span) => Math.max(Math.min(span / 2 - size, REST_MARGIN), Math.min(span / 2, offset));
    return {
      scale: view.scale,
      x: clampAxis(view.x, content.w * view.scale, viewport.w),
      y: clampAxis(view.y, content.h * view.scale, viewport.h),
    };
  }

  // The view that follows `rect` (a box's bounds in diagram units, its halo included) without changing the zoom. The rect is
  // centred horizontally, or, when it is wider than the viewport inside `margin`, its left edge sits at the margin. Vertically
  // the view moves only as far as it takes to bring `band` (the bounds of the box and the boxes it is joined to) inside the
  // margin, staying put when the band already is. A band taller than the viewport inside the margin is pinned to the side of
  // it the box is nearer, then moved just enough to keep the box in view. The result keeps clampView's limits.
  function followBoxView(view, rect, band, content, viewport, margin = BOX_MARGIN) {
    const scale = view.scale;
    const centre = rect.y + rect.h / 2;
    const low = viewport.h - margin;
    const bandEnd = band.y + band.h;
    let y = view.y;
    if (band.h * scale > viewport.h - 2 * margin) {
      y = centre - band.y <= bandEnd - centre ? margin - band.y * scale : low - bandEnd * scale;
      const boxBottom = (rect.y + rect.h) * scale + y;
      if (boxBottom > low) y -= boxBottom - low;
      const boxTop = rect.y * scale + y;
      if (boxTop < margin) y += margin - boxTop;
    } else {
      const top = band.y * scale + y;
      const bottom = bandEnd * scale + y;
      if (top < margin) y += margin - top;
      else if (bottom > low) y -= bottom - low;
    }
    const x = rect.w * scale > viewport.w - 2 * margin ? margin - rect.x * scale : viewport.w / 2 - (rect.x + rect.w / 2) * scale;
    return clampView({ scale, x, y }, content, viewport);
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

  // The svg's emphasizable parts: node groups by id, edges with the nodes they join and the arrowheads they point
  // with, and the halos drawn around the emphasized boxes by id.
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
      if (!ends) continue;
      const isPath = element.localName === "path";
      const markers = isPath ? MARKER_ATTRIBUTES.filter((name) => element.hasAttribute(name)).map((name) => [name, element.getAttribute(name)]) : [];
      edges.push({ element: isPath ? element : (element.closest(".edgeLabel") ?? element), ends, markers });
    }
    return { svg, nodes, edges, halos: new Map() };
  }

  // The reference to the accent copy of the marker that `reference` (`url(#id)`) names, made beside it on first use.
  function accentMarker(svg, reference) {
    const id = /^url\(#(.+)\)$/.exec(reference)?.[1];
    const marker = id ? svg.querySelector(`[id="${id}"]`) : null;
    if (!marker) return reference;
    const copyId = `${id}-prd-on`;
    if (!svg.querySelector(`[id="${copyId}"]`)) {
      const copy = marker.cloneNode(true);
      copy.id = copyId;
      for (const path of copy.querySelectorAll("path")) path.style.setProperty("stroke", ACCENT, "important");
      marker.after(copy);
    }
    return `url(#${copyId})`;
  }

  // A corner radius of a shape in user units: a length in px or a plain number from its computed style or its attribute,
  // null for `auto`, a percentage or nothing.
  function lengthOf(value) {
    return typeof value === "string" && /^\d*\.?\d+(px)?$/.test(value.trim()) ? parseFloat(value) : null;
  }

  // The corner radii of a box's rect. Mermaid sets them with CSS (the theme's `rx`/`ry` properties) as often as with
  // attributes; one that is unset takes the other's value, as SVG does, and both unset mean square corners.
  function radiiOf(shape) {
    const style = getComputedStyle(shape);
    const rx = lengthOf(style.rx) ?? lengthOf(shape.getAttribute("rx"));
    const ry = lengthOf(style.ry) ?? lengthOf(shape.getAttribute("ry"));
    return { rx: rx ?? ry ?? 0, ry: ry ?? rx ?? 0 };
  }

  // A ring around a box's rect, HALO_GAP outside it with corners HALO_GAP wider than the box's own so the two curves stay
  // parallel; null for a shape that is not a rect with a position.
  function haloOf(shape) {
    const [x, y, width, height] = ["x", "y", "width", "height"].map((name) => Number(shape.getAttribute(name)));
    if (![x, y, width, height].every(Number.isFinite) || shape.localName !== "rect") return null;
    const { rx, ry } = radiiOf(shape);
    const ring = document.createElementNS(SVG_NS, "rect");
    ring.setAttribute("class", "prd-halo");
    ring.setAttribute("x", String(x - HALO_GAP));
    ring.setAttribute("y", String(y - HALO_GAP));
    ring.setAttribute("width", String(width + 2 * HALO_GAP));
    ring.setAttribute("height", String(height + 2 * HALO_GAP));
    ring.setAttribute("rx", String(rx + HALO_GAP));
    ring.setAttribute("ry", String(ry + HALO_GAP));
    return ring;
  }

  // null restores; an empty list dims the whole diagram a little. Otherwise the listed
  // boxes are marked and ringed with a halo, and so is every edge with an end on one of them, which also points with
  // an accent arrowhead. Nothing else changes.
  function applyEmphasis(card, found, ids) {
    card.classList.toggle("prd-none", Array.isArray(ids) && ids.length === 0);
    const active = new Set(ids ?? []);
    for (const [id, group] of found.nodes) {
      const on = ids !== null && active.has(id);
      group.classList.toggle(ON, on);
      const halo = found.halos.get(id);
      if (on && !halo) {
        const shape = group.querySelector(":scope > rect");
        const ring = shape ? haloOf(shape) : null;
        if (ring) {
          shape.after(ring);
          found.halos.set(id, ring);
        }
      } else if (!on && halo) {
        halo.remove();
        found.halos.delete(id);
      }
    }
    for (const { element, ends, markers } of found.edges) {
      const on = ids !== null && ends.some((end) => active.has(end));
      element.classList.toggle(ON, on);
      for (const [name, reference] of markers) element.setAttribute(name, on ? accentMarker(found.svg, reference) : reference);
    }
  }

  const SVG_NS = "http://www.w3.org/2000/svg";
  const MARKER_ATTRIBUTES = ["marker-start", "marker-end"];
  const ACCENT = "var(--prf-guide, #534ab7)";
  const HALO_GAP = 6;
  // How far the halo reaches outside the box: its gap plus half its 8px stroke (see .prd-halo).
  const HALO_REACH = HALO_GAP + 4;

  let root = null;
  let card = null;
  let found = null;
  let shownText = null;
  let emphasis = null;
  let canvas = null;
  let panelWidth = defaultWidth(globalThis.innerWidth);
  // The width the reader dragged the panel to, which wins over the default; null until they do.
  let chosenWidth = null;
  let boxWidth = 0;
  let caption = "";

  // The remembered width is read once when the script loads, so it is usually known before the first render.
  function readStoredWidth() {
    if (!ns.alive?.() || !globalThis.chrome?.storage?.local) return;
    chrome.storage.local
      .get(WIDTH_KEY)
      .then((stored) => {
        if (stored[WIDTH_KEY] === undefined) return;
        chosenWidth = Number.isFinite(Number(stored[WIDTH_KEY])) ? Number(stored[WIDTH_KEY]) : null;
        if (root) setWidth(root, chosenWidth);
      })
      .catch(() => {});
  }

  // Remembers the reader's width, or forgets it for `null`, which puts the default back.
  function storeWidth(width) {
    if (!ns.alive?.() || !globalThis.chrome?.storage?.local) return;
    const stored = width === null ? chrome.storage.local.remove(WIDTH_KEY) : chrome.storage.local.set({ [WIDTH_KEY]: width });
    stored.catch(() => {});
  }

  // Sets the panel's width: `width` clamped, or the default for the diagram on show for `null`.
  function setWidth(panel, width) {
    panelWidth = width === null ? defaultWidth(innerWidth, boxWidth) : clampWidth(width, innerWidth);
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
      chosenWidth = panelWidth;
      storeWidth(chosenWidth);
    };
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
    handle.addEventListener("dblclick", () => {
      chosenWidth = null;
      setWidth(panel, null);
      storeWidth(null);
    });
    return handle;
  }

  const SHAPES = "rect, polygon, path, circle, ellipse";
  const CONTEXT_CAPTION = "Dashed boxes are unchanged context";

  // The line under the diagram explaining its dashed boxes; empty when the diagram has none.
  function captionFor(svg) {
    return svg.querySelector("g.node.context") ? CONTEXT_CAPTION : "";
  }

  function buildCaption(text) {
    return make("p", "prd-caption", text);
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
  // transform. The view is a { scale, x, y } in viewport pixels; `resting` keeps it in its resting view
  // (restingView) until the user zooms or pans or a box is focused. Any wheel event, pinch included, zooms around the pointer and never scrolls the
  // page, a drag anywhere pans, and a press that stays under DRAG_THRESHOLD is a click on the box under it.
  // `centerOn` glides to a box list at the current zoom, with its halo inside the margin and followed vertically through
  // the boxes joined to it (followBoxView); any wheel or press interrupts the glide, and panning and zooming stay free
  // until the next call. While
  // the viewport is hidden (the panel is collapsed) it remembers the latest target and moves to it once the viewport has
  // a size again.
  function createCanvas(viewport, svg, { onNode, onView }) {
    const content = contentSize(svg.getAttribute("viewBox"), svg.getAttribute("width"), svg.getAttribute("height"));
    svg.style.width = `${content.w}px`;
    svg.style.height = `${content.h}px`;
    let view = { scale: 1, x: 0, y: 0 };
    let resting = true;
    let drag = null;
    let glideFrame = null;
    let target = null;
    let placed = false;

    const size = () => ({ w: viewport.clientWidth, h: viewport.clientHeight });

    function paint() {
      svg.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.scale})`;
      onView(view);
    }

    function show(next, isResting) {
      view = clampView(next, content, size());
      resting = isResting;
      paint();
    }

    function rest() {
      if (size().w <= 0) return;
      show(restingView(content, size()), true);
    }

    function zoomTo(scale, px = size().w / 2, py = size().h / 2) {
      target = null;
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

    // The bounds of the listed boxes in diagram units, or null when none is drawn. A box is measured by its own shape,
    // so its halo does not count.
    function boundsOf(ids) {
      const wanted = new Set(ids);
      const origin = svg.getBoundingClientRect();
      let box = null;
      for (const group of svg.querySelectorAll("g.node")) {
        if (!wanted.has(nodeIdOf(group.id))) continue;
        const r = (group.querySelector(`:scope > :is(${SHAPES})`) ?? group).getBoundingClientRect();
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

    // The ids of the boxes joined to any of `ids` by a solid edge, in either direction, apart from `ids` themselves. A
    // dotted or dashed edge marks a return to an earlier box and joins nothing.
    function neighboursOf(ids) {
      const wanted = new Set(ids);
      const known = new Set([...svg.querySelectorAll("g.node")].map((group) => nodeIdOf(group.id)));
      const found = new Set();
      for (const path of svg.querySelectorAll("path[data-id]")) {
        if (DASHED_EDGE.test(path.getAttribute("class") ?? "")) continue;
        const ends = edgeEnds(path.getAttribute("data-id"), known);
        if (!ends) continue;
        const [from, to] = ends;
        if (wanted.has(from) && !wanted.has(to)) found.add(to);
        if (wanted.has(to) && !wanted.has(from)) found.add(from);
      }
      return [...found];
    }

    // `ids` is a list of box ids; an empty list leaves the canvas as it is and forgets the boxes it was following. The
    // boxes stay the canvas's target until the reader pans or zooms: a viewport that has no size yet, or gets its first
    // one after this call, is taken to them once it has one.
    function centerOn(ids) {
      target = ids.length > 0 ? ids : null;
      if (!target || size().w <= 0) return;
      const rect = boundsOf(ids);
      if (!rect) return;
      resting = false;
      const own = grown(rect);
      const joined = boundsOf(neighboursOf(ids));
      const band = joined ? union(own, joined) : own;
      glide(followBoxView(view, own, band, content, size()));
    }

    function union(a, b) {
      const x = Math.min(a.x, b.x);
      const y = Math.min(a.y, b.y);
      return { x, y, w: Math.max(a.x + a.w, b.x + b.w) - x, h: Math.max(a.y + a.h, b.y + b.h) - y };
    }

    // `rect` grown by the reach of the focus halo, which is drawn outside the box's own shape.
    function grown(rect) {
      return { x: rect.x - HALO_REACH, y: rect.y - HALO_REACH, w: rect.w + 2 * HALO_REACH, h: rect.h + 2 * HALO_REACH };
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
      if (drag.moved) {
        target = null;
        show({ ...drag.from, x: drag.from.x + dx, y: drag.from.y + dy }, false);
      }
    }

    // The canvas is built before its panel is in the page, so its viewport has no size until the panel is attached, and
    // the observer's first report of a size is the viewport appearing: the diagram takes its resting view then, or is
    // taken to the boxes it was asked to follow, rather than carrying on a glide that began against an unplaced view.
    let observed = size();
    placed = observed.w > 0;
    if (placed) rest();
    const resizeObserver = globalThis.ResizeObserver
      ? new ResizeObserver(() => {
          const now = size();
          const appeared = observed.w <= 0 && now.w > 0;
          const changed = now.w !== observed.w || now.h !== observed.h;
          observed = now;
          if (now.w <= 0 || !changed) return;
          cancelGlide();
          if (appeared && !placed) {
            placed = true;
            rest();
          } else if (resting) rest();
          else show(view, false);
          if (appeared && target) centerOn(target);
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
      rest,
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
    const reset = button("prd-zoom-reset", "↺", "Reset");
    group.append(out, percent, zoomIn, reset);
    return { group, out, percent, zoomIn, reset };
  }

  // The Reset button's click: returns the canvas to its resting view, then lets the host put the rest of the review back.
  function resetAction(canvasOf, handlers) {
    return () => {
      canvasOf().rest();
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
    zoom.reset.addEventListener("click", resetAction(() => canvas, handlers));
    panel.classList.toggle("prd-collapsed", collapsed);
    panel.append(resizeHandle(panel), header, cardElement, ...(caption ? [buildCaption(caption)] : []));
    setWidth(panel, chosenWidth);
    return panel;
  }

  // Docks the diagram as the leftmost pane, right before the host's file pane in its own flex row, so the file
  // pane and the diff column narrow to make room. Safe to call repeatedly: it re-mounts only when the panel is
  // gone. handlers: { onNode(nodeId), onReset() }; the Reset button returns the canvas to its resting view and then calls onReset.
  function render(svgText, handlers) {
    const host = ns.page.diagramHost();
    if (!host) return;
    if (!root?.isConnected || shownText !== svgText) {
      const svg = parseSvg(svgText);
      if (!svg) return;
      canvas?.destroy();
      root?.remove();
      caption = captionFor(svg);
      boxWidth = widestBox(svg);
      root = build(svg, handlers, readCollapsed());
      card = root.querySelector(".prd-card");
      found = index(svg);
      shownText = svgText;
      applyEmphasis(card, found, emphasis);
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

  // Zooms to the listed boxes, halo included, and follows them through the boxes joined to them (see createCanvas).
  // Does nothing without a diagram.
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
  }

  function owns(node) {
    const element = node?.nodeType === 1 ? node : node?.parentElement;
    return Boolean(element?.closest(`#${ROOT_ID}`));
  }

  readStoredWidth();

  ns.diagram = { applyEmphasis, resetAction, zoomControls, render, emphasize, centerOn, titleOf, remove, owns, nodeIdOf, edgeEnds, unsafeAttribute, clampWidth, defaultWidth, widestBox, captionFor, clampScale, contentSize, restingView, zoomAround, stepScale, clampView, followBoxView, wheelZoomFactor, createCanvas };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.diagram;
