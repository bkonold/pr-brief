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

  // Hides every diff outside `chunk` and scrolls to the chunk's first loaded diff. apply(null) shows all.
  async function apply(chunk, { scroll = true } = {}) {
    const mine = ++generation;
    if (!chunk) {
      clear();
      return {};
    }
    const scanned = ns.page.fileBlocks();
    const found = await Promise.all(chunk.files.map(({ path }) => entryOfPath(path, scanned)));
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
  const CHIP = "prf-box-chip";
  const CHIP_MS = 2500;

  let boxGeneration = 0;
  let announceGeneration = 0;
  let chip = null;
  let chipTimer = null;
  let chipHost = null;
  let chipHostPosition = "";

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

  function clearChip() {
    clearTimeout(chipTimer);
    chipTimer = null;
    chip?.remove();
    chip = null;
    if (chipHost) chipHost.style.position = chipHostPosition;
    chipHost = null;
  }

  function showChip(header, text) {
    clearChip();
    if (getComputedStyle(header).position === "static") {
      chipHostPosition = header.style.position;
      chipHost = header;
      header.style.position = "relative";
    }
    chip = document.createElement("div");
    chip.className = CHIP;
    chip.textContent = text;
    header.append(chip);
    chipTimer = setTimeout(clearChip, CHIP_MS);
  }

  // Flashes the active files' headers and, given a label, labels the first one, once, after the scroll has
  // landed. Under reduced motion the headers keep only their bar and the label just appears and goes.
  async function announceBox(paths, label) {
    const mine = ++announceGeneration;
    const headers = await headersOf(paths);
    if (mine !== announceGeneration || !ns.alive?.() || headers.length === 0) return;
    if (!reducedMotion()) for (const header of headers) flash(header);
    if (label) showChip(headers[0], label);
  }

  function clearBox() {
    boxGeneration += 1;
    announceGeneration += 1;
    clearChip();
    for (const header of document.querySelectorAll(`.${ACTIVE}, .${FLASH}`)) header.classList.remove(ACTIVE, FLASH);
  }

  function owns(node) {
    const element = node?.nodeType === 1 ? node : node?.parentElement;
    return Boolean(element?.closest(`.${CHIP}`));
  }

  ns.focus = { apply, scrollTo, markBox, announceBox, clearBox, owns };
})();
