from pathlib import Path

import pytest

from zetruth.corpus.fredsum import Turn
from zetruth.reference.annotations import COLUMNS, read_annotations, validate_rows
from zetruth.sources.registry import parse_registry

TURNS = {
    "debat.txt": [
        Turn(0, "P1", "Parlons du chômage."),
        Turn(1, "Nicolas Sarkozy", "Le chômage a baissé de 5 % depuis 2007, c'est un fait."),
    ]
}

REGISTRY = parse_registry(
    {
        "sources": {
            "insee": {
                "nom": "INSEE",
                "urls": ["https://insee.fr/"],
                "domaines": ["economie"],
                "statut": "a_verifier",
            }
        }
    }
)


def make_row(**overrides: str) -> dict[str, str]:
    row = dict.fromkeys(COLUMNS, "")
    row.update(
        id="a1",
        fichier="debat.txt",
        tour="1",
        locuteur="Nicolas Sarkozy",
        citation="Le chômage a baissé de 5 % depuis 2007",
        type="factuelle",
        indicateur="taux de chômage BIT",
        valeur="-5",
        periode="2007-2012",
        verdict="FAUX",
        valeur_officielle="+2,3 points",
        source_organisme="insee",
        source_reference="série 001688526",
        source_url="https://www.insee.fr/",
        date_consultation="2026-11-26",
    )
    row.update(overrides)
    return row


def test_une_affirmation_complete_est_valide() -> None:
    assert validate_rows([make_row()], TURNS, REGISTRY) == []


def test_un_verdict_source_exige_la_source() -> None:
    errors = validate_rows([make_row(source_url="", valeur_officielle="")])

    assert errors == [
        "ligne 2 : champ obligatoire vide (verdict sourcé) : valeur_officielle",
        "ligne 2 : champ obligatoire vide (verdict sourcé) : source_url",
    ]


def test_inverifiable_ne_demande_pas_de_source() -> None:
    row = make_row(verdict="INVERIFIABLE", valeur_officielle="", source_organisme="", source_url="")

    assert validate_rows([row]) == []


def test_une_opinion_doit_etre_non_factuelle() -> None:
    assert validate_rows([make_row(type="opinion", verdict="NON_FACTUEL")]) == []
    assert validate_rows([make_row(type="opinion", verdict="VRAI")]) == [
        "ligne 2 : une affirmation de type opinion doit avoir le verdict NON_FACTUEL"
    ]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"type": "rumeur"}, "type inconnu"),
        ({"verdict": "PLUTOT_VRAI"}, "verdict 'PLUTOT_VRAI' invalide"),
        ({"tour": "-1"}, "tour doit être un entier positif"),
        ({"citation": ""}, "champ obligatoire vide : citation"),
        ({"date_consultation": "26/11/2026"}, "date_consultation doit être au format AAAA-MM-JJ"),
        ({"indicateur": ""}, "champ obligatoire vide : indicateur"),
    ],
)
def test_les_valeurs_invalides_sont_signalees(overrides: dict[str, str], expected: str) -> None:
    errors = validate_rows([make_row(**overrides)])

    assert len(errors) == 1
    assert expected in errors[0]


def test_les_id_en_double_sont_signales() -> None:
    errors = validate_rows([make_row(), make_row()])

    assert errors == ["ligne 3 : id 'a1' en double"]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"citation": "Le chômage a baissé de 6 %"}, "ne figure pas mot pour mot"),
        ({"locuteur": "François Hollande"}, "différent de celui du tour"),
        ({"tour": "9"}, "tour 9 absent"),
        ({"fichier": "autre.txt"}, "fichier inconnu"),
    ],
)
def test_la_citation_est_verifiee_contre_la_transcription(
    overrides: dict[str, str], expected: str
) -> None:
    errors = validate_rows([make_row(**overrides)], TURNS)

    assert len(errors) == 1
    assert expected in errors[0]


def test_un_fichier_avec_de_mauvaises_colonnes_est_refuse(tmp_path: Path) -> None:
    path = tmp_path / "affirmations.csv"
    path.write_text("id,citation\n", encoding="utf-8")

    with pytest.raises(ValueError, match="colonnes attendues"):
        read_annotations(path)


def test_le_fichier_du_depot_a_les_bonnes_colonnes() -> None:
    read_annotations(Path("data/reference/affirmations.csv"))


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"source_organisme": "le_monde"}, "source hors liste blanche : 'le_monde'"),
        (
            {"source_url": "https://www.lemonde.fr/les-decodeurs/"},
            "source_url n'appartient pas à la source insee",
        ),
        ({"source_url": "insee.fr/statistiques"}, "URL invalide"),
    ],
)
def test_la_source_doit_appartenir_a_la_liste_blanche(
    overrides: dict[str, str], expected: str
) -> None:
    errors = validate_rows([make_row(**overrides)], registry=REGISTRY)

    assert len(errors) == 1
    assert expected in errors[0]
