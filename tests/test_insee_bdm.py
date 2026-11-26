from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from zetruth.sources.client import SourceClient
from zetruth.sources.insee_bdm import (
    BASE_URL,
    SOURCE_ID,
    InseeResponseError,
    describe,
    fetch_history,
    history_url,
    parse_history,
)
from zetruth.sources.registry import load_registry
from zetruth.sources.store import ResponseStore

# Extrait réel de la réponse de l'API (série 001688527, chômage BIT), 3 publications.
FIXTURE = (Path(__file__).parent / "fixtures" / "insee_bdm_historique.xml").read_bytes()
SERIES = "001688527"
MOMENT = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)


def make_client(tmp_path: Path, urls: list[str]) -> SourceClient:
    def fake_insee(url: str) -> bytes:
        urls.append(url)
        return FIXTURE

    return SourceClient(
        SOURCE_ID, ResponseStore(tmp_path), load_registry(), 0, fetch=fake_insee, now=lambda: MOMENT
    )


def test_lecture_d_une_reponse_reelle() -> None:
    history = parse_history(FIXTURE, SERIES)

    assert history.title.startswith("Taux de chômage au sens du BIT")
    assert history.unit == "POURCENT"
    assert len(history.vintages) == 3
    known = history.value_as_of("2021-Q4", date(2022, 4, 20))
    assert known is not None
    assert (known.value, known.published_on) == (Decimal("7.4"), date(2022, 2, 18))


def test_fetch_history_demande_l_historique_complet(tmp_path: Path) -> None:
    urls: list[str] = []

    history, record = fetch_history(make_client(tmp_path, urls), SERIES)

    assert urls == [f"{BASE_URL}/{SERIES}?includeHistory=true"]
    assert record.url == urls[0]
    assert len(history.vintages) == 3


def test_l_url_de_l_insee_est_dans_la_liste_blanche() -> None:
    assert load_registry().for_url(history_url(SERIES)).id == SOURCE_ID


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
    history, record = fetch_history(make_client(tmp_path, []), SERIES)

    lines = describe(history, record, "2021-Q4", date(2022, 4, 20))

    assert "valeur connue au 2022-04-20 : 7.4 (publiée le 2022-02-18)" in lines
    assert "  publiée le 2023-02-14 : 7.5" in lines
    assert "consultée le : 2026-11-26" in lines


def test_description_quand_l_historique_ne_remonte_pas_assez_loin(tmp_path: Path) -> None:
    history, record = fetch_history(make_client(tmp_path, []), SERIES)

    lines = describe(history, record, "2012-Q1", date(2012, 5, 2))

    assert "aucune publication de 2012-Q1 connue au 2012-05-02" in lines[1]
