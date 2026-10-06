import logging
import time
from collections import defaultdict
from dataclasses import dataclass

from .client import JsonCollector, component
from .http import DownloadError
from .result_schedule import RESULT_LEVELS, ResultSchedule, result_levels

LOG = logging.getLogger("apuracao")


@dataclass(frozen=True)
class ResultTarget:
    url: str
    election: int
    office: int
    round: int
    kind: str
    area: str
    scope: str
    uf: str
    municipality: str = ""


class ResultCollector(JsonCollector):
    def __init__(self, db, config, fetch_json, limiter=None):
        super().__init__(db, config, fetch_json, limiter)
        self.levels = result_levels(config)
        self.schedule = ResultSchedule(db, self.dataset)

    def catalog(self):
        poll = self._load_poll_catalog()
        targets = {}
        self.municipalities_by_state = defaultdict(set)
        for election in poll["e"]:
            self._save_election(election)
            for target in self._election_result_targets(election):
                targets[target.url] = target
        if not targets:
            raise ValueError("Nenhum resultado encontrado para o filtro configurado")
        self.targets = list(targets.values())
        self.next_catalog = time.monotonic() + self.config.get("catalog_interval_seconds", 900)
        LOG.info("Resultados: %d recortes descobertos", len(self.targets))

    def _election_result_targets(self, election):
        states = self._load_election_states(election)
        for coverage in election["abr"]:
            for office in coverage.get("cp", []):
                yield from self._office_result_targets(election, coverage["cd"], int(office["cd"]), states)

    def _load_election_states(self, election):
        election_code = int(election["cd"])
        directory = self.directory("cm", cd_eleicao=election_code)
        geography = self.json(f"{directory}/mun-e{election_code:06d}-cm.json")
        self.check_phase(geography)
        selected_ufs = self.config.get("ufs")
        states = [
            state for state in geography["abr"]
            if state["cd"] != "br" and (not selected_ufs or state["cd"] in selected_ufs)
        ]
        for state in states:
            self.municipalities_by_state[state["cd"]].update(
                component(city["cd"]).zfill(5) for city in state.get("mu", [])
            )
        return states

    def _office_result_targets(self, election, coverage, office, states):
        # O filtro de UFs limita os recortes territoriais, mas mantém o consolidado presidencial nacional.
        if office == 1:
            yield self._build_result_target(
                election, office, uf="br", territory="br", kind="br", area="br", scope="br"
            )
        for state in states:
            uf = component(state["cd"])
            if coverage in ("br", uf) and _office_applies_to_state(office, uf):
                yield from self._state_result_targets(election, office, state, uf)

    def _state_result_targets(self, election, office, state, uf):
        municipal = election.get("tp") == "3" or office in (11, 13, 25)
        scope = "br" if office == 1 else uf
        if not municipal:
            yield self._build_result_target(
                election, office, uf=uf, territory=uf, kind="uf", area=uf, scope=scope)
        for city in state.get("mu", []):
            municipality = component(city["cd"]).zfill(5)
            territory = uf + municipality
            candidate_scope = territory if municipal else scope
            yield self._build_result_target(
                election, office, uf=uf, territory=territory,
                kind="mu", area=municipality, scope=candidate_scope, municipality=municipality)
            for number in city.get("z", []):
                zone = component(number).zfill(4)
                yield self._build_result_target(
                    election, office, uf=uf, territory=territory + "-z" + zone,
                    kind="zona", area=zone, scope=candidate_scope, municipality=municipality)

    def _build_result_target(self, election, office, *, uf, territory, kind, area, scope, municipality=""):
        election_code = int(election["cd"])
        directory = self.directory("u", cd_eleicao=election_code, uf=uf)
        url = f"{directory}/{territory}-c{office:04d}-e{election_code:06d}-u.json"
        return ResultTarget(
            url=url,
            election=election_code,
            office=office,
            round=int(election["t"]),
            kind=kind,
            area=area,
            scope=scope,
            uf=uf,
            municipality=municipality,
        )

    def collect(self, target):
        payload = self.json(target.url, allow_not_modified=True)
        if payload is None:
            # HTTP 304 confirma o conteúdo da URL, mas não garante que o cache pertença ao recorte.
            payload = self._cached_result_identity(target)
        self._validate_result_identity(payload, target)

    def _cached_result_identity(self, target):
        row = self.db.execute("""SELECT reported_election AS ele, reported_round AS t,
                phase AS f, kind AS tpabr, area AS cdabr, office
            FROM results
            WHERE dataset=? AND office=? AND source_url=?""",
            (self.dataset, target.office, target.url)).fetchone()
        if row is None:
            raise ValueError(f"Resposta 304 sem resultado estruturado: {target.url}")
        return {**dict(row), "carg": [{"cd": row["office"]}]}

    def _validate_result_identity(self, payload, target):
        self.check_phase(payload)
        expected_identity = (str(target.election), str(target.round), target.kind, target.area)
        reported_identity = (
            str(payload.get("ele")),
            str(payload.get("t")),
            payload.get("tpabr"),
            str(payload.get("cdabr", "")).lower(),
        )
        has_office = any(
            str(office.get("cd")) == str(target.office)
            for office in payload.get("carg", [])
        )
        if reported_identity != expected_identity or not has_office:
            raise ValueError(f"Identidade do resultado incompatível: {target.url}")

    def cycle(self):
        remaining_pause = self.remaining_pause()
        if remaining_pause:
            LOG.warning("Coleta de resultados em pausa por mais %.0f segundos", remaining_pause)
            return False
        self.limiter.blocked.clear()
        try:
            if time.monotonic() >= self.next_catalog:
                self.catalog()
            return self._collect_levels()
        except DownloadError as error:
            if error.cooldown:
                self.pause(error.cooldown)
            LOG.error("Coleta de resultados: %s", error)
            return False

    def _collect_levels(self):
        self.schedule.begin_pass()
        local_budget = self.config.get("max_local_results_per_cycle", 1000)
        for kind, level in RESULT_LEVELS:
            if not self.levels[level]:
                continue
            pending = self.schedule.pending(self.targets, kind, self.municipalities_by_state)
            is_local = kind in ("mu", "zona")
            batch = pending[:local_budget] if is_local else pending
            failures = self._collect_batch(batch)
            remaining = len(pending) - len(batch) + failures
            if batch:
                LOG.info(
                    "Resultados — %s: %d consultados, %d pendentes nesta etapa",
                    level, len(batch), remaining,
                )
            if is_local:
                local_budget -= len(batch)
            # Não avance para outro nível enquanto houver falhas ou recortes fora do orçamento.
            if remaining:
                return failures == 0
        self.schedule.finish_pass()
        LOG.info("Passagem pelos níveis de resultados habilitados concluída")
        return True

    def _collect_batch(self, targets):
        failures = 0
        for target in targets:
            if self._collect_target(target):
                # A passagem registra a tentativa válida; completed no banco encerra futuras consultas.
                self.schedule.complete(target)
            else:
                failures += 1
        return failures

    def _collect_target(self, target):
        try:
            self.collect(target)
            return True
        except DownloadError as error:
            if error.cooldown:
                raise
            LOG.warning("Resultado: %s", error)
        except (ValueError, KeyError, TypeError) as error:
            LOG.warning("Resultado %s: %s", target.url, error)
        return False


def _office_applies_to_state(office, uf):
    if uf == "zz":
        return office == 1
    if office == 7:
        return uf != "df"
    if office == 8:
        return uf == "df"
    return True
