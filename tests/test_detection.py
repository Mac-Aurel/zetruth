from pathlib import Path

import pytest

from zetruth.detection.evaluate import (
    CONTROL_FILE,
    DETECTION_FILE,
    Scores,
    is_expected,
    read_rows,
    reference_sentences,
    score,
)
from zetruth.detection.rules import detect, has_figure, has_statistic
from zetruth.detection.sentences import split_sentences


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Le chômage baisse. Il est à 7,4 %.", ["Le chômage baisse.", "Il est à 7,4 %."]),
        ("Vraiment ? Oui ! Bien sûr.", ["Vraiment ?", "Oui !", "Bien sûr."]),
        ("M. Macron a parlé. Mme Le Pen aussi.", ["M. Macron a parlé.", "Mme Le Pen aussi."]),
        ("Prix, salaires, etc. Tout augmente.", ["Prix, salaires, etc. Tout augmente."]),
        ("  espaces   en   trop.  ", ["espaces en trop."]),
        ("", []),
    ],
)
def test_decoupage_en_phrases(text: str, expected: list[str]) -> None:
    assert split_sentences(text) == expected


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("L'inflation est de 4,5 %.", True),
        ("Le chômage est le plus bas depuis quinze ans.", True),
        ("Nous avons recréé un million d'emplois en cinq ans.", True),
        ("Un trader de vingt-huit ans ne paiera plus d'impôt.", False),
        ("L'infirmière de vingt et un ans paie des impôts.", False),
        ("Si Emmanuel Macron est élu le vingt-quatre avril.", False),
        ("Des millions de Français souffrent.", False),
        ("On dépense des dizaines de milliards d'euros.", True),
        ("C'est une injustice.", False),
    ],
)
def test_chiffre_statistique(sentence: str, expected: bool) -> None:
    assert has_statistic(sentence) is expected


@pytest.mark.parametrize(
    ("sentence", "worthy", "reason"),
    [
        ("La dette a augmenté de 600 milliards d'euros.", True, "chiffre et fait constaté"),
        ("L'inflation est de 4,5 % en mars.", True, "chiffre affirmé"),
        ("Pourquoi nous, c'est deux fois moins ?", False, "question"),
        ("Nous abaissons la TVA de vingt à cinq virgule cinq pour cent.", False, "promesse"),
        ("On va augmenter les retraites de cinq pour cent.", False, "promesse"),
        ("On finira par avoir dix pour cent de chômage.", False, "prédiction"),
        ("C'est une mesure démagogique.", False, "aucun chiffre statistique"),
        (
            "Nous doublerons les aides, parce qu'il y a un quart des familles monoparentales.",
            True,
            "chiffre et fait constaté",
        ),
    ],
)
def test_detection(sentence: str, worthy: bool, reason: str) -> None:
    assert detect(sentence).check_worthy is worthy
    assert detect(sentence).reason == reason


def test_scores() -> None:
    rows = [
        {"texte": "a", "verifiable": "oui", "chiffree": "oui"},
        {"texte": "b", "verifiable": "oui", "chiffree": "oui"},
        {"texte": "c", "verifiable": "non", "chiffree": ""},
        {"texte": "d", "verifiable": "oui", "chiffree": "non"},
    ]

    s = score(rows, lambda text: text in {"a", "c"})

    assert s == Scores(true_positives=1, false_positives=1, false_negatives=1)
    assert (s.precision, s.recall, s.f1) == (0.5, 0.5, 0.5)
    assert Scores(0, 0, 0).f1 == 0.0


def test_seules_les_affirmations_chiffrees_sont_attendues() -> None:
    assert is_expected({"verifiable": "oui", "chiffree": "oui"})
    assert not is_expected({"verifiable": "oui", "chiffree": "non"})
    assert not is_expected({"verifiable": "non", "chiffree": ""})


def test_phrases_du_jeu_de_reference() -> None:
    annotations = [
        {"type": "factuelle", "fichier": "d.txt", "tour": "1", "citation": "7,4 %"},
        {"type": "promesse", "fichier": "d.txt", "tour": "1", "citation": "1 100 euros"},
    ]
    turns = {("d.txt", 1): "Bonsoir. Le chômage est à 7,4 %. Je veux 1 100 euros."}

    assert reference_sentences(annotations, turns) == ["Le chômage est à 7,4 %."]


@pytest.mark.parametrize(("path", "size"), [(DETECTION_FILE, 151), (CONTROL_FILE, 112)])
def test_les_jeux_de_detection_sont_coherents(path: Path, size: int) -> None:
    rows = read_rows(path)

    assert len(rows) == size
    for row in rows:
        assert row["verifiable"] in {"oui", "non"}
        assert (row["verifiable"] == "oui") == (row["type"] == "factuelle")
        assert row["chiffree"] in ({"oui", "non"} if row["verifiable"] == "oui" else {""})


def test_les_regles_battent_la_reference_triviale() -> None:
    """Garde-fou : modifier les règles ne doit pas les rendre pires que « contient un chiffre »."""
    rows = read_rows()
    rules, trivial = score(rows, lambda s: detect(s).check_worthy), score(rows, has_figure)

    assert rules.f1 > trivial.f1
