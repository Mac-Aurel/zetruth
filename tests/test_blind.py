import csv
from pathlib import Path

import pytest

from zetruth.reference.blind import (
    EXPORT_COLUMNS,
    REVIEW_FILE,
    blind_row,
    cohen_kappa,
    main,
    measure,
    sample,
)

REFERENCE = [
    {"id": f"a{i}", "type": "factuelle", "verdict": verdict}
    for i, verdict in enumerate(["VRAI", "VRAI", "FAUX", "FAUX", "TROMPEUR"])
] + [{"id": "p", "type": "promesse", "verdict": "NON_FACTUEL"}]


def test_echantillon_reproductible_sans_promesses() -> None:
    first = sample(REFERENCE, 3, seed=1)

    assert first == sample(REFERENCE, 3, seed=1)
    assert all(r["type"] == "factuelle" for r in first)
    assert len(sample(REFERENCE, 50, seed=1)) == 5


def test_le_relecteur_ne_voit_ni_verdict_ni_commentaire() -> None:
    row = {
        "id": "x",
        "locuteur": "X",
        "citation": "c",
        "indicateur": "dette",
        "qualificatif": "egal",
        "valeur": "600",
        "valeur_max": "",
        "unite": "milliards d'euros",
        "periode": "2017-2021",
        "perimetre": "France",
        "valeur_officielle": "571",
        "source_reference": "série",
        "source_url": "https://insee.fr/x",
        "verdict": "FAUX",
        "commentaire": "secret",
        "eclairage": "secret",
    }

    blind = blind_row(row)

    assert list(blind) == EXPORT_COLUMNS
    assert "secret" not in blind.values()
    assert "FAUX" not in blind.values()
    assert blind["ce_qui_est_affirme"] == (
        "dette, 600 milliards d'euros, période 2017-2021, périmètre France"
    )


def test_kappa() -> None:
    assert cohen_kappa([("VRAI", "VRAI"), ("FAUX", "FAUX")]) == 1.0
    assert cohen_kappa([("VRAI", "FAUX"), ("FAUX", "VRAI")]) == -1.0
    assert cohen_kappa([("VRAI", "VRAI"), ("VRAI", "VRAI")]) == 1.0
    assert cohen_kappa([]) == 0.0
    assert round(cohen_kappa([("VRAI", "VRAI"), ("VRAI", "FAUX"), ("FAUX", "FAUX")]), 2) == 0.4


def test_mesure_de_l_accord() -> None:
    review = [
        {"id": "a0", "verdict_relecteur": "vrai"},
        {"id": "a2", "verdict_relecteur": "IMPRECIS"},
        {"id": "a4", "verdict_relecteur": ""},
    ]

    result = measure(REFERENCE, review)

    assert (result.compared, result.agreed, result.rate) == (2, 1, 0.5)
    assert result.disagreements == [("a2", "FAUX", "IMPRECIS")]


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({"id": "a0", "verdict_relecteur": "PLUTOT VRAI"}, "verdict inconnu"),
        ({"id": "zz", "verdict_relecteur": "VRAI"}, "absent du jeu de référence"),
    ],
)
def test_relecture_invalide(row: dict[str, str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        measure(REFERENCE, [row])


def test_l_export_n_ecrase_pas_une_relecture(tmp_path: Path) -> None:
    existing = tmp_path / "relecture.csv"
    existing.write_text("déjà rempli", encoding="utf-8")

    assert main(["exporter", "--sortie", str(existing)]) == 1
    assert existing.read_text(encoding="utf-8") == "déjà rempli"


def test_le_fichier_de_relecture_du_depot_est_a_l_aveugle() -> None:
    with REVIEW_FILE.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == EXPORT_COLUMNS
        assert len(list(reader)) == 10
