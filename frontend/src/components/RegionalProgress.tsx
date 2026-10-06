import type { RegionalProgress as Region } from "../types";
import { number } from "../format";
import { partyColor } from "../partyColors";

const percent = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 });
export default function RegionalProgress({ regions, office, colors }: { regions: Region[]; office: string; colors: Record<string, string> }) {
  if (!regions.length) return null;
  return <section className="regional-panel regional-results" aria-labelledby="regional-heading">
    <div className="panel-heading"><h2 id="regional-heading">Por região</h2><span>{office}</span></div>
    <p className="muted">Apuração oficial · 1º e 2º lugar</p>
    <div className="regional-grid">{regions.map(region => <article key={region.id} aria-labelledby={`region-${region.id}`}>
      <h3 id={`region-${region.id}`}>{region.name}</h3>
      <span className="region-count" title={region.percentage == null ? 'Contagens indisponíveis' : `Faltam ${number(Math.max(0, (region.total || 0) - (region.totalized || 0)))} urnas`}>
        {region.percentage == null ? '—' : `${percent.format(Math.floor(region.percentage * 10) / 10)}%`} apurado
      </span>
      {region.ranking?.status === 'available' ? <div className="region-vote-overview"><ol className="region-leaders">{region.ranking.items.map((candidate, index) => {
        const share = candidate.percentage;
        const gap = share == null ? null : 50 - share;
        const distance = gap == null ? 'Percentual indisponível' : gap > 0 ? `Faltam ${percent.format(gap)} p.p. para 50%` : gap < 0 ? `${percent.format(-gap)} p.p. acima de 50%` : 'Atingiu 50%';
        const label = `${index + 1}º · ${candidate.name} · ${candidate.party_name || candidate.party} · ${share == null ? '—' : `${percent.format(share)}%`} · ${distance}`;
        return <li key={`${candidate.scope}:${candidate.number}`} tabIndex={0} title={label} aria-label={label}
          style={{ color: partyColor(candidate.party, candidate.party_name, colors) }}>
          <span>{candidate.party_name || candidate.party}</span><strong>{share == null ? '—' : `${percent.format(share)}%`}</strong>
        </li>;
      })}</ol>
        <div className="region-comparison-bar" role="img" aria-label={`${region.name}: proporção dos votos dos dois primeiros candidatos; marca de 50%; cinza representa os demais`}>
          {region.ranking.items.map((candidate, index) => <span key={`${candidate.scope}:${candidate.number}`}
            style={{ width: `${Math.max(0, Math.min(100, candidate.percentage || 0))}%`, background: partyColor(candidate.party, candidate.party_name, colors), [index === 0 ? 'left' : 'right']: 0 }} />)}
          <i />
        </div>
      </div> : <span className="regional-pending">{region.ranking?.status === 'not_applicable' ? 'Disputa por UF' : region.ranking?.status === 'incomplete' ? 'Ranking incompleto' : 'Aguardando votos'}</span>}
      {!!region.error_ufs.length && <p className="regional-warning">Falha na coleta: {region.error_ufs.join(', ').toUpperCase()}. Últimos dados preservados.</p>}
    </article>)}</div>
    <p className="regional-footnote">Passe sobre os percentuais para ver o candidato e a distância até 50%.</p>
  </section>;
}
