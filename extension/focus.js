(() => {
  const ns = (globalThis.prFocus ??= {});
  async function entryOfPath(path, scanned) {
    return (await ns.page.entryFor(path)) ?? ns.page.entryOf(scanned.get(path));
  }

  async function scrollTo(path) {
    const entry = await entryOfPath(path, ns.page.fileBlocks());
    if (entry) await ns.page.scrollToElement(entry);
  }

  const ACTIVE = "prf-box-active";
  const FLASH = "prf-box-flash";
  const CHUNK = "prf-chunk-mark";

  let boxGeneration = 0;
  let chunkGeneration = 0;
  let announceGeneration = 0;

  function reducedMotion() {
    return Boolean(globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
  }

  // The loaded file headers for `paths`, in order; a file whose diff isn't in the page yet is left out.
  async function headersOf(paths) {
    const scanned = ns.page.fileBlocks();
    const entries = await Promise.all(paths.map((path) => entryOfPath(path, scanned)));
    return entries.filter(Boolean).map((entry) => ns.page.fileHeaderOf(entry) ?? entry);
  }

  // Gives the active box's files an accent bar on their headers, and takes it off every other header. An
  // empty list takes it off all of them. GitHub re-renders diffs, so this is re-applied on each refresh.
  async function markBox(paths) {
    const mine = ++boxGeneration;
    const headers = new Set(paths.length ? await headersOf(paths) : []);
    if (mine !== boxGeneration || !ns.alive?.()) return;
    for (const header of document.querySelectorAll(`.${ACTIVE}`)) {
      if (!headers.has(header)) header.classList.remove(ACTIVE);
    }
    for (const header of headers) header.classList.add(ACTIVE);
  }

  // Tints the headers of the chunk's files with a quiet accent stripe and takes it off every other header. A null
  // chunk takes it off all of them. No diff is hidden: the stripe only shows where the chunk's files are. GitHub
  // re-renders diffs, so this is re-applied on each refresh.
  async function markChunk(chunk) {
    const mine = ++chunkGeneration;
    const headers = new Set(chunk ? await headersOf(chunk.files.map(({ path }) => path)) : []);
    if (mine !== chunkGeneration || !ns.alive?.()) return;
    for (const header of document.querySelectorAll(`.${CHUNK}`)) {
      if (!headers.has(header)) header.classList.remove(CHUNK);
    }
    for (const header of headers) header.classList.add(CHUNK);
  }

  function flash(header) {
    header.classList.remove(FLASH);
    void header.offsetWidth;
    header.classList.add(FLASH);
    header.addEventListener("animationend", () => header.classList.remove(FLASH), { once: true });
  }

  // Flashes the active files' headers once, after the scroll has landed. Under reduced motion the headers keep only
  // their bar.
  async function announceBox(paths) {
    const mine = ++announceGeneration;
    const headers = await headersOf(paths);
    if (mine !== announceGeneration || !ns.alive?.() || headers.length === 0) return;
    if (!reducedMotion()) for (const header of headers) flash(header);
  }

  function clearBox() {
    boxGeneration += 1;
    announceGeneration += 1;
    for (const header of document.querySelectorAll(`.${ACTIVE}, .${FLASH}`)) header.classList.remove(ACTIVE, FLASH);
  }

  ns.focus = { scrollTo, markBox, markChunk, announceBox, clearBox };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.focus;
