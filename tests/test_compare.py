from datetime import date
from decimal import Decimal
from typing import Any

from zetruth.model import (
    Claim,
    ClaimedValue,
    Confidence,
    OfficialValue,
    Utterance,
    Verdict,
    VerdictLabel,
)
from zetruth.verdicts.compare import compare

SEUIL = Decimal("0.02")
BDF_URL = (
    "https://www.banque-france.fr/fr/publications-et-statistiques/publications/"
    "projections-macroeconomiques-mars-2022"
)


def claim(qualifier: str = "egal", value: str = "5.5", **overrides: Any) -> Claim:
    data: dict[str, Any] = {
        "utterance": Utterance(source_file="d.txt", turn=31, speaker="Marine Le Pen", quote="x"),
        "type": "factuelle",
        "indicator": "demandeurs d'emploi inscrits en catégories A, B et C",
        "claimed": ClaimedValue.model_validate({"qualifier": qualifier, "value": value}),
        "unit": "millions",
        "period": "2017-Q1",
        "scope": "France métropolitaine",
    }
    data.update(overrides)
    return Claim(**data)


def official(value: str = "5.51", **overrides: Any) -> OfficialValue:
    data: dict[str, Any] = {
        "source_id": "insee",
        "reference": "série 010598455",
        "url": "https://api.insee.fr/series/BDM/V1/data/SERIES_BDM/010598455",
        "value": Decimal(value),
        "unit": "millions",
        "period": "2017-Q1",
        "scope": "France métropolitaine",
        "nature": "constatee",
        "consulted_on": date(2026, 11, 26),
        "known_at_debate": True,
    }
    data.update(overrides)
    return OfficialValue(**data)


def run(c: Claim, *values: OfficialValue) -> Verdict:
    return compare(c, values, SEUIL)


def test_valeur_conforme() -> None:
    v = run(claim(), official())

    assert v.label is VerdictLabel.VRAI
    assert v.gap == Decimal("-0.01")
    assert v.confidence is Confidence.HAUTE
    assert not v.needs_review


def test_valeur_fausse() -> None:
    v = run(claim(value="600", unit="milliards d'euros"), official("571", unit="milliards d'euros"))

    assert v.label is VerdictLabel.FAUX
    assert v.gap == Decimal("29")


def test_ce_qui_n_est_pas_factuel_n_est_pas_compare() -> None:
    promesse = claim(type="promesse", indicator=None, claimed=None, period=None)

    v = run(promesse, official())

    assert v.label is VerdictLabel.NON_FACTUEL
    assert v.official_values == ()


def test_sans_valeur_officielle() -> None:
    v = run(claim())

    assert v.label is VerdictLabel.INVERIFIABLE
    assert v.confidence is Confidence.FAIBLE


def test_unite_differente_on_ne_compare_pas() -> None:
    v = run(claim(unit="%"), official())

    assert v.label is VerdictLabel.INVERIFIABLE
    assert v.limits is not None
    assert "unité annoncée '%'" in v.limits


def test_periode_differente_on_ne_compare_pas() -> None:
    v = run(claim(period="2022-03"), official(period="2022"))

    assert v.label is VerdictLabel.INVERIFIABLE
    assert v.limits is not None
    assert "période annoncée '2022-03', période officielle '2022'" in v.limits


def test_perimetre_different_on_ne_compare_pas() -> None:
    v = run(claim(scope="France entière"), official())

    assert v.label is VerdictLabel.INVERIFIABLE
    assert v.limits is not None
    assert "périmètre" in v.limits


def test_perimetre_inconnu_d_un_cote_ne_bloque_pas() -> None:
    assert run(claim(scope=None), official()).label is VerdictLabel.VRAI
    assert run(claim(), official(scope=None)).label is VerdictLabel.VRAI


def test_differences_de_casse_et_d_espaces_ignorees() -> None:
    assert run(claim(unit="  Millions "), official()).label is VerdictLabel.VRAI


def test_valeur_revisee_depuis_le_debat_baisse_la_confiance() -> None:
    v = run(claim(), official(known_at_debate=False))

    assert v.label is VerdictLabel.VRAI
    assert v.confidence is Confidence.MOYENNE
    assert v.limits is not None
    assert "révisée" in v.limits


def test_scenarios_concurrents_a_revoir() -> None:
    """Le cas Banque de France : chiffre exact, mais un autre scénario existe."""
    prevision = claim(
        value="3.7",
        indicator="prévision d'inflation 2022",
        unit="%",
        period="2022",
        scope="France",
    )
    central = official(
        "3.7",
        source_id="banque_de_france",
        reference="scénario conventionnel",
        url=BDF_URL,
        unit="%",
        period="2022",
        scope="France",
        nature="prevision",
    )
    degrade = central.model_copy(update={"value": Decimal("4.4"), "reference": "scénario dégradé"})

    v = run(prevision, central, degrade)

    assert v.label is VerdictLabel.VRAI
    assert v.needs_review
    assert [(r.reference, r.label) for r in v.readings] == [
        ("scénario conventionnel", VerdictLabel.VRAI),
        ("scénario dégradé", VerdictLabel.FAUX),
    ]
    assert v.limits is not None
    assert "FAUX avec scénario dégradé (4.4)" in v.limits


def test_une_valeur_complementaire_d_une_autre_periode_n_est_pas_concurrente() -> None:
    v = run(claim(), official(), official("5.38", period="2021-Q4"))

    assert not v.needs_review


def test_le_verdict_produit_respecte_le_modele() -> None:
    v = run(claim(), official())

    assert Verdict.model_validate_json(v.model_dump_json()) == v


def test_definitions_qui_concordent_verdict_net() -> None:
    """« Plus de 4 % » : vrai avec l'IPC (4,5) comme avec l'IPCH (5,1), rien à revoir."""
    plus_de_4 = claim("plus_de", "4", unit="%", period="2022-03", scope="France")
    ipc = official("4.5", reference="IPC", unit="%", period="2022-03", scope="France")
    ipch = official("5.1", reference="IPCH", unit="%", period="2022-03", scope="France")

    v = run(plus_de_4, ipc, ipch)

    assert v.label is VerdictLabel.VRAI
    assert not v.needs_review
    assert [r.label for r in v.readings] == [VerdictLabel.VRAI, VerdictLabel.VRAI]
    assert v.limits is not None
    assert "même verdict avec les autres définitions officielles : IPCH (5.1)" in v.limits


def test_definitions_qui_divergent() -> None:
    """« 4,5 % » : vrai avec l'IPC, faux avec l'IPCH : le verdict le dit."""
    egal = claim("egal", "4.5", unit="%", period="2022-03", scope="France")
    ipc = official("4.5", reference="IPC", unit="%", period="2022-03", scope="France")
    ipch = official("5.1", reference="IPCH", unit="%", period="2022-03", scope="France")

    v = run(egal, ipc, ipch)

    assert v.label is VerdictLabel.VRAI
    assert v.needs_review
    assert "VRAI avec IPC (4.5), FAUX avec IPCH (5.1)" in (v.limits or "")


def test_une_seule_lecture() -> None:
    v = run(claim(), official())

    assert len(v.readings) == 1
    assert v.limits is None
