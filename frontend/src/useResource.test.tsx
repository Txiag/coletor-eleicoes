import {
  act,
  renderHook,
  cleanup,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useResource } from "./useResource";
beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
const reply = (value: string) => ({ ok: true, json: async () => ({ value }) });
it("ignora resposta atrasada de outro contexto e preserva dados após falha no mesmo contexto", async () => {
  let resolveOld!: (value: unknown) => void;
  const fetcher = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    )
    .mockResolvedValueOnce(reply("novo"))
    .mockRejectedValueOnce(new Error("offline"));
  vi.stubGlobal("fetch", fetcher);
  const { result, rerender } = renderHook(
    ({ url }) => useResource<{ value: string }>(url, 30, false),
    { initialProps: { url: "/old" } },
  );
  rerender({ url: "/new" });
  await act(async () => {});
  expect(result.current.data?.value).toBe("novo");
  await act(async () => resolveOld(reply("antigo")));
  expect(result.current.data?.value).toBe("novo");
  await act(async () => result.current.refresh());
  expect(result.current.data?.value).toBe("novo");
  expect(result.current.error).toBe("offline");
});
it("agenda após conclusão e pausa sem sobrepor atualização manual", async () => {
  let finish!: (value: unknown) => void;
  const fetcher = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    )
    .mockResolvedValue(reply("atual"));
  vi.stubGlobal("fetch", fetcher);
  const { result, rerender } = renderHook(
    ({ paused }) => useResource<{ value: string }>("/poll", 30, paused),
    { initialProps: { paused: false } },
  );
  await act(async () => {
    vi.advanceTimersByTime(60000);
    result.current.refresh();
  });
  expect(fetcher).toHaveBeenCalledTimes(1);
  await act(async () => finish(reply("inicial")));
  rerender({ paused: true });
  await act(async () => vi.advanceTimersByTime(60000));
  expect(fetcher).toHaveBeenCalledTimes(1);
  rerender({ paused: false });
  await act(async () => vi.advanceTimersByTime(30000));
  expect(result.current.data?.value).toBe("atual");
  expect(fetcher).toHaveBeenCalledTimes(2);
});

