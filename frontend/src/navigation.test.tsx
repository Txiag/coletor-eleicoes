import { act, cleanup, fireEvent, render, renderHook, screen, within, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useRouting } from "./routing";
import SearchSelect from "./components/SearchSelect";
import App from "./App";
import RegionalProgress from "./components/RegionalProgress";

afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); history.replaceState(null, "", "/"); });

it("restaura o recorte compartilhado e acompanha o histórico sem perder zeros", async () => {
  history.replaceState(null, "", "/uf/ac/municipio/01074?dataset=1&election=6259&office=3&source=bulletins&zone=0004");
  const { result } = renderHook(() => useRouting());
  expect(result.current.filters).toMatchObject({ uf: "ac", municipality: "01074", zone: "0004", election: "6259" });
  expect(result.current.source).toBe("official");
  expect(new URLSearchParams(location.search).get("source")).toBe("official");
  act(() => result.current.setFilters(current => ({ ...current, municipality: "", zone: "" })));
  expect(location.pathname).toBe("/uf/ac");
  act(() => history.back());
  await waitFor(() => expect(result.current.filters.municipality).toBe("01074"));
  expect(result.current.filters.zone).toBe("0004");
  act(() => history.forward());
  await waitFor(() => expect(result.current.filters.municipality).toBe(""));
});

it("preserva resultados oficiais ao navegar", () => {
  history.replaceState(null, "", "/");
  const { result } = renderHook(() => useRouting());
  expect(result.current.source).toBe("official");
  act(() => result.current.setFilters(current => ({ ...current, uf: "ac" })));
  expect(new URLSearchParams(location.search).get("source")).toBe("official");
  act(() => window.dispatchEvent(new PopStateEvent("popstate")));
  expect(result.current.source).toBe("official");
  expect(result.current.filters.uf).toBe("ac");
});

it("avisa sobre coleta desatualizada", async () => {
  history.replaceState(null, "", "/?dataset=1&election=6257&office=1");
  const requests: URL[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    const url = new URL(input, location.origin);
    requests.push(url);
    let body: unknown;
    if (url.pathname === "/api/metadata") body = {
      datasets: [{ id: "1", elections: [{ code: "6257", round: 1, offices: [{ code: "1", name: "Presidente", scopes: ["br"] }] }] }],
      parties: [], stale_seconds: 300,
    };
    else if (url.pathname === "/api/dashboard") body = {
      source: { available: false, kind: "official", label: "Resultados oficiais",
        updated_at: "20261004T154409", collected_at: new Date(Date.now() - 600_000).toISOString() },
      summary: { categories: [] }, parties: [], regions: [], territories: { items: [], level: "uf" },
      candidates: { items: [], total: 0, page: 1, page_size: 5, denominator: null },
    };
    else if (url.pathname === "/api/geography") body = { features: [], available: true };
    else body = { items: [], territories: { items: [] } };
    return { ok: true, json: async () => body };
  }));
  render(<App />);
  await screen.findByText("Dados desatualizados");

});

it("preserva a busca remota ao retornar da paginação pelo teclado", () => {
  const search = vi.fn();
  render(<SearchSelect label="Município" value="" options={[]} onChange={() => {}} onSearch={search}
    footer={<button>Mais opções</button>} />);
  const input = screen.getByRole("combobox");
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: "Fort" } });
  const next = screen.getByRole("button", { name: "Mais opções" });
  fireEvent.blur(input, { relatedTarget: next });
  fireEvent.focus(next);
  fireEvent.blur(next, { relatedTarget: input });
  fireEvent.focus(input);
  expect((input as HTMLInputElement).value).toBe("Fort");
  expect(search).toHaveBeenLastCalledWith("Fort");
});

it("busca opções e seleciona pelo teclado, preservando o valor ao cancelar", () => {
  const change = vi.fn();
  render(<SearchSelect label="Cargo" value="1" options={[{value:"1",label:"Presidente"}, {value:"3",label:"Governador"}]} onChange={change} />);
  const input = screen.getByRole("combobox", { name: "Cargo" });
  fireEvent.focus(input);
  fireEvent.change(input, {target:{value:"gover"}});
  expect(screen.queryByRole("option", {name:"Presidente"})).toBeNull();
  fireEvent.keyDown(input, {key:"ArrowDown"});
  fireEvent.keyDown(input, {key:"Enter"});
  expect(change).toHaveBeenCalledWith("3", "Governador");
  fireEvent.focus(input);
  fireEvent.change(input, {target:{value:"inexistente"}});
  fireEvent.keyDown(input, {key:"Escape"});
  expect((input as HTMLInputElement).value).toBe("Presidente");
  expect(change).toHaveBeenCalledTimes(1);
});

