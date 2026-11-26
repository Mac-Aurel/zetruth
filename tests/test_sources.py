from datetime import date
from typing import Any

import pytest

from zetruth.sources.registry import (
    DOMAINS,
    InvalidRegistryError,
    UnknownSourceError,
    load_registry,
    normalize_url,
    parse_registry,
)


def raw_source(**overrides: Any) -> dict[str, Any]:
    source: dict[str, Any] = {
        "nom": "Institut national de la statistique",
        "urls": ["https://www.insee.fr/", "https://api.insee.fr"],
        "domaines": ["economie", "emploi"],
        "statut": "a_verifier",
    }
    source.update(overrides)
    return source


def registry_of(**sources: dict[str, Any]) -> Any:
    return parse_registry({"sources": sources})


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.insee.fr/fr/statistiques", "https://insee.fr/fr/statistiques"),
        ("http://INSEE.fr", "https://insee.fr/"),
        ("  https://insee.fr/a?x=1  ", "https://insee.fr/a"),
    ],
)
def test_normalisation_des_url(url: str, expected: str) -> None:
    assert normalize_url(url) == expected


@pytest.mark.parametrize("url", ["insee.fr", "ftp://insee.fr/", ""])
def test_une_url_sans_schema_http_est_refusee(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_url(url)


def test_une_url_de_la_liste_blanche_est_attribuee_a_sa_source() -> None:
    registry = registry_of(insee=raw_source())

    assert registry.for_url("https://www.insee.fr/fr/statistiques/2381394").id == "insee"
    assert registry.for_url("https://api.insee.fr/series/BDM/V1/data").id == "insee"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.lemonde.fr/les-decodeurs/",
        "https://insee.fr.exemple.com/",
        "https://faux-insee.fr/",
    ],
)
def test_une_url_hors_liste_blanche_est_refusee(url: str) -> None:
    registry = registry_of(insee=raw_source())

    with pytest.raises(UnknownSourceError):
        registry.for_url(url)


def test_un_prefixe_de_chemin_ne_couvre_pas_un_chemin_voisin() -> None:
    registry = registry_of(eurostat=raw_source(urls=["https://ec.europa.eu/eurostat"]))

    assert registry.for_url("https://ec.europa.eu/eurostat/databrowser").id == "eurostat"
    assert registry.for_url("https://ec.europa.eu/eurostat").id == "eurostat"
    with pytest.raises(UnknownSourceError):
        registry.for_url("https://ec.europa.eu/eurostatistiques")


def test_une_source_inconnue_est_refusee() -> None:
    with pytest.raises(UnknownSourceError, match="hors liste blanche"):
        registry_of(insee=raw_source()).get("le_monde")


def test_recherche_par_domaine() -> None:
    registry = registry_of(
        insee=raw_source(),
        rte=raw_source(urls=["https://rte-france.com/"], domaines=["energie"]),
    )

    assert [s.id for s in registry.for_domain("energie")] == ["rte"]
    with pytest.raises(ValueError, match="domaine inconnu"):
        registry.for_domain("astrologie")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"nom": ""}, "champ manquant : nom"),
        ({"urls": []}, "champ manquant : urls"),
        ({"domaines": ["astrologie"]}, "domaines inconnus"),
        ({"statut": "ok"}, "statut inconnu"),
        ({"urls": ["insee.fr"]}, "URL invalide"),
        ({"statut": "verifiee"}, "source vérifiée sans"),
        (
            {
                "statut": "verifiee",
                "acces": "api",
                "documentation": "https://portail-api.insee.fr/",
                "conditions_usage": "Licence Ouverte 2.0",
                "date_verification": "2026-11-26",
            },
            "date_verification doit être une date",
        ),
    ],
)
def test_une_source_mal_declaree_est_refusee(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(InvalidRegistryError, match=message):
        registry_of(insee=raw_source(**overrides))


def test_une_source_verifiee_complete_est_acceptee() -> None:
    registry = registry_of(
        insee=raw_source(
            statut="verifiee",
            acces="api",
            documentation="https://portail-api.insee.fr/",
            conditions_usage="Licence Ouverte 2.0",
            date_verification=date(2026, 11, 26),
        )
    )

    assert registry.get("insee").verified_on == date(2026, 11, 26)


def test_deux_sources_ne_peuvent_pas_couvrir_la_meme_url() -> None:
    with pytest.raises(InvalidRegistryError, match="se recouvrent"):
        registry_of(
            interieur=raw_source(urls=["https://interieur.gouv.fr/"]),
            ssmsi=raw_source(urls=["https://interieur.gouv.fr/Interstats/"]),
        )


def test_un_referentiel_vide_est_refuse() -> None:
    with pytest.raises(InvalidRegistryError, match="aucune source"):
        parse_registry({})


def test_le_referentiel_du_projet_est_valide() -> None:
    registry = load_registry()

    assert len(registry) > 0
    for domain in DOMAINS:
        assert registry.for_domain(domain), f"aucune source pour le domaine {domain}"
    assert registry.for_url("https://www.insee.fr/fr/statistiques").id == "insee"
