import { chooseVariant } from "./choose_variant.js";
import { classifyFetch } from "./classify.js";
import { DEFAULTS } from "./defaults.js";

const SAFE_NAME = /^[\w.-]+$/;

async function settings() {
  const stored = await chrome.storage.sync.get(DEFAULTS);
  return { variant: stored.variant || DEFAULTS.variant, baseUrl: (stored.baseUrl || DEFAULTS.baseUrl).replace(/\/+$/, "") };
}

function matchesPr(review, owner, repo, pr) {
  return (
    review?.schema === 2 &&
    Array.isArray(review.chunks) &&
    String(review.repo).toLowerCase() === `${owner}/${repo}`.toLowerCase() &&
    Number(review.pr) === Number(pr)
  );
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

// The variants this PR has runs for, from runs/<key>/variants.json; empty when the file is missing.
async function loadVariants(baseUrl, key) {
  try {
    const response = await fetch(`${baseUrl}/runs/${key}/variants.json`, { cache: "no-store" });
    if (!response.ok) return [];
    const listed = await response.json();
    return Array.isArray(listed)
      ? listed.filter((entry) => SAFE_NAME.test(entry?.variant ?? "")).map((entry) => ({ ...entry, label: entry.label || entry.variant }))
      : [];
  } catch {
    return [];
  }
}

// The run a PR page shows: its review.json, the variant that was read and the PR's variants. Null when the PR has
// no usable run; { error: "server" } when the page server can't be reached. The page server sends no CORS headers,
// so the fetch happens here rather than in the content script. `requested` is a variant the user just picked;
// otherwise the stored default decides.
async function findRun({ owner, repo, pr, variant: requested, key: requestedKey }) {
  const { variant: stored, baseUrl } = await settings();
  const key = SAFE_NAME.test(requestedKey ?? "") ? requestedKey : String(pr);
  const variants = await loadVariants(baseUrl, key);
  const variant = SAFE_NAME.test(requested ?? "") ? requested : chooseVariant(stored, variants);
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
    return matchesPr(review, owner, repo, pr) ? { baseUrl, key, variant, variants, review } : null;
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
  return bodyHtml === null ? null : { variant, bodyHtml, diagramSvg };
}

const HANDLERS = { loadReview, loadBrief };

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!Object.hasOwn(HANDLERS, message?.type)) return false;
  HANDLERS[message.type](message).then(sendResponse);
  return true;
});
