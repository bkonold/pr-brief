// How a fetch of review.json went: "server" when the request itself failed (connection refused, network error),
// "none" for a response that isn't OK (a 404: this PR has no run), "ok" otherwise.
export function classifyFetch(response, error) {
  if (error !== undefined) return "server";
  return response?.ok ? "ok" : "none";
}
