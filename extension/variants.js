(() => {
  const ns = (globalThis.prFocus ??= {});

  // The chunk of `newReview` to keep selected after switching variants: the one named like the selected chunk
  // of `oldReview`, or null when nothing is selected or no chunk has that name.
  function keepSelection(oldReview, selectedN, newReview) {
    const selected = oldReview.chunks.find((chunk) => chunk.n === selectedN);
    if (!selected) return null;
    return newReview.chunks.find((chunk) => chunk.name === selected.name)?.n ?? null;
  }

  ns.variants = { keepSelection };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.variants;
