from decimal import Decimal
from pathlib import Path

import pytest

from zetruth.model import ClaimedValue, VerdictLabel
from zetruth.verdicts.tolerance import load_threshold, numeric_verdict, relative_gap, round_like

SEUIL = Decimal("0.02")


def annonce(qualifier: str, value: str, upper: str | None = None) -> ClaimedValue:
    return ClaimedValue.model_validate({"qualifier": qualifier, "value": value, "upper": upper})


def verdict(qualifier: str, value: str, official: str, upper: str | None = None) -> VerdictLabel:
    return numeric_verdict(annonce(qualifier, value, upper), Decimal(official), SEUIL)


@pytest.mark.parametrize(
    ("official", "claimed", "expected"),
    [
        ("5.51", "5.5", "5.5"),
        ("5.55", "5.5", "5.6"),
        ("571.4", "600", "571"),
        ("4.5", "4", "5"),
        ("-2.25", "-2.2", "-2.3"),
        ("1.92", "2", "2"),
    ],
)
def test_arrondi_a_la_precision_annoncee(official: str, claimed: str, expected: str) -> None:
    assert round_like(Decimal(official), Decimal(claimed)) == Decimal(expected)


@pytest.mark.parametrize(
    ("qualifier", "value", "official", "expected"),
    [
        # Cas réels du jeu de référence
        ("egal", "5.5", "5.51", "VRAI"),  # inscrits A, B, C au T1 2017
        ("egal", "5.4", "5.38", "VRAI"),  # inscrits A, B, C au T4 2021
        ("egal", "9.6", "9.6", "VRAI"),  # chômage BIT T1 2017
        ("plus_de", "2", "2.2", "VRAI"),  # baisse du chômage
        ("plus_de", "4", "4.5", "VRAI"),  # inflation de mars 2022
        ("environ", "2", "1.92", "VRAI"),  # deux fois moins d'inflation que l'Espagne
        ("egal", "600", "571", "FAUX"),  # hausse de la dette, écart de 5 %
        ("egal", "9.8", "9.2", "FAUX"),  # personnes pauvres, écart de 6,5 %
        ("egal", "200", "475", "FAUX"),  # part de l'État dans la hausse de la dette
        ("egal", "60", "33", "FAUX"),  # écart d'inflation avec l'Allemagne
        # Cas limites
        ("egal", "7.5", "7.4", "IMPRECIS"),  # 1,35 % d'écart
        ("egal", "4", "4.5", "FAUX"),  # « 4 % » quand c'est 4,5 : l'arrondi donne 5
        ("environ", "600", "590", "IMPRECIS"),  # « environ » ne donne pas de marge
        ("plus_de", "2", "2", "IMPRECIS"),  # « plus de 2 » quand c'est exactement 2
        ("plus_de", "2", "1.5", "FAUX"),
        ("moins_de", "10", "9.9", "VRAI"),
        ("moins_de", "10", "10.1", "IMPRECIS"),
    ],
)
def test_verdicts(qualifier: str, value: str, official: str, expected: str) -> None:
    assert verdict(qualifier, value, official) == expected


@pytest.mark.parametrize(
    ("official", "expected"),
    [("60", "VRAI"), ("62", "VRAI"), ("61", "VRAI"), ("62.5", "IMPRECIS"), ("70", "FAUX")],
)
def test_fourchette(official: str, expected: str) -> None:
    assert verdict("entre", "60", official, upper="62") == expected


def test_l_ecart_se_mesure_a_la_borne_la_plus_proche() -> None:
    assert relative_gap(annonce("entre", "60", "62"), Decimal("64")) == Decimal(2) / Decimal(64)
    assert relative_gap(annonce("entre", "60", "62"), Decimal("50")) == Decimal(10) / Decimal(50)


def test_valeur_officielle_nulle() -> None:
    assert verdict("egal", "0", "0") == "VRAI"
    assert verdict("egal", "0.1", "0") == "FAUX"


def test_seuil_nul_supprime_imprecis() -> None:
    assert numeric_verdict(annonce("egal", "7.5"), Decimal("7.4"), Decimal(0)) == "FAUX"


def test_le_seuil_du_projet_est_lu_dans_la_config() -> None:
    assert load_threshold() == SEUIL


@pytest.mark.parametrize("raw", ['"2 %"', "1.5", "-0.1", "true"])
def test_un_seuil_invalide_est_refuse(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "tolerances.toml"
    path.write_text(f"seuil_imprecis = {raw}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="seuil_imprecis"):
        load_threshold(path)
