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

async function loadDiagram(baseUrl, variant, pr, file) {
  if (!/^[\w.-]+\.svg$/.test(file ?? "")) return null;
  try {
    const response = await fetch(`${baseUrl}/runs/${pr}/${variant}/${file}`, { cache: "no-store" });
    return response.ok ? await response.text() : null;
  } catch {
    return null;
  }
}

// The variants this PR has runs for, from runs/<pr>/variants.json; empty when the file is missing.
async function loadVariants(baseUrl, pr) {
  try {
    const response = await fetch(`${baseUrl}/runs/${pr}/variants.json`, { cache: "no-store" });
    if (!response.ok) return [];
    const listed = await response.json();
    return Array.isArray(listed)
      ? listed.filter((entry) => SAFE_NAME.test(entry?.variant ?? "")).map((entry) => ({ ...entry, label: entry.label || entry.variant }))
      : [];
  } catch {
    return [];
  }
}

// The page server sends no CORS headers, so the fetch happens here rather than in the content script.
// `requested` is a variant the user just picked; otherwise the stored default decides.
async function loadReview({ owner, repo, pr, variant: requested }) {
  const { variant: stored, baseUrl } = await settings();
  const variants = await loadVariants(baseUrl, pr);
  const variant = SAFE_NAME.test(requested ?? "") ? requested : chooseVariant(stored, variants);
  let response;
  let failure;
  try {
    response = await fetch(`${baseUrl}/runs/${pr}/${variant}/review.json`, { cache: "no-store" });
  } catch (error) {
    failure = error;
  }
  const outcome = classifyFetch(response, failure);
  if (outcome === "server") return { error: "server", baseUrl };
  if (outcome === "none") return null;
  try {
    const review = await response.json();
    if (!matchesPr(review, owner, repo, pr)) return null;
    return { ...review, variants, diagramSvg: await loadDiagram(baseUrl, variant, pr, review.diagram) };
  } catch {
    return null;
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "loadReview") return false;
  loadReview(message).then(sendResponse);
  return true;
});
