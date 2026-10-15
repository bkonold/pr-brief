const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

async function withCommands({ commands = true, stored = {} } = {}, body) {
  let onCommand;
  const written = [];
  const saved = globalThis.chrome;
  globalThis.chrome = {
    storage: { local: { get: async (defaults) => ({ ...defaults, ...stored }), set: async (items) => written.push(items) } },
    ...(commands ? { commands: { onCommand: { addListener: (callback) => (onCommand = callback) } } } : {}),
  };
  try {
    await import(`${pathToFileURL(path.join(__dirname, "../background.js")).href}?${Math.random()}`);
    return await body({ onCommand, written });
  } finally {
    globalThis.chrome = saved;
  }
}

test("the toggle-brief command flips the stored pane owner between the brief and the host", async () => {
  await withCommands({}, async ({ onCommand, written }) => {
    await onCommand("toggle-brief");
    assert.deepEqual(written, [{ paneOwner: "host" }]);
  });
  await withCommands({ stored: { paneOwner: "host" } }, async ({ onCommand, written }) => {
    await onCommand("toggle-brief");
    assert.deepEqual(written, [{ paneOwner: "brief" }]);
  });
});

test("a command other than toggle-brief changes nothing, and a browser without commands loads the background all the same", async () => {
  await withCommands({}, async ({ onCommand, written }) => {
    await onCommand("other");
    assert.deepEqual(written, []);
  });
  await withCommands({ commands: false }, async ({ onCommand }) => assert.equal(onCommand, undefined));
});
