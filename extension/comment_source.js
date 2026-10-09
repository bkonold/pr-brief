// Reads a brief out of the pull request's own comment: the Action posts it with a collapsed "Brief data" block whose
// code fence holds the base64 of the gzip of review.json plus the run's `diagram_svg` and `body_html`. Nothing here
// needs a server or a token; the page's own session reads the comment. The DOM-touching parts are thin (a selector
// and a fetch), so the selection and the decoding are tested without a browser.
(() => {
  const ns = (globalThis.prFocus ??= {});

  const SUMMARY = "Brief data";
  // GitHub renders a comment's markdown in `.markdown-body`, Forgejo in `.render-content.markup`. Other <details>
  // elements on the page (Forgejo's "View command line instructions") are outside both.
  const DETAILS = ".markdown-body details, .render-content.markup details";
  // A brief's JSON is a few hundred KB at most; a payload that inflates past this is not one.
  const MAX_INFLATED_BYTES = 16 * 1024 * 1024;

  // The text of the code fence in the earliest "Brief data" block of `doc` (a Document or a DocumentFragment), in
  // document order, or null when the page has none.
  function extractPayload(doc) {
    for (const details of doc.querySelectorAll(DETAILS)) {
      if (details.querySelector("summary")?.textContent.trim() !== SUMMARY) continue;
      const text = details.querySelector("pre")?.textContent.trim();
      if (text) return text;
    }
    return null;
  }

  // The JSON object that `base64` holds as gzip, or null when it is not base64, not gzip, too large or not an object.
  async function inflate(base64) {
    try {
      const bytes = Uint8Array.from(atob(String(base64).replace(/\s+/g, "")), (char) => char.charCodeAt(0));
      const reader = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip")).getReader();
      const decoder = new TextDecoder();
      let text = "";
      let size = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.length;
        if (size > MAX_INFLATED_BYTES) {
          await reader.cancel();
          return null;
        }
        text += decoder.decode(value, { stream: true });
      }
      const data = JSON.parse(text + decoder.decode());
      return data !== null && typeof data === "object" && !Array.isArray(data) ? data : null;
    } catch {
      return null;
    }
  }

  // { review, bodyHtml, diagramSvg } for the brief in `doc`, or null when it has none or it cannot be read. `review`
  // is the posted review.json as it was, without the two keys the Action added.
  async function readBrief(doc) {
    const encoded = extractPayload(doc);
    const data = encoded ? await inflate(encoded) : null;
    if (!data) return null;
    const { diagram_svg: diagramSvg, body_html: bodyHtml, ...review } = data;
    return {
      review,
      bodyHtml: typeof bodyHtml === "string" ? bodyHtml : null,
      diagramSvg: typeof diagramSvg === "string" ? diagramSvg : null,
    };
  }

  // The page at `url` as a Document, read with the user's own session, or null when the request fails or is refused.
  async function fetchConversation(url) {
    try {
      const response = await fetch(url, { credentials: "include", cache: "no-store" });
      return response.ok ? new DOMParser().parseFromString(await response.text(), "text/html") : null;
    } catch {
      return null;
    }
  }

  ns.commentSource = { extractPayload, inflate, readBrief, fetchConversation };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.commentSource;
