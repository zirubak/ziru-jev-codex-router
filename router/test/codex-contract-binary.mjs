// Unpinned discovery continues to cover every installed binary.
export function contractBinaryPaths({ explicit, expectedVersion, discovered }) {
  if (explicit) return [explicit];
  return [...new Set(discovered)];
}
