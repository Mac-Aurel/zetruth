import csv
from pathlib import Path

REFERENCE = Path("data/reference")
CATEGORIES = {
    "statistique",
    "juridique",
    "evenement",
    "programme",
    "propos_rapportes",
    "causalite",
    "vague",
}


def _rows(name: str) -> list[dict[str, str]]:
    with (REFERENCE / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_chaque_phrase_verifiable_est_classee_une_fois() -> None:
    verifiables = [
        (r["fichier"], r["tour"], r["phrase"])
        for name in ("detection.csv", "detection_controle.csv")
        for r in _rows(name)
        if r["verifiable"] == "oui"
    ]
    classees = [(r["fichier"], r["tour"], r["phrase"]) for r in _rows("couverture.csv")]

    assert len(classees) == len(set(classees))
    assert set(classees) == set(verifiables)


def test_categories_et_valeurs_connues() -> None:
    for row in _rows("couverture.csv"):
        assert row["categorie"] in CATEGORIES, row
        assert row["chiffree"] in {"oui", "non"}, row
