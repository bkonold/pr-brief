const test = require("node:test");
const assert = require("node:assert/strict");

const { applyEmphasis, resetAction, zoomControls, clampScale, contentSize, fitView, zoomAround, stepScale, clampView, centerView, followView, wheelZoomFactor, createCanvas } = require("../diagram.js");

const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} is not ${expected}`);

test("clampScale keeps the zoom between 25% and 400%", () => {
  assert.equal(clampScale(0.1), 0.25);
  assert.equal(clampScale(9), 4);
  assert.equal(clampScale(1.5), 1.5);
});

test("contentSize reads the viewBox, then absolute width and height, then falls back", () => {
  assert.deepEqual(contentSize("0 0 640 480", "100%", null), { w: 640, h: 480 });
  assert.deepEqual(contentSize("-8, -8, 200.5, 100", null, null), { w: 200.5, h: 100 });
  assert.deepEqual(contentSize(null, "320", "240px"), { w: 320, h: 240 });
  assert.deepEqual(contentSize("0 0 0 0", "100%", "auto"), { w: 300, h: 200 });
  assert.deepEqual(contentSize("nonsense", null, null), { w: 300, h: 200 });
});

test("fitView fits the width with a margin, centred and top-aligned", () => {
  assert.deepEqual(fitView({ w: 400, h: 900 }, { w: 216, h: 500 }, 8), { scale: 0.5, x: 8, y: 8 });
});

test("fitView centres a diagram whose fit scale is capped", () => {
  const view = fitView({ w: 50, h: 50 }, { w: 800, h: 500 }, 8);
  assert.equal(view.scale, 4);
  assert.equal(view.x, 300);
  assert.equal(view.y, 8);
});

test("fitView never goes below the minimum zoom", () => {
  assert.equal(fitView({ w: 10000, h: 10 }, { w: 200, h: 200 }).scale, 0.25);
});

test("zoomAround keeps the point under the pointer fixed", () => {
  const view = { scale: 1, x: 20, y: 30 };
  const next = zoomAround(view, 2, 120, 130);
  assert.equal(next.scale, 2);
  const diagramPoint = (v) => [(120 - v.x) / v.scale, (130 - v.y) / v.scale];
  assert.deepEqual(diagramPoint(next), diagramPoint(view));
});

test("zoomAround clamps the scale and anchors at the clamped value", () => {
  const next = zoomAround({ scale: 3, x: 0, y: 0 }, 10, 100, 100);
  assert.equal(next.scale, 4);
  close(next.x, 100 - 100 * (4 / 3));
});

test("stepScale moves a quarter at a time within the zoom range", () => {
  close(stepScale(1, 1), 1.25);
  close(stepScale(1, -1), 0.8);
  assert.equal(stepScale(4, 1), 4);
  assert.equal(stepScale(0.25, -1), 0.25);
});

test("clampView lets an edge reach the viewport middle and no further", () => {
  const content = { w: 400, h: 600 };
  const viewport = { w: 200, h: 300 };
  assert.deepEqual(clampView({ scale: 1, x: 500, y: 500 }, content, viewport), { scale: 1, x: 100, y: 150 });
  assert.deepEqual(clampView({ scale: 1, x: -900, y: -900 }, content, viewport), { scale: 1, x: -300, y: -450 });
  assert.deepEqual(clampView({ scale: 1, x: -50, y: 20 }, content, viewport), { scale: 1, x: -50, y: 20 });
});

test("clampView leaves a short diagram resting at the fit margin", () => {
  assert.deepEqual(clampView({ scale: 1, x: 8, y: 8 }, { w: 100, h: 100 }, { w: 400, h: 400 }), { scale: 1, x: 8, y: 8 });
  assert.equal(clampView({ scale: 1, x: -50, y: -50 }, { w: 100, h: 100 }, { w: 400, h: 400 }).y, 8);
});

test("clampView accounts for the scale", () => {
  const view = clampView({ scale: 2, x: -5000, y: 0 }, { w: 400, h: 100 }, { w: 200, h: 300 });
  assert.equal(view.x, 100 - 800);
});

test("wheelZoomFactor zooms in on a negative delta, out on a positive one, and is bounded", () => {
  assert.ok(wheelZoomFactor({ deltaY: -5, deltaMode: 0 }) > 1);
  assert.ok(wheelZoomFactor({ deltaY: 5, deltaMode: 0 }) < 1);
  assert.equal(wheelZoomFactor({ deltaY: 0, deltaMode: 0 }), 1);
  assert.equal(wheelZoomFactor({ deltaY: -100, deltaMode: 0 }), wheelZoomFactor({ deltaY: -5000, deltaMode: 0 }));
  close(wheelZoomFactor({ deltaY: -4, deltaMode: 0 }) * wheelZoomFactor({ deltaY: 4, deltaMode: 0 }), 1);
});

function fakeCanvas() {
  const listeners = {};
  const viewport = {
    clientWidth: 400,
    clientHeight: 300,
    clientLeft: 0,
    clientTop: 0,
    classList: { add() {}, remove() {} },
    addEventListener: (type, handler) => (listeners[type] = handler),
    getBoundingClientRect: () => ({ left: 10, top: 20 }),
  };
  const attributes = { viewBox: "0 0 400 300" };
  const svg = { style: {}, getAttribute: (name) => attributes[name] ?? null };
  const views = [];
  const canvas = createCanvas(viewport, svg, { onNode() {}, onView: (view) => views.push(view) });
  const wheel = (init) => {
    const event = { deltaY: 0, deltaMode: 0, ctrlKey: false, metaKey: false, clientX: 10, clientY: 20, prevented: false, ...init };
    event.preventDefault = () => (event.prevented = true);
    listeners.wheel(event);
    return event;
  };
  return { canvas, wheel, views };
}

test("a plain wheel zooms the canvas and is kept from scrolling the page", () => {
  const { wheel, views } = fakeCanvas();
  const before = views.at(-1).scale;
  assert.equal(wheel({ deltaY: -100 }).prevented, true);
  assert.ok(views.at(-1).scale > before);
  const zoomedIn = views.at(-1).scale;
  assert.equal(wheel({ deltaY: 100 }).prevented, true);
  assert.ok(views.at(-1).scale < zoomedIn);
});

test("a plain wheel and a ctrl or cmd wheel zoom by the same amount", () => {
  const scaleAfter = (init) => {
    const { wheel, views } = fakeCanvas();
    wheel({ deltaY: -40, ...init });
    return views.at(-1).scale;
  };
  const plain = scaleAfter({});
  close(scaleAfter({ ctrlKey: true }), plain);
  close(scaleAfter({ metaKey: true }), plain);
});

test("wheel zoom keeps the point under the pointer fixed and stays within the scale caps", () => {
  const { wheel, views } = fakeCanvas();
  const start = views.at(-1);
  wheel({ deltaY: -100, clientX: 110, clientY: 120 });
  const next = views.at(-1);
  close((100 - next.x) / next.scale, (100 - start.x) / start.scale);
  for (let i = 0; i < 40; i++) wheel({ deltaY: -100 });
  assert.equal(views.at(-1).scale, 4);
  for (let i = 0; i < 80; i++) wheel({ deltaY: 100 });
  assert.equal(views.at(-1).scale, 0.25);
});

test("centerView puts the rect's centre at the viewport's centre and keeps the zoom", () => {
  const view = centerView({ scale: 1, x: 8, y: 8 }, { x: 400, y: 300, w: 100, h: 60 }, { w: 1000, h: 800 }, { w: 400, h: 300 });
  assert.deepEqual(view, { scale: 1, x: 200 - 450, y: 150 - 330 });
  const zoomed = centerView({ scale: 2, x: 0, y: 0 }, { x: 400, y: 300, w: 50, h: 30 }, { w: 1000, h: 800 }, { w: 400, h: 300 });
  assert.deepEqual(zoomed, { scale: 2, x: 200 - 850, y: 150 - 630 });
});

test("centerView zooms out just enough for a rect larger than the viewport", () => {
  const content = { w: 1000, h: 800 };
  const wide = centerView({ scale: 1, x: 0, y: 0 }, { x: 100, y: 100, w: 768, h: 100 }, content, { w: 400, h: 300 });
  close(wide.scale, 0.5);
  close(wide.x, 200 - (100 + 384) * 0.5);
  const tall = centerView({ scale: 1, x: 0, y: 0 }, { x: 100, y: 100, w: 100, h: 568 }, content, { w: 400, h: 300 });
  close(tall.scale, 0.5);
  close(tall.y, 150 - (100 + 284) * 0.5);
  assert.equal(centerView({ scale: 1, x: 0, y: 0 }, { x: 0, y: 0, w: 1e6, h: 1e6 }, content, { w: 400, h: 300 }).scale, 0.25);
});

test("centerView never zooms in, even for a small rect", () => {
  const view = centerView({ scale: 0.5, x: 0, y: 0 }, { x: 100, y: 100, w: 10, h: 10 }, { w: 1000, h: 800 }, { w: 400, h: 300 });
  assert.equal(view.scale, 0.5);
});

test("centerView keeps clampView's limits near the diagram's edges", () => {
  const content = { w: 1000, h: 800 };
  const viewport = { w: 400, h: 300 };
  const view = centerView({ scale: 1, x: 0, y: 0 }, { x: -100, y: -100, w: 50, h: 50 }, content, viewport);
  assert.deepEqual(view, { scale: 1, x: 200, y: 150 });
  const far = centerView({ scale: 1, x: 0, y: 0 }, { x: 1100, y: 900, w: 50, h: 50 }, content, viewport);
  assert.deepEqual(far, { scale: 1, x: 200 - 1000, y: 150 - 800 });
});

const SOLID = "edge-thickness-normal edge-pattern-solid flowchart-link";
const DOTTED = "edge-thickness-normal edge-pattern-dotted edge-thickness-normal edge-pattern-solid flowchart-link";
const PATH_EDGES = [["p1", "p2", SOLID], ["p2", "p3", SOLID], ["p3", "p4", SOLID], ["p3", "q", SOLID], ["p4", "p5", SOLID], ["p5", "p1", DOTTED]];

function boxCanvas({ viewportSize = { w: 400, h: 500 } } = {}) {
  const listeners = {};
  const viewport = {
    clientWidth: viewportSize.w,
    clientHeight: viewportSize.h,
    clientLeft: 0,
    clientTop: 0,
    classList: { add() {}, remove() {} },
    addEventListener: (type, handler) => (listeners[type] = handler),
    getBoundingClientRect: () => ({ left: 0, top: 0 }),
    setPointerCapture() {},
  };
  const attributes = { viewBox: "0 0 1000 1600" };
  const views = [];
  const clicked = [];
  const at = (x, y) => ({ x, y, w: 100, h: 60 });
  const boxes = {
    a: at(500, 400),
    b: at(700, 500),
    huge: { x: 0, y: 0, w: 2000, h: 1600 },
    p1: at(450, 100),
    p2: at(450, 300),
    p3: at(450, 500),
    p4: at(450, 700),
    p5: at(450, 900),
    q: at(700, 720),
    ctx: at(450, 1200),
  };
  const edges = PATH_EDGES.map(([from, to, className]) => ({
    getAttribute: (name) => ({ "data-id": `L_${from}_${to}_0`, class: className })[name] ?? null,
  }));
  const state = {
    get svgLeft() {
      return views.at(-1).x;
    },
    get svgTop() {
      return views.at(-1).y;
    },
    get scale() {
      return views.at(-1).scale;
    },
  };
  const HALO = 6;
  const group = (id) => {
    const rectOf = (grow) => {
      const b = boxes[id];
      return {
        left: state.svgLeft + (b.x - grow) * state.scale,
        top: state.svgTop + (b.y - grow) * state.scale,
        right: state.svgLeft + (b.x + b.w + grow) * state.scale,
        bottom: state.svgTop + (b.y + b.h + grow) * state.scale,
      };
    };
    const shape = { getBoundingClientRect: () => rectOf(0) };
    return {
      id: `diagram-flowchart-${id}-0`,
      classList: { contains: () => false },
      querySelector: (selector) => (selector.startsWith(":scope > :is(") ? shape : null),
      getBoundingClientRect: () => rectOf(HALO),
    };
  };
  const groups = Object.keys(boxes).map(group);
  const svg = {
    style: {},
    getAttribute: (name) => attributes[name] ?? null,
    querySelectorAll: (selector) => (selector === "path[data-id]" ? edges : groups),
    getBoundingClientRect: () => ({ left: state.svgLeft, top: state.svgTop }),
  };
  const canvas = createCanvas(viewport, svg, { onNode: (id) => clicked.push(id), onView: (view) => views.push(view) });
  const pointer = (type, init) => listeners[type]({ pointerId: 1, button: 0, clientX: 0, clientY: 0, preventDefault() {}, ...init });
  const clickBox = (id) => {
    pointer("pointerdown", { target: { closest: () => group(id) } });
    pointer("pointerup", {});
  };
  return { canvas, views, clicked, clickBox, viewport };
}

test("centerOn centres a box horizontally and leaves y alone when the box is in view", () => {
  const { canvas, views } = boxCanvas();
  canvas.centerOn(["a"]);
  const view = views.at(-1);
  assert.equal(view.scale, 1);
  assert.deepEqual({ x: view.x, y: view.y }, { x: 200 - 550, y: 0 });
});

test("centerOn centres the bounds of several boxes horizontally and brings them into view", () => {
  const { canvas, views } = boxCanvas();
  canvas.centerOn(["a", "b"]);
  const view = views.at(-1);
  assert.deepEqual({ x: view.x, y: view.y }, { x: 200 - 650, y: 492 - 560 });
});

test("centerOn measures boxes against the current pan and zoom", () => {
  const { canvas, views } = boxCanvas();
  canvas.centerOn(["a"]);
  canvas.centerOn(["b"]);
  const view = views.at(-1);
  assert.deepEqual({ x: view.x, y: view.y }, { x: 200 - 750, y: 492 - 560 });
});

test("centerOn zooms out to fit a box larger than the pane", () => {
  const { canvas, views } = boxCanvas();
  canvas.centerOn(["huge"]);
  assert.equal(views.at(-1).scale, 0.25);
});

test("centerOn accepts a rect in diagram units", () => {
  const { canvas, views } = boxCanvas();
  canvas.centerOn({ x: 500, y: 400, w: 100, h: 60 });
  const view = views.at(-1);
  assert.deepEqual({ x: view.x, y: view.y }, { x: 200 - 550, y: 250 - 430 });
});

test("centerOn leaves the canvas alone for an empty list or boxes that are not drawn", () => {
  const { canvas, views } = boxCanvas();
  const count = views.length;
  canvas.centerOn([]);
  canvas.centerOn(["missing"]);
  assert.equal(views.length, count);
});

function follow(ids, { from = [], viewportSize } = {}) {
  const { canvas, views } = boxCanvas({ viewportSize });
  for (const earlier of from) canvas.centerOn(earlier);
  canvas.centerOn(ids);
  const view = views.at(-1);
  return { x: view.x, y: view.y, scale: view.scale };
}

test("centerOn follows the first box on the path with its one neighbour, ignoring the dotted return edge", () => {
  assert.deepEqual(follow(["p1"]), { x: 200 - 500, y: 0, scale: 1 });
});

test("centerOn follows the last box on the path with its one neighbour", () => {
  assert.deepEqual(follow(["p5"]), { x: 200 - 500, y: 492 - 960, scale: 1 });
});

test("centerOn leaves y alone when the box and its neighbours are already in view", () => {
  assert.deepEqual(follow(["p4"], { from: [["p5"]] }), { x: 200 - 500, y: 492 - 960, scale: 1 });
});

test("centerOn moves only as far as it takes to bring a band below the view into it", () => {
  assert.deepEqual(follow(["p4"]), { x: 200 - 500, y: 492 - 960, scale: 1 });
});

test("centerOn moves only as far as it takes to bring a band above the view into it", () => {
  assert.deepEqual(follow(["p1"], { from: [["p5"]] }), { x: 200 - 500, y: 8 - 100, scale: 1 });
});

test("centerOn follows both successors of a branch", () => {
  assert.deepEqual(follow(["p3"]), { x: 200 - 500, y: 492 - 780, scale: 1 });
});

test("centerOn follows a box with no edges alone", () => {
  assert.deepEqual(follow(["ctx"]), { x: 200 - 500, y: 492 - 1260, scale: 1 });
});

test("centerOn follows a chunk's boxes together with their neighbours", () => {
  assert.deepEqual(follow(["p1", "p2"]), { x: 200 - 500, y: 492 - 560, scale: 1 });
});

test("centerOn centres the box vertically when its band is taller than the viewport", () => {
  assert.deepEqual(follow(["p2"], { viewportSize: { w: 400, h: 400 } }), { x: 200 - 500, y: 200 - 330, scale: 1 });
});

test("followView leaves y alone for a band inside the margin and centres the rect horizontally", () => {
  const view = followView({ scale: 1, x: 0, y: -50 }, { x: 300, y: 200, w: 100, h: 60 }, { x: 300, y: 150, w: 100, h: 100 }, { w: 1000, h: 800 }, { w: 400, h: 300 });
  assert.deepEqual(view, { scale: 1, x: 200 - 350, y: -50 });
});

test("followView raises the view until the band's top reaches the margin, and lowers it until the bottom does", () => {
  const content = { w: 1000, h: 800 };
  const viewport = { w: 400, h: 300 };
  const rect = { x: 300, y: 400, w: 100, h: 60 };
  assert.equal(followView({ scale: 1, x: 0, y: 0 }, rect, { x: 300, y: 380, w: 100, h: 120 }, content, viewport).y, 292 - 500);
  assert.equal(followView({ scale: 1, x: 0, y: -450 }, rect, { x: 300, y: 380, w: 100, h: 120 }, content, viewport).y, 8 - 380);
});

test("followView centres the rect vertically for a band taller than the viewport inside the margin", () => {
  const view = followView({ scale: 1, x: 0, y: 0 }, { x: 300, y: 400, w: 100, h: 60 }, { x: 300, y: 100, w: 100, h: 500 }, { w: 1000, h: 800 }, { w: 400, h: 300 });
  assert.deepEqual(view, { scale: 1, x: 200 - 350, y: 150 - 430 });
});

test("followView scales as centerView does, dropping only when the rect alone does not fit", () => {
  const content = { w: 1000, h: 800 };
  const viewport = { w: 400, h: 300 };
  const rect = { x: 100, y: 100, w: 768, h: 100 };
  const view = followView({ scale: 1, x: 0, y: 0 }, rect, { ...rect, h: 300 }, content, viewport);
  assert.equal(view.scale, centerView({ scale: 1, x: 0, y: 0 }, rect, content, viewport).scale);
  assert.equal(followView({ scale: 0.5, x: 0, y: 0 }, { x: 100, y: 100, w: 10, h: 10 }, { x: 100, y: 100, w: 10, h: 10 }, content, viewport).scale, 0.5);
});

test("followView keeps clampView's limits near the diagram's edges", () => {
  const view = followView({ scale: 1, x: 0, y: 0 }, { x: -100, y: -300, w: 50, h: 50 }, { x: -100, y: -300, w: 50, h: 50 }, { w: 1000, h: 800 }, { w: 400, h: 300 });
  assert.deepEqual(view, { scale: 1, x: 200, y: 150 });
});

test("a click on a box is reported and does not move the canvas by itself", () => {
  const { views, clicked, clickBox } = boxCanvas();
  const count = views.length;
  clickBox("a");
  assert.deepEqual(clicked, ["a"]);
  assert.equal(views.length, count);
});

test("a hidden viewport keeps the latest target and centres on it once it has a size", () => {
  const original = globalThis.ResizeObserver;
  let notify = null;
  globalThis.ResizeObserver = class {
    constructor(callback) {
      notify = callback;
    }
    observe() {}
    disconnect() {}
  };
  try {
    const { canvas, views, viewport } = boxCanvas({ viewportSize: { w: 0, h: 0 } });
    const count = views.length;
    canvas.centerOn(["a"]);
    canvas.centerOn(["b"]);
    assert.equal(views.length, count);
    viewport.clientWidth = 400;
    viewport.clientHeight = 300;
    notify();
    const view = views.at(-1);
    close(view.scale, 0.384);
    close(view.x, 200 - 750 * 0.384);
    close(view.y, 8);
  } finally {
    globalThis.ResizeObserver = original;
  }
});

test("centerOn glides to the target over about 200ms and a wheel interrupts it", () => {
  const frames = [];
  const originalRaf = globalThis.requestAnimationFrame;
  const originalCancel = globalThis.cancelAnimationFrame;
  globalThis.requestAnimationFrame = (callback) => frames.push(callback);
  globalThis.cancelAnimationFrame = (id) => (frames[id - 1] = null);
  try {
    const { canvas, views } = boxCanvas();
    const start = views.at(-1);
    canvas.centerOn(["a"]);
    assert.deepEqual(views.at(-1), start);
    frames.shift()(1000);
    frames.shift()(1100);
    const middle = views.at(-1);
    assert.ok(middle.x < start.x && middle.x > 200 - 550);
    frames.shift()(1200);
    assert.deepEqual({ x: views.at(-1).x, y: views.at(-1).y }, { x: 200 - 550, y: 0 });
    assert.equal(frames.length, 0);
  } finally {
    globalThis.requestAnimationFrame = originalRaf;
    globalThis.cancelAnimationFrame = originalCancel;
  }
});

test("the zoom controls end with a Reset button, titled and labelled Reset, beside the zoom buttons", () => {
  const element = (tag) => ({ tag, className: "", textContent: "", attributes: {}, children: [], setAttribute(name, value) { this.attributes[name] = value; }, append(...nodes) { this.children.push(...nodes); } });
  globalThis.document = { createElement: element };
  try {
    const { group, reset } = zoomControls();
    assert.deepEqual(group.children.map((child) => child.textContent), ["−", "100%", "+", "Fit", "↺"]);
    assert.equal(group.children.at(-1), reset);
    assert.deepEqual([reset.className, reset.title, reset.attributes["aria-label"], reset.type], ["prd-zoom-reset", "Reset", "Reset", "button"]);
  } finally {
    delete globalThis.document;
  }
});

test("Reset refits a zoomed and panned canvas to the pane, then calls the host's reset", () => {
  const { canvas, views } = boxCanvas();
  canvas.fit();
  const fitted = views.at(-1);
  canvas.zoomIn();
  canvas.zoomIn();
  assert.notEqual(views.at(-1).scale, fitted.scale);
  const order = [];
  const refit = { fit: () => (canvas.fit(), order.push("fit")) };
  resetAction(() => refit, { onReset: () => order.push("onReset") })();
  assert.deepEqual(order, ["fit", "onReset"]);
  assert.deepEqual(views.at(-1), fitted);
  resetAction(() => refit, {})();
  assert.deepEqual(order, ["fit", "onReset", "fit"]);
});

function emphasisFixture() {
  const classes = () => {
    const set = new Set();
    return { set, toggle: (name, on) => (on ? set.add(name) : set.delete(name)), add: (name) => set.add(name), remove: (name) => set.delete(name), contains: (name) => set.has(name) };
  };
  const created = [];
  global.document = {
    createElementNS: () => {
      const attrs = {};
      const ring = {
        attrs,
        removed: false,
        setAttribute: (name, value) => (attrs[name] = value),
        getAttribute: (name) => attrs[name] ?? null,
        remove() {
          ring.removed = true;
          const at = children.indexOf(ring);
          if (at >= 0) children.splice(at, 1);
        },
      };
      created.push(ring);
      return ring;
    },
  };
  const children = [];
  const rectAttrs = { x: "100", y: "50", width: "80", height: "40", rx: "4" };
  const shape = {
    localName: "rect",
    getAttribute: (name) => rectAttrs[name] ?? null,
    after: (node) => children.splice(0, 0, node),
  };
  const node = (withShape = true) => ({ classList: classes(), querySelector: () => (withShape ? shape : null) });
  const marker = { id: "head", cloneNode: () => ({ id: "", querySelectorAll: () => [], after() {} }), after() {} };
  const svg = { querySelector: (selector) => (selector === '[id="head"]' ? marker : null) };
  const edge = (ends) => {
    const attrs = { "marker-end": "url(#head)" };
    return {
      element: { classList: classes(), getAttribute: (name) => attrs[name] ?? null, hasAttribute: (name) => name in attrs, setAttribute: (name, value) => (attrs[name] = value) },
      ends,
      markers: [["marker-end", "url(#head)"]],
    };
  };
  const found = {
    svg,
    nodes: new Map([["a", node()], ["b", node()], ["c", node()], ["d", node(false)]]),
    edges: [edge(["a", "b"]), edge(["b", "c"]), edge(["c", "d"])],
    halos: new Map(),
  };
  const card = { classList: classes() };
  return { found, card, created, children };
}

test("applyEmphasis marks the listed boxes and every edge touching one, and dims nothing", () => {
  const { found, card } = emphasisFixture();
  applyEmphasis(card, found, ["b"]);
  const on = (entry) => (entry.element ?? entry).classList.contains("prd-on");
  assert.deepEqual([...found.nodes.values()].map(on), [false, true, false, false]);
  assert.deepEqual(found.edges.map(on), [true, true, false]);
  for (const entry of [...found.nodes.values(), ...found.edges.map((edge) => edge.element), card]) assert.equal((entry.classList ?? entry).contains("prd-off"), false);
  assert.equal(card.classList.contains("prd-none"), false);
});

test("applyEmphasis marks an edge with one active end", () => {
  const { found, card } = emphasisFixture();
  applyEmphasis(card, found, ["a", "c"]);
  assert.deepEqual(found.edges.map((edge) => edge.element.classList.contains("prd-on")), [true, true, true]);
});

test("applyEmphasis clears everything for null and dims the whole diagram for an empty list", () => {
  const { found, card } = emphasisFixture();
  applyEmphasis(card, found, ["b"]);
  applyEmphasis(card, found, []);
  assert.equal(card.classList.contains("prd-none"), true);
  assert.deepEqual([...found.nodes.values()].map((group) => group.classList.contains("prd-on")), [false, false, false, false]);
  assert.deepEqual(found.edges.map((edge) => edge.element.classList.contains("prd-on")), [false, false, false]);
  applyEmphasis(card, found, null);
  assert.equal(card.classList.contains("prd-none"), false);
});

test("applyEmphasis ringes a focused rect box with a halo 6px outside it and removes it when focus moves", () => {
  const { found, card, created, children } = emphasisFixture();
  applyEmphasis(card, found, ["a"]);
  assert.equal(created.length, 1);
  assert.deepEqual(created[0].attrs, { class: "prd-halo", x: "94", y: "44", width: "92", height: "52", rx: "10" });
  assert.equal(found.halos.get("a"), created[0]);
  applyEmphasis(card, found, ["a"]);
  assert.equal(created.length, 1);
  applyEmphasis(card, found, ["b"]);
  assert.equal(created[0].removed, true);
  assert.equal(found.halos.has("a"), false);
  assert.equal(found.halos.has("b"), true);
  assert.equal(children.length, 1);
  applyEmphasis(card, found, null);
  assert.equal(found.halos.size, 0);
  assert.equal(children.length, 0);
});

test("applyEmphasis draws no halo for a box without a rect", () => {
  const { found, card, created } = emphasisFixture();
  applyEmphasis(card, found, ["d"]);
  assert.equal(created.length, 0);
  assert.equal(found.nodes.get("d").classList.contains("prd-on"), true);
});

test("applyEmphasis points emphasized edges with an accent arrowhead and restores the original one", () => {
  const { found, card } = emphasisFixture();
  applyEmphasis(card, found, ["a"]);
  assert.equal(found.edges[0].element.getAttribute("marker-end"), "url(#head-prd-on)");
  assert.equal(found.edges[1].element.getAttribute("marker-end"), "url(#head)");
  applyEmphasis(card, found, null);
  assert.equal(found.edges[0].element.getAttribute("marker-end"), "url(#head)");
});
