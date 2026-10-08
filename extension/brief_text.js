// The text half of the PR brief card: turns a run's body.html into the safe HTML the card shows. All of it is pure
// string work, so it runs (and is tested) without a DOM. render.py's body.html is a standalone page that draws
// itself, with the description as a markdown string in a script, so renderBody reads that string and renders the
// subset of markdown render.py writes, then removes anything that could run script.
(() => {
  const ns = (globalThis.prFocus ??= {});

  const MD_LITERAL = /const md = ("(?:[^"\\]|\\.)*");/;
  const BLOCK_HTML = /^\s{0,3}<\/?(?:details|summary|table|thead|tbody|tr|td|th|div|p|ul|ol|li|h[1-6]|hr|blockquote|pre|section|figure)\b/i;
  const DIAGRAM_HEADING = /^diagram walkthrough$/i;

  // The markdown string body.html feeds to marked, or null when the page has none.
  function extractMarkdown(bodyHtml) {
    const literal = MD_LITERAL.exec(bodyHtml)?.[1];
    if (literal === undefined) return null;
    try {
      const md = JSON.parse(literal);
      return typeof md === "string" ? md : null;
    } catch {
      return null;
    }
  }

  const CAPTION = /^Dashed boxes are unchanged context$/;

  function escapeText(text) {
    return text.replace(/&(?!#?\w+;)/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Inline markdown: code spans, bold, italics and links. Tags written inline pass through for sanitize to judge;
  // every other `<` is text.
  function inline(text) {
    return text
      .split(/(`[^`]+`)/)
      .map((part, index) => {
        if (index % 2) return `<code>${escapeText(part.slice(1, -1))}</code>`;
        return part
          .split(/(<\/?[a-zA-Z][^>]*>)/)
          .map((piece, at) => (at % 2 ? piece : escapeText(piece)))
          .join("")
          .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
          .replace(/(^|[^*\w])\*([^*\s][^*]*)\*(?![*\w])/g, "$1<em>$2</em>")
          .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2">$1</a>');
      })
      .join("");
  }

  const TABLE_SEPARATOR = /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$/;

  // The cells of a pipe-table row; `\|` is a pipe inside a cell.
  function tableCells(row) {
    return row
      .trim()
      .replace(/^\|/, "")
      .replace(/(?<!\\)\|$/, "")
      .split(/(?<!\\)\|/)
      .map((cell) => cell.replace(/\\\|/g, "|").trim());
  }

  // A pipe table as HTML.
  function renderTable(rows) {
    const [head, , ...body] = rows.map(tableCells);
    const header = `<thead><tr>${head.map((cell) => `<th>${inline(cell)}</th>`).join("")}</tr></thead>`;
    const lines = body.map((cells) => `<tr>${cells.map((cell) => `<td>${inline(cell)}</td>`).join("")}</tr>`);
    return `<table>${header}<tbody>${lines.join("")}</tbody></table>`;
  }

  // Renders the markdown render.py writes: headings, rules, nested lists, pipe tables, paragraphs, fenced code and raw
  // HTML blocks. The title heading and the "Diagram Walkthrough" section's heading and mermaid fence are left out (the
  // page shows the title and the card shows the rendered diagram); the paragraph after them that says the diagram's
  // dashed boxes are unchanged context is returned apart as `caption` so it can sit under the diagram.
  function renderMarkdown(md) {
    const lines = md.replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    const lists = [];
    let caption = "";
    let paragraph = [];

    function closeLists(toIndent = -1) {
      while (lists.length && lists.at(-1) > toIndent) {
        lists.pop();
        out.push("</li></ul>");
      }
    }

    function flushParagraph() {
      if (!paragraph.length) return;
      const html = inline(paragraph.join("\n"));
      if (CAPTION.test(paragraph.join(" ").trim())) caption = html;
      else out.push(`<p>${html}</p>`);
      paragraph = [];
    }

    for (let at = 0; at < lines.length; at += 1) {
      const line = lines[at];
      const trimmed = line.trim();
      if (trimmed === "") {
        flushParagraph();
        continue;
      }
      if (/^<!--.*-->$/.test(trimmed)) continue;

      const fence = /^\s*(`{3,}|~{3,})\s*([\w-]*)/.exec(line);
      if (fence) {
        flushParagraph();
        closeLists();
        const body = [];
        for (at += 1; at < lines.length && !lines[at].trim().startsWith(fence[1]); at += 1) body.push(lines[at]);
        if (fence[2] !== "mermaid") out.push(`<pre><code>${escapeText(body.join("\n"))}</code></pre>`);
        continue;
      }

      const heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);
      if (heading && line.trimStart() === line) {
        flushParagraph();
        closeLists();
        const text = heading[2];
        if (heading[1].length > 1 && !DIAGRAM_HEADING.test(text.replace(/[*_`]/g, ""))) {
          out.push(`<h${heading[1].length}>${inline(text)}</h${heading[1].length}>`);
        }
        continue;
      }

      if (/^(?:_{3,}|-{3,}|\*{3,})$/.test(trimmed)) {
        flushParagraph();
        closeLists();
        out.push("<hr>");
        continue;
      }

      const item = /^(\s*)(?:[-*+]|\d+\.)\s+(.*)$/.exec(line);
      if (item) {
        flushParagraph();
        const indent = item[1].length;
        closeLists(indent);
        if (lists.length && lists.at(-1) === indent) out.push("</li>");
        else {
          lists.push(indent);
          out.push("<ul>");
        }
        out.push(`<li>${inline(item[2])}`);
        continue;
      }

      if (trimmed.startsWith("|") && TABLE_SEPARATOR.test(lines[at + 1] ?? "")) {
        flushParagraph();
        closeLists();
        const rows = [line, lines[at + 1]];
        for (at += 2; at < lines.length && lines[at].trim().startsWith("|"); at += 1) rows.push(lines[at]);
        at -= 1;
        out.push(renderTable(rows));
        continue;
      }

      if (BLOCK_HTML.test(line)) {
        flushParagraph();
        closeLists();
        const block = [line];
        while (at + 1 < lines.length && lines[at + 1].trim() !== "") block.push(lines[(at += 1)]);
        out.push(block.join("\n"));
        continue;
      }

      if (lists.length && line.trimStart() !== line) {
        out.push(` ${inline(trimmed)}`);
        continue;
      }
      closeLists();
      paragraph.push(line);
    }
    flushParagraph();
    closeLists();
    return { html: out.join("\n"), caption };
  }

  // ---- sanitizing

  const TAG = /<(\/?)([a-zA-Z][\w:-]*)((?:"[^"]*"|'[^']*'|[^>"'])*)>/g;
  const ATTRIBUTE = /([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
  const BODY_TAGS = new Set(
    "a b blockquote br code details div em h1 h2 h3 h4 h5 h6 hr i li ol p pre small span strong sub summary sup table tbody td th thead tr ul wbr".split(" "),
  );
  const DROPPED_WITH_CONTENT = new Set("script iframe object embed noscript template applet frame frameset".split(" "));
  const BODY_ATTRIBUTES = new Set(["href", "title", "class", "style", "align", "colspan", "rowspan", "open"]);
  const URL_ATTRIBUTES = new Set(["href", "src", "xlink:href", "action", "formaction"]);
  const STYLE_PROPERTIES = new Set(["width", "display", "vertical-align", "border-radius", "background", "border", "height", "text-align"]);
  const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", colon: ":", tab: "\t", newline: "\n" };

  function decodeEntities(value) {
    return value
      .replace(/&#x([0-9a-f]+);?/gi, (_, hex) => String.fromCodePoint(Math.min(Number.parseInt(hex, 16), 0x10ffff)))
      .replace(/&#(\d+);?/g, (_, digits) => String.fromCodePoint(Math.min(Number(digits), 0x10ffff)))
      .replace(/&(\w+);/g, (match, name) => ENTITIES[name.toLowerCase()] ?? match);
  }

  // Only web links and in-page anchors survive; a scheme hidden behind entities or control characters is decoded first.
  function safeUrl(value) {
    // eslint-disable-next-line no-control-regex
    const plain = decodeEntities(value).replace(/[\u0000- \u007f-\u009f]+/g, "");
    return !/^[a-z][a-z0-9+.-]*:/i.test(plain) || /^(?:https?|mailto):/i.test(plain);
  }

  function safeStyle(value) {
    const kept = decodeEntities(value)
      .split(";")
      .map((declaration) => declaration.trim())
      .filter((declaration) => {
        const [property, ...rest] = declaration.split(":");
        return STYLE_PROPERTIES.has(property.trim().toLowerCase()) && !/url\(|expression\(|@import|\\|<|>/i.test(rest.join(":"));
      });
    return kept.join("; ");
  }

  function escapeAttribute(value) {
    return value.replace(/&(?!#?\w+;)/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }

  function cleanAttributes(raw, mode) {
    const attributes = [];
    for (const [, name, double, single, bare] of raw.matchAll(ATTRIBUTE)) {
      const lower = name.toLowerCase();
      const value = double ?? single ?? bare ?? "";
      if (lower.startsWith("on") || lower === "srcdoc" || lower === "formaction") continue;
      if (mode === "body" && (!BODY_ATTRIBUTES.has(lower) || lower === "open")) continue;
      if (URL_ATTRIBUTES.has(lower) && !safeUrl(value)) continue;
      if (lower === "style" && mode === "body") {
        const style = safeStyle(value);
        if (style) attributes.push(`style="${escapeAttribute(style)}"`);
        continue;
      }
      attributes.push(double === undefined && single === undefined && bare === undefined ? lower : `${name}="${escapeAttribute(value)}"`);
    }
    return attributes.length ? ` ${attributes.join(" ")}` : "";
  }

  // Rebuilds `html` from its tags. mode "body" keeps only the tags and attributes a PR description needs and drops
  // <style>; mode "svg" keeps a diagram's own tags and <style> and removes only what can run script.
  function sanitize(html, mode = "body") {
    const source = html.replace(/<!--[\s\S]*?(?:-->|$)/g, "").replace(/<\?[\s\S]*?(?:\?>|$)/g, "");
    const dropped = new Set(DROPPED_WITH_CONTENT);
    if (mode === "body") dropped.add("style");
    let result = "";
    let last = 0;
    TAG.lastIndex = 0;
    for (let match = TAG.exec(source); match; match = TAG.exec(source)) {
      const [whole, closing, rawName, rawAttributes] = match;
      const name = rawName.toLowerCase();
      result += source.slice(last, match.index);
      last = match.index + whole.length;
      if (dropped.has(name)) {
        if (!closing) {
          const end = source.toLowerCase().indexOf(`</${name}`, last);
          const close = end === -1 ? -1 : source.indexOf(">", end);
          last = close === -1 ? source.length : close + 1;
          TAG.lastIndex = last;
        }
        continue;
      }
      if (mode === "body" && !BODY_TAGS.has(name)) continue;
      if (closing) result += `</${rawName}>`;
      else result += `<${rawName}${cleanAttributes(rawAttributes, mode)}${/\/\s*$/.test(rawAttributes) ? " /" : ""}>`;
    }
    result += source.slice(last);
    return result.replace(/<(?=\s*\/?\s*(?:script|iframe|object|embed))/gi, "&lt;");
  }

  // ---- the card's body

  // Links into the PR's files view (either host's path, any origin) are pointed at this host's files view,
  // keeping the fragment that names the diff or the line.
  function rewriteLinks(html, filesUrl) {
    return html.replace(/\bhref="([^"]*)"/g, (whole, href) => {
      let link;
      try {
        link = new URL(decodeEntities(href));
      } catch {
        return whole;
      }
      if (!/^\/[^/]+\/[^/]+\/pulls?\/\d+\/(?:files|changes)\/?$/.test(link.pathname)) return whole;
      const target = new URL(filesUrl);
      target.hash = link.hash;
      return `href="${escapeAttribute(target.href)}"`;
    });
  }

  function bodyOf(bodyHtml) {
    const match = /<body[^>]*>([\s\S]*?)(?:<\/body>|$)/i.exec(bodyHtml);
    return match ? match[1] : bodyHtml;
  }

  // The HTML of the card's text for a run's body.html: `html` is the description, `caption`
  // the line under the diagram (empty when there is none). A body.html with no markdown string is used as written.
  function renderBody(bodyHtml, filesUrl) {
    const md = extractMarkdown(bodyHtml);
    const rendered = md === null ? { html: bodyOf(bodyHtml), caption: "" } : renderMarkdown(md);
    const finish = (html) => rewriteLinks(sanitize(html), filesUrl);
    return { html: finish(rendered.html), caption: finish(rendered.caption) };
  }

  ns.briefText = { extractMarkdown, renderMarkdown, sanitize, rewriteLinks, renderBody };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.briefText;
