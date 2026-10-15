import { PANE_OWNER_KEY } from "./defaults.js";

// The keyboard shortcut flips who owns the file pane; every open PR page follows the stored value. `chrome.commands` is
// absent where the browser has no command support.
chrome.commands?.onCommand.addListener(async (command) => {
  if (command !== "toggle-brief") return;
  const stored = await chrome.storage.local.get({ [PANE_OWNER_KEY]: "brief" });
  await chrome.storage.local.set({ [PANE_OWNER_KEY]: stored[PANE_OWNER_KEY] === "host" ? "brief" : "host" });
});
