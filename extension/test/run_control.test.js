const test = require("node:test");
const assert = require("node:assert/strict");

const { create, stagePills, formatElapsed, problemMessage } = require("../run_control.js");

const settle = () => new Promise((resolve) => setImmediate(resolve));

// A clock and timers that only move when the test advances them, a second at a time.
function fakeTime() {
  let now = 0;
  let next = 1;
  const timeouts = new Map();
  const intervals = new Map();
  const timers = {
    setTimeout: (fn, ms) => (timeouts.set(next, { fn, due: now + ms }), next++),
    clearTimeout: (id) => timeouts.delete(id),
    setInterval: (fn, ms) => (intervals.set(next, { fn, ms, due: now + ms }), next++),
    clearInterval: (id) => intervals.delete(id),
  };
  async function advance(seconds) {
    for (let second = 0; second < seconds; second += 1) {
      now += 1000;
      for (const [id, timer] of [...timeouts]) {
        if (timer.due <= now && timeouts.delete(id)) timer.fn();
      }
      for (const timer of [...intervals.values()]) {
        while (timer.due <= now) {
          timer.due += timer.ms;
          timer.fn();
        }
      }
      await settle();
    }
  }
  return { timers, now: () => now, advance, pending: () => timeouts.size + intervals.size };
}

const RUN = { host: "forgejo", owner: "acme", repo: "widgets", pr: 7, key: "fj-7" };

function harness(sourceOverrides = {}) {
  const time = fakeTime();
  const events = [];
  const calls = [];
  const source = {
    startRun: async (run) => (calls.push("start"), { ok: true, key: run.key, state: "running" }),
    runStatus: async () => (calls.push("status"), { ok: true, state: "running", stage: "write", elapsed: 3 }),
    cancelRun: async (run) => (calls.push("cancel"), { ok: true, key: run.key, state: "canceled" }),
    ...sourceOverrides,
  };
  const on = {
    running: (view) => events.push(["running", view.stage, view.elapsed]),
    error: (view) => events.push(["error", view.message]),
    idle: () => events.push(["idle"]),
    done: () => events.push(["done"]),
  };
  return { controller: create({ source, run: RUN, on, timers: time.timers, now: time.now }), events, calls, time };
}

test("formatElapsed writes minutes and zero-padded seconds", () => {
  assert.deepEqual([0, 9, 65, 600, -2].map(formatElapsed), ["0:00", "0:09", "1:05", "10:00", "0:00"]);
});

test("stagePills marks the stages before the current one done and the later ones pending", () => {
  assert.deepEqual(stagePills("write").map((pill) => [pill.label, pill.state]), [
    ["Fetch PR", "done"],
    ["Gather context", "done"],
    ["Write", "current"],
    ["Render", "pending"],
  ]);
  assert.deepEqual(stagePills(undefined).map((pill) => pill.state), ["current", "pending", "pending", "pending"]);
  assert.deepEqual(stagePills("elsewhere").map((pill) => pill.state), ["current", "pending", "pending", "pending"]);
});

test("each problem has its own message", () => {
  assert.equal(problemMessage({ problem: "server" }), "Start the server with `pd serve` to generate briefs");
  assert.equal(problemMessage({ problem: "token" }), "Server token missing or wrong — set it in the extension options");
  assert.equal(problemMessage({ problem: "busy", message: "2 briefs already running" }), "2 briefs already running");
  assert.equal(problemMessage({ problem: "busy" }), "2 briefs already running");
  assert.equal(problemMessage({ problem: "error", message: "boom" }), "boom");
});

test("generate shows the first stage at once, ticks every second, polls every three and ends on done", async () => {
  let answers = [
    { ok: true, state: "running", stage: "write", elapsed: 3 },
    { ok: true, state: "done", stage: "render", elapsed: 6 },
  ];
  const { controller, events, calls, time } = harness({ runStatus: async () => (calls.push("status"), answers.shift()) });
  const started = controller.generate();
  assert.deepEqual(events, [["running", "fetch", 0]]);
  await started;
  await time.advance(1);
  await time.advance(1);
  assert.deepEqual(events.slice(2), [["running", "fetch", 1], ["running", "fetch", 2]]);
  await time.advance(1);
  assert.deepEqual(calls, ["start", "status"]);
  assert.deepEqual(events.at(-1), ["running", "write", 3]);
  await time.advance(3);
  assert.deepEqual(events.at(-1), ["done"]);
  assert.deepEqual(calls, ["start", "status", "status"]);
  assert.equal(time.pending(), 0);
  await time.advance(10);
  assert.deepEqual(calls, ["start", "status", "status"]);
});

