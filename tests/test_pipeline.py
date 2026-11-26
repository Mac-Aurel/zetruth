from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from zetruth.corpus.fredsum import Turn
from zetruth.evaluation import Result, classify, evaluate
from zetruth.indicators.catalog import parse_catalog
from zetruth.indicators.values import IndicatorService
from zetruth.model import Utterance, VerdictLabel
from zetruth.normalization.normalize import Debate
from zetruth.pipeline import verify_sentence
from zetruth.sources.client import SourceClient
from zetruth.sources.registry import load_registry
from zetruth.sources.store import ResponseStore

# Série réelle 001688527 (chômage BIT) : 2021-Q3 et 2021-Q4, publiées avant le débat.
FIXTURE = (Path(__file__).parent / "fixtures" / "insee_bdm_historique.xml").read_bytes()
REGISTRY = load_registry()
DEBAT = Debate("Debat", date(2022, 4, 20), date(2017, 5, 14))
SEUIL = Decimal("0.02")


def service(tmp_path: Path) -> IndicatorService:
    catalog = parse_catalog(
        {
            "indicateurs": {
                "chomage_bit": {
                    "nom": "Taux de chômage au sens du BIT",
                    "definition": "Part des chômeurs dans la population active.",
                    "source": "insee",
                    "serie": "001688527",
                    "unite": "%",
                    "unite_evolution": "points",
                    "frequence": "trimestrielle",
                    "mots_cles": ["chômage"],
                }
            }
        },
        REGISTRY,
    )
    client = SourceClient(
        "insee",
        ResponseStore(tmp_path),
        REGISTRY,
        0,
        fetch=lambda url: FIXTURE,
        now=lambda: datetime(2026, 11, 26, tzinfo=UTC),
    )
    return IndicatorService(catalog, {"insee": client})


def run(tmp_path: Path, sentence: str, context: str = "") -> list[Any]:
    utterance = Utterance(source_file="Debat--x.txt", turn=0, speaker="X", quote=sentence)
    return verify_sentence(utterance, DEBAT, service(tmp_path), SEUIL, context)


def test_niveau_juste(tmp_path: Path) -> None:
    (outcome,) = run(tmp_path, "Le taux de chômage est de 7,4 %.")

    assert outcome.verdict is not None
    assert outcome.verdict.label is VerdictLabel.VRAI
    assert outcome.verdict.claim.period == "2021-Q4"
    assert outcome.verdict.confidence == "haute"


def test_niveau_imprecis(tmp_path: Path) -> None:
    (outcome,) = run(tmp_path, "Le taux de chômage est de 7,5 %.")

    assert outcome.verdict is not None
    assert outcome.verdict.label is VerdictLabel.IMPRECIS


def test_tres_grand_ecart_a_revoir(tmp_path: Path) -> None:
    (outcome,) = run(tmp_path, "Le taux de chômage est de 20 %.")

    assert outcome.verdict is not None
    assert outcome.verdict.label is VerdictLabel.FAUX
    assert outcome.verdict.needs_review
    assert "écart très grand" in (outcome.verdict.limits or "")


def test_evolution_sans_donnee_de_depart(tmp_path: Path) -> None:
    (outcome,) = run(tmp_path, "Le chômage a baissé de 2 points.")

    assert outcome.verdict is not None
    assert outcome.verdict.label is VerdictLabel.INVERIFIABLE


def test_prevision_annoncee_au_tour_precedent(tmp_path: Path) -> None:
    (outcome,) = run(tmp_path, "Le chômage sera de 7 %.", context="selon la Banque de France")

    assert outcome.verdict is None
    assert "prévision" in (outcome.reason or "")


def test_phrase_non_retenue(tmp_path: Path) -> None:
    assert run(tmp_path, "C'est une injustice.") == []


def test_evaluation_de_bout_en_bout(tmp_path: Path) -> None:
    annotations = [
        {
            "id": "a",
            "type": "factuelle",
            "fichier": "Debat--x.txt",
            "tour": "0",
            "locuteur": "X",
            "citation": "7,4 %",
            "valeur": "7.4",
            "verdict": "VRAI",
        },
        {
            "id": "b",
            "type": "promesse",
            "fichier": "Debat--x.txt",
            "tour": "0",
            "locuteur": "X",
            "citation": "x",
            "valeur": "",
            "verdict": "NON_FACTUEL",
        },
    ]
    turns = {"Debat--x.txt": [Turn(0, "X", "Le taux de chômage est de 7,4 %.")]}

    evaluated = evaluate(annotations, turns, {"Debat": DEBAT}, service(tmp_path), SEUIL)

    assert [(e.annotation_id, e.result) for e in evaluated] == [("a", Result.JUSTE)]


def test_classement_des_resultats(tmp_path: Path) -> None:
    (juste,) = run(tmp_path, "Le taux de chômage est de 7,4 %.")
    (gros_ecart,) = run(tmp_path, "Le taux de chômage est de 20 %.")
    (imprecis,) = run(tmp_path, "Le taux de chômage est de 7,5 %.")

    assert classify("VRAI", juste)[0] is Result.JUSTE
    assert classify("VRAI", gros_ecart)[0] is Result.FAUX_SIGNALE
    assert classify("VRAI", imprecis)[0] is Result.FAUX_NON_SIGNALE
    assert classify("VRAI", None)[0] is Result.ABSTENTION
    assert classify("INVERIFIABLE", None)[0] is Result.JUSTE
