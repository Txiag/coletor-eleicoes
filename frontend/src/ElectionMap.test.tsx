import { render, screen, cleanup, fireEvent, waitFor, act } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CanvasMapRenderer } from "./canvasMapRenderer";
import ElectionMap from "./components/ElectionMap";
import type { Territory } from "./types";
import type { Feature } from "./useMapData";
import { MapHitIndex, prepare, project, fitCamera, zoomAround, interpolateCamera } from "./mapGeometry";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const shape = (id: string, name: string, uf: string, x: number): Feature => ({ type: 'Feature', properties: { id, name, uf },
  geometry: { type: 'Polygon', coordinates: [[[x, -4], [x + 1, -4], [x + 1, -3], [x, -4]]] } });
const geography = (features: ReturnType<typeof shape>[]) => ({ features, available: true, reason: null, attribution: 'IBGE', edition: '2020' });
const country = geography([shape('ce', 'Ceará', 'ce', -40), shape('pe', 'Pernambuco', 'pe', -37)]);
const territory = (id: string, name: string, level: Territory['level'] = 'municipality'): Territory => ({
  id, name, level, votes: 10, candidate_votes: null, leader: { number: '10', name: 'Partido', votes: 10 }, runner_up: null,
  margin: 100, state: 'available',
  source: { label: 'Resultados oficiais do TSE — EA20', updated_at: null, collected_at: null, url: null, official_progress: 75 },
});
const base = { uf: '', municipality: '', resultUrl: '/api/dashboard?dataset=1&election=6257&office=1', seconds: 0, paused: true, refresh: 0, colors: { '10': '#ff0000' }, onSelect: vi.fn() };
it('mantém o ponto sob o cursor fixo ao interromper e inverter uma rajada de zoom', () => {
  let camera = { x: -500, y: 100, zoom: 1 };
  const anchor: [number, number] = [-420, 70];
  const screenOffset = [(anchor[0] - camera.x) * camera.zoom, (anchor[1] - camera.y) * camera.zoom];
  let targetZoom = 1;
  for (const factor of [2, 2, 2, 2, 0.5, 0.5, 4]) {
    targetZoom *= factor;
    const target = zoomAround(camera, targetZoom, anchor);
    const start = camera;
    for (const progress of [0.1, 0.25, 0.4]) {
      camera = interpolateCamera(start, target, progress);
      expect((anchor[0] - camera.x) * camera.zoom).toBeCloseTo(screenOffset[0], 8);
      expect((anchor[1] - camera.y) * camera.zoom).toBeCloseTo(screenOffset[1], 8);
    }
  }
});
function mockFetch(results: (url: URL) => Promise<unknown>) {
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const url = new URL(input, location.origin);
    if (url.pathname === '/api/geography') return { ok: true, json: async () => url.searchParams.has('uf')
      ? geography([shape('00001', url.searchParams.get('uf') === 'ce' ? 'Fortaleza' : 'Recife', url.searchParams.get('uf')!, url.searchParams.get('uf') === 'ce' ? -40 : -37)]) : country };
    return { ok: true, json: () => results(url) };
  }));
}

