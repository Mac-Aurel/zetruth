from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from zetruth.model import (
    Claim,
    ClaimedValue,
    ClaimType,
    Confidence,
    Lead,
    OfficialValue,
    Qualifier,
    Utterance,
    Verdict,
    VerdictLabel,
    check_sources,
)
from zetruth.sources.registry import load_registry

UTTERANCE = Utterance(
    source_file="Macron_Lepen_2--Partie_1_Pouvoir_D_Achat.txt",
    turn=3,
    speaker="Emmanuel Macron",
    quote="là on a une inflation d'un peu plus de 4 %",
)
INSEE_URL = "https://api.insee.fr/series/BDM/V1/data/SERIES_BDM/001761313?includeHistory=true"


def claim(**overrides: Any) -> Claim:
    data: dict[str, Any] = {
        "utterance": UTTERANCE,
        "type": ClaimType.FACTUELLE,
        "indicator": "glissement annuel de l'IPC",
        "claimed": ClaimedValue(qualifier=Qualifier.PLUS_DE, value=Decimal("4")),
        "unit": "%",
        "period": "mars 2022",
        "scope": "France",
    }
    data.update(overrides)
    return Claim(**data)


def official(**overrides: Any) -> OfficialValue:
    data: dict[str, Any] = {
        "source_id": "insee",
        "reference": "série 001761313",
        "url": INSEE_URL,
        "value": Decimal("4.5"),
        "unit": "%",
        "period": "2022-03",
        "nature": "constatee",
        "published_on": date(2022, 4, 15),
        "consulted_on": date(2026, 11, 26),
        "known_at_debate": True,
    }
    data.update(overrides)
    return OfficialValue(**data)


def verdict(**overrides: Any) -> Verdict:
    data: dict[str, Any] = {
        "claim": claim(),
        "label": VerdictLabel.VRAI,
        "official_values": (official(),),
        "gap": Decimal("0.5"),
        "confidence": Confidence.HAUTE,
    }
    data.update(overrides)
    return Verdict(**data)


def test_un_verdict_source_complet_se_construit() -> None:
    assert verdict().official_values[0].value == Decimal("4.5")


@pytest.mark.parametrize("label", ["VRAI", "FAUX", "TROMPEUR", "IMPRECIS"])
def test_un_verdict_tranche_sans_source_est_impossible(label: str) -> None:
    with pytest.raises(ValidationError, match="au moins une valeur officielle"):
        verdict(label=label, official_values=())


def test_inverifiable_sans_source_est_possible() -> None:
    assert verdict(label="INVERIFIABLE", official_values=(), confidence="moyenne").gap is not None


@pytest.mark.parametrize("kind", ["opinion", "promesse", "prediction"])
def test_ce_qui_n_est_pas_factuel_est_non_factuel(kind: str) -> None:
    non_factual = claim(type=kind, indicator=None, claimed=None, period=None)

    built = verdict(claim=non_factual, label="NON_FACTUEL", official_values=())
    assert built.label == "NON_FACTUEL"
    with pytest.raises(ValidationError, match="est NON_FACTUEL"):
        verdict(claim=non_factual, label="VRAI")


def test_une_affirmation_factuelle_n_est_jamais_non_factuelle() -> None:
    with pytest.raises(ValidationError, match="ne peut pas être NON_FACTUEL"):
        verdict(label="NON_FACTUEL", official_values=())


def test_non_factuel_ne_cite_pas_de_source() -> None:
    non_factual = claim(type="opinion", indicator=None, claimed=None, period=None)

    with pytest.raises(ValidationError, match="aucune valeur officielle"):
        verdict(claim=non_factual, label="NON_FACTUEL")


@pytest.mark.parametrize("missing", ["indicator", "claimed", "period"])
def test_une_affirmation_factuelle_doit_etre_complete(missing: str) -> None:
    with pytest.raises(ValidationError, match=f"incomplète : {missing}"):
        claim(**{missing: None})


