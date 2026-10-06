import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { partyColor } from '../partyColors';
import type { Territory } from '../types';
import { useMapData, territoryKey } from '../useMapData';
import type { Feature, Position } from '../useMapData';

import { prepare, fitCamera, project, MapHitIndex, zoomAround, interpolateCamera } from '../mapGeometry';
import type { Camera, Prepared } from '../mapGeometry';
import { CanvasMapRenderer } from '../canvasMapRenderer';

type Props = {
  uf: string; municipality: string; colors: Record<string, string>; sourceLabel?: string;
  resultUrl: string; seconds: number; paused: boolean; refresh: number;
  onSelect: (level: 'uf' | 'municipality', id: string, uf?: string, name?: string) => void;
};
const number = new Intl.NumberFormat('pt-BR');
const progressNumber = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 });
const labelPositions: Record<string, Position> = { rn: [-32, -5], pb: [-32, -7], pe: [-32, -9], al: [-32, -11], se: [-32, -13], df: [-45, -14.5], sc: [-44, -28] };

function description(feature: Pick<Feature, 'properties'>, territory: Territory | undefined, contextual = false): string {
  const label = feature.properties.name;
  if (!feature.properties.id) return `${label}: sem correspondência oficial TSE/IBGE. Consulte a tabela.`;
  if (contextual) return `${label}: mapa de referência, sem votação atribuída ao polígono nesta visualização. Consulte os resultados de zonas na lista.`;
  if (!territory || territory.state === 'pending') return `${label}: aguardando dados.`;
  if (territory.state === 'unavailable') return `${label}: liderança indisponível nesta fonte ou abrangência.`;
  if (territory.state === 'tie') return `${label}: empate entre partidos.`;
  if (territory.state === 'zero') return `${label}: sem votos partidários.`;
  if (!territory.leader || territory.margin === null) return `${label}: liderança indisponível.`;
  const runner = territory.runner_up ? ` Segundo: ${territory.runner_up.name}, ${number.format(territory.runner_up.votes)} votos.` : ' Sem segundo partido com votos.';
  const winner = territory.winner ? ` ${territory.winner.name} lidera com ${number.format(territory.winner.votes || 0)} votos${territory.winner.percentage == null ? '' : ` (${number.format(territory.winner.percentage)}%)`}.` : '';
  return `${label}: ${territory.leader.name}, ${number.format(territory.leader.votes)} votos.${winner}${runner} Margem: ${territory.margin.toFixed(2).replace('.', ',')} p.p.`;
}
function color(territory: Territory | undefined, colors: Record<string, string>) {
  if (!territory || territory.state !== 'available' || !territory.leader || territory.margin === null) return '#303238';
  const hex = partyColor(territory.leader.number, territory.leader.name, colors);
  const base = /^#[0-9a-f]{6}$/i.test(hex || '') ? hex : '#3569a8';
  const strength = 0.35 + 0.65 * Math.max(0, Math.min(100, territory.margin)) / 100;
  const channels = [1, 3, 5].map(start => Math.round(24 + (parseInt(base.slice(start, start + 2), 16) - 24) * strength));
  return `rgb(${channels.join(',')})`;
}

function describe(feature: Pick<Feature, 'properties'>, territory?: Territory) {
  const source = territory?.source;
  const progress = source?.official_progress;
  return `${description(feature, territory)}${progress == null ? '' : ` Seções totalizadas: ${progressNumber.format(progress)}%.`} Fonte: ${source?.label || 'Não informado'}. Atualização na fonte: ${source?.updated_at || 'Não informado'}. Importação: ${source?.collected_at || 'Não informado'}.`;
}
function viewBox(camera: Camera) {
  return `${camera.x - 250 / camera.zoom} ${camera.y - 240 / camera.zoom} ${500 / camera.zoom} ${480 / camera.zoom}`;
}

