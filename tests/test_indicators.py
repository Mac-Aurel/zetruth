from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from zetruth.indicators.__main__ import describe
from zetruth.indicators.catalog import InvalidCatalogError, load_catalog, parse_catalog
from zetruth.indicators.values import IndicatorService
from zetruth.sources.client import SourceClient
from zetruth.sources.registry import load_registry
from zetruth.sources.store import ResponseStore

FIXTURES = Path(__file__).parent / "fixtures"
INSEE_FIXTURE = (FIXTURES / "insee_bdm_historique.xml").read_bytes()  # série 001688527
EUROSTAT_FIXTURE = (FIXTURES / "eurostat_une_rt_m_fr.json").read_bytes()
EUROSTAT_FILTERS = {"geo": "FR", "age": "TOTAL", "sex": "T", "unit": "PC_ACT", "s_adj": "SA"}
DEBAT = date(2022, 4, 20)
REGISTRY = load_registry()


def raw_indicator(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "nom": "Taux de chômage BIT",
        "definition": "Part des chômeurs dans la population active.",
        "source": "insee",
        "serie": "001688527",
        "unite": "%",
        "unite_evolution": "points",
        "perimetre": "France hors Mayotte",
        "frequence": "trimestrielle",
    }
    data.update(overrides)
    return data


EUROSTAT_INDICATOR = raw_indicator(
    nom="Chômage mensuel",
    source="eurostat",
    serie=None,
    dataset="une_rt_m",
    filtres=EUROSTAT_FILTERS,
    perimetre="France",
    frequence="mensuelle",
)


def service(tmp_path: Path, **indicators: dict[str, Any]) -> IndicatorService:
    catalog = parse_catalog({"indicateurs": indicators}, REGISTRY)

    def client(source_id: str, content: bytes) -> SourceClient:
        return SourceClient(
            source_id,
            ResponseStore(tmp_path / source_id),
            REGISTRY,
            0,
            fetch=lambda url: content,
            now=lambda: datetime(2026, 11, 26, tzinfo=UTC),
        )

    clients = {
        "insee": client("insee", INSEE_FIXTURE),
        "eurostat": client("eurostat", EUROSTAT_FIXTURE),
    }
    return IndicatorService(catalog, clients)


def test_valeur_connue_le_jour_du_debat(tmp_path: Path) -> None:
    v = service(tmp_path, chomage=raw_indicator()).value("chomage", "2021-Q4", DEBAT)

    assert v is not None
    assert (v.value, v.unit, v.scope) == (Decimal("7.4"), "%", "France hors Mayotte")
    assert (v.published_on, v.known_at_debate) == (date(2022, 2, 18), True)
    assert v.consulted_on == date(2026, 11, 26)
    assert v.url.endswith("001688527?includeHistory=true")


def test_sans_historique_assez_ancien_on_prend_la_derniere_valeur_et_on_le_dit(
    tmp_path: Path,
) -> None:
    v = service(tmp_path, chomage=raw_indicator()).value("chomage", "2021-Q3", date(2021, 1, 1))

    assert v is not None
    assert (v.value, v.published_on, v.known_at_debate) == (
        Decimal("8.0"),
        date(2023, 2, 14),
        False,
    )


def test_periode_absente(tmp_path: Path) -> None:
    assert service(tmp_path, chomage=raw_indicator()).value("chomage", "1990-Q1", DEBAT) is None


def test_baisse_entre_deux_periodes(tmp_path: Path) -> None:
    v = service(tmp_path, chomage=raw_indicator()).change(
        "chomage", "2021-Q3", "2021-Q4", DEBAT, decrease=True
    )

    assert v is not None
    assert (v.value, v.unit, v.period) == (Decimal("0.6"), "points", "2021-Q3/2021-Q4")
    assert v.known_at_debate
    assert "8.0 en 2021-Q3, 7.4 en 2021-Q4" in v.reference


def test_hausse_negative_quand_ca_baisse(tmp_path: Path) -> None:
    v = service(tmp_path, chomage=raw_indicator()).change("chomage", "2021-Q3", "2021-Q4", DEBAT)

    assert v is not None
    assert v.value == Decimal("-0.6")


