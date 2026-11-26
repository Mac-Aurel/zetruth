from datetime import date
from pathlib import Path

import pytest

from zetruth.normalization.normalize import Debate, load_debates
from zetruth.reference.annotations import COLUMNS
from zetruth.report import (
    REPORTS_DIR,
    claimed_value,
    french_date,
    french_number,
    french_text,
    render,
    report_for,
)
from zetruth.sources.registry import load_registry


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("4.5", "4,5"),
        ("160000", "160 000"),
        ("2823.7", "2823,7"),
        ("-12500", "-12 500"),
        ("110000 (moyenne 2006-2017)", "110 000 (moyenne 2006-2017)"),
        ("versement unique de 100 euros", "versement unique de 100 euros"),
    ],
)
def test_nombres_a_la_francaise(value: str, expected: str) -> None:
    assert french_number(value) == expected


def test_decimales_dans_un_texte_sans_toucher_aux_liens() -> None:
    text = "IPCH 5.1 contre 4.5, voir https://ec.europa.eu/eurostat/statistics/1.0/data"

    assert french_text(text) == (
        "IPCH 5,1 contre 4,5, voir https://ec.europa.eu/eurostat/statistics/1.0/data"
    )


def test_dates() -> None:
    assert french_date(date(2022, 4, 1)) == "1er avril 2022"
    assert french_date("2021-10-12") == "12 octobre 2021"


def row(**overrides: str) -> dict[str, str]:
    data = dict.fromkeys(COLUMNS, "")
    data.update(
        id="x1",
        fichier="Debat--a.txt",
        tour="3",
        locuteur="Marine Le Pen",
        citation="la dette a augmenté de 600 milliards",
        type="factuelle",
        sujet="dette publique",
        indicateur="hausse de la dette publique",
        qualificatif="egal",
        valeur="600",
        unite="milliards d'euros",
        periode="T1 2017 - T4 2021",
        perimetre="France",
        nature_valeur="constatee",
        verdict="FAUX",
        valeur_officielle="571.4",
        source_organisme="insee",
        source_reference="série 010596744",
        source_url="https://api.insee.fr/series/BDM/V1/data/SERIES_BDM/010596744",
        date_publication="2024-03-25",
        date_consultation="2026-11-26",
        valeur_du_debat="non",
    )
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, "600 milliards d'euros"),
        ({"qualificatif": "plus_de", "valeur": "2", "unite": "points"}, "plus de 2 points"),
        (
            {"qualificatif": "entre", "valeur": "4", "valeur_max": "4.5", "unite": "%"},
            "entre 4 et 4,5 %",
        ),
    ],
)
def test_valeur_annoncee(overrides: dict[str, str], expected: str) -> None:
    assert claimed_value(row(**overrides)) == expected


def test_rapport() -> None:
    debate = Debate("Debat", date(2022, 4, 20), title="Débat test")
    rows = [
        row(),
        row(
            id="x2",
            locuteur="Emmanuel Macron",
            citation="un sondage dit 75 %",
            verdict="VRAI",
            attribution="oui",
            source_organisme="odoxa",
            source_url="https://www.odoxa.fr/sondage/x/",
        ),
        row(id="x3", type="promesse", citation="je ferai 1 100 euros", verdict="NON_FACTUEL"),
    ]

    report = render(debate, rows, load_registry())

    assert report.startswith("# Débat test, 20 avril 2022")
    assert "| Marine Le Pen | 0 | 1 | 0 | 0 | 0 |" in report
    assert "**Verdict : Faux**" in report
    assert "Ce que disent les sources : 571,4." in report
    assert "Source : Institut national de la statistique et des études économiques" in report
    assert "a pu être légèrement différente" in report
    assert "un sondage mesure une opinion" in report
    assert "- Marine Le Pen : « je ferai 1 100 euros »" in report


@pytest.mark.parametrize("name", sorted(load_debates()))
def test_les_rapports_versionnes_sont_a_jour(name: str) -> None:
    """Les rapports du dépôt suivent le jeu de référence (uv run python -m zetruth.report)."""
    expected = report_for(name)
    path = REPORTS_DIR / f"{name}.md"

    if expected is None:
        assert not path.exists()
    else:
        assert Path(path).read_text(encoding="utf-8") == expected
