export function applyScope<
  T extends { uf: string; municipality: string; zone: string },
>(filters: T, scopes: string[]): T {
  if (!scopes.length || scopes.includes("br")) return filters;
  const allowed = scopes.map((scope) => scope.toLowerCase());
  const current = allowed.find(
    (scope) =>
      scope === filters.uf || scope === `${filters.uf}${filters.municipality}`,
  );
  if (current) return filters;
  const compatible = allowed.find(
    (scope) => scope.startsWith(filters.uf) && filters.uf,
  );
  const scope = compatible || allowed[0];
  return {
    ...filters,
    uf: scope.slice(0, 2),
    municipality: scope.length > 2 ? scope.slice(2) : "",
    zone: "",
  };
}
