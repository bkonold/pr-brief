// The variant to load for a PR: the stored default when this PR has a run for it, else the first variant
// the PR does have. Without a variants list (the file is missing or unreadable) only the stored default is known.
export function chooseVariant(stored, variants) {
  if (!Array.isArray(variants) || variants.length === 0) return stored;
  return variants.some((entry) => entry.variant === stored) ? stored : variants[0].variant;
}
