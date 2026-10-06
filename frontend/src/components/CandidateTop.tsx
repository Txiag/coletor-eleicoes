import type { Dashboard } from '../types';
import { number } from "../format";

export default function CandidateTop({ data, colors, error }: {
  data?: Dashboard; colors: Record<string, string>; error: string;
}) {
  if (!data) return <p role="status" className="muted">{error || 'Carregando resultados…'}</p>;
  if (!data.source.available) return <p className="muted">{data.source.reason || 'Aguardando resultados neste recorte.'}</p>;
  const ranking = data.candidates;
  return <>
    <p className="muted denominator">{data.source.label} · Percentual sobre {number(ranking.denominator)} {ranking.denominator_label}.</p>
    <ol className="ranking">
      {ranking.items.slice(0, 5).map((item, index) => <li key={`${item.scope}:${item.number}`}>
        <div className="candidate-card">
          <span className="rank-position">{index + 1}</span>
          <span className="candidate-content">
            <span className="candidate-name">{item.name}</span>
            <span className="candidate-meta"><i style={{ background: colors[item.party] || '#7b8798' }} />{item.party_name || item.party} · {item.number}</span>
            <span className="vote-bar"><i style={{ width: `${Math.max(0, Math.min(100, item.percentage || 0))}%`, background: colors[item.party] || '#7b8798' }} /></span>
          </span>
          <span className="candidate-values"><strong>{item.percentage == null ? '—' : `${number(item.percentage)}%`}</strong><small>{number(item.votes)} votos</small></span>
        </div>
      </li>)}
    </ol>
    {!!ranking.remaining?.count && <p className="remaining-candidates">Mais {number(ranking.remaining.count)} candidatos com {ranking.remaining.percentage == null ? 'percentual indisponível' : `${number(ranking.remaining.percentage)}%`} e {ranking.remaining.votes == null ? 'votos pendentes' : `${number(ranking.remaining.votes)} votos`}.</p>}
    {!ranking.items.length && <p className="muted">Aguardando resultados.</p>}
  </>;
}
