import { classifyFetch } from "./classify.js";
import { DEFAULTS, TOKEN_KEY } from "./defaults.js";
import { TOKEN_HEADER, describeResponse } from "./serve_api.js";

const SAFE_NAME = /^[\w.-]+$/;

// The run server's base URL, "" when none is set. Without one the extension makes no request to a server.
async function settings() {
  const stored = await chrome.storage.sync.get(DEFAULTS);
  return { baseUrl: String(stored.baseUrl || DEFAULTS.baseUrl).trim().replace(/\/+$/, "") };
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

// The server's { default_variant }, or the server's problem ({ problem }) when it can't be read: nothing is listening,
// or the token is missing or wrong.
async function loadConfig() {
  const config = await callServer("/api/config");
  return config.ok && typeof config.default_variant === "string" ? config : { problem: config.problem ?? "error" };
}

// The run a PR page shows: its review.json and the server's default variant it was read from. Null when the PR has
// no run or no server URL is set; { error: "old" } when its run was written by an older version; { error: "server" } when the page server
// can't be reached. The page server sends no CORS headers, so the fetch happens here rather than in the content script.
async function findRun({ owner, repo, pr, key: requestedKey }) {
  const { baseUrl } = await settings();
  if (!baseUrl) return null;
  const key = SAFE_NAME.test(requestedKey ?? "") ? requestedKey : String(pr);
  const config = await loadConfig();
  const variant = config.default_variant;
  if (!SAFE_NAME.test(variant ?? "")) return config.problem === "server" ? { error: "server", baseUrl } : null;
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
    return isCurrentRun(review) ? { baseUrl, key, variant, review } : { error: "old", baseUrl };
  } catch {
    return null;
  }
}

async function loadReview(request) {
  const run = await findRun(request);
  if (!run || run.error) return run;
  const { baseUrl, key, variant, review } = run;
  return { ...review, diagramSvg: await loadDiagram(baseUrl, variant, key, review.diagram) };
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
  return bodyHtml === null ? null : { variant, model: review.model ?? null, bodyHtml, diagramSvg, headSha: review.head_sha ?? null, origin: "server" };
}

// One call to serve.py's /api/ with the token; see describeResponse for the shapes that come back, and
// { ok: false, problem: "unset" } when no server URL is set, in which case nothing is requested.
async function callServer(path, { method = "GET", body } = {}) {
  const { baseUrl } = await settings();
  if (!baseUrl) return { ok: false, problem: "unset" };
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
