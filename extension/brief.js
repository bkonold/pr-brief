// The PR brief card: the run's description, review order and diagram, in a collapsed <details> that the content
// script places above the PR's description on the conversation page. Before there is a run it is a bar with a
// "Generate brief" button, while one is being written a bar with the stage pills and a Cancel link, and when the run
// is for an older head commit than the page's the badge says so and a Regenerate button appears; otherwise a quiet
// Regenerate link sits in the header. It lives in a
// shadow root, so neither page's CSS reaches it. The colours are the site's own (GitHub's Primer names, which the Forgejo adapter points at
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
      --success: var(--fgColor-success, #1a7f37);
      --danger: var(--fgColor-danger, #d1242f);
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
        --success: var(--fgColor-success, #3fb950);
        --danger: var(--fgColor-danger, #f85149);
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
    .bar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 8px 16px; background: var(--header); border-radius: 5px; }
    .bar .btn, .bar .link { margin-left: auto; }
    .btn { padding: 1px 12px; font: inherit; font-size: 12px; line-height: 20px; color: var(--fg); background: var(--surface); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; }
    .btn:hover { background: var(--header); }
    .link { padding: 0; font: inherit; font-size: 12px; color: var(--accent); background: none; border: 0; cursor: pointer; }
    .link:hover { text-decoration: underline; }
    summary .btn, summary .link { margin-left: auto; }
    summary .btn + .files-link, summary .link + .files-link { margin-left: 0; }
    .link.quiet { color: var(--muted); }
    .link.quiet:hover { color: var(--accent); }
    .progress { color: var(--muted); font-variant-numeric: tabular-nums; }
    .stages { display: flex; flex-wrap: wrap; gap: 8px; margin: 0; padding: 12px 16px; list-style: none; }
    .pill { padding: 0 10px; font-size: 12px; line-height: 20px; color: var(--muted); border: 1px solid var(--border); border-radius: 2em; }
    .pill.done { color: var(--success); border-color: var(--success); }
    .pill.current { color: var(--accent); border-color: var(--accent); font-weight: 600; }
    .error { margin: 0; padding: 12px 16px; color: var(--danger); }
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
    .pill.p0 { font-weight: 600; color: var(--surface); background: var(--fg); border-color: var(--fg); }
    .pill.p1 { font-weight: 600; color: var(--fg); border-color: var(--fg); }
    .text details { margin: 0 0 6px; }
    .text details > summary { line-height: 22px; }
    .text details > summary .pill { margin: 0 4px; font-size: 11px; line-height: 16px; padding: 0 7px; }
    .text details > ul { margin: 4px 0 8px; padding-left: 20px; }
    .text details li { margin-bottom: 4px; }
    ul.contract { margin: 0 0 12px; padding-left: 20px; }
    .text > ul.contract > li { margin-bottom: 4px; }
    .order-switch { margin: 4px 0 8px; font-size: 12px; color: var(--muted); }
    .order-switch .link { margin: 0 2px; }
    .order-switch .link[aria-pressed="true"] { color: var(--fg); font-weight: 600; cursor: default; text-decoration: none; }
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
    details.start { margin: 0; }
    details.start > summary { font-size: 12px; line-height: 18px; color: var(--accent); }
    details.start[open] > summary { margin-bottom: 2px; }
    details.files > summary { color: var(--accent); }
  `;

  function escapeHtml(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // The description and the review order are split at the review order's <details>, so the diagram's own <details>
  // can sit between them. The <details> groups of the Contract and Data sections stay in the description.
  function splitOrder(html) {
    const table = html.indexOf('class="review-order"');
    const at = table === -1 ? html.indexOf("<details") : html.lastIndexOf("<details", table);
    return at === -1 ? { text: html, order: "" } : { text: html.slice(0, at), order: html.slice(at) };
  }

  const ORDERS = [["flow", "by flow"], ["risk", "by risk"]];
  const DEFAULT_ORDER = "flow";

  // The "Order: by flow | by risk" switch, drawn only for a review order whose rows carry both ranks. Its buttons
  // are `order:<mode>` actions.
  function orderSwitch(mode) {
    const buttons = ORDERS.map(([value, label]) => `<button class="link" type="button" data-action="order:${value}" aria-pressed="${value === mode}">${label}</button>`);
    return `<div class="order-switch">Order: ${buttons.join(" | ")}</div>`;
  }

  // The review-order block in `mode` ("flow" unless the view asks for "risk"), with the switch under its heading.
  function orderBlock(order, mode) {
    if (!ns.briefText.hasOrders(order)) return order;
    const shown = mode === "risk" ? "risk" : DEFAULT_ORDER;
    const ordered = ns.briefText.orderRows(order, shown);
    const heading = ordered.indexOf("</summary>");
    return heading === -1 ? ordered : `${ordered.slice(0, heading + "</summary>".length)}${orderSwitch(shown)}${ordered.slice(heading + "</summary>".length)}`;
  }

  const SHORT_SHA = 7;

  // `text` escaped, with `code` spans in backticks drawn as <code>.
  function formatMessage(text) {
    return escapeHtml(text).replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function short(sha) {
    return String(sha).slice(0, SHORT_SHA);
  }

  // True when the run was made for another head commit than the one the page shows; unknown shas are never stale.
  function isStale(runSha, pageSha) {
    return Boolean(runSha && pageSha && String(runSha).toLowerCase() !== String(pageSha).toLowerCase());
  }

  function badge(key, variant, label) {
    const where = variant ? `Run ${escapeHtml(key)}, variant ${escapeHtml(variant)}` : "No run yet";
    return `<span class="badge" title="${where}">${escapeHtml(label)}</span>`;
  }

  const TITLE = '<span class="title">PR brief</span>';

  function bar(inner) {
    return `<div class="brief"><div class="bar">${TITLE}${inner}</div>`;
  }

  // The card as HTML for one view:
  //   { kind: "none", canGenerate }                         no run yet
  //   { kind: "running", stage, elapsed }                   a run is going
  //   { kind: "error", message }                            the call or the run failed
  //   { kind: "brief", variant, bodyHtml, diagramSvg, runSha, pageSha, canGenerate, order }   a run, closed
  //                                                       (`order`: "flow", the default, or "risk" for the review order)
  // `key` and `filesUrl` name the run and the PR's files view on this host. Every button is a
  // data-action: generate, cancel.
  function cardHtml(view, { key, filesUrl }) {
    if (view.kind === "none") {
      return bar(`${badge(key, null, "local, not posted")}${view.canGenerate === false ? "" : '<button class="btn" type="button" data-action="generate">Generate brief</button>'}`) + "</div>";
    }
    if (view.kind === "running") {
      const pills = ns.runControl.stagePills(view.stage).map((pill) => `<li class="pill ${pill.state}">${escapeHtml(pill.label)}</li>`).join("");
      return (
        bar(`${badge(key, null, "local, not posted")}<span class="progress">Writing brief · ${ns.runControl.formatElapsed(view.elapsed)}</span><button class="link" type="button" data-action="cancel">Cancel</button>`) +
        `<ol class="stages" aria-label="Brief progress">${pills}</ol></div>`
      );
    }
    if (view.kind === "error") {
      return bar(`${badge(key, null, "local, not posted")}<button class="btn" type="button" data-action="generate">Retry</button>`) + `<p class="error" role="alert">${formatMessage(view.message)}</p></div>`;
    }
    const { html, legend } = ns.briefText.renderBody(view.bodyHtml, filesUrl);
    const svg = /^\s*<svg[\s>]/.test(view.diagramSvg ?? "") ? ns.briefText.sanitize(view.diagramSvg, "svg") : "";
    const { text, order } = splitOrder(html);
    const diagram = svg
      ? `<details class="diagram-box"><summary>Diagram</summary><figure class="diagram"><div class="paper" role="img" aria-label="Change diagram">${svg}</div>${legend ? `<p class="legend">${legend}</p>` : ""}</figure></details>`
      : "";
    const stale = isStale(view.runSha, view.pageSha);
    const label = stale ? `for ${short(view.runSha)}, PR is at ${short(view.pageSha)}` : "local, not posted";
    const regenerate =
      view.canGenerate === false
        ? ""
        : stale
          ? '<button class="btn" type="button" data-action="generate">Regenerate</button>'
          : '<button class="link quiet" type="button" data-action="generate">Regenerate</button>';
    return (
      '<details class="brief">' +
      `<summary><span class="chevron"></span>${TITLE}${badge(key, view.variant, label)}${regenerate}` +
      `<a class="files-link" href="${escapeHtml(filesUrl)}">Review in files view</a></summary>` +
      `<div class="content"><div class="text">${text}</div>${diagram}` +
      `${order ? `<div class="order">${orderBlock(order, view.order)}</div>` : ""}</div></details>`
    );
  }

  // Builds the card host for a run folder `key`, empty until `show(view)` draws it (see cardHtml for the views).
  // `onAction(name)` is called with "generate" or "cancel" when the matching button is clicked. The "order:flow" and
  // "order:risk" buttons only reorder the review order in place, keeping it open; the choice is not remembered, and
  // the next `show` draws the default order again. A brief view is drawn closed every time.
  function buildCard({ key, filesUrl, onAction }) {
    const host = document.createElement("div");
    host.id = HOST_ID;
    host.setAttribute("data-run", key);
    const shadow = host.attachShadow({ mode: "open" });
    let shown = null;

    function reorder(mode) {
      if (shown?.kind !== "brief") return;
      shown = { ...shown, order: mode };
      const target = shadow.querySelector?.(".order");
      if (!target) return;
      const wasOpen = target.querySelector?.("details")?.open;
      target.innerHTML = orderBlock(splitOrder(ns.briefText.renderBody(shown.bodyHtml, filesUrl).html).order, mode);
      if (wasOpen) target.querySelector?.("details")?.setAttribute?.("open", "");
    }

    shadow.addEventListener?.("click", (event) => {
      const action = event.target?.closest?.("[data-action]")?.getAttribute("data-action");
      if (!action) return;
      event.preventDefault();
      if (action.startsWith("order:")) reorder(action.slice("order:".length));
      else onAction?.(action);
    });
    host.show = (view) => {
      shown = view;
      if (view.variant) host.setAttribute("data-variant", view.variant);
      shadow.innerHTML = `<style>${STYLE}</style>${cardHtml(view, { key, filesUrl })}`;
    };
    return host;
  }

  // The card for a run that exists, drawn closed.
  function buildBrief({ key, variant, bodyHtml, diagramSvg, filesUrl, runSha, pageSha, onAction }) {
    const host = buildCard({ key, filesUrl, onAction });
    host.show({ kind: "brief", variant, bodyHtml, diagramSvg, runSha, pageSha });
    return host;
  }

  ns.brief = { splitOrder, HOST_ID, buildCard, buildBrief, cardHtml, isStale, orderBlock };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.brief;
