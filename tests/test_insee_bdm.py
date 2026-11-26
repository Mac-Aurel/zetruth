import urllib.error
import urllib.request
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from zetruth.sources import insee_bdm
from zetruth.sources.insee_bdm import (
    MIN_SECONDS_BETWEEN_CALLS,
    InseeBdmClient,
    InseeResponseError,
    InseeUnavailableError,
    describe,
    history_url,
    parse_history,
)
from zetruth.sources.registry import UnknownSourceError, load_registry, parse_registry
from zetruth.sources.store import ResponseStore

# Extrait réel de la réponse de l'API (série 001688527, chômage BIT), 3 publications.
FIXTURE = (Path(__file__).parent / "fixtures" / "insee_bdm_historique.xml").read_bytes()
SERIES = "001688527"
MOMENT = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)


class FakeInsee:
    def __init__(self, content: bytes = FIXTURE) -> None:
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
    tmp_path: Path, fetch: insee_bdm.Fetcher, clock: FakeClock | None = None
) -> InseeBdmClient:
    clock = clock or FakeClock()
    return InseeBdmClient(
        ResponseStore(tmp_path),
        load_registry(),
        fetch=fetch,
        now=lambda: MOMENT,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )


def test_lecture_d_une_reponse_reelle() -> None:
    history = parse_history(FIXTURE, SERIES)

    assert history.title.startswith("Taux de chômage au sens du BIT")
    assert history.unit == "POURCENT"
    assert len(history.vintages) == 3
    known = history.value_as_of("2021-Q4", date(2022, 4, 20))
    assert known is not None
    assert (known.value, known.published_on) == (Decimal("7.4"), date(2022, 2, 18))


def test_le_premier_appel_interroge_l_insee_et_garde_la_reponse(tmp_path: Path) -> None:
    insee = FakeInsee()

    history, record = make_client(tmp_path, insee).history(SERIES)

    assert insee.urls == [f"{insee_bdm.BASE_URL}/{SERIES}?includeHistory=true"]
    assert len(history.vintages) == 3
    assert record.url == insee.urls[0]
    assert record.fetched_at == MOMENT.isoformat()
    assert ResponseStore(tmp_path).latest(SERIES) == (FIXTURE, record)


def test_une_serie_deja_telechargee_est_relue_sans_appel(tmp_path: Path) -> None:
    make_client(tmp_path, FakeInsee()).history(SERIES)
    insee = FakeInsee()

    _, record = make_client(tmp_path, insee).history(SERIES)

    assert insee.urls == []
    assert record.fetched_at == MOMENT.isoformat()


def test_le_rafraichissement_force_un_appel(tmp_path: Path) -> None:
    make_client(tmp_path, FakeInsee()).history(SERIES)
    insee = FakeInsee()

    make_client(tmp_path, insee).history(SERIES, refresh=True)

    assert len(insee.urls) == 1


def test_une_reponse_illisible_n_est_pas_gardee(tmp_path: Path) -> None:
    with pytest.raises(InseeResponseError):
        make_client(tmp_path, FakeInsee(b"<pas du xml")).history(SERIES)

    assert ResponseStore(tmp_path).latest(SERIES) is None


def test_les_appels_sont_espaces(tmp_path: Path) -> None:
    clock = FakeClock()
    client = make_client(tmp_path, FakeInsee(), clock)

    client.history(SERIES, refresh=True)
    clock.now += 0.5
    client.history(SERIES, refresh=True)

    assert clock.sleeps == [MIN_SECONDS_BETWEEN_CALLS - 0.5]


def test_pas_d_attente_pour_une_lecture_locale(tmp_path: Path) -> None:
    clock = FakeClock()
    client = make_client(tmp_path, FakeInsee(), clock)

    client.history(SERIES)
    client.history(SERIES)

    assert clock.sleeps == []


def test_l_url_doit_appartenir_a_l_insee_dans_la_liste_blanche(tmp_path: Path) -> None:
    sans_insee = parse_registry(
        {
            "sources": {
                "eurostat": {
                    "nom": "Eurostat",
                    "urls": ["https://ec.europa.eu/eurostat/"],
                    "domaines": ["international"],
                    "statut": "a_verifier",
                }
            }
        }
    )
    insee = FakeInsee()
    client = InseeBdmClient(ResponseStore(tmp_path), sans_insee, fetch=insee)

    with pytest.raises(UnknownSourceError):
        client.history(SERIES)
    assert insee.urls == []


def test_une_erreur_reseau_devient_une_erreur_explicite(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(url: str, timeout: float) -> None:
        raise urllib.error.URLError("pas de réseau")

    monkeypatch.setattr(urllib.request, "urlopen", unreachable)

    with pytest.raises(InseeUnavailableError, match="injoignable"):
        insee_bdm.http_fetch(history_url(SERIES))


@pytest.mark.parametrize("series_id", ["", "abc", "001688527&x=1", "../x"])
def test_un_identifiant_invalide_est_refuse(series_id: str) -> None:
    with pytest.raises(ValueError, match="invalide"):
        history_url(series_id)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"<pas du xml", "illisible"),
        (b"<root></root>", "aucune série"),
        (b'<root><Series IDBANK="999" LAST_UPDATE="2022-01-01"/></root>', "série inattendue"),
        (
            b'<root><Series IDBANK="001" LAST_UPDATE="2022-01-01">'
            b'<Obs TIME_PERIOD="2021" OBS_VALUE="n/a"/></Series></root>',
            "valeur illisible",
        ),
    ],
)
def test_une_reponse_anormale_est_refusee(content: bytes, message: str) -> None:
    with pytest.raises(InseeResponseError, match=message):
        parse_history(content, "001")


def test_une_observation_sans_valeur_est_ignoree() -> None:
    content = (
        b'<root><Series IDBANK="001" LAST_UPDATE="2022-01-01">'
        b'<Obs TIME_PERIOD="2021-Q4"/><Obs TIME_PERIOD="2021-Q3" OBS_VALUE="8.0"/></Series></root>'
    )

    assert parse_history(content, "001").vintages[0].values == {"2021-Q3": Decimal("8.0")}


def test_description_pour_l_annotation(tmp_path: Path) -> None:
    history, record = make_client(tmp_path, FakeInsee()).history(SERIES)

    lines = describe(history, record, "2021-Q4", date(2022, 4, 20))

    assert "valeur connue au 2022-04-20 : 7.4 (publiée le 2022-02-18)" in lines
    assert "  publiée le 2023-02-14 : 7.5" in lines
    assert "consultée le : 2026-11-26" in lines


def test_description_quand_l_historique_ne_remonte_pas_assez_loin(tmp_path: Path) -> None:
    history, record = make_client(tmp_path, FakeInsee()).history(SERIES)

    lines = describe(history, record, "2012-Q1", date(2012, 5, 2))

    assert "aucune publication de 2012-Q1 connue au 2012-05-02" in lines[1]
