// The PR brief card: the run's description, review order and diagram, in a collapsed <details> that the content
// script places above the PR's description on the conversation page. It lives in a shadow root, so neither
// page's CSS reaches it. The colours are the site's own (GitHub's Primer names, which the Forgejo adapter points at
// Forgejo's colours), with light and dark fallbacks for when the page defines none.
(() => {
  const ns = (globalThis.prFocus ??= {});

  const HOST_ID = "pr-brief";

  const STYLE = `
    :host { display: block; margin: 0 0 16px; }
    * { box-sizing: border-box; }
    .brief {
      --fg: var(--fgColor-default, #1f2328);
      --muted: var(--fgColor-muted, #59636e);
      --accent: var(--fgColor-accent, #0969da);
      --surface: var(--bgColor-default, #ffffff);
      --header: var(--bgColor-muted, #f6f8fa);
      --border: var(--borderColor-default, #d1d9e0);
      --code: var(--bgColor-neutral-muted, #818b981f);
      color: var(--fg);
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 6px;
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    }
    @media (prefers-color-scheme: dark) {
      .brief {
        --fg: var(--fgColor-default, #f0f6fc);
        --muted: var(--fgColor-muted, #9198a1);
        --accent: var(--fgColor-accent, #4493f8);
        --surface: var(--bgColor-default, #0d1117);
        --header: var(--bgColor-muted, #151b23);
        --border: var(--borderColor-default, #3d444d);
        --code: var(--bgColor-neutral-muted, #656c7633);
      }
    }
    .brief > summary {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      padding: 8px 16px;
      list-style: none;
      cursor: pointer;
      user-select: none;
      background: var(--header);
      border-radius: 5px;
    }
    .brief[open] > summary { border-bottom: 1px solid var(--border); border-radius: 5px 5px 0 0; }
    .brief > summary::-webkit-details-marker { display: none; }
    .chevron { width: 8px; height: 8px; border: solid var(--muted); border-width: 0 2px 2px 0; transform: rotate(-45deg); transition: transform 0.1s; }
    .brief[open] .chevron { transform: rotate(45deg); }
    .title { font-weight: 600; }
    .badge { padding: 0 7px; font-size: 12px; line-height: 18px; color: var(--muted); border: 1px solid var(--border); border-radius: 2em; }
    .files-link { margin-left: auto; color: var(--accent); font-size: 12px; text-decoration: none; }
    .files-link:hover { text-decoration: underline; }
    .content { padding: 16px; }
    .text > :first-child { margin-top: 0; }
    h1, h2, h3, h4 { margin: 16px 0 8px; font-size: 14px; line-height: 1.25; }
    p, ul, ol, details { margin: 0 0 12px; }
    ul, ol { padding-left: 24px; }
    li > ul { margin: 2px 0; }
    .text > ul > li, .text > ol > li { margin-bottom: 1.5em; }
    hr { height: 1px; margin: 12px 0; border: 0; background: var(--border); }
    code { padding: 0.1em 0.35em; font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; background: var(--code); border-radius: 4px; overflow-wrap: anywhere; }
    a { color: var(--accent); }
    sub { font-size: 12px; color: var(--muted); }
    summary { cursor: pointer; }
    summary h3 { display: inline; margin: 0; }
    details.diagram-box > summary { font-weight: 600; }
    .diagram { margin: 8px 0 0; }
    .paper { padding: 8px; overflow: auto; color: #1f2328; background: #ffffff; border: 1px solid var(--border); border-radius: 6px; }
    .paper svg { display: block; width: 100%; max-width: 100%; height: auto; }
    .legend { margin: 8px 0 0; font-size: 12px; color: var(--muted); }
    table.review-order { display: table; width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 13px; }
    table.review-order th, table.review-order td { padding: 6px 8px; vertical-align: top; text-align: left; border: 1px solid var(--border); overflow-wrap: anywhere; }
    table.review-order th { background: var(--header); }
    table.review-order th:nth-child(1) { width: 8%; }
    table.review-order th:nth-child(2) { width: 25%; }
    table.review-order th:nth-child(3) { width: 11%; }
    table.review-order th:nth-child(4) { width: 26%; }
    table.review-order table { width: 100%; table-layout: fixed; border-collapse: collapse; margin-top: 4px; }
    table.review-order table td { padding: 2px 0; border: 0; }
    details.files { margin: 0; }
    details.files > summary { color: var(--accent); }
  `;

  function escapeHtml(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // The description and the review order are split at the review order's <details>, so the diagram's own <details>
  // can sit between them.
  function splitOrder(html) {
    const at = html.indexOf("<details");
    return at === -1 ? { text: html, order: "" } : { text: html.slice(0, at), order: html.slice(at) };
  }

  // Returns the card for a run, closed. `key` and `variant` name the run; `filesUrl` is the PR's files view on this
  // host. The card holds no state: it is closed every time it is built.
  function buildBrief({ key, variant, bodyHtml, diagramSvg, filesUrl }) {
    const { html, legend } = ns.briefText.renderBody(bodyHtml, filesUrl);
    const svg = /^\s*<svg[\s>]/.test(diagramSvg ?? "") ? ns.briefText.sanitize(diagramSvg, "svg") : "";
    const { text, order } = splitOrder(html);
    const diagram = svg
      ? `<details class="diagram-box"><summary>Diagram</summary><figure class="diagram"><div class="paper" role="img" aria-label="Change diagram">${svg}</div>${legend ? `<p class="legend">${legend}</p>` : ""}</figure></details>`
      : "";

    const host = document.createElement("div");
    host.id = HOST_ID;
    host.setAttribute("data-run", key);
    host.setAttribute("data-variant", variant);
    host.attachShadow({ mode: "open" }).innerHTML =
      `<style>${STYLE}</style>` +
      '<details class="brief">' +
      '<summary><span class="chevron"></span><span class="title">PR brief</span>' +
      `<span class="badge" title="Run ${escapeHtml(key)}, variant ${escapeHtml(variant)}">local, not posted</span>` +
      `<a class="files-link" href="${escapeHtml(filesUrl)}">Review in files view</a></summary>` +
      `<div class="content"><div class="text">${text}</div>${diagram}` +
      `${order ? `<div class="order">${order}</div>` : ""}</div></details>`;
    return host;
  }

  ns.brief = { HOST_ID, buildBrief };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.brief;
