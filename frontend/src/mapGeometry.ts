import { territoryKey } from './useMapData';
import type { Feature, Geography, Position } from './useMapData';

function rings(feature: Feature): Position[][] {
  return feature.geometry.type === 'Polygon' ? feature.geometry.coordinates : feature.geometry.coordinates.flat();
}
export function project([lon, lat]: Position): Position {
  return [lon * 10, -Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) * 1800 / Math.PI];
}
function bounds(features: Feature[]) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const feature of features) for (const ring of rings(feature)) for (const point of ring) {
    const [x, y] = project(point);
    minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
  }
  return { minX, minY, maxX, maxY };
}
export type Camera = { x: number; y: number; zoom: number };
export function zoomAround(camera: Camera, zoom: number, [x, y]: Position): Camera {
  return { zoom, x: x - (x - camera.x) * camera.zoom / zoom, y: y - (y - camera.y) * camera.zoom / zoom };
}

export function interpolateCamera(from: Camera, to: Camera, progress: number): Camera {
  const zoom = from.zoom * Math.pow(to.zoom / from.zoom, progress);
  // O centro precisa acompanhar a escala inversa para manter a âncora imóvel na tela.
  const weight = Math.abs(to.zoom - from.zoom) < 1e-10 ? progress : (from.zoom / zoom - 1) / (from.zoom / to.zoom - 1);
  return { zoom, x: from.x + (to.x - from.x) * weight, y: from.y + (to.y - from.y) * weight };
}

export function fitCamera(features: Feature[]): Camera {
  const box = bounds(features);
  return { x: (box.minX + box.maxX) / 2, y: (box.minY + box.maxY) / 2,
    zoom: Math.min(460 / Math.max(box.maxX - box.minX, 0.000001), 440 / Math.max(box.maxY - box.minY, 0.000001)) };
}


export type Prepared = { feature: Feature; rings: Position[][]; path: string; x: number; y: number; box: ReturnType<typeof bounds>; key: string; level: 'uf' | 'municipality' };
const preparedCache = new WeakMap<Geography, Prepared[]>();
export function prepare(data: Geography, level: 'uf' | 'municipality'): Prepared[] {
  const cached = preparedCache.get(data);
  if (cached) return cached;
  const result = data.features.map(feature => {
    const box = bounds([feature]);
    return { feature, rings: rings(feature).map(ring => ring.map(project)), box, level, key: territoryKey(level, feature.properties.uf, feature.properties.id || feature.properties.ibge_code || feature.properties.name),
      path: rings(feature).map(ring => ring.map((point, index) => `${index ? 'L' : 'M'}${project(point).map(n => n.toFixed(4)).join(',')}`).join('') + 'Z').join(''),
      x: (box.minX + box.maxX) / 2, y: (box.minY + box.maxY) / 2 };
  });
  preparedCache.set(data, result);
  return result;
}

export function contains(item: Prepared, x: number, y: number) {
  if (x < item.box.minX || x > item.box.maxX || y < item.box.minY || y > item.box.maxY) return false;
  let inside = false;
  for (const ring of item.rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
  }
  return inside;
}

export class MapHitIndex {
  private cells = new Map<string, Prepared[]>();
  constructor(items: Prepared[]) {
    for (const item of items) {
      for (let x = Math.floor(item.box.minX / 10); x <= Math.floor(item.box.maxX / 10); x++)
        for (let y = Math.floor(item.box.minY / 10); y <= Math.floor(item.box.maxY / 10); y++) {
          const key = `${x}:${y}`;
          const bucket = this.cells.get(key) || [];
          bucket.push(item);
          this.cells.set(key, bucket);
        }
    }
  }
  pick(x: number, y: number) {
    return this.cells.get(`${Math.floor(x / 10)}:${Math.floor(y / 10)}`)?.find(item => contains(item, x, y));
  }
}
