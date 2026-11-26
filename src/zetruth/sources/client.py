"""Accès HTTP commun aux connecteurs de sources officielles.

Un SourceClient garantit, pour une source donnée :
- qu'on n'appelle que des URL de cette source dans la liste blanche ;
- que les appels sont espacés ;
- que chaque réponse est gardée et journalisée (voir store.py), et relue
  en local tant qu'on ne demande pas de rafraîchissement.
"""

import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeVar

from zetruth.sources.registry import Registry
from zetruth.sources.store import FetchRecord, ResponseStore

TIMEOUT_SECONDS = 60

Fetcher = Callable[[str], bytes]
T = TypeVar("T")


class SourceUnavailableError(RuntimeError):
    pass


def http_fetch(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            content: bytes = response.read()
            return content
    except urllib.error.HTTPError as e:
        # Le corps de la réponse explique souvent l'erreur (série inconnue, requête trop lourde...).
        detail = e.read(500).decode("utf-8", errors="replace").strip()
        raise SourceUnavailableError(f"réponse {e.code} pour {url} : {detail}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise SourceUnavailableError(f"source injoignable pour {url} : {e}") from e


class SourceClient:
    def __init__(
        self,
        source_id: str,
        store: ResponseStore,
        registry: Registry,
        min_seconds_between_calls: float,
        fetch: Fetcher = http_fetch,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.source_id = source_id
        self._store = store
        self._registry = registry
        self._min_interval = min_seconds_between_calls
        self._fetch = fetch
        self._now = now
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_call: float | None = None
        # Réponses utilisées depuis le dernier drain_used(), pour le journal d'audit.
        self._used: list[FetchRecord] = []

    def get(
        self, key: str, url: str, parse: Callable[[bytes], T], refresh: bool = False
    ) -> tuple[T, FetchRecord]:
        """Réponse analysée par `parse`, et l'appel dont elle provient.

        Une réponse que `parse` refuse n'est pas gardée.
        """
        cached = None if refresh else self._store.latest(key)
        if cached is not None:
            content, record = cached
            parsed = parse(content)
        else:
            content = self._call(url)
            parsed = parse(content)
            record = self._store.save(key, url, content, self._now())
        self._used.append(record)
        return parsed, record

    def drain_used(self) -> list[FetchRecord]:
        """Les réponses utilisées depuis le dernier appel, et remise à zéro."""
        used, self._used = self._used, []
        return used

    def _call(self, url: str) -> bytes:
        source = self._registry.for_url(url)  # lève si l'URL sort de la liste blanche
        if source.id != self.source_id:
            raise ValueError(f"{url} appartient à {source.id}, pas à {self.source_id}")
        if self._last_call is not None:
            wait = self._min_interval - (self._monotonic() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        try:
            return self._fetch(url)
        finally:
            self._last_call = self._monotonic()
