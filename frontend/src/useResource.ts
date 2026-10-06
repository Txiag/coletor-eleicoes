import { useCallback, useEffect, useRef, useState } from "react";
export function query(
  path: string,
  values: Record<string, string | number | undefined>,
) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  return `${path}?${params}`;
}
export async function getJSON<T>(
  url: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(url, { signal });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      body.detail || `Falha na consulta (HTTP ${response.status}).`,
    );
  }
  return response.json();
}
type Snapshot<T> = {
  data?: T;
  error: string;
  loading: boolean;
  receivedAt: number;
};
export function useResource<T>(
  url: string | null,
  seconds = 0,
  paused = false,
) {
  const cache = useRef(new Map<string, Snapshot<T>>());
  const [, setRevision] = useState(0);
  const runRef = useRef<() => Promise<void>>(async () => {});
  const scheduleRef = useRef<() => void>(() => {});
  const config = useRef({ seconds, paused });
  config.current = { seconds, paused };
  useEffect(() => {
    if (!url) return;
    let active = true,
      busy = false,
      timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    const publish = (patch: Partial<Snapshot<T>>) => {
      if (!active) return;
      cache.current.set(url, {
        error: "",
        loading: false,
        receivedAt: 0,
        ...cache.current.get(url),
        ...patch,
      });
      if (cache.current.size > 24)
        cache.current.delete(cache.current.keys().next().value!);
      setRevision((n) => n + 1);
    };
    const schedule = () => {
      clearTimeout(timer);
      if (
        active &&
        !busy &&
        !config.current.paused &&
        config.current.seconds > 0
      )
        timer = setTimeout(run, config.current.seconds * 1000);
    };
    const run = async () => {
      if (!active || busy) return;
      clearTimeout(timer);
      busy = true;
      publish({ loading: true });
      try {
        const data = await getJSON<T>(url, controller.signal);
        publish({ data, error: "", receivedAt: Date.now() });
      } catch (error) {
        if (!controller.signal.aborted)
          publish({
            error:
              error instanceof Error ? error.message : "Falha na consulta.",
          });
      } finally {
        busy = false;
        publish({ loading: false });
        schedule();
      }
    };
    runRef.current = run;
    scheduleRef.current = schedule;
    void run();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
      runRef.current = async () => {};
      scheduleRef.current = () => {};
    };
  }, [url]);
  useEffect(() => scheduleRef.current(), [seconds, paused]);
  const refresh = useCallback(() => runRef.current(), []);
  return {
    ...(url ? cache.current.get(url) : undefined),
    error: url ? cache.current.get(url)?.error || "" : "",
    loading: url ? (cache.current.get(url)?.loading ?? true) : false,
    receivedAt: url ? cache.current.get(url)?.receivedAt || 0 : 0,
    refresh,
  };
}
