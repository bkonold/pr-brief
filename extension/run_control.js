// Starts a brief on the run server and follows it: one controller per PR page, shared by the brief card and the
// files view's "Generate brief" line. It owns the polling (status every 3 s) and the one-second clock that makes
// "Writing brief · m:ss" tick between polls, and reports what the page should draw through `on`:
//   on.running({ stage, elapsed })  a run is going; `elapsed` is seconds
//   on.error({ message })           the call or the run failed; the page offers Retry
//   on.idle()                       nothing is running (canceled, or the status vanished): draw the base view
//   on.done()                       the run finished: load and draw the brief
// `run` is { host, owner, repo, pr, key } and goes to the source calls as is.
(() => {
  const ns = (globalThis.prFocus ??= {});

  const POLL_MS = 3000;
  const TICK_MS = 1000;

  const STAGES = [
    { id: "fetch", label: "Fetch PR" },
    { id: "context", label: "Gather context" },
    { id: "write", label: "Write" },
    { id: "render", label: "Render" },
  ];

  const MESSAGES = {
    server: "Start the server with `pd serve` to generate briefs",
    token: "Server token missing or wrong — set it in the extension options",
  };

  // What a failed call tells the reader.
  function problemMessage(result) {
    if (result.problem === "busy") return result.message || "2 briefs already running";
    return MESSAGES[result.problem] ?? result.message ?? "The server could not start the brief";
  }

  // 83 seconds is "1:23".
  function formatElapsed(seconds) {
    const whole = Math.max(0, Math.floor(seconds));
    return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
  }

  // Each stage as { id, label, state: "done" | "current" | "pending" } for the stage pills. A stage the server
  // does not know (or none) leaves the first one current.
  function stagePills(stage) {
    const at = Math.max(0, STAGES.findIndex((entry) => entry.id === stage));
    return STAGES.map((entry, index) => ({ ...entry, state: index < at ? "done" : index === at ? "current" : "pending" }));
  }

  function create({ source, run, on, timers = globalThis, now = Date.now }) {
    let generation = 0;
    let pollTimer = null;
    let tickTimer = null;
    let last = { stage: "fetch", elapsed: 0, at: now() };

    function stopTimers() {
      if (pollTimer !== null) timers.clearTimeout(pollTimer);
      if (tickTimer !== null) timers.clearInterval(tickTimer);
      pollTimer = null;
      tickTimer = null;
    }

    function draw() {
      on.running({ stage: last.stage, elapsed: last.elapsed + Math.max(0, Math.floor((now() - last.at) / 1000)) });
    }

    function show(result) {
      last = { stage: result.stage ?? last.stage, elapsed: result.elapsed ?? last.elapsed, at: now() };
      draw();
    }

    function follow(token) {
      if (tickTimer === null) tickTimer = timers.setInterval(draw, TICK_MS);
      pollTimer = timers.setTimeout(() => poll(token), POLL_MS);
    }

    async function poll(token) {
      pollTimer = null;
      const result = await source.runStatus(run);
      if (token === generation) handle(result, token);
    }

    // Draws what a status or a start answer says, and keeps following the run while it is running.
    function handle(result, token) {
      if (result.problem) {
        stopTimers();
        on.error({ message: problemMessage(result) });
      } else if (result.state === "running") {
        show(result);
        follow(token);
      } else if (result.state === "done") {
        stopTimers();
        on.done();
      } else if (result.state === "failed") {
        stopTimers();
        on.error({ message: result.error || "The brief failed" });
      } else {
        stopTimers();
        on.idle();
      }
    }

    // Starts a run (or joins the one already going for this PR).
    async function generate() {
      generation += 1;
      const token = generation;
      stopTimers();
      last = { stage: "fetch", elapsed: 0, at: now() };
      draw();
      tickTimer = timers.setInterval(draw, TICK_MS);
      const result = await source.startRun(run);
      if (token === generation) handle(result, token);
    }

    // Follows a run the server already reports as running, for a visit that began while it was going.
    function adopt(status) {
      generation += 1;
      stopTimers();
      handle(status, generation);
    }

    async function cancel() {
      generation += 1;
      const token = generation;
      stopTimers();
      const result = await source.cancelRun(run);
      if (token === generation) handle(result, token);
    }

    function stop() {
      generation += 1;
      stopTimers();
    }

    return { generate, adopt, cancel, stop };
  }

  ns.runControl = { create, stagePills, formatElapsed, problemMessage, STAGES };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.runControl;
