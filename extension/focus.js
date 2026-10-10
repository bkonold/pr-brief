(() => {
  const ns = (globalThis.prFocus ??= {});
  // The blocks scan runs only for a path whose entry is not found by its id, and at most once per `scan` taken.
  function lazyScan() {
    let scanned;
    return () => (scanned ??= ns.page.fileBlocks());
  }

  async function entryOfPath(path, scan) {
    return (await ns.page.entryFor(path)) ?? ns.page.entryOf(scan().get(path));
  }

  async function scrollTo(path) {
    const entry = await entryOfPath(path, lazyScan());
    if (entry) await ns.page.scrollToElement(entry);
  }

  const ACTIVE = "prf-box-active";
  const FLASH = "prf-box-flash";

  // The headers carrying ACTIVE or FLASH.
  let marked = new Set();
  let boxGeneration = 0;
  let announceGeneration = 0;

  function reducedMotion() {
    return Boolean(globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
  }

  // The loaded file headers for `paths`, in order; a file whose diff isn't in the page yet is left out.
  async function headersOf(paths) {
    const scan = lazyScan();
    const entries = await Promise.all(paths.map((path) => entryOfPath(path, scan)));
    return entries.filter(Boolean).map((entry) => ns.page.fileHeaderOf(entry) ?? entry);
  }

  // Gives the active box's files an accent bar on their headers, and takes it off every other header. An
  // empty list takes it off all of them. GitHub re-renders diffs, so this is re-applied on each refresh.
  async function markBox(paths) {
    const mine = ++boxGeneration;
    const headers = new Set(paths.length ? await headersOf(paths) : []);
    if (mine !== boxGeneration || !ns.alive?.()) return;
    for (const header of marked) {
      if (headers.has(header)) continue;
      header.classList.remove(ACTIVE);
      if (!header.classList.contains(FLASH)) marked.delete(header);
    }
    for (const header of headers) {
      header.classList.add(ACTIVE);
      marked.add(header);
    }
  }

  function flash(header) {
    header.classList.remove(FLASH);
    void header.offsetWidth;
    header.classList.add(FLASH);
    marked.add(header);
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
    for (const header of marked) header.classList.remove(ACTIVE, FLASH);
    marked = new Set();
  }

  ns.focus = { scrollTo, markBox, announceBox, clearBox };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.focus;
