// How a call to serve.py's /api/ went, as the background script hands it to the page. `response` is the fetch
// response (undefined when the request itself failed), `failure` the error it threw, `data` the parsed JSON body or
// null. A success is { ok: true, ...data }; anything else is { problem, message? } with `problem` one of "server"
// (nothing is listening), "token" (the server refused the token or origin), "busy" (two runs already going) or "error".
export function describeResponse(response, failure, data) {
  if (failure !== undefined || !response) return { problem: "server" };
  if (response.status === 403 && data?.error === "auth") return { problem: "token" };
  if (response.status === 429) return { problem: "busy", message: data?.message };
  if (!response.ok) return { problem: "error", message: data?.message ?? `The server answered ${response.status}` };
  return { ok: true, ...data };
}

export const TOKEN_HEADER = "X-PR-Brief-Token";