def test_plusieurs_valeurs_officielles_pour_une_comparaison() -> None:
    eurostat = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_manr"
    values = tuple(
        official(
            source_id="eurostat", url=f"{eurostat}?geo={geo}", value=value, known_at_debate=False
        )
        for geo, value in (("FR", Decimal("5.1")), ("ES", Decimal("9.8")))
    )

    assert len(verdict(official_values=values, confidence="moyenne").official_values) == 2


def test_pas_de_confiance_haute_avec_une_valeur_revisee_depuis_le_debat() -> None:
    with pytest.raises(ValidationError, match="confiance haute impossible"):
        verdict(official_values=(official(known_at_debate=False),))


def test_une_prevision_se_distingue_d_une_valeur_constatee() -> None:
    assert official(nature="prevision").nature == "prevision"
    with pytest.raises(ValidationError):
        official(nature="estimation au doigt mouille")


@pytest.mark.parametrize(
    ("qualifier", "value", "upper", "ok"),
    [
        ("egal", "4", None, True),
        ("plus_de", "2", None, True),
        ("entre", "60", "62", True),
        ("entre", "62", "60", False),
        ("entre", "60", None, False),
        ("environ", "4", "5", False),
    ],
)
def test_valeurs_annoncees(qualifier: str, value: str, upper: str | None, ok: bool) -> None:
    def build() -> ClaimedValue:
        return ClaimedValue.model_validate({"qualifier": qualifier, "value": value, "upper": upper})

    if ok:
        assert build().value == Decimal(value)
    else:
        with pytest.raises(ValidationError):
            build()


def test_les_valeurs_numeriques_restent_exactes() -> None:
    assert official(value="0.1").value + official(value="0.2").value == Decimal("0.3")


@pytest.mark.parametrize("overrides", [{"turn": -1}, {"speaker": ""}, {"quote": "   "}])
def test_une_citation_mal_reperee_est_refusee(overrides: dict[str, Any]) -> None:
    data = UTTERANCE.model_dump() | overrides
    with pytest.raises(ValidationError):
        Utterance(**data)


def test_un_champ_inconnu_est_refuse() -> None:
    with pytest.raises(ValidationError):
        official(valeur_au_pif="12")


def test_une_url_non_http_est_refusee() -> None:
    with pytest.raises(ValidationError, match="URL invalide"):
        official(url="insee.fr/serie")


def test_le_modele_est_immuable() -> None:
    v = verdict()
    with pytest.raises(ValidationError):
        v.label = VerdictLabel.FAUX


def test_aller_retour_json_sans_perte() -> None:
    v = verdict()

    assert Verdict.model_validate_json(v.model_dump_json()) == v


def test_les_sources_doivent_etre_dans_la_liste_blanche() -> None:
    registry = load_registry()

    assert check_sources(verdict(), registry) == []
    assert check_sources(verdict(official_values=(official(source_id="le_monde"),)), registry) == [
        "source hors liste blanche : 'le_monde'"
    ]
    wrong_url = official(url="https://ec.europa.eu/eurostat/api/x")
    assert check_sources(verdict(official_values=(wrong_url,)), registry) == [
        "https://ec.europa.eu/eurostat/api/x n'appartient pas à la source insee"
    ]


def test_une_piste_n_est_pas_une_valeur_officielle() -> None:
    lead = Lead(publisher="Reporterre", url="https://reporterre.net/x", summary="Relaie.")

    v = verdict(label="INVERIFIABLE", official_values=(), confidence="faible", leads=(lead,))

    assert v.leads == (lead,)
    assert v.official_values == ()
    with pytest.raises(ValidationError, match="au moins une valeur officielle"):
        verdict(label="VRAI", official_values=(), leads=(lead,))


def test_une_source_d_attribution_ne_prouve_pas_un_fait() -> None:
    registry = load_registry()
    sondage = official(
        source_id="odoxa", url="https://www.odoxa.fr/sondage/x/", value=Decimal("75")
    )

    fait = verdict(official_values=(sondage,))
    attribution = verdict(claim=claim(attribution=True), official_values=(sondage,))

    assert check_sources(fait, registry) == [
        "odoxa ne peut vérifier qu'une attribution, pas un fait"
    ]
    assert check_sources(attribution, registry) == []
