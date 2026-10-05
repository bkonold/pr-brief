(() => {
  const ns = (globalThis.prFocus ??= {});
  const HIDDEN = "prf-hidden";
  const FADE_IN = "prf-fade-in";

  // A newer apply() supersedes an older one still waiting on the path hashes.
  let generation = 0;

  // Hidden diffs vanish at once; a diff that becomes visible fades in (focus.css).
  function setHidden(entry, hidden) {
    if (entry.classList.contains(HIDDEN) === hidden) return;
    entry.classList.toggle(HIDDEN, hidden);
    if (hidden) return;
    entry.classList.add(FADE_IN);
    entry.addEventListener("animationend", () => entry.classList.remove(FADE_IN), { once: true });
  }

  function clear() {
    for (const element of document.querySelectorAll(`.${HIDDEN}`)) setHidden(element, false);
  }

  async function entryOfPath(path, scanned) {
    return (await ns.page.entryFor(path)) ?? ns.page.entryOf(scanned.get(path));
  }

  // The paths whose diffs stay visible for `chunk`: its files, then `extra`, files outside it that something in its row
  // points at (a contract line in the spec's diff).
  function visiblePaths(chunk, extra) {
    const own = chunk.files.map(({ path }) => path);
    return [...own, ...extra.filter((path) => !own.includes(path))];
  }

  // Hides every diff outside `chunk` and `extra` and scrolls to the chunk's first loaded diff. apply(null) shows all.
  async function apply(chunk, { scroll = true, extra = [] } = {}) {
    const mine = ++generation;
    if (!chunk) {
      clear();
      return {};
    }
    const scanned = ns.page.fileBlocks();
    const found = await Promise.all(visiblePaths(chunk, extra).map((path) => entryOfPath(path, scanned)));
    if (mine !== generation) return { stale: true };

    const keep = new Set(found.filter(Boolean));
    for (const entry of ns.page.diffEntries()) setHidden(entry, !keep.has(entry));
    const first = found.find(Boolean);
    if (scroll && first) ns.page.scrollToElement(first);
    return {};
  }

  async function scrollTo(path) {
    const entry = await entryOfPath(path, ns.page.fileBlocks());
    if (entry) await ns.page.scrollToElement(entry);
  }

  const ACTIVE = "prf-box-active";
  const FLASH = "prf-box-flash";

  let boxGeneration = 0;
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

  ns.focus = { visiblePaths, apply, scrollTo, markBox, announceBox, clearBox };
})();

if (typeof module !== "undefined") module.exports = globalThis.prFocus.focus;
