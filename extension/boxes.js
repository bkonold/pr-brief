(() => {
  const ns = (globalThis.prFocus ??= {});

  // File path -> the box numbers whose `nodes` entry lists it, ascending. Empty when review.json has no `nodes`.
  function fileBadges(review) {
    const badges = new Map();
    for (const node of review.nodes ?? []) {
      if (node.number == null) continue;
      for (const path of node.files) badges.set(path, [...(badges.get(path) ?? []), node.number]);
    }
    for (const numbers of badges.values()) numbers.sort((a, b) => a - b);
    return badges;
  }

  // The first file of a box and the chunk that holds it; null for an unknown box, a context box (no files) or
  // a file no chunk lists.
  function targetOfNode(review, nodeId) {
    const path = review.nodes?.find((node) => node.id === nodeId)?.files[0];
    const chunk = path ? review.chunks.find((candidate) => candidate.files.some((file) => file.path === path)) : null;
    return chunk ? { path, n: chunk.n } : null;
  }

  const BOX_NUMBER = /^\s*\d+\s*[·.:)–-]\s*/;

  // The title of a box from its label text, one line per `\n` or `<br>`: the first non-empty line without its
  // leading "3 ·" number.
  function boxTitle(label) {
    const first = String(label ?? "")
      .split(/\r?\n|<br\s*\/?>/i)
      .map((line) => line.trim())
      .find(Boolean);
    return (first ?? "").replace(BOX_NUMBER, "").trim();
  }

  ns.boxes = { fileBadges, targetOfNode, boxTitle };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.boxes;
