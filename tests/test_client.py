import urllib.error
import urllib.request
from datetime import UTC, datetime
from email.message import Message
from io import BytesIO
from pathlib import Path

import pytest

from zetruth.sources.client import SourceClient, SourceUnavailableError, http_fetch
from zetruth.sources.registry import UnknownSourceError, load_registry
from zetruth.sources.store import ResponseStore

URL = "https://api.insee.fr/series/BDM/V1/data/SERIES_BDM/001688527?includeHistory=true"
MOMENT = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)
MIN_INTERVAL = 2.0


class FakeServer:
    def __init__(self, content: bytes = b"donnees") -> None:
        self.content = content
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return self.content


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(
    tmp_path: Path, server: FakeServer, clock: FakeClock | None = None, source_id: str = "insee"
) -> SourceClient:
    clock = clock or FakeClock()
    return SourceClient(
        source_id,
        ResponseStore(tmp_path),
        load_registry(),
        MIN_INTERVAL,
        fetch=server,
        now=lambda: MOMENT,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )


def as_text(content: bytes) -> str:
    return content.decode()


def test_le_premier_appel_interroge_la_source_et_garde_la_reponse(tmp_path: Path) -> None:
    server = FakeServer()

    text, record = make_client(tmp_path, server).get("cle", URL, as_text)

    assert (text, server.urls) == ("donnees", [URL])
    assert (record.url, record.fetched_at) == (URL, MOMENT.isoformat())
    assert ResponseStore(tmp_path).latest("cle") == (b"donnees", record)


def test_une_reponse_deja_gardee_est_relue_sans_appel(tmp_path: Path) -> None:
    make_client(tmp_path, FakeServer()).get("cle", URL, as_text)
    server = FakeServer(b"autre")

    text, _ = make_client(tmp_path, server).get("cle", URL, as_text)

    assert (text, server.urls) == ("donnees", [])


def test_le_rafraichissement_force_un_appel(tmp_path: Path) -> None:
    make_client(tmp_path, FakeServer()).get("cle", URL, as_text)
    server = FakeServer(b"nouvelles")

    text, _ = make_client(tmp_path, server).get("cle", URL, as_text, refresh=True)

    assert (text, len(server.urls)) == ("nouvelles", 1)


def test_une_reponse_refusee_par_l_analyse_n_est_pas_gardee(tmp_path: Path) -> None:
    def refuse(content: bytes) -> str:
        raise ValueError("illisible")

    with pytest.raises(ValueError, match="illisible"):
        make_client(tmp_path, FakeServer()).get("cle", URL, refuse)

    assert ResponseStore(tmp_path).latest("cle") is None


def test_les_appels_sont_espaces(tmp_path: Path) -> None:
    clock = FakeClock()
    client = make_client(tmp_path, FakeServer(), clock)

    client.get("cle", URL, as_text, refresh=True)
    clock.now += 0.5
    client.get("cle", URL, as_text, refresh=True)

    assert clock.sleeps == [MIN_INTERVAL - 0.5]


def test_pas_d_attente_pour_une_lecture_locale(tmp_path: Path) -> None:
    clock = FakeClock()
    client = make_client(tmp_path, FakeServer(), clock)

    client.get("cle", URL, as_text)
    client.get("cle", URL, as_text)

    assert clock.sleeps == []


def test_une_url_hors_liste_blanche_n_est_jamais_appelee(tmp_path: Path) -> None:
    server = FakeServer()

    with pytest.raises(UnknownSourceError):
        make_client(tmp_path, server).get("cle", "https://www.lemonde.fr/x", as_text)
    assert server.urls == []


def test_une_url_d_une_autre_source_est_refusee(tmp_path: Path) -> None:
    server = FakeServer()
    client = make_client(tmp_path, server, source_id="eurostat")

    with pytest.raises(ValueError, match="appartient à insee, pas à eurostat"):
        client.get("cle", URL, as_text)
    assert server.urls == []


def test_une_erreur_reseau_devient_une_erreur_explicite(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(url: str, timeout: float) -> None:
        raise urllib.error.URLError("pas de réseau")

    monkeypatch.setattr(urllib.request, "urlopen", unreachable)

    with pytest.raises(SourceUnavailableError, match="injoignable"):
        http_fetch(URL)


def test_une_erreur_http_garde_l_explication_de_la_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b'{"error": [{"status": 404, "label": "ERR_NOT_FOUND"}]}'

    def not_found(url: str, timeout: float) -> None:
        raise urllib.error.HTTPError(url, 404, "Not Found", Message(), BytesIO(body))

    monkeypatch.setattr(urllib.request, "urlopen", not_found)

    with pytest.raises(SourceUnavailableError, match=r"réponse 404 .*ERR_NOT_FOUND"):
        http_fetch(URL)
