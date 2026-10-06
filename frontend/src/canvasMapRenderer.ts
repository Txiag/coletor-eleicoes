import type { Camera, Prepared } from './mapGeometry';
import type { Position } from './useMapData';

export type PaintedFeature = { geometry: Prepared; fill: string; tie: boolean };

function simplify(points: Position[], tolerance: number): Position[] {
  if (!tolerance || points.length < 6) return points;
  const keep = new Set([0, points.length - 1]);
  const stack = [[0, points.length - 1]];
  while (stack.length) {
    const [first, last] = stack.pop()!;
    const [x, y] = points[first], [endX, endY] = points[last];
    const dx = endX - x, dy = endY - y, length = dx * dx + dy * dy;
    let distance = tolerance * tolerance, selected = -1;
    for (let i = first + 1; i < last; i++) {
      const [px, py] = points[i];
      const t = length ? Math.max(0, Math.min(1, ((px - x) * dx + (py - y) * dy) / length)) : 0;
      const squared = (px - x - dx * t) ** 2 + (py - y - dy * t) ** 2;
      if (squared > distance) { selected = i; distance = squared; }
    }
    if (selected >= 0) { keep.add(selected); stack.push([first, selected], [selected, last]); }
  }
  const result = [...keep].sort((a, b) => a - b).map(index => points[index]);
  return result.length >= 4 ? result : points;
}

export class CanvasMapRenderer {
  private ctx: CanvasRenderingContext2D | null;
  private buffer = document.createElement('canvas');
  private bufferContext: CanvasRenderingContext2D | null;
  private paths = new WeakMap<Prepared, Map<number, Path2D>>();
  private scene: PaintedFeature[] = [];
  private borders: Prepared[] = [];
  private cachedCamera: Camera | null = null;
  private width = 0;
  private height = 0;
  private ratio = 1;
  private padding = 128;
  private redraw: number | undefined;
  private camera: Camera = { x: -540, y: 150, zoom: 1 };
  private moving = false;
  private pattern: CanvasPattern | null = null;

  constructor(private canvas: HTMLCanvasElement) {
    this.ctx = typeof CanvasRenderingContext2D === 'undefined' ? null : canvas.getContext('2d');
    this.bufferContext = this.ctx ? this.buffer.getContext('2d') : null;
    if (this.bufferContext) {
      const hatch = document.createElement('canvas');
      hatch.width = hatch.height = 6;
      const ctx = hatch.getContext('2d')!;
      ctx.fillStyle = '#303238'; ctx.fillRect(0, 0, 6, 6);
      ctx.strokeStyle = '#8994a5'; ctx.beginPath(); ctx.moveTo(0, 6); ctx.lineTo(6, 0); ctx.stroke();
      this.pattern = this.bufferContext.createPattern(hatch, 'repeat');
    }
  }

  setScene(scene: PaintedFeature[], borders: Prepared[]) {
    this.scene = scene; this.borders = borders; this.cachedCamera = null;
    this.draw(this.camera, false);
  }

  resize(width: number, height: number) {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    if (width === this.width && height === this.height && ratio === this.ratio) return;
    this.width = width; this.height = height; this.ratio = ratio;
    this.canvas.width = Math.round(width * ratio); this.canvas.height = Math.round(height * ratio);
    this.buffer.width = Math.round((width + this.padding * 2) * ratio);
    this.buffer.height = Math.round((height + this.padding * 2) * ratio);
    this.cachedCamera = null;
    this.draw(this.camera, false);
  }

  draw(camera: Camera, moving: boolean) {
    this.camera = camera; this.moving = moving;
    if (this.redraw == null) this.redraw = requestAnimationFrame(() => { this.redraw = undefined; this.paint(); });
  }

  destroy() { if (this.redraw != null) cancelAnimationFrame(this.redraw); }

  private scale(camera: Camera) { return Math.min(this.width / 500, this.height / 480) * camera.zoom; }

  private path(item: Prepared, scale: number) {
    const tolerance = scale < 2 ? 0.2 : scale < 6 ? 0.06 : 0;
    let paths = this.paths.get(item);
    if (!paths) { paths = new Map(); this.paths.set(item, paths); }
    let path = paths.get(tolerance);
    if (!path) {
      path = new Path2D();
      for (const ring of item.rings) {
        const points = simplify(ring, tolerance);
        points.forEach(([x, y], index) => { if (index) path!.lineTo(x, y); else path!.moveTo(x, y); });
        path.closePath();
      }
      paths.set(tolerance, path);
    }
    return path;
  }

  private rasterize() {
    const ctx = this.bufferContext!, camera = this.camera, scale = this.scale(camera), padding = this.padding;
    const halfWidth = (this.width / 2 + padding) / scale, halfHeight = (this.height / 2 + padding) / scale;
    const visible = (item: Prepared) => item.box.maxX >= camera.x - halfWidth && item.box.minX <= camera.x + halfWidth
      && item.box.maxY >= camera.y - halfHeight && item.box.minY <= camera.y + halfHeight;
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, this.buffer.width, this.buffer.height);
    ctx.setTransform(scale * this.ratio, 0, 0, scale * this.ratio,
      (this.width / 2 + padding - camera.x * scale) * this.ratio, (this.height / 2 + padding - camera.y * scale) * this.ratio);
    ctx.lineJoin = 'round'; ctx.strokeStyle = '#101011'; ctx.lineWidth = 0.35 / scale;
    if (this.pattern) this.pattern.setTransform(new DOMMatrix().scale(1 / scale));
    for (const item of this.scene) {
      if (!visible(item.geometry)) continue;
      const path = this.path(item.geometry, scale);
      ctx.fillStyle = item.tie && this.pattern ? this.pattern : item.fill;
      ctx.fill(path, 'evenodd');
      ctx.stroke(path);
    }
    ctx.setLineDash([]); ctx.strokeStyle = '#080809'; ctx.lineWidth = 1 / scale;
    for (const item of this.borders) if (visible(item)) ctx.stroke(this.path(item, scale));
    this.cachedCamera = { ...camera };
  }

  private paint() {
    if (!this.ctx || !this.bufferContext || !this.width || !this.height) return;
    const scale = this.scale(this.camera);
    let ratio = this.cachedCamera ? scale / this.scale(this.cachedCamera) : 1;
    const placement = () => ({
      x: this.width / 2 + (this.cachedCamera!.x - this.camera.x) * scale - (this.width / 2 + this.padding) * ratio,
      y: this.height / 2 + (this.cachedCamera!.y - this.camera.y) * scale - (this.height / 2 + this.padding) * ratio,
    });
    const old = this.cachedCamera ? placement() : null;
    // A margem permite mover uma imagem já desenhada; novas áreas e o fim do gesto refinam a malha.
    if (!this.cachedCamera || !this.moving || ratio < 0.6 || ratio > 1.8 || !old || old.x > 0 || old.y > 0
      || old.x + (this.width + this.padding * 2) * ratio < this.width || old.y + (this.height + this.padding * 2) * ratio < this.height) {
      this.rasterize(); ratio = 1;
    }
    const { x, y } = placement();
    this.ctx.setTransform(this.ratio, 0, 0, this.ratio, 0, 0);
    this.ctx.clearRect(0, 0, this.width, this.height);
    this.ctx.drawImage(this.buffer, x, y, (this.width + this.padding * 2) * ratio, (this.height + this.padding * 2) * ratio);
  }
}