def test_evolution_impossible_si_une_periode_manque(tmp_path: Path) -> None:
    svc = service(tmp_path, chomage=raw_indicator())

    assert svc.change("chomage", "1990-Q1", "2021-Q4", DEBAT) is None


def test_le_facteur_change_l_echelle_ou_le_signe(tmp_path: Path) -> None:
    svc = service(
        tmp_path, en_millier=raw_indicator(facteur=0.001), negatif=raw_indicator(facteur=-1)
    )

    milliers = svc.value("en_millier", "2021-Q4", DEBAT)
    negatif = svc.value("negatif", "2021-Q4", DEBAT)
    assert milliers is not None and negatif is not None
    assert (milliers.value, negatif.value) == (Decimal("0.0074"), Decimal("-7.4"))


def test_valeur_eurostat_revisee_depuis_le_debat(tmp_path: Path) -> None:
    v = service(tmp_path, mensuel=EUROSTAT_INDICATOR).value("mensuel", "2022-01", DEBAT)

    assert v is not None
    assert (v.value, v.known_at_debate, v.published_on) == (Decimal("7.3"), False, None)
    assert v.source_id == "eurostat"


def test_autre_pays_eurostat_prend_le_libelle_de_la_source(tmp_path: Path) -> None:
    v = service(tmp_path, mensuel=EUROSTAT_INDICATOR).value(
        "mensuel", "2022-01", DEBAT, filters={"geo": "FR"}
    )

    assert v is not None
    assert v.scope == "France"


def test_valeurs_des_definitions_concurrentes(tmp_path: Path) -> None:
    svc = service(
        tmp_path,
        trimestriel=raw_indicator(concurrents=["autre"]),
        autre=raw_indicator(nom="Autre mesure", facteur=2),
    )

    values = svc.with_competitors("trimestriel", "2021-Q4", DEBAT)

    assert [v.value for v in values] == [Decimal("7.4"), Decimal("14.8")]


def test_pas_de_concurrent_sans_valeur_principale(tmp_path: Path) -> None:
    svc = service(tmp_path, a=raw_indicator(concurrents=["b"]), b=raw_indicator())

    assert svc.with_competitors("a", "1990-Q1", DEBAT) == []


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"nom": ""}, "champs manquants"),
        ({"source": "ofpra"}, "source sans connecteur"),
        ({"serie": "abc"}, "identifiant de série INSEE manquant"),
        ({"source": "eurostat", "dataset": "une_rt_m"}, "dataset et filtres Eurostat requis"),
        ({"frequence": "hebdomadaire"}, "fréquence inconnue"),
        ({"facteur": 0}, "facteur nul"),
        ({"concurrents": ["fantome"]}, "concurrent inconnu"),
        ({"concurrents": ["x"]}, "concurrent inconnu"),
    ],
)
def test_un_indicateur_mal_declare_est_refuse(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(InvalidCatalogError, match=message):
        parse_catalog({"indicateurs": {"x": raw_indicator(**overrides)}}, REGISTRY)


def test_le_catalogue_du_projet_est_valide() -> None:
    catalog = load_catalog(REGISTRY)

    assert {"chomage_bit", "inflation_ipc", "dette_publique", "deficit_public_pib"} <= set(catalog)
    for indicator in catalog.values():
        for competitor in indicator.competitors:
            assert indicator.id in catalog[competitor].competitors, (indicator.id, competitor)


def test_resume_du_pre_calcul(tmp_path: Path) -> None:
    svc = service(tmp_path, chomage=raw_indicator(), mensuel=EUROSTAT_INDICATOR)
    clients = svc._clients

    insee_line = describe(svc.catalog["chomage"], clients["insee"], refresh=False)
    eurostat_line = describe(svc.catalog["mensuel"], clients["eurostat"], refresh=False)

    assert insee_line.startswith("chomage : 2 périodes, dernière 2021-Q4, 3 publications")
    assert eurostat_line.startswith("mensuel : 6 périodes, dernière 2022-03")
    assert "mise à jour du 2026-11-24" in eurostat_line
