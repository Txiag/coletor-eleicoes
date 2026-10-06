import { useCallback, useEffect, useRef, useState } from "react";
import type { SetStateAction } from "react";

export const initialFilters = {
  dataset: "", election: "", office: "", uf: "", municipality: "", zone: "",
};
type Filters = typeof initialFilters;
function readRoute() {
  const params = new URLSearchParams(window.location.search);
  const path = window.location.pathname.match(/^\/uf\/([a-z]{2})(?:\/municipio\/(\d{5}))?\/?$/i);
  const filters = { ...initialFilters };
  for (const key of ["dataset", "election", "office"] as const)
    filters[key] = params.get(key) || "";
  filters.uf = path?.[1].toLowerCase() || "";
  filters.municipality = path?.[2] || "";
  if (filters.municipality) filters.zone = params.get("zone") || "";
  return { filters, source: "official" as const };
}
type Route = ReturnType<typeof readRoute>;
function routeURL({ filters, source }: Route) {
  let path = filters.uf ? `/uf/${encodeURIComponent(filters.uf)}` : "/";
  if (filters.uf && filters.municipality) path += `/municipio/${encodeURIComponent(filters.municipality)}`;
  const params = new URLSearchParams();
  for (const key of ["dataset", "election", "office", "zone"] as const)
    if (filters[key]) params.set(key, filters[key]);
  params.set("source", source);
  return `${path}?${params}${window.location.hash}`;
}
export function useRouting() {
  const [route, setRoute] = useState(readRoute);
  const current = useRef(route);
  const [navigation, setNavigation] = useState(0);
  useEffect(() => {
    window.history.replaceState(null, "", routeURL(current.current));
    const restore = () => {
      current.current = readRoute();
      window.history.replaceState(null, "", routeURL(current.current));
      setRoute(current.current);
      setNavigation(n => n + 1);
    };
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);
  const update = useCallback((next: Route, replace = false) => {
    const url = routeURL(next);
    if (url !== `${window.location.pathname}${window.location.search}${window.location.hash}`)
      window.history[replace ? "replaceState" : "pushState"](null, "", url);
    current.current = next;
    setRoute(next);
  }, []);
  const setFilters = useCallback((value: SetStateAction<Filters>, replace = false) => {
    update({ ...current.current, filters: typeof value === "function" ? value(current.current.filters) : value }, replace);
  }, [update]);
  return { ...route, setFilters, navigation };
}
