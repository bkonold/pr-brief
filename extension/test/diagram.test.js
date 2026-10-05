const test = require("node:test");
const assert = require("node:assert/strict");

const { resetAction, zoomControls, clampScale, contentSize, fitView, zoomAround, stepScale, clampView, centerView, wheelZoomFactor, createCanvas } = require("../diagram.js");

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

function boxCanvas({ viewportSize = { w: 400, h: 300 } } = {}) {
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
  const attributes = { viewBox: "0 0 1000 800" };
  const views = [];
  const clicked = [];
  const boxes = { a: { x: 500, y: 400, w: 100, h: 60 }, b: { x: 700, y: 500, w: 100, h: 60 }, huge: { x: 0, y: 0, w: 2000, h: 1600 } };
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
  const group = (id) => ({
    id: `diagram-flowchart-${id}-0`,
    classList: { contains: () => false },
    getBoundingClientRect: () => {
      const b = boxes[id];
      return {
        left: state.svgLeft + b.x * state.scale,
        top: state.svgTop + b.y * state.scale,
        right: state.svgLeft + (b.x + b.w) * state.scale,
        bottom: state.svgTop + (b.y + b.h) * state.scale,
      };
    },
  });
  const groups = Object.keys(boxes).map(group);
  const svg = {
    style: {},
    getAttribute: (name) => attributes[name] ?? null,
    querySelectorAll: () => groups,
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

test("centerOn centres a box in the pane at the current zoom", () => {
  const { canvas, views } = boxCanvas();
  canvas.centerOn(["a"]);
  const view = views.at(-1);
  assert.equal(view.scale, 1);
  assert.deepEqual({ x: view.x, y: view.y }, { x: 200 - 550, y: 150 - 430 });
});

test("centerOn centres the bounds of several boxes", () => {
  const { canvas, views } = boxCanvas();
  canvas.centerOn(["a", "b"]);
  const view = views.at(-1);
  assert.deepEqual({ x: view.x, y: view.y }, { x: 200 - 650, y: 150 - 480 });
});

test("centerOn measures boxes against the current pan and zoom", () => {
  const { canvas, views } = boxCanvas();
  canvas.centerOn(["a"]);
  canvas.centerOn(["b"]);
  const view = views.at(-1);
  assert.deepEqual({ x: view.x, y: view.y }, { x: 200 - 750, y: 150 - 530 });
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
  assert.deepEqual({ x: view.x, y: view.y }, { x: 200 - 550, y: 150 - 430 });
});

test("centerOn leaves the canvas alone for an empty list or boxes that are not drawn", () => {
  const { canvas, views } = boxCanvas();
  const count = views.length;
  canvas.centerOn([]);
  canvas.centerOn(["missing"]);
  assert.equal(views.length, count);
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
    close(view.y, 150 - 530 * 0.384);
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
    assert.deepEqual({ x: views.at(-1).x, y: views.at(-1).y }, { x: 200 - 550, y: 150 - 430 });
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
