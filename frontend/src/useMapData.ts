import { useEffect, useRef, useState } from 'react';
import type { Dashboard, Territory } from './types';
import { getJSON } from './useResource';

export type Position = [number, number];
export type Feature = {
  type: 'Feature';
  properties: { id: string | null; name: string; uf: string; ibge_code?: string };
  geometry: { type: 'Polygon'; coordinates: Position[][] } | { type: 'MultiPolygon'; coordinates: Position[][][] };
};
export type Geography = { features: Feature[]; available: boolean; reason: string | null; attribution: string; edition: string };
export const territoryKey = (level: string, uf: string, id: string) => `${level}:${level === 'uf' ? '' : uf}:${id}`;

export function useMapData(url: string, seconds: number, paused: boolean, refresh: number, priority: string) {
  const cache = useRef(new Map<string, { data: Pick<Dashboard, 'territories'>; etag: string; expires: number }>());
  const lastRefresh = useRef(refresh);
  const [geography, setGeography] = useState<Record<string, Geography>>({});
  const [geometryErrors, setGeometryErrors] = useState<string[]>([]);
  const [results, setResults] = useState<{ url: string; items: Record<string, Territory>; completed: number; loading: boolean; errors: string[] }>({ url: '', items: {}, completed: 0, loading: false, errors: [] });
  const config = useRef({ seconds, paused, priority });
  config.current = { seconds, paused, priority };
  const scheduleRef = useRef(() => {});
  useEffect(() => {
    const controller = new AbortController();
    const load = async (uf: string) => {
      try {
        const data = await getJSON<Geography>(`/api/geography${uf ? `?uf=${uf}` : ''}`, controller.signal);
        if (!controller.signal.aborted) {
          setGeography(current => ({ ...current, [uf]: data }));
          if (!data.available) setGeometryErrors(current => [...current, uf || 'Brasil']);
        }
        return data;
      } catch {
        if (!controller.signal.aborted) setGeometryErrors(current => [...current, uf || 'Brasil']);
      }
    };
    void (async () => {
      const country = await load('');
      const queue = (country?.features || []).map(f => f.properties.id).filter((id): id is string => !!id);
      await Promise.all(Array.from({ length: 3 }, async () => {
        while (queue.length && !controller.signal.aborted) {
          const preferred = queue.indexOf(config.current.priority);
          await load(queue.splice(preferred >= 0 ? preferred : 0, 1)[0]);
        }
      }));
    })();
    return () => controller.abort();
  }, []);
  const country = geography[''];
  useEffect(() => {
    if (!country || !url) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let busy = false;
    const force = refresh !== lastRefresh.current;
    lastRefresh.current = refresh;
    const readResults = async (key: string, revalidate: boolean) => {
      const cached = cache.current.get(key);
      if (cached && !revalidate && cached.expires > Date.now()) return cached.data;
      const response = await fetch(key, { signal: controller.signal, cache: 'no-cache',
        headers: cached?.etag ? { 'If-None-Match': cached.etag } : {} });
      if (controller.signal.aborted) throw new DOMException('Consulta cancelada', 'AbortError');
      if (response.status === 304 && cached) {
        cached.expires = Date.now() + 15000;
        return cached.data;
      }
      if (!response.ok) throw new Error('Não foi possível atualizar o mapa.');
      const data: Pick<Dashboard, 'territories'> = await response.json();
      if (controller.signal.aborted) throw new DOMException('Consulta cancelada', 'AbortError');
      cache.current.delete(key);
      cache.current.set(key, { data, etag: response.headers?.get('ETag') || '', expires: Date.now() + 15000 });
      while (cache.current.size > 84) cache.current.delete(cache.current.keys().next().value!);
      return data;
    };
    const previousResponses = new Map<string, Pick<Dashboard, 'territories'>>();
    const schedule = () => {
      clearTimeout(timer);
      if (!busy && !controller.signal.aborted && !config.current.paused && config.current.seconds > 0)
        timer = setTimeout(run, config.current.seconds * 1000);
    };
    const run = async (revalidate = false) => {
      busy = true;
      setResults(current => ({ url, items: current.url === url ? current.items : {}, completed: 0, loading: true, errors: [] }));
      const queue = ['', ...country.features.map(f => f.properties.id).filter((id): id is string => !!id)];
      await Promise.all(Array.from({ length: 2 }, async () => {
        while (queue.length && !controller.signal.aborted) {
          const preferred = queue.indexOf(config.current.priority);
          const uf = queue.splice(preferred >= 0 ? preferred : 0, 1)[0];
          try {
            const request = new URL(url, window.location.origin);
            if (uf) request.searchParams.set('uf', uf);
            const response = await readResults(request.pathname + request.search, revalidate);
            const changed = previousResponses.get(uf) !== response;
            previousResponses.set(uf, response);
            if (!controller.signal.aborted) setResults(current => ({ ...current, completed: current.completed + 1,
              items: changed ? Object.fromEntries([...Object.entries(current.items).filter(([key]) => !key.startsWith(uf ? `municipality:${uf}:` : 'uf::')), ...response.territories.items.map(t => [territoryKey(t.level, uf, t.id), t] as const)]) : current.items }));
          } catch {
            if (!controller.signal.aborted) setResults(current => ({ ...current, completed: current.completed + 1, errors: [...current.errors, uf || 'Brasil'] }));
          }
        }
      }));
      busy = false;
      if (!controller.signal.aborted) setResults(current => ({ ...current, loading: false }));
      schedule();
    };
    scheduleRef.current = schedule;
    void run(force);
    return () => { controller.abort(); clearTimeout(timer); scheduleRef.current = () => {}; };
  }, [url, country, refresh]);
  useEffect(() => scheduleRef.current(), [seconds, paused]);
  return { geography, geometryErrors, items: results.url === url ? results.items : {},
    loading: results.url !== url || results.loading, completed: results.url === url ? results.completed : 0,
    errors: results.url === url ? results.errors : [] };
}
