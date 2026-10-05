const test = require("node:test");
const assert = require("node:assert/strict");

const { clampScale, contentSize, fitView, zoomAround, stepScale, clampView, wheelZoomFactor, createCanvas } = require("../diagram.js");

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