it("abre link direto, resolve município fora da primeira página e restaura navegação", async () => {
  history.replaceState(null, "", "/uf/ac/municipio/01074");
  const requests: URL[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    const url = new URL(input, location.origin);
    requests.push(url);
    if (url.pathname === "/api/metadata") return { ok: true, json: async () => ({
      datasets: [{id:"1",name:"Eleição de teste",phase:"Simulado",elections:[{code:"6259",name:"Geral",round:1,offices:[{code:"3",name:"Governador",scopes:["ac","ce"]}]}]}],
      parties: [], refresh_seconds:30, stale_seconds:300,
    }) };
    if (url.pathname === "/api/options") {
      const items = url.searchParams.get("level") === "uf"
        ? [{value:"ac",label:"Acre"},{value:"ce",label:"Ceará"}]
        : url.searchParams.get("q") === "01074"
          ? [{value:"01074",label:"Município de teste"}]
          : [];
      return {ok:true,json:async () => ({items,total:items.length,page:1,page_size:30})};
    }
    return {ok:false,json:async () => ({detail:"Sem resultados neste teste"})};
  }));
  render(<App />);
  await screen.findByRole("heading", {name:"Governador · Município de teste"});
  expect(location.pathname).toBe("/uf/ac/municipio/01074");
  expect(new URLSearchParams(location.search).get("election")).toBe("6259");
  await waitFor(() => expect(requests.some(url => url.pathname === "/api/dashboard" && url.searchParams.get("municipality") === "01074")).toBe(true));
  const original = location.pathname + location.search;
  fireEvent.click(screen.getByRole("button", {name:"AC"}));
  expect(location.pathname).toBe("/uf/ac");
  await screen.findByRole("heading", {name:"Governador · AC"});
  act(() => { history.replaceState(null, "", original); window.dispatchEvent(new PopStateEvent("popstate")); });
  await screen.findByRole("heading", {name:"Governador · Município de teste"});
});

it("resolve a eleição por cargo e turno preservando um território compatível", async () => {
  history.replaceState(null, "", "/uf/ce?dataset=antigo");
  const requests: URL[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    const url = new URL(input, location.origin);
    requests.push(url);
    if (url.pathname === "/api/metadata") return { ok: true, json: async () => ({
      datasets: [{ id:"1", elections: [
        {code:"f1",round:1,offices:[{code:"1",name:"Presidente",scopes:["br"]}]},
        {code:"e1",round:1,offices:[{code:"3",name:"Governador",scopes:["ac","ce"]},{code:"5",name:"Senador",scopes:["ac","ce"]}]},
        {code:"f2",round:2,offices:[{code:"1",name:"Presidente",scopes:["br"]}]},
        {code:"e2",round:2,offices:[{code:"3",name:"Governador",scopes:["ce"]}]},
      ] }], parties: [], refresh_seconds:30, stale_seconds:300,
    }) };
    return {ok:false,json:async () => ({detail:"Sem resultados neste teste"})};
  }));
  render(<App />);
  fireEvent.click(await screen.findByRole("button", {name:"Governador"}));
  await waitFor(() => expect(requests.some(url => url.pathname === "/api/dashboard" && url.searchParams.get("election") === "e1" && url.searchParams.get("office") === "3")).toBe(true));
  fireEvent.change(screen.getByRole("combobox", {name:"Turno"}), {target:{value:"2"}});
  await waitFor(() => expect(requests.some(url => url.pathname === "/api/dashboard" && url.searchParams.get("election") === "e2" && url.searchParams.get("office") === "3" && url.searchParams.get("uf") === "ce")).toBe(true));
  expect(new URLSearchParams(location.search).get("dataset")).toBe("1");
  fireEvent.change(screen.getByRole("combobox", {name:"Turno"}), {target:{value:"1"}});
  fireEvent.click(screen.getByRole("button", {name:"Senador"}));
  fireEvent.change(screen.getByRole("combobox", {name:"Turno"}), {target:{value:"2"}});
  await waitFor(() => expect(requests.some(url => url.pathname === "/api/dashboard" && url.searchParams.get("election") === "f2" && url.searchParams.get("office") === "1")).toBe(true));
});

