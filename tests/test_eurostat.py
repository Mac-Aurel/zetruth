import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from zetruth.sources.client import SourceClient
from zetruth.sources.eurostat import (
    BASE_URL,
    SOURCE_ID,
    EurostatResponseError,
    cache_key,
    describe,
    fetch_series,
    parse_series,
    series_url,
)
from zetruth.sources.registry import load_registry
from zetruth.sources.store import ResponseStore

# Réponse réelle : chômage mensuel France, octobre 2021 à mars 2022.
FIXTURE = (Path(__file__).parent / "fixtures" / "eurostat_une_rt_m_fr.json").read_bytes()
FILTERS = {"geo": "FR", "age": "TOTAL", "sex": "T", "unit": "PC_ACT", "s_adj": "SA"}
MOMENT = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)


def jsonstat(**overrides: Any) -> bytes:
    data: dict[str, Any] = {
        "label": "Dette",
        "updated": "2022-04-22T11:00:00+0200",
        "id": ["geo", "time"],
        "size": [1, 2],
        "dimension": {
            "geo": {"category": {"index": {"FR": 0}, "label": {"FR": "France"}}},
            "time": {"category": {"index": {"2020": 0, "2021": 1}}},
        },
        "value": {"0": 115.0, "1": 112.9},
    }
    data.update(overrides)
    return json.dumps(data).encode()


def test_lecture_d_une_reponse_reelle() -> None:
    series = parse_series(FIXTURE, "une_rt_m")

    assert series.dataset_label == "Chômage par sexe et âge - données mensuelles"
    assert series.dimensions["geo"] == ("FR", "France")
    assert series.dimensions["unit"] == ("PC_ACT", "Pourcentage de la population active")
    assert series.values["2022-01"] == Decimal("7.3")
    assert len(series.values) == 6


def test_les_drapeaux_sont_rattaches_a_leur_periode() -> None:
    series = parse_series(jsonstat(status={"1": "p"}), "gov")

    assert series.flags == {"2021": "p"}


def test_les_valeurs_sont_exactes() -> None:
    series = parse_series(jsonstat(value={"0": 0.1, "1": 112.9}), "gov")

    assert series.values == {"2020": Decimal("0.1"), "2021": Decimal("112.9")}


def test_une_periode_sans_valeur_est_absente() -> None:
    assert parse_series(jsonstat(value={"1": 112.9}), "gov").values == {"2021": Decimal("112.9")}


def test_valeur_connue_seulement_si_la_mise_a_jour_precede_le_debat() -> None:
    history = parse_series(jsonstat(), "gov").history()

    assert history.value_as_of("2021", date(2022, 4, 20)) is None
    known = history.value_as_of("2021", date(2022, 4, 25))
    assert known is not None
    assert known.value == Decimal("112.9")


def test_plusieurs_series_dans_la_reponse_sont_refusees() -> None:
    content = jsonstat(
        id=["geo", "time"],
        size=[2, 2],
        dimension={
            "geo": {"category": {"index": {"FR": 0, "DE": 1}}},
            "time": {"category": {"index": {"2020": 0, "2021": 1}}},
        },
    )

    with pytest.raises(EurostatResponseError, match="geo a 2 valeurs"):
        parse_series(content, "gov")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"pas du json", "illisible"),
        (b"[]", "un objet JSON était attendu"),
        (b'{"error": [{"status": 404, "label": "ERR_NOT_FOUND"}]}', "ERR_NOT_FOUND"),
        (b'{"label": "x"}', "incomplète"),
    ],
)
def test_une_reponse_anormale_est_refusee(content: bytes, message: str) -> None:
    with pytest.raises(EurostatResponseError, match=message):
        parse_series(content, "gov")


def test_l_url_est_stable_quel_que_soit_l_ordre_des_filtres() -> None:
    reversed_filters = dict(reversed(list(FILTERS.items())))

    assert series_url("une_rt_m", FILTERS) == series_url("une_rt_m", reversed_filters)
    assert series_url("une_rt_m", FILTERS).startswith(f"{BASE_URL}/une_rt_m?format=JSON&lang=FR")


@pytest.mark.parametrize(
    ("dataset", "filters"),
    [("une rt m", {}), ("une_rt_m", {"geo": "FR&x=1"}), ("../x", {}), ("une_rt_m", {"g o": "FR"})],
)
def test_un_code_invalide_est_refuse(dataset: str, filters: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="code Eurostat invalide"):
        series_url(dataset, filters)


def test_l_url_d_eurostat_est_dans_la_liste_blanche() -> None:
    assert load_registry().for_url(series_url("une_rt_m", FILTERS)).id == SOURCE_ID


def test_fetch_series_garde_la_reponse_sous_une_cle_propre_a_la_requete(tmp_path: Path) -> None:
    urls: list[str] = []

    def fake_eurostat(url: str) -> bytes:
        urls.append(url)
        return FIXTURE

    client = SourceClient(
        SOURCE_ID, ResponseStore(tmp_path), load_registry(), 0, fetch=fake_eurostat
    )
    series, record = fetch_series(client, "une_rt_m", FILTERS)
    assert record.url == urls[0]

    assert urls == [series_url("une_rt_m", FILTERS)]
    assert ResponseStore(tmp_path).latest(cache_key("une_rt_m", urls[0])) is not None
    assert series.values["2022-01"] == Decimal("7.3")


def test_description_signale_une_mise_a_jour_posterieure_au_debat(tmp_path: Path) -> None:
    series = parse_series(FIXTURE, "une_rt_m")
    record = ResponseStore(tmp_path).save("k", series_url("une_rt_m", FILTERS), FIXTURE, MOMENT)

    lines = describe(series, record, "2022-01", date(2022, 4, 20))

    assert "valeur actuelle : 7.3 (mise à jour du 2026-11-24)" in lines
    assert any("la valeur a pu être révisée" in line for line in lines)
    assert "consultée le : 2026-11-26" in lines


def test_description_d_une_periode_absente(tmp_path: Path) -> None:
    series = parse_series(FIXTURE, "une_rt_m")
    record = ResponseStore(tmp_path).save("k", series_url("une_rt_m", FILTERS), FIXTURE, MOMENT)

    assert "aucune valeur pour 2030-01" in describe(series, record, "2030-01", date(2030, 2, 1))
