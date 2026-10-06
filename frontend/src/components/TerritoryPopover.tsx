import { useEffect, useRef } from 'react';
import type { Dashboard } from '../types';
import CandidateTop from './CandidateTop';

export default function TerritoryPopover({ title, data, colors, error, onClose }: {
  title: string; data?: Dashboard; colors: Record<string, string>; error: string; onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      if (event.target instanceof Node && !ref.current?.contains(event.target)) onClose();
    };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('pointerdown', dismiss);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', dismiss); document.removeEventListener('keydown', escape); };
  }, [onClose]);
  return <div ref={ref} className="territory-popover" role="dialog" aria-label={`Votação em ${title}`}>
    <div className="panel-heading"><div><p className="eyebrow">Votação local</p><h2>{title}</h2></div>
      <button type="button" aria-label="Fechar votação local" onClick={onClose}>✕</button>
    </div>
    <CandidateTop data={data} colors={colors} error={error} />
  </div>;
}