it("mantém o top nacional enquanto o popover acompanha o território e permite fechar", async () => {
  history.replaceState(null, "", "/uf/ac?dataset=1&election=6257&office=1");
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    const url = new URL(input, location.origin);
    let body: unknown;
    if (url.pathname === "/api/metadata") body = {
      datasets: [{ id: "1", elections: [{ code: "6257", round: 1, offices: [{ code: "1", name: "Presidente", scopes: ["br"] }] }] }], parties: [],
    };
    else if (url.pathname === "/api/dashboard") {
      const place = url.searchParams.get("municipality") ? "Municipal" : url.searchParams.has("uf") ? "Estadual" : "Nacional";
      body = {
        source: { available: true, label: "Resultados oficiais", kind: "official" },
        summary: { categories: [] }, parties: [], regions: [], territories: { items: [], level: "uf" },
        candidates: { items: Array.from({ length: 5 }, (_, i) => ({ number: String(i), scope: "br", name: `${place} ${i}`, party: "10", votes: 100 - i * 10, percentage: 20 - i * 2 })),
          total: 7, page: 1, page_size: 5, denominator: 500, denominator_label: "votos nominais", remaining: { count: 2, votes: 100, percentage: 20 } },
      };
    } else if (url.pathname === "/api/options") body = { items: [{ value: "01074", label: "Cidade teste" }] };
    else if (url.pathname === "/api/geography") body = { features: [], available: true };
    else body = { territories: { items: [] } };
    return { ok: true, json: async () => body };
  }));
  render(<App />);
  const national = await screen.findByRole("region", { name: "Votação nacional por candidato" });
  await within(national).findByText("Nacional 0");
  expect(within(national).getAllByRole("listitem")).toHaveLength(5);
  expect(within(national).getByText("Mais 2 candidatos com 20% e 100 votos.")).toBeTruthy();
  const local = await screen.findByRole("dialog", { name: "Votação em AC" });
  expect(within(local).getByText("Estadual 0")).toBeTruthy();
  act(() => { history.replaceState(null, "", "/uf/ac/municipio/01074?dataset=1&election=6257&office=1"); window.dispatchEvent(new PopStateEvent("popstate")); });
  await screen.findByText("Municipal 0");
  expect(within(national).getByText("Nacional 0")).toBeTruthy();
  fireEvent.click(screen.getByRole('dialog'));
  expect(location.pathname).toBe('/uf/ac/municipio/01074');

  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(within(national).getByText("Nacional 0")).toBeTruthy();
  fireEvent.click(within(national).getByText('Nacional 0'));
  expect(location.pathname).toBe('/');
  expect(new URLSearchParams(location.search).get('office')).toBe('1');

});

it("distingue a apuração das urnas e a distância de cada candidato até 50%", () => {
  render(<RegionalProgress office="Presidente" colors={{}} regions={[{
    id: 'sul', name: 'Sul', total: 100, totalized: 75, percentage: 75, status: 'available',
    expected_ufs: ['pr', 'rs', 'sc'], missing_ufs: [], error_ufs: [], updated_at: null, collected_at: null,
    ranking: { status: 'available', items: [
      { number: '90', scope: 'br', name: 'Ana', party: '90', party_name: 'A', votes: 600, percentage: 60 },
      { number: '91', scope: 'br', name: 'Bia', party: '91', party_name: 'B', votes: 350, percentage: 35 },
    ] },
  }]} />);
  expect(screen.getByText('75% apurado')).toBeTruthy();
  expect(screen.getByTitle('Faltam 25 urnas')).toBeTruthy();
  expect(screen.getByRole('listitem', { name: /Ana.*10 p.p. acima de 50%/ })).toBeTruthy();
  expect(screen.getByRole('listitem', { name: /Bia.*Faltam 15 p.p. para 50%/ })).toBeTruthy();
  expect(screen.getAllByRole('listitem').map(item => item.getAttribute('aria-label'))).toEqual([expect.stringContaining('Ana'), expect.stringContaining('Bia')]);
});
