const test = require("node:test");
const assert = require("node:assert/strict");

const { resizeHandle } = require("../page_common.js");

// The parts of an element that resizeHandle touches: its listeners, which `fire` calls as the browser would.
class FakeElement {
  constructor() {
    this.listeners = new Map();
  }
  addEventListener(type, handler) {
    this.listeners.set(type, handler);
  }
  setPointerCapture() {}
  fire(type, event = {}) {
    this.listeners.get(type)?.({ button: 0, pointerId: 1, preventDefault() {}, ...event });
  }
}

test("resizeHandle ignores other buttons, and reports no width for a drag that never moved", () => {
  const saved = globalThis.document;
  globalThis.document = { createElement: () => new FakeElement() };
  try {
    const calls = [];
    const handle = resizeHandle({
      className: "x",
      widthOf: () => 100,
      setWidth: (width) => calls.push(["set", width]),
      onStart: () => calls.push(["start"]),
      onEnd: (width) => calls.push(["end", width]),
    });
    handle.fire("pointerdown", { button: 2, clientX: 10 });
    handle.fire("pointerup");
    assert.deepEqual(calls, []);
    handle.fire("pointerdown", { clientX: 10 });
    handle.fire("pointerup");
    handle.fire("pointerdown", { clientX: 10 });
    handle.fire("pointermove", { clientX: 35 });
    handle.fire("pointercancel");
    assert.deepEqual(calls, [["start"], ["end", null], ["start"], ["set", 125], ["end", 125]]);
    assert.equal(handle.listeners.has("dblclick"), false);
  } finally {
    globalThis.document = saved;
    if (saved === undefined) delete globalThis.document;
  }
});
