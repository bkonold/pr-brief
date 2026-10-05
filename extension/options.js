import { DEFAULTS, TOKEN_KEY } from "./defaults.js";

const form = document.getElementById("form");
const status = document.getElementById("status");

async function load() {
  const stored = await chrome.storage.sync.get(DEFAULTS);
  form.variant.value = stored.variant;
  form.baseUrl.value = stored.baseUrl;
  form.token.value = (await chrome.storage.local.get({ [TOKEN_KEY]: "" }))[TOKEN_KEY];
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await chrome.storage.sync.set({ variant: form.variant.value.trim(), baseUrl: form.baseUrl.value.trim() });
  await chrome.storage.local.set({ [TOKEN_KEY]: form.token.value.trim() });
  status.textContent = "Saved";
});

load();
