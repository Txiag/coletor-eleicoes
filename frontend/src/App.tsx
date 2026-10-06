import { useEffect, useMemo, useState } from "react";
import type { Candidate, Dashboard, Metadata, Party, Territory } from "./types";
import { query, useResource } from "./useResource";
import { applyScope } from "./scope";
import { useRouting } from "./routing";

import { partyColor } from "./partyColors";
import { categoryLabel } from "./labels";

import { number, timestamp } from "./format";
import ElectionMap from "./components/ElectionMap";
import RegionalProgress from "./components/RegionalProgress";
import CandidateTop from "./components/CandidateTop";
import TerritoryPopover from "./components/TerritoryPopover";
const levels = ["uf", "municipality", "zone"] as const;
const names = {
  uf: "UF",
  municipality: "Município",
  zone: "Zona",
};
const states = {
  available: "Disponível",
  pending: "Aguardando dados",
  tie: "Empate",
  zero: "Sem votos partidários",
  unavailable: "Indisponível",
};
function ColorEditor({
  parties,
  colors,
  setColor,
  reset,
}: {
  parties: Party[];
  colors: Record<string, string>;
  setColor: (party: string, color: string) => void;
  reset: () => void;
}) {
  return (
    <details className="color-editor">
      <summary>Personalizar cores dos partidos</summary>
      <p className="muted">
        Preferências locais por eleição. As cores não alteram a votação.
      </p>
      <div className="color-grid">
        {parties.map((party) => (
          <label key={party.number}>
            <input
              type="color"
              aria-label={`Cor de ${party.name}`}
              value={colors[party.number] || "#205fb3"}
              onChange={(event) => setColor(party.number, event.target.value)}
            />
            <span>
              {party.name} <small>{party.number}</small>
            </span>
            <input
              aria-label={`Hexadecimal de ${party.name}`}
              key={colors[party.number]}
              defaultValue={colors[party.number] || "#205fb3"}
              pattern="#[0-9a-fA-F]{6}"
              maxLength={7}
              onBlur={(event) => {
                if (/^#[0-9a-f]{6}$/i.test(event.target.value))
                  setColor(party.number, event.target.value);
                else event.target.value = colors[party.number] || "#205fb3";
              }}
            />
          </label>
        ))}
      </div>
      <button onClick={reset}>Restaurar paleta</button>
    </details>
  );
}
export default function App() {
  const [retainedView, setRetainedView] = useState<{ context: string; data: Dashboard; uf: string; municipality: string } | null>(null);
  const meta = useResource<Metadata>("/api/metadata");
  const { filters, setFilters, source, navigation } = useRouting();
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [localOpen, setLocalOpen] = useState(Boolean(filters.uf));
  useEffect(() => setLocalOpen(Boolean(filters.uf)), [filters.uf, filters.municipality, navigation]);

  const [paused, setPaused] = useState(false),
    [seconds, setSeconds] = useState(30),
    [staleSeconds, setStaleSeconds] = useState(300),
    [now, setNow] = useState(Date.now());
  const [mapRefresh, setMapRefresh] = useState(0);
  const [view, setView] = useState<"map" | "table">("map");
  useEffect(() => {
    if (!filters.uf || view !== 'map') return;
    const clearOutsideMap = (event: MouseEvent) => {
      if (!(event.target instanceof Element) || event.target.closest('.election-map, .territory-popover, .breadcrumbs, .map-election-controls')) return;
      setLocalOpen(false);
      setCandidate(null);
      setLabels({});
      setFilters(current => ({ ...current, uf: '', municipality: '', zone: '' }));
    };
    document.addEventListener('click', clearOutsideMap);
    return () => document.removeEventListener('click', clearOutsideMap);
  }, [filters.uf, view, setFilters]);

  const [preferences, setPreferences] = useState<
    Record<string, Record<string, string>>
  >(() => {
    try {
      return JSON.parse(localStorage.getItem("apuracao-party-colors") || "{}");
    } catch {
      return {};
    }
  });
  const dataset = meta.data?.datasets[0];
  const election = dataset?.elections.find(item => String(item.code) === filters.election);
  const office = election?.offices.find(item => String(item.code) === filters.office);
  const rounds = [...new Set(dataset?.elections.map(item => item.round) || [])].sort((a, b) => a - b);
  const round = election?.round ?? rounds[0];
  const offices = [...new Map((dataset?.elections || [])
    .filter(item => item.round === round)
    .flatMap(item => item.offices)
    .map(item => [String(item.code), item])).values()];
  useEffect(() => {
    if (!meta.data) return;
    const ds = meta.data.datasets[0];
    const el = ds?.elections.find(item => String(item.code) === filters.election)
      || ds?.elections.find(item => item.offices.some(candidate => String(candidate.code) === filters.office))
      || ds?.elections[0];
    const selectedOffice = el?.offices.find(item => String(item.code) === filters.office) || el?.offices[0];
    if (ds && el && selectedOffice) {
      const contextChanged = filters.dataset !== String(ds.id) || filters.election !== String(el.code) || filters.office !== String(selectedOffice.code);
      const next = contextChanged ? applyScope({ ...filters, dataset: String(ds.id), election: String(el.code), office: String(selectedOffice.code) }, selectedOffice.scopes) : filters;
      if (JSON.stringify(next) !== JSON.stringify(filters)) setFilters(next, true);
    }
  }, [meta.data, filters, setFilters]);
  useEffect(() => {
    if (meta.data) {
      setSeconds(meta.data.refresh_seconds || 30);
      setStaleSeconds(meta.data.stale_seconds || 300);
    }
  }, [meta.data]);
  useEffect(() => {
    setLabels({});
    setCandidate(null);
  }, [navigation]);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 10000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem(
        "apuracao-party-colors",
        JSON.stringify(preferences),
      );
    } catch {
      /* Preferências continuam disponíveis nesta sessão quando o navegador bloqueia armazenamento. */
    }
  }, [preferences]);
  const url =
    filters.dataset && filters.election && filters.office
      ? query("/api/dashboard", {
          ...filters,
          source,
          candidate: candidate?.number,
          candidate_scope: candidate?.scope,
          page: 1,
          candidate_page: 1,
          page_size: 5,
        })
      : null;
  const result = useResource<Dashboard>(url, seconds, paused);
  const nationalUrl = url ? query("/api/dashboard", {
    dataset: filters.dataset, election: filters.election, office: filters.office,
    source, page: 1, candidate_page: 1, page_size: 5,
  }) : null;
  const nationalResult = useResource<Dashboard>(filters.uf ? nationalUrl : null, seconds, paused);
  const national = filters.uf ? nationalResult.data : result.data;
  const displayContext = `${filters.dataset}:${filters.election}:${filters.office}:${source}`;
  const data = result.data || retainedView?.data;
  const switchingView = !result.data && !!retainedView;
  useEffect(() => {
    if (result.data) setRetainedView({ context: displayContext, data: result.data, uf: filters.uf, municipality: filters.municipality });
  }, [result.data, displayContext, filters.uf, filters.municipality]);
  const partyList = useMemo(() => [...new Map([...(meta.data?.parties || []), ...(data?.parties || [])].map(party => [party.number, party])).values()], [meta.data?.parties, data?.parties]);
  const colorKey = `${filters.dataset}:${filters.election}`;
  const colors = useMemo(() => ({ ...preferences[colorKey], ...Object.fromEntries(partyList.map(party => [party.number, partyColor(party.number, party.name, preferences[colorKey] || {})])) }), [partyList, preferences, colorKey]);
  const sourceEpoch = [data?.source.updated_at, data?.source.collected_at]
    .map(value => value ? new Date(value).getTime() : NaN)
    .find(Number.isFinite) ?? NaN;
  const stale =
    Number.isFinite(sourceEpoch) && now - sourceEpoch > staleSeconds * 1000;
  const responseStale =
    !!result.receivedAt && now - result.receivedAt > staleSeconds * 1000;
  function territory(level: Territory["level"], value: string, label = value) {
    const index = levels.indexOf(level);
    const next = { ...filters, [level]: value };
    levels.slice(index + 1).forEach((key) => (next[key] = ""));
    const scoped = level === "uf" && !value ? next : applyScope(next, office?.scopes || []);
    if (
      candidate &&
      candidate.scope !== "br" &&
      candidate.scope !== scoped.uf &&
      candidate.scope !== `${scoped.uf}${scoped.municipality}`
    )
      setCandidate(null);
    setFilters(scoped);
    setLabels((current) => ({ ...current, [level]: label }));
  }
  function changeContext(key: "round" | "office", value: string) {
    const nextRound = key === "round" ? Number(value) : round;
    const nextOffice = key === "office" ? value : filters.office;
    const elections = dataset?.elections.filter(item => item.round === nextRound) || [];
    const nextElection = elections.find(item => item.offices.some(candidate => String(candidate.code) === nextOffice)) || elections[0];
    const selectedOffice = nextElection?.offices.find(item => String(item.code) === nextOffice) || nextElection?.offices[0];
    if (!dataset || !nextElection || !selectedOffice) return;
    setCandidate(null);
    setFilters(current => applyScope({
      ...current,
      dataset: String(dataset.id),
      election: String(nextElection.code),
      office: String(selectedOffice.code),
    }, selectedOffice.scopes));
  }
  const context = {
    dataset: filters.dataset,
    election: filters.election,
    office: filters.office,
  };
  const municipalityName = useResource<{ items: { value: string; label: string }[] }>(
    filters.municipality && filters.office ? query("/api/options", {
      ...context, uf: filters.uf, level: "municipality", q: filters.municipality, page_size: 30,
    }) : null,
  );
  const location = filters.zone
      ? `Zona ${filters.zone}`
      : filters.municipality
        ? labels.municipality || municipalityName.data?.items.find(item => item.value === filters.municipality)?.label || filters.municipality
        : filters.uf
          ? labels.uf && labels.uf !== filters.uf ? labels.uf : filters.uf.toUpperCase()
          : "Brasil";
  return (
    <>
      <a className="skip-link" href="#resultados">
        Ir para resultados
      </a>
      <main className="map-page">
        <div className="election-navigation map-election-controls">
        <nav className="office-tabs" aria-label="Cargos da eleição">
          {offices.map(item => (
            <button key={item.code} aria-pressed={filters.office === String(item.code)}
              onClick={() => changeContext("office", String(item.code))}>{item.name}</button>
          ))}
        </nav>
        <label className="round-select">
          <span className="sr-only">Turno</span>
          <select value={round ?? ""} disabled={!rounds.length}
            onChange={event => changeContext("round", event.target.value)}>
            {!rounds.length && <option value="">Turno</option>}
            {rounds.map(item => <option key={item} value={item}>{item}º turno</option>)}
          </select>
        </label>
        </div>
        <section className="hero" id="visao-geral">
          <h1>{office?.name || "Apuração"} <span>· {location}</span></h1>
          <aside className="live-panel">
            <span className={`badge ${paused ? "neutral" : ""}`}>
              <i />
              {result.error
                ? "Falha na atualização"
                : result.loading
                  ? "Atualizando"
                  : stale || responseStale
                    ? "Dados desatualizados"
                    : data
                      ? "Consulta atualizada"
                      : "Aguardando dados"}
            </span>
            <small className="refresh-mode">
              {paused
                ? "Atualização automática pausada"
                : `Atualização automática a cada ${seconds}s`}
            </small>
            <p>
              Consulta do navegador
              <strong>{timestamp(data?.queried_at)}</strong>
            </p>
            <div className="actions">
              <button
                className="primary"
                disabled={result.loading || !url}
                onClick={() => {
                  void result.refresh();
                  void nationalResult.refresh();
                  setMapRefresh(value => value + 1);
                }}
              >
                ↻ Atualizar agora
              </button>
              <button onClick={() => setPaused((value) => !value)}>
                {paused ? "Retomar" : "Pausar"}
              </button>
            </div>
            <details>
              <summary>Configurar atualização</summary>
              <label>
                Intervalo (segundos)
                <input
                  type="number"
                  min="5"
                  max="3600"
                  value={seconds}
                  onChange={(event) =>
                    setSeconds(
                      Math.max(
                        5,
                        Math.min(3600, Number(event.target.value) || 30),
                      ),
                    )
                  }
                />
              </label>
              <label>
                Considerar antigo após (segundos)
                <input
                  type="number"
                  min="30"
                  value={staleSeconds}
                  onChange={(event) =>
                    setStaleSeconds(
                      Math.max(30, Number(event.target.value) || 300),
                    )
                  }
                />
              </label>
            </details>
          </aside>
        </section>
        {meta.error && (
          <div className="notice error" role="alert">
            {meta.error}{" "}
            <button onClick={meta.refresh}>Tentar novamente</button>
          </div>
        )}
        {meta.loading && !meta.data && (
          <p role="status">Carregando eleições disponíveis…</p>
        )}
        <div className="source-row"><span>Resultados oficiais do TSE · EA20</span></div>
        <nav className="breadcrumbs" aria-label="Navegação territorial">
          <button onClick={() => territory("uf", "")}>Brasil</button>
          {levels
            .filter((level) => filters[level])
            .map((level) => (
              <span key={level}>
                {" "}
                /{" "}
                <button
                  onClick={() =>
                    territory(level, filters[level], labels[level])
                  }
                >
                  {level === "uf"
                    ? filters.uf.toUpperCase()
                    : level === "municipality"
                      ? labels.municipality || municipalityName.data?.items.find(item => item.value === filters.municipality)?.label || filters.municipality
                      : `${names[level]} ${filters[level]}`}
                </button>
              </span>
            ))}
        </nav>

        {result.loading && !data && (
          <div className="loading-state" role="status">
            <span className="spinner" /> Consultando{" "}
            {office?.name || "resultados"} em {location}…
          </div>
        )}
        {data && (
          <>
            <div className="map-workspace" aria-busy={switchingView} data-pending={switchingView}>
            {switchingView && <p className="map-loading-indicator" role="status">{result.error ? "Consulta indisponível" : "Carregando nova consulta…"} · Mapa anterior preservado</p>}
            <div className="left-rail">
              <section className="panel results-panel" id="resultados" aria-label="Votação nacional por candidato">
                <div className="panel-heading"><div>
                  <p className="eyebrow">Votação por candidato · Brasil</p>
                  <h2>{office?.name || "Resultados"}</h2>
                </div></div>
                <CandidateTop data={national} colors={colors} error={filters.uf ? nationalResult.error : result.error} />
              </section>
              {data.regions.length > 0 && <aside className="region-rail" aria-label="Resultados por região">
                <RegionalProgress colors={colors} regions={data.regions} office={office?.name || "Cargo selecionado"} />
              </aside>}
            </div>
            <aside className="context-rail" aria-label="Andamento da apuração">
            <section className="counted-ballots" aria-label="Urnas apuradas">
              <p className="eyebrow">{location} · Apuração oficial</p>
              <h2>{number(data.source.totalized_sections)}</h2>
              <p>seções totalizadas de {number(data.source.total_sections)}</p>
              <strong>{data.source.official_progress == null ? "—" : `${number(data.source.official_progress)}%`} apurado</strong>
              <small>Contagem de seções informada pelo TSE (EA20).</small>
            </section>

            <details className="provenance"><summary>Origem dos dados</summary>
              <div>
                <h3>Origem dos resultados</h3>
                <p>
                  {data.source.label}
                  {data.source.url && (
                    <>
                      {" "}
                      ·{" "}
                      <a
                        href={data.source.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Consultar arquivo ↗
                      </a>
                    </>
                  )}
                </p>
                <p>
                  Votos em todas as categorias:{" "}
                  <strong>{number(data.summary.votes)}</strong>
                </p>
                <div className="category-tags">
                  {data.summary.categories.map((category) => (
                    <span key={category.type}>
                      {categoryLabel(category.type)}:{" "}
                      <strong>{number(category.votes)}</strong>
                    </span>
                  ))}
                </div>
              </div>
              <dl>
                <div>
                  <dt>Atualização informada pela fonte</dt>
                  <dd>{timestamp(data.source.updated_at)}</dd>
                </div>
                <div>
                  <dt>Importação dos dados</dt>
                  <dd>{timestamp(data.source.collected_at)}</dd>
                </div>
                <div>
                  <dt>Última consulta do coletor</dt>
                  <dd>{timestamp(data.source.checked_at)}</dd>
                </div>
              </dl>
            </details>
                <ColorEditor
                  parties={partyList}
                  colors={colors}
                  setColor={(party, color) =>
                    setPreferences((current) => ({
                      ...current,
                      [colorKey]: { ...current[colorKey], [party]: color },
                    }))
                  }
                  reset={() =>
                    setPreferences((current) => ({
                      ...current,
                      [colorKey]: {},
                    }))
                  }
                />
            </aside>
            <div className="main-grid">
              <section className="panel territory-panel" id="territorios">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Explore o território</p>
                    <h2>{location}</h2>
                  </div>
                  <div className="segmented compact">
                    <button
                      aria-pressed={view === "map"}
                      className={view === "map" ? "active" : ""}
                      onClick={() => setView("map")}
                    >
                      Mapa
                    </button>
                    <button
                      aria-pressed={view === "table"}
                      className={view === "table" ? "active" : ""}
                      onClick={() => setView("table")}
                    >
                      Tabela
                    </button>
                  </div>
                </div>
                <p className="muted">
                  Liderança partidária no resultado oficial{" "}
                  · {office?.name}
                </p>
                {candidate && (
                  <div className="candidate-selection">
                    <span>
                      Explorando <strong>{candidate.name}</strong> ·{" "}
                      {candidate.number}
                    </span>
                    <button
                      onClick={() => setCandidate(null)}
                      aria-label="Limpar candidato"
                    >
                      ✕
                    </button>
                  </div>
                )}
                {view === "map" && (
                  <ElectionMap
                    sourceLabel="Resultados oficiais do TSE — EA20"
                    uf={filters.uf}
                    municipality={filters.municipality}
                    resultUrl={query('/api/map', { dataset: filters.dataset, election: filters.election, office: filters.office, source })}
                    seconds={seconds}
                    paused={paused}
                    refresh={mapRefresh}
                    colors={colors}
                    onSelect={(level, id, state, name) => {
                      setLocalOpen(Boolean(id));
                      if (level === 'municipality' && state) {
                        setFilters(current => ({ ...current, uf: state, municipality: id, zone: '' }));
                        setLabels({ uf: state.toUpperCase(), municipality: name || id });
                        setCandidate(null);
                                          } else territory(level, id, name || id);
                    }}
                  />
                )}
                {localOpen && filters.uf && view === "map" && <TerritoryPopover
                  title={location} data={result.data} colors={colors} error={result.error}
                  onClose={() => setLocalOpen(false)} />}
                {(view === "table" || filters.uf === "zz") && (
                  <div className="table-scroll">
                    <table>
                      <caption className="sr-only">
                        Votação por território
                      </caption>
                      <thead>
                        <tr>
                          <th>Território</th>
                          <th>
                            {candidate ? "Votos do candidato" : "Partido líder"}
                          </th>
                          <th>Margem</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.territories.items.map((item) => (
                          <tr key={item.id}>
                            <td>
                              <button
                                className="text-button"
                                onClick={() =>
                                  territory(item.level, item.id, item.name)
                                }
                              >
                                {item.name}
                              </button>
                              <small>{states[item.state]}</small>
                            </td>
                            <td>
                              {candidate
                                ? number(item.candidate_votes)
                                : item.leader?.name || "—"}
                            </td>
                            <td>
                              {item.margin == null
                                ? "—"
                                : `${number(item.margin)} p.p.`}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!data.territories.items.length && (
                      <p className="empty-state">
                        Nenhum território disponível neste recorte.
                      </p>
                    )}
                  </div>
                )}

              </section>

            </div>
            </div>

          </>
        )}

      </main>

    </>
  );
}
