import re
import time

from .http import DownloadError, RateLimiter


def component(value):
    value = str(value)
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", value) or value in {".", ".."}:
        raise ValueError("Componente de URL inválido na resposta do TSE")
    return value


class JsonCollector:
    def __init__(self, db, config, fetch_json, limiter=None):
        self.db = db
        self.config = config
        self.fetch_json = fetch_json
        self.base = config["base_url"].rstrip("/")
        self.poll = int(config["poll"])
        self.dataset = f'{self.base}/{config["cycle"]}/{self.poll}'
        self.limiter = limiter if limiter is not None else RateLimiter(config.get("requests_per_second", 20))
        self.timeout = config.get("timeout_seconds", 20)
        self.next_catalog = 0
        self.directories = {}
        with db:
            # Inserir fonte
            db.execute("INSERT OR IGNORE INTO datasets VALUES(?,?,?,?,?)",
                       (self.dataset, self.base, config["cycle"], self.poll, config["phase"]))

    def pause(self, seconds):
        # Adicionar cooldown da api ao banco para ser considerada em reinicializaćões
        deadline = time.time() + seconds
        with self.db:
            self.db.execute("INSERT INTO collection_state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=MAX(value,excluded.value)",
                            (self.base + "/cooldown", deadline))

    def remaining_pause(self):
        row = self.db.execute("SELECT value FROM collection_state WHERE key=?", (self.base + "/cooldown",)).fetchone()
        return max(0, row[0] - time.time()) if row else 0

    def directory(self, kind, **values):
        root, environment = self.base.rsplit("/", 1)
        tokens = {"base": root, "ambiente": environment, "ciclo": self.config["cycle"],
                  "cd_pleito": str(self.poll), **{key: component(value) for key, value in values.items()}}
        result = self.directories[kind]
        for key, value in tokens.items():
            result = result.replace(f"<{key}>", value)
        if "<" in result or not result.startswith(self.base + "/"):
            raise ValueError(f"Diretório {kind} inválido no EA11")
        return result

    def json(self, url, *, allow_not_modified=False):
        self.limiter.wait()
        received = []
        status = self.fetch_json(self.db, {"name": url.rsplit("/", 1)[-1], "url": url}, self.timeout,
                                 on_payload=received.append, conditional=allow_not_modified)
        if status not in (200, 304):
            if status in (403, 404, 429):
                self.limiter.blocked.set()
            raise DownloadError(f"Falha HTTP {status} em {url}", 610 if status in (403, 404, 429) else 0)
        if status == 304 and allow_not_modified:
            return None
        if not received:
            raise DownloadError(f'Resposta sem conteúdo para {url}')
        return received[0]

    def check_phase(self, payload):
        expected = {"official": "o", "simulated": "s"}[self.config["phase"]]
        received = payload.get("f")
        if not isinstance(received, str) or received.lower() != expected:
            raise ValueError(f"Resposta pertence a outra fase da eleição: esperada {expected!r}, recebida {received!r}")

    def _load_poll_catalog(self):
        config = self.json(self.base + "/comum/config/ele-c.json")
        poll = next((poll for poll in config["pl"]
                     if int(poll["cd"]) == self.poll and poll["c"] == self.config["cycle"]), None)
        if poll is None:
            raise ValueError("Pleito/ciclo não encontrado no EA11")
        self.directories = {item["tp"]: item["dir"] for item in config["arq"]}
        return poll

    def _save_election(self, election):
        with self.db:
            self.db.execute(
                "INSERT INTO elections(dataset,code,name,round) VALUES(?,?,?,?) "
                "ON CONFLICT(dataset,code) DO UPDATE SET name=excluded.name,round=excluded.round",
                (self.dataset, int(election["cd"]), election["nm"], int(election["t"])),
            )