it('centraliza a seleção mantendo cidades de outras UFs e preserva a câmera ao atualizar os dados', async () => {
  mockFetch(async url => ({ territories: { items: url.searchParams.has('uf') ? [territory('00001', url.searchParams.get('uf') === 'ce' ? 'Fortaleza' : 'Recife')] : [territory('ce', 'Ceará', 'uf'), territory('pe', 'Pernambuco', 'uf')] } }));
  const onSelect = vi.fn();
  const { container, rerender } = render(<ElectionMap {...base} onSelect={onSelect} />);
  fireEvent.click(await screen.findByText('Buscar município', { selector: 'summary' }));
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Recife' } });
  await screen.findByRole('button', { name: /Recife:/ });
  const svg = container.querySelector('svg')!;
  const initialCamera = svg.getAttribute('viewBox');
  fireEvent.click(screen.getByRole('button', { name: 'Aproximar mapa' }));
  fireEvent.click(screen.getByRole('button', { name: 'Aproximar mapa' }));
  expect(onSelect).not.toHaveBeenCalled();
  expect(svg.getAttribute('viewBox')).not.toBe(initialCamera);
  const zoomed = svg.getAttribute('viewBox');
  const recife = await screen.findByRole('button', { name: /Recife: Partido/ });
  fireEvent.focus(recife);
  expect(recife.getAttribute('aria-label')).toContain('Recife: Partido');
  fireEvent.click(recife);
  expect(onSelect).toHaveBeenLastCalledWith('municipality', '00001', 'pe', 'Recife');
  const selectedCamera = svg.getAttribute('viewBox');
  expect(selectedCamera).not.toBe(zoomed);
  const cityCamera = fitCamera([shape('00001', 'Recife', 'pe', -37)]);
  const cityView = selectedCamera!.split(' ').map(Number);
  expect(cityView[0] + cityView[2] / 2).toBeCloseTo(cityCamera.x);
  rerender(<ElectionMap {...base} uf='pe' municipality='00001' onSelect={onSelect} />);
  expect(container.querySelector('svg')).toBe(svg);
  expect(svg.getAttribute('viewBox')).toBe(selectedCamera);
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Fortaleza' } });
  expect(screen.getByRole('button', { name: /Fortaleza:/ })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Afastar mapa' }));
  expect(onSelect).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Enquadrar Brasil' }));
  expect(svg.getAttribute('viewBox')).toBe(initialCamera);
  rerender(<ElectionMap {...base} onSelect={onSelect} />);
  fireEvent.click(container.querySelector('[data-key="uf::ce"]')!);
  expect(onSelect).toHaveBeenLastCalledWith('uf', 'ce', 'ce', 'Ceará');
  const stateCamera = fitCamera([country.features[0]]);
  const stateView = svg.getAttribute('viewBox')!.split(' ').map(Number);
  expect(stateView[2]).toBeCloseTo(500 / stateCamera.zoom);
  expect(stateView[0] + stateView[2] / 2).toBeCloseTo(stateCamera.x);
  expect(container.querySelector('[data-key="municipality:ce:00001"]')).toBeTruthy();
  fireEvent.click(container.querySelector('[data-key="municipality:ce:00001"]')!);
  expect(onSelect).toHaveBeenLastCalledWith('municipality', '00001', 'ce', 'Fortaleza');
  fireEvent.click(screen.getByRole('button', { name: 'Enquadrar Brasil' }));
  expect(svg.getAttribute('viewBox')).toBe(initialCamera);
  expect(container.querySelector('[data-key="uf::pe"]')).toBeTruthy();
});

it('descarta resultados atrasados de outra eleição e preserva o exterior sem polígono', async () => {
  let resolveOld: (value: unknown) => void = () => {};
  mockFetch(async url => {
    if (url.searchParams.get('election') === 'old') return new Promise(resolve => { resolveOld = resolve; });
    return { territories: { items: url.searchParams.has('uf') ? [] : [territory('zz', 'Exterior', 'uf')] } };
  });
  const { container, rerender } = render(<ElectionMap {...base} resultUrl={base.resultUrl.replace('election=6257', 'election=old')} />);
  fireEvent.click(await screen.findByText('Buscar município', { selector: 'summary' }));
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Fortaleza' } });
  await screen.findByRole('button', { name: /Fortaleza:/ });
  rerender(<ElectionMap {...base} resultUrl={base.resultUrl.replace('election=6257', 'election=new')} />);
  const exterior = await screen.findByRole('button', { name: /Exterior/ });
  fireEvent.focus(exterior);
  expect(exterior.getAttribute('aria-label')).toContain('Fonte: Resultados oficiais');
  fireEvent.click(exterior);
  expect(base.onSelect).toHaveBeenLastCalledWith('uf', 'zz');
  await act(async () => resolveOld({ territories: { items: [territory('00001', 'Fortaleza')] } }));
  expect(screen.getByRole('button', { name: /Fortaleza: aguardando dados/ })).toBeTruthy();
  expect(container.querySelector('canvas')).toBeTruthy();
});

it('revalida com ETag e preserva os resultados quando a resposta é 304', async () => {
  const requests: { url: string; etag?: string }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(input, location.origin);
    if (url.pathname === '/api/geography') return { ok: true, json: async () => url.searchParams.has('uf')
      ? geography([shape('00001', 'Cidade', url.searchParams.get('uf')!, -40)]) : country };
    const etag = new Headers(init?.headers).get('If-None-Match') || undefined;
    requests.push({ url: input, etag });
    if (etag) return { ok: false, status: 304 };
    return { ok: true, status: 200, headers: new Headers({ ETag: '"version-1"' }), json: async () => ({ territories: { items: url.searchParams.has('uf') ? [territory('00001', 'Cidade')] : [] } }) };
  }));
  const { container, rerender } = render(<ElectionMap {...base} />);
  fireEvent.click(await screen.findByText('Buscar município', { selector: 'summary' }));
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Cidade' } });
  await waitFor(() => expect(screen.getAllByRole('button', { name: /Cidade: Partido/ })).toHaveLength(2));
  const before = screen.getAllByRole('button', { name: /Cidade: Partido/ }).map(item => item.getAttribute('aria-label'));
  rerender(<ElectionMap {...base} refresh={1} />);
  await waitFor(() => expect(requests.filter(request => request.etag === '"version-1"')).toHaveLength(3));
  expect(screen.getAllByRole('button', { name: /Cidade: Partido/ })).toHaveLength(2);
  expect(screen.getAllByRole('button', { name: /Cidade: Partido/ }).map(item => item.getAttribute('aria-label'))).toEqual(before);
});

