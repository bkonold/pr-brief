// Chooses the page adapter for the host the content script runs on: prFocus.page is the adapter whose `hosts`
// lists location.host, or null on any other host. Every other module calls the page through it.
(() => {
  const ns = (globalThis.prFocus ??= {});

  function chooseAdapter(host, adapters) {
    return adapters.find((adapter) => adapter?.hosts.includes(host)) ?? null;
  }

  ns.chooseAdapter = chooseAdapter;
  ns.page = chooseAdapter(globalThis.location?.host, [ns.githubPage, ns.forgejoPage]);
})();

if (typeof module !== "undefined") module.exports = { chooseAdapter: globalThis.prFocus.chooseAdapter };