export default function ElectionMap({ uf, municipality, colors, sourceLabel, resultUrl, seconds, paused, refresh, onSelect }: Props) {
  const [search, setSearch] = useState('');
  const [active, setActive] = useState<string | null>(null);
  useEffect(() => { if (!uf) setActive(null); }, [uf]);
  const [camera, setCamera] = useState<Camera>({ x: -540, y: 150, zoom: 1 });
  const [priority, setPriority] = useState(uf);
  const map = useMapData(resultUrl, seconds, paused, refresh, priority);
  const data = map.geography[''];
  const svgRef = useRef<SVGSVGElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const renderer = useRef<CanvasMapRenderer | null>(null);
  const cameraRef = useRef(camera);
  const targetRef = useRef(camera);
  const homeRef = useRef<Camera | null>(null);
  const frameRef = useRef<number | undefined>(undefined);
  const refinementRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const pointerSelection = useRef<string | null | undefined>(undefined);
  const dragRef = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const initialSelection = useRef({ uf, municipality, fitted: false });
  const states = useMemo(() => data ? prepare(data, 'uf') : [], [data]);
  const cities = useMemo(() => Object.entries(map.geography).flatMap(([key, value]) => key ? prepare(value, 'municipality') : []), [map.geography]);
  const features = useMemo(() => new Map([...states, ...cities].map(item => [item.key, item])), [states, cities]);
  const changeCamera = (next: Camera, commit = false) => {
    const homeZoom = homeRef.current?.zoom || 1;
    const changedLevel = (cameraRef.current.zoom / homeZoom > 3) !== (next.zoom / homeZoom > 3);
    cameraRef.current = next;
    renderer.current?.draw(next, !commit);
    svgRef.current?.setAttribute('viewBox', viewBox(next));
    if (commit || changedLevel) setCamera(next);
  };
  const stopAnimation = () => {
    if (frameRef.current != null) cancelAnimationFrame(frameRef.current);
    clearTimeout(refinementRef.current);
  };
  const animateCamera = (next: Camera) => {
    stopAnimation(); targetRef.current = next;
    if (!window.matchMedia || window.matchMedia('(prefers-reduced-motion: reduce)').matches) { changeCamera(next, true); return; }
    const from = cameraRef.current;
    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / 280);
      const eased = 1 - Math.pow(1 - progress, 3);
      changeCamera(interpolateCamera(from, next, eased), progress === 1);
      if (progress < 1) frameRef.current = requestAnimationFrame(tick);
    };
    frameRef.current = requestAnimationFrame(tick);
  };
  const focusTerritory = (item: Prepared) => {
    const svg = svgRef.current;
    const viewport = svg?.getBoundingClientRect();
    if (!svg || !viewport?.width || !viewport.height) {
      animateCamera(fitCamera([item.feature]));
      return;
    }
    const style = getComputedStyle(svg.parentElement!);
    const inset = (edge: string) => parseFloat(style.getPropertyValue(`--focus-${edge}`)) || 0;
    const left = inset('left'), right = inset('right'), top = inset('top'), bottom = inset('bottom');
    const width = Math.max(1, viewport.width - left - right);
    const height = Math.max(1, viewport.height - top - bottom);
    const unitScale = Math.min(viewport.width / 500, viewport.height / 480);
    const fitScale = 0.85 * Math.min(width / Math.max(item.box.maxX - item.box.minX, 0.000001), height / Math.max(item.box.maxY - item.box.minY, 0.000001));
    const zoom = Math.min(fitScale / unitScale, (homeRef.current?.zoom || 1) * 128);
    const scale = unitScale * zoom;
    animateCamera({ zoom,
      x: item.x - (left + width / 2 - viewport.width / 2) / scale,
      y: item.y - (top + height / 2 - viewport.height / 2) / scale,
    });
  };
  useEffect(() => () => stopAnimation(), []);
  useLayoutEffect(() => {
    if (!states.length || homeRef.current) return;
    const home = fitCamera(states.map(item => item.feature));
    homeRef.current = home; targetRef.current = home; changeCamera(home, true);
  }, [states]);
  useEffect(() => {
    const initial = initialSelection.current;
    if (initial.fitted || !homeRef.current) return;
    if (!initial.uf || initial.uf === 'zz') { initial.fitted = true; return; }
    const selected = initial.municipality ? cities.find(item => item.feature.properties.uf === initial.uf && item.feature.properties.id === initial.municipality)
      : states.find(item => item.feature.properties.id === initial.uf);
    if (selected) { initial.fitted = true; focusTerritory(selected); }
  }, [states, cities]);
  const zoomAt = (factor: number, point?: Position) => {
    stopAnimation();
    const current = cameraRef.current, home = homeRef.current;
    if (!home) return;
    const zoom = Math.max(home.zoom, Math.min(home.zoom * 128, current.zoom * factor));
    const [x, y] = point || [current.x, current.y];
    const next = zoom === home.zoom ? home : zoomAround(current, zoom, [x, y]);
    targetRef.current = next;
    changeCamera(next);
    setCamera(next);
    refinementRef.current = setTimeout(() => renderer.current?.draw(cameraRef.current, false), 100);
  };
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      if (!event.deltaY) return;
      const point = svg.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
      const matrix = svg.getScreenCTM();
      const local = matrix ? point.matrixTransform(matrix.inverse()) : null;
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 480 : 1);
      zoomAt(Math.exp(-Math.max(-180, Math.min(180, delta)) * 0.0022), local ? [local.x, local.y] : undefined);
    };
    svg.addEventListener('wheel', wheel, { passive: false });
    return () => svg.removeEventListener('wheel', wheel);
  }, [data]);
  const relativeZoom = camera.zoom / (homeRef.current?.zoom || 1);
  const cityView = relativeZoom > 3;
  const selectedKey = territoryKey(municipality ? 'municipality' : 'uf', uf, municipality || uf);
  const focused = active ? features.get(active) : features.get(selectedKey);
  const exterior = map.items[territoryKey('uf', '', 'zz')];
  const exteriorFeature = { properties: { id: 'zz', name: 'Exterior (ZZ)', uf: 'zz' } };
  const select = (key: string) => {
    const item = features.get(key);
    if (item?.feature.properties.id) {
      const { id, uf: state, name } = item.feature.properties;
      if (item.level === 'uf') {
        setPriority(id);
        setActive(null);
      }
      focusTerritory(item);
      onSelect(item.level, id, state, name);
    }
  };
  const visibleGeometry = useMemo(() => cityView ? [...cities, ...states.filter(item => !map.geography[item.feature.properties.id || '']?.features.length)] : states, [cityView, cities, states, map.geography]);
  const scene = useMemo(() => visibleGeometry.map(geometry => {
    const territory = map.items[geometry.key];
    return { geometry, fill: color(territory, colors), tie: territory?.state === 'tie' };
  }), [visibleGeometry, map.items, colors]);
  const hitIndex = useMemo(() => new MapHitIndex(visibleGeometry), [visibleGeometry]);
  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const painter = new CanvasMapRenderer(canvas);
    renderer.current = painter;
    const resize = () => { const box = canvas.getBoundingClientRect(); painter.resize(box.width, box.height); painter.draw(cameraRef.current, false); };
    resize();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize);
    observer?.observe(canvas);
    window.addEventListener('resize', resize);
    return () => { observer?.disconnect(); window.removeEventListener('resize', resize); painter.destroy(); renderer.current = null; };
  }, [data]);
  useLayoutEffect(() => { renderer.current?.setScene(scene, states); renderer.current?.draw(cameraRef.current, false); }, [scene, states]);
  const pointAt = (clientX: number, clientY: number): Position | null => {
    const svg = svgRef.current, matrix = svg?.getScreenCTM();
    if (!svg || !matrix) return null;
    const point = svg.createSVGPoint(); point.x = clientX; point.y = clientY;
    const local = point.matrixTransform(matrix.inverse());
    return [local.x, local.y];
  };
  const hitAt = (clientX: number, clientY: number) => { const point = pointAt(clientX, clientY); return point ? hitIndex.pick(...point) : undefined; };
  const searchMatches = useMemo(() => {
    const normalize = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
    const term = normalize(search.trim());
    return term ? cities.filter(item => normalize(`${item.feature.properties.name} ${item.feature.properties.uf}`).includes(term)).slice(0, 8) : [];
  }, [cities, search]);
  const visibleCities = cityView ? cities.filter(item => {
    const { box, x, y } = item;
    return Math.abs(x - camera.x) < 240 / camera.zoom && Math.abs(y - camera.y) < 225 / camera.zoom
      && Math.min(box.maxX - box.minX, box.maxY - box.minY) * camera.zoom > 28;
  }).sort((a, b) => (b.box.maxX - b.box.minX) * (b.box.maxY - b.box.minY) - (a.box.maxX - a.box.minX) * (a.box.maxY - a.box.minY)).slice(0, 35) : [];
  const labels = !cityView ? states : [...new Map([...visibleCities, ...(focused ? [focused] : [])].map(item => [item.key, item])).values()];
  return <div className="election-map">
    {!data ? <p role="status" className="map-notice">{map.geometryErrors.length ? 'Não foi possível carregar a malha. Recarregue a página para tentar novamente.' : 'Carregando mapa…'}</p> : <>
      <div className="map-controls" aria-label="Zoom do mapa">
        <button type="button" aria-label="Aproximar mapa" onClick={() => zoomAt(1.5)}>+</button>
        <button type="button" aria-label="Afastar mapa" disabled={relativeZoom <= 1} onClick={() => zoomAt(1 / 1.5)}>−</button>
        <button type="button" aria-label="Enquadrar Brasil" onClick={() => { setActive(null); if (homeRef.current) animateCamera(homeRef.current); onSelect('uf', ''); }}>⌂</button>
        <span>{relativeZoom.toFixed(1)}× · Arraste para explorar</span>
      </div>
      <div className="map-load-status" role="status">
        {map.loading ? `Carregando resultados · ${map.completed}/${states.length + 1}` : `${number.format(cities.length)} municípios no mapa`}
        {(map.errors.length > 0 || map.geometryErrors.length > 0) && <span> · Consulta incompleta: {[...new Set([...map.errors, ...map.geometryErrors])].join(', ').toUpperCase()}</span>}
      </div>
      <details className="map-search">
        <summary>Buscar município</summary>
        <label><span className="sr-only">Buscar município no mapa</span><input type="search" aria-label="Buscar município no mapa" placeholder="Nome da cidade ou UF" value={search} onChange={event => setSearch(event.target.value)} /></label>
        {searchMatches.map(item => <button type="button" key={item.key} aria-label={describe(item.feature, map.items[item.key])}
          onFocus={() => setActive(item.key)} onMouseEnter={() => setActive(item.key)} onClick={() => { setActive(item.key); select(item.key); }}>
          {item.feature.properties.name} · {item.feature.properties.uf.toUpperCase()}
        </button>)}
        {search && !searchMatches.length && <p role="status">Nenhum município encontrado nas malhas carregadas.</p>}
      </details>
      <canvas ref={canvasRef} className="map-canvas map-raster" aria-hidden="true" />
      <svg ref={svgRef} className="map-canvas" viewBox={viewBox(camera)} role="group" tabIndex={0} aria-label="Mapa contínuo dos municípios do Brasil. Use as setas para mover, mais e menos para zoom ou a busca para selecionar uma cidade."
        onPointerDown={event => { pointerSelection.current = undefined; stopAnimation(); targetRef.current = cameraRef.current; dragRef.current = { x: event.clientX, y: event.clientY, moved: false }; }}
        onPointerMove={event => {
          const drag = dragRef.current;
          if (!drag || !event.buttons) {
            const key = (event.target as Element).closest('[data-key]')?.getAttribute('data-key');
            const item = key ? features.get(key) : hitAt(event.clientX, event.clientY);
            setActive(item?.key || null);
            if (item) setPriority(item.feature.properties.uf);
            return;
          }
          const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
          if (Math.abs(dx) + Math.abs(dy) < 3) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          const matrix = event.currentTarget.getScreenCTM();
          if (matrix) { const next = { ...cameraRef.current, x: cameraRef.current.x - dx / matrix.a, y: cameraRef.current.y - dy / matrix.d }; targetRef.current = next; changeCamera(next); }
          dragRef.current = { x: event.clientX, y: event.clientY, moved: true };
        }}
        onPointerUp={event => {
          if (!dragRef.current?.moved) pointerSelection.current = (event.target as Element).closest('[data-key]')?.getAttribute('data-key') || hitAt(event.clientX, event.clientY)?.key || null;
          if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
          changeCamera(cameraRef.current, true);
        }}
        onPointerCancel={() => { pointerSelection.current = undefined; dragRef.current = null; changeCamera(cameraRef.current, true); }}
        onPointerLeave={() => { if (!dragRef.current?.moved) setActive(null); }}
        onFocus={event => { const el = (event.target as Element).closest('[data-key]'); if (el) setActive(el.getAttribute('data-key')); }}
        onClick={event => {
          if (dragRef.current?.moved) return;
          // Click arredonda coordenadas no Chromium; pointerup preserva a precisão em cidades pequenas.
          const key = pointerSelection.current !== undefined ? pointerSelection.current : (event.target as Element).closest('[data-key]')?.getAttribute('data-key') || hitAt(event.clientX, event.clientY)?.key;
          pointerSelection.current = undefined;
          if (key) { setActive(key); select(key); }
          else { setActive(null); onSelect('uf', ''); }
        }}
        onKeyDown={event => {
          if (event.key === '+' || event.key === '=') { event.preventDefault(); zoomAt(1.5); }
          else if (event.key === '-') { event.preventDefault(); zoomAt(1 / 1.5); }
          else if (event.key.startsWith('Arrow')) {
            event.preventDefault(); const next = { ...targetRef.current };
            const step = 35 / next.zoom;
            if (event.key === 'ArrowLeft') next.x -= step;
            if (event.key === 'ArrowRight') next.x += step;
            if (event.key === 'ArrowUp') next.y -= step;
            if (event.key === 'ArrowDown') next.y += step;
            animateCamera(next);
          } else if (event.key === 'Enter' && focused) { event.preventDefault(); select(focused.key); }
        }}>
        <g pointerEvents="none" aria-hidden="true">{[selectedKey, active].filter((key, index, all) => key && all.indexOf(key) === index).map(key => { const item = features.get(key!); return item && (cityView || item.level === 'uf') ? <path key={key} d={item.path} fill="none" stroke="#fff" strokeWidth="1.6" vectorEffect="non-scaling-stroke" /> : null; })}</g>
        {labels.map(item => {
          const { key, x, y, level, feature } = item;
          const territory = map.items[key];
          const position = level === 'uf' ? labelPositions[feature.properties.id || ''] : undefined;
          const [labelX, labelY] = position ? project(position) : [x, y];
          const progress = territory?.source?.official_progress;
          return <g key={key} data-key={key} data-uf={feature.properties.uf} pointerEvents={level === 'uf' ? 'auto' : 'none'} style={{ cursor: 'pointer' }}>
            {position && <line x1={x} y1={y} x2={labelX - 12 / camera.zoom} y2={labelY} stroke="#77776c" strokeWidth="0.7" vectorEffect="non-scaling-stroke" pointerEvents="none" />}
            <text x={labelX} y={labelY - 4 / camera.zoom} textAnchor="middle" dominantBaseline="central" fontSize={9 / camera.zoom} fontWeight="650" fill="#fff" stroke="#161719" strokeWidth={2 / camera.zoom} paintOrder="stroke" aria-hidden="true">
              <tspan x={labelX}>{level === 'uf' ? feature.properties.uf.toUpperCase() : feature.properties.name}</tspan>
              {level === 'uf' ? <tspan x={labelX} dy={11 / camera.zoom} fontSize={8 / camera.zoom} fontWeight="500">{progress == null ? '—' : `${progressNumber.format(progress)}%`}</tspan>
                : (key === active || key === selectedKey) && territory?.winner && <tspan x={labelX} dy={12 / camera.zoom} fontSize={8 / camera.zoom}>{territory.winner.name}{territory.winner.percentage == null ? '' : ` · ${progressNumber.format(territory.winner.percentage)}%`}</tspan>}
            </text>
          </g>;
        })}
      </svg>
      {exterior && <div className="map-exterior"><button type="button" aria-label={describe(exteriorFeature, exterior)} onFocus={() => setActive('exterior')} onMouseEnter={() => setActive('exterior')} onClick={() => onSelect('uf', 'zz')}>
        <span className="map-exterior-swatch" style={{ background: color(exterior, colors) }} />Exterior (ZZ)</button><small>Votos no exterior · sem representação geográfica</small></div>}
    </>}
  </div>;
}
