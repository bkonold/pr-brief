import { chooseVariant, switcherVariants } from "./choose_variant.js";
import { classifyFetch } from "./classify.js";
import { DEFAULTS, TOKEN_KEY } from "./defaults.js";
import { TOKEN_HEADER, describeResponse } from "./serve_api.js";

const SAFE_NAME = /^[\w.-]+$/;

async function settings() {
  const stored = await chrome.storage.sync.get(DEFAULTS);
  return { baseUrl: (stored.baseUrl || DEFAULTS.baseUrl).replace(/\/+$/, "") };
}

// The server token lives in chrome.storage.local, which no other device or page script can read. Only this script
// sends it, so the content scripts never see it.
async function serverToken() {
  const stored = await chrome.storage.local.get({ [TOKEN_KEY]: "" });
  return String(stored[TOKEN_KEY] ?? "").trim();
}

function namesPr(review, owner, repo, pr) {
  return String(review?.repo).toLowerCase() === `${owner}/${repo}`.toLowerCase() && Number(review.pr) === Number(pr);
}

// A review.json this version writes: the current schema, with the walkthrough the pane lists.
function isCurrentRun(review) {
  return review.schema === 4 && review.nodes !== null && typeof review.nodes === "object" && Array.isArray(review.walkthrough);
}

// A text file of a run, or null when it can't be read.
async function loadRunFile(baseUrl, variant, key, file) {
  try {
    const response = await fetch(`${baseUrl}/runs/${key}/${variant}/${file}`, { cache: "no-store" });
    return response.ok ? await response.text() : null;
  } catch {
    return null;
  }
}

async function loadDiagram(baseUrl, variant, key, file) {
  return /^[\w.-]+\.svg$/.test(file ?? "") ? loadRunFile(baseUrl, variant, key, file) : null;
}

// The variants this PR has runs for, from runs/<key>/variants.json: empty when the file is missing, null when the
// page server can't be reached.
async function loadVariants(baseUrl, key) {
  let response;
  try {
    response = await fetch(`${baseUrl}/runs/${key}/variants.json`, { cache: "no-store" });
  } catch {
    return null;
  }
  if (!response.ok) return [];
  try {
    const listed = await response.json();
    return Array.isArray(listed)
      ? listed.filter((entry) => SAFE_NAME.test(entry?.variant ?? "")).map((entry) => ({ ...entry, label: entry.label || entry.variant }))
      : [];
  } catch {
    return [];
  }
}

// The server's { default_variant, variants }, or null when it can't be read (server down, token missing or wrong).
async function loadConfig() {
  const config = await callServer("/api/config");
  return config.ok && Array.isArray(config.variants) ? config : null;
}

// The run a PR page shows: its review.json, the variant that was read and the PR's variants. Null when the PR has
// no run; { error: "old" } when its run was written by an older version; { error: "server" } when the page server
// can't be reached. The page server sends no CORS headers,
// so the fetch happens here rather than in the content script. `requested` is a variant picked on the page; otherwise
// chooseVariant decides from the server's config. The variants returned are the ones the switcher may list.
async function findRun({ owner, repo, pr, variant: requested, key: requestedKey }) {
  const { baseUrl } = await settings();
  const key = SAFE_NAME.test(requestedKey ?? "") ? requestedKey : String(pr);
  const [available, config] = await Promise.all([loadVariants(baseUrl, key), loadConfig()]);
  const variant = chooseVariant(SAFE_NAME.test(requested ?? "") ? requested : undefined, config, available);
  if (!SAFE_NAME.test(variant ?? "")) return available === null && config === null ? { error: "server", baseUrl } : null;
  const variants = switcherVariants(available, config);
  let response;
  let failure;
  try {
    response = await fetch(`${baseUrl}/runs/${key}/${variant}/review.json`, { cache: "no-store" });
  } catch (error) {
    failure = error;
  }
  const outcome = classifyFetch(response, failure);
  if (outcome === "server") return { error: "server", baseUrl };
  if (outcome === "none") return null;
  try {
    const review = await response.json();
    if (!namesPr(review, owner, repo, pr)) return null;
    return isCurrentRun(review) ? { baseUrl, key, variant, variants, review } : { error: "old", baseUrl };
  } catch {
    return null;
  }
}

async function loadReview(request) {
  const run = await findRun(request);
  if (!run || run.error) return run;
  const { baseUrl, key, variant, variants, review } = run;
  return { ...review, variants, diagramSvg: await loadDiagram(baseUrl, variant, key, review.diagram) };
}

// The PR brief card reads the run's rendered description and its diagram.
async function loadBrief(request) {
  const run = await findRun(request);
  if (!run || run.error) return run;
  const { baseUrl, key, variant, review } = run;
  const [bodyHtml, diagramSvg] = await Promise.all([
    loadRunFile(baseUrl, variant, key, "body.html"),
    loadDiagram(baseUrl, variant, key, review.diagram),
  ]);
  return bodyHtml === null ? null : { variant, bodyHtml, diagramSvg, headSha: review.head_sha ?? null };
}

// One call to serve.py's /api/ with the token; see describeResponse for the shapes that come back.
async function callServer(path, { method = "GET", body } = {}) {
  const { baseUrl } = await settings();
  const headers = { [TOKEN_HEADER]: await serverToken() };
  if (body) headers["Content-Type"] = "application/json";
  let response;
  let failure;
  let data = null;
  try {
    response = await fetch(`${baseUrl}${path}`, { method, headers, body: body && JSON.stringify(body), cache: "no-store" });
    data = await response.json().catch(() => null);
  } catch (error) {
    failure = error;
  }
  return describeResponse(response, failure, data);
}

// Starts a run for the PR on the page: { ok, key, state }.
function startRun({ host, owner, repo, pr }) {
  return callServer("/api/run", { method: "POST", body: { host, owner, repo, n: pr } });
}

// A run's progress: { ok, state, stage, elapsed, error? }. With host, owner and repo it also says whether the
// server may start runs for that repository (`allowed`).
function runStatus({ key, host, owner, repo }) {
  const query = new URLSearchParams({ key, ...(host ? { host, owner, repo } : {}) });
  return callServer(`/api/status?${query}`);
}

// The PR's current head commit as the server reads it from the host: { ok, sha } with `sha` null when the host
// could not say. The server answers only for repositories it may run.
function headSha({ host, owner, repo, pr }) {
  const query = new URLSearchParams({ host, owner, repo, n: String(pr) });
  return callServer(`/api/head?${query}`);
}

function cancelRun({ key }) {
  return callServer("/api/cancel", { method: "POST", body: { key } });
}

const HANDLERS = { loadReview, loadBrief, startRun, runStatus, cancelRun, headSha };

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!Object.hasOwn(HANDLERS, message?.type)) return false;
  HANDLERS[message.type](message).then(sendResponse);
  return true;
});
