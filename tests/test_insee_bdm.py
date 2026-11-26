from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from zetruth.sources.insee_bdm import (
    InseeResponseError,
    describe,
    fetch_history,
    history_url,
    parse_history,
)

# Extrait réel de la réponse de l'API (série 001688527, chômage BIT), 3 publications.
FIXTURE = (Path(__file__).parent / "fixtures" / "insee_bdm_historique.xml").read_bytes()


def test_lecture_d_une_reponse_reelle() -> None:
    history = parse_history(FIXTURE, "001688527")

    assert history.title.startswith("Taux de chômage au sens du BIT")
    assert history.unit == "POURCENT"
    assert len(history.vintages) == 3
    known = history.value_as_of("2021-Q4", date(2022, 4, 20))
    assert known is not None
    assert (known.value, known.published_on) == (Decimal("7.4"), date(2022, 2, 18))


def test_fetch_history_demande_l_historique() -> None:
    urls: list[str] = []

    def fake_fetch(url: str) -> bytes:
        urls.append(url)
        return FIXTURE

    fetch_history("001688527", fetch=fake_fetch)

    assert urls == [
        "https://api.insee.fr/series/BDM/V1/data/SERIES_BDM/001688527?includeHistory=true"
    ]


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
    series_id = "001"
    with pytest.raises(InseeResponseError, match=message):
        parse_history(content, series_id)


def test_une_observation_sans_valeur_est_ignoree() -> None:
    content = (
        b'<root><Series IDBANK="001" LAST_UPDATE="2022-01-01">'
        b'<Obs TIME_PERIOD="2021-Q4"/><Obs TIME_PERIOD="2021-Q3" OBS_VALUE="8.0"/></Series></root>'
    )

    assert parse_history(content, "001").vintages[0].values == {"2021-Q3": Decimal("8.0")}


def test_description_pour_l_annotation() -> None:
    history = parse_history(FIXTURE, "001688527")

    lines = describe(history, "2021-Q4", date(2022, 4, 20))

    assert "valeur connue au 2022-04-20 : 7.4 (publiée le 2022-02-18)" in lines
    assert "  publiée le 2023-02-14 : 7.5" in lines


def test_description_quand_l_historique_ne_remonte_pas_assez_loin() -> None:
    history = parse_history(FIXTURE, "001688527")

    lines = describe(history, "2012-Q1", date(2012, 5, 2))

    assert "aucune publication de 2012-Q1 connue au 2012-05-02" in lines[1]
