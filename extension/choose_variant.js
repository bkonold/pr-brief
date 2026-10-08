// Orders variant names so a higher version sorts later: digit runs compare as numbers, so v9 < v10 < v23.
function compareNames(a, b) {
  const left = a.match(/\d+|\D+/g) ?? [];
  const right = b.match(/\d+|\D+/g) ?? [];
  for (let i = 0; i < Math.min(left.length, right.length); i++) {
    if (left[i] === right[i]) continue;
    const numbers = /^\d/.test(left[i]) && /^\d/.test(right[i]);
    if (numbers) return Number(left[i]) - Number(right[i]);
    return left[i] < right[i] ? -1 : 1;
  }
  return left.length - right.length;
}

// The newest of the given variant names, or undefined for none.
export function newest(names) {
  return [...names].sort(compareNames).at(-1);
}

// The variants the on-page switcher lists: those the PR has a run for that are also active on the server, in the
// PR's own order. Without the server's config no variant is known to be active.
export function switcherVariants(variants, config) {
  const active = new Set(config?.variants ?? []);
  return (variants ?? []).filter((entry) => active.has(entry.variant));
}

// The variant to show for a PR. `picked` is the variant chosen on the page during this visit, `config` the server's
// { default_variant, variants } (null when it could not be read), `variants` the entries of the PR's variants.json.
// Order: the pick, the server's default, the newest active variant the PR has, the newest variant the PR has.
// Without a variants list (the file is missing or unreadable) only the pick and the server's default are known.
export function chooseVariant(picked, config, variants) {
  const have = new Set((variants ?? []).map((entry) => entry.variant));
  if (have.size === 0) return picked ?? config?.default_variant;
  if (picked && have.has(picked)) return picked;
  if (config?.default_variant && have.has(config.default_variant)) return config.default_variant;
  const active = switcherVariants(variants, config).map((entry) => entry.variant);
  return newest(active.length > 0 ? active : have);
}