test("a failed start or poll shows the message for its problem, and stops following", async () => {
  for (const [result, message] of [
    [{ problem: "server" }, "Start the server with `pd serve` to generate briefs"],
    [{ problem: "token" }, "Server token missing or wrong — set it in the extension options"],
    [{ problem: "busy", message: "2 briefs already running" }, "2 briefs already running"],
  ]) {
    const { controller, events, time } = harness({ startRun: async () => result });
    await controller.generate();
    assert.deepEqual(events.at(-1), ["error", message]);
    assert.equal(time.pending(), 0);
  }
  const { controller, events, time } = harness({ runStatus: async () => ({ problem: "server" }) });
  await controller.generate();
  await time.advance(3);
  assert.deepEqual(events.at(-1), ["error", "Start the server with `pd serve` to generate briefs"]);
  assert.equal(time.pending(), 0);
});

test("a failed status poll is drawn as an error with the run's own line", async () => {
  const { controller, events, time } = harness({ runStatus: async () => ({ ok: true, state: "failed", error: "claude exited with status 1: boom" }) });
  await controller.generate();
  await time.advance(3);
  assert.deepEqual(events.at(-1), ["error", "claude exited with status 1: boom"]);
  const second = harness({ runStatus: async () => ({ ok: true, state: "failed" }) });
  await second.controller.generate();
  await second.time.advance(3);
  assert.deepEqual(second.events.at(-1), ["error", "The brief failed"]);
});

test("cancel asks the server, stops the clock and returns to idle", async () => {
  const { controller, events, calls, time } = harness();
  await controller.generate();
  await controller.cancel();
  assert.deepEqual(calls, ["start", "cancel"]);
  assert.deepEqual(events.at(-1), ["idle"]);
  assert.equal(time.pending(), 0);
});

test("a run that finished before the cancel arrived is reported done", async () => {
  const { controller, events } = harness({ cancelRun: async (run) => ({ ok: true, key: run.key, state: "done" }) });
  await controller.generate();
  await controller.cancel();
  assert.deepEqual(events.at(-1), ["done"]);
});

test("a run already going when the page opens is followed from its own stage and time", async () => {
  const { controller, events, time } = harness({ runStatus: async () => ({ ok: true, state: "done" }) });
  controller.adopt({ ok: true, state: "running", stage: "render", elapsed: 95 });
  assert.deepEqual(events, [["running", "render", 95]]);
  await time.advance(2);
  assert.deepEqual(events.slice(1), [["running", "render", 96], ["running", "render", 97]]);
  await time.advance(1);
  assert.deepEqual(events.at(-1), ["done"]);
});

test("stop ends the clock and ignores an answer that arrives afterwards", async () => {
  let release;
  const slow = new Promise((resolve) => (release = resolve));
  const { controller, events, time } = harness({ startRun: () => slow });
  const started = controller.generate();
  controller.stop();
  assert.equal(time.pending(), 0);
  release({ ok: true, key: "fj-7", state: "done" });
  await started;
  assert.deepEqual(events, [["running", "fetch", 0]]);
});

test("a second generate replaces the first: only the newer answer is drawn", async () => {
  let first;
  const answers = [new Promise((resolve) => (first = resolve)), Promise.resolve({ ok: true, key: "fj-7", state: "running" })];
  const { controller, events } = harness({ startRun: () => answers.shift() });
  const one = controller.generate();
  const two = controller.generate();
  await two;
  first({ problem: "server" });
  await one;
  assert.ok(events.every(([kind]) => kind === "running"));
});

test("describeResponse sorts what the server said", async () => {
  const { describeResponse } = await import("../serve_api.js");
  assert.deepEqual(describeResponse(undefined, new TypeError("Failed to fetch"), null), { problem: "server" });
  assert.deepEqual(describeResponse({ status: 403, ok: false }, undefined, { error: "auth" }), { problem: "token" });
  assert.deepEqual(describeResponse({ status: 403, ok: false }, undefined, { error: "repo_not_allowed", message: "no" }), { problem: "error", message: "no" });
  assert.deepEqual(describeResponse({ status: 429, ok: false }, undefined, { message: "2 briefs already running" }), { problem: "busy", message: "2 briefs already running" });
  assert.deepEqual(describeResponse({ status: 500, ok: false }, undefined, null), { problem: "error", message: "The server answered 500" });
  assert.deepEqual(describeResponse({ status: 200, ok: true }, undefined, { key: "7", state: "running" }), { ok: true, key: "7", state: "running" });
});
