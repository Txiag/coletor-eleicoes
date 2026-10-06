import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOG = logging.getLogger("apuracao")


class DownloadError(Exception):
    def __init__(self, message, cooldown=0):
        super().__init__(message)
        self.cooldown = cooldown


class RateLimiter:
    def __init__(self, per_second):
        self.spacing = 1 / per_second
        self.next_request = 0
        self.lock = threading.Lock()
        self.blocked = threading.Event()

    def wait(self):
        with self.lock:
            if self.blocked.is_set():
                raise DownloadError("Coleta pausada após resposta de bloqueio", 610)
            delay = self.next_request - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            if self.blocked.is_set():
                raise DownloadError("Coleta pausada após resposta de bloqueio", 610)
            self.next_request = time.monotonic() + self.spacing


def _register_source(db, endpoint):
    url, name = endpoint["url"], endpoint["name"]
    with db:
        db.execute(
            "INSERT INTO sources(url, name) VALUES (?, ?) "
            "ON CONFLICT(url) DO UPDATE SET name=excluded.name", (url, name)
        )
    return db.execute("SELECT * FROM sources WHERE url=?", (url,)).fetchone()


def _build_json_request(url, previous, conditional):
    headers = {"Accept": "application/json", "User-Agent": "apuracao-2026/0.1"}
    if conditional and previous["etag"]:
        headers["If-None-Match"] = previous["etag"]
    if conditional and previous["last_modified"]:
        headers["If-Modified-Since"] = previous["last_modified"]
    return Request(url, headers=headers)


# hash de payload para detectar mudanćas
def _hash_json_content(parsed):
    canonical = json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _save_json_response(db, previous, response, payload, digest, checked_at):
    from ..official_store import save_response

    url = previous["url"]
    with db:
        # Reprojete somente quando o conteúdo consolidado mudar.
        if digest != previous["content_hash"]:
            save_response(db, url, checked_at, digest, payload)
        db.execute(
            "UPDATE sources SET etag=?, last_modified=?, content_hash=?, "
            "checked_at=?, status=200, error=NULL WHERE url=?",
            (response.headers.get("ETag"), response.headers.get("Last-Modified"), digest, checked_at, url),
        )


def _record_source_check(db, url, checked_at, status, error=None):
    with db:
        db.execute(
            "UPDATE sources SET checked_at=?, status=?, error=? WHERE url=?",
            (checked_at, status, error, url),
        )


def fetch(db, endpoint, timeout, *, on_payload=None, conditional=True):
    url, name = endpoint["url"], endpoint["name"]
    previous = _register_source(db, endpoint)
    now = datetime.now(timezone.utc).isoformat()
    status = None
    try:
        request = _build_json_request(url, previous, conditional)
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            if status != 200:
                raise ValueError(f"Resposta HTTP inesperada: {status}")
            payload = response.read().decode("utf-8-sig")
            parsed = json.loads(payload)
            digest = _hash_json_content(parsed)
            _save_json_response(db, previous, response, payload, digest, now)
            if on_payload is not None:
                on_payload(parsed)
            LOG.info("%s: %s", name, "consolidado atualizado" if digest != previous["content_hash"] else "sem alterações")
            return 200
    except HTTPError as error:
        status = error.code
        error.close()
        if status == 304 and previous["content_hash"]:
            _record_source_check(db, url, now, 304)
            LOG.info("%s: sem alterações (304)", name)
            return 304
        message = str(error)
    except (URLError, TimeoutError, OSError, ValueError) as error:
        message = str(error)
    _record_source_check(db, url, now, status, message)
    LOG.error("%s: %s", name, message)
    return status if status and status != 200 else 0