it('identifica polígonos e ilhas sem selecionar o município dentro de um buraco', () => {
  const feature: Feature = { type: 'Feature', properties: { id: '00001', name: 'Território', uf: 'ce' }, geometry: { type: 'MultiPolygon', coordinates: [
    [[[-40, -5], [-38, -5], [-38, -3], [-40, -3], [-40, -5]], [[-39.5, -4.5], [-38.5, -4.5], [-38.5, -3.5], [-39.5, -3.5], [-39.5, -4.5]]],
    [[[-37, -4], [-36, -4], [-36, -3], [-37, -3], [-37, -4]]],
  ] } };
  const items = prepare(geography([feature]), 'municipality');
  const index = new MapHitIndex(items);
  expect(index.pick(...project([-39.8, -4]))?.key).toBe('municipality:ce:00001');
  expect(index.pick(...project([-39, -4]))).toBeUndefined();
  expect(index.pick(...project([-36.5, -3.5]))?.key).toBe('municipality:ce:00001');
  expect(index.pick(...project([-35, -4]))).toBeUndefined();
});

it('troca a malha e a liderança estadual pela municipal somente acima de 3× e restaura ao afastar', async () => {
  mockFetch(async url => ({ territories: { items: url.searchParams.has('uf')
    ? [territory('00001', 'Cidade')]
    : ['ce', 'pe'].map(id => ({ ...territory(id, id, 'uf'), leader: { number: '20', name: 'Outro partido', votes: 10 } })) } }));
  const painted = vi.spyOn(CanvasMapRenderer.prototype, 'setScene');
  const { container } = render(<ElectionMap {...base} colors={{ '10': '#ff0000', '20': '#0000ff' }} />);
  await screen.findByText('2 municípios no mapa');
  const lastScene = () => painted.mock.calls.at(-1)![0];
  await waitFor(() => expect(lastScene().every(item => item.fill === 'rgb(0,0,255)')).toBe(true));
  const zoomIn = screen.getByRole('button', { name: 'Aproximar mapa' });
  fireEvent.click(zoomIn); fireEvent.click(zoomIn);
  expect(lastScene().every(item => item.geometry.level === 'uf')).toBe(true);
  expect(container.querySelector('[data-key="uf::ce"]')).toBeTruthy();
  fireEvent.click(zoomIn);
  expect(lastScene().every(item => item.geometry.level === 'municipality' && item.fill === 'rgb(255,0,0)')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Afastar mapa' }));
  expect(lastScene().every(item => item.geometry.level === 'uf' && item.fill === 'rgb(0,0,255)')).toBe(true);
  expect(container.querySelector('[data-key="uf::ce"]')).toBeTruthy();
});
