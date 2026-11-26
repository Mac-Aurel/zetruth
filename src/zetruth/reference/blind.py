"""Relecture à l'aveugle du jeu de référence et mesure de l'accord.

Les verdicts du jeu de référence ont été établis par un seul annotateur. Pour
savoir s'ils sont fiables, un second relecteur juge un échantillon sans voir
les verdicts ni les commentaires, puis on mesure l'accord.

    uv run python -m zetruth.reference.blind exporter [--nombre 10] [--graine 2026]
    uv run python -m zetruth.reference.blind mesurer data/reference/relecture.csv

L'échantillon est tiré au hasard avec une graine fixe : celui qui a annoté ne
choisit pas ce qui sera relu.
"""

import argparse
import csv
import random
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from zetruth.reference.annotations import ANNOTATIONS_FILE, read_annotations
from zetruth.report import claimed_value

REVIEW_FILE = Path("data/reference/relecture.csv")
VERDICTS = ("VRAI", "FAUX", "TROMPEUR", "IMPRECIS", "INVERIFIABLE")
EXPORT_COLUMNS = [
    "id",
    "locuteur",
    "citation",
    "ce_qui_est_affirme",
    "valeur_officielle",
    "source",
    "lien",
    "verdict_relecteur",
    "commentaire_relecteur",
]

Row = Mapping[str, str]


def sample(rows: Sequence[Row], size: int, seed: int) -> list[Row]:
    """Échantillon des affirmations factuelles, tiré au hasard avec une graine fixe."""
    factual = [r for r in rows if r["type"] == "factuelle"]
    return random.Random(seed).sample(factual, min(size, len(factual)))


def blind_row(row: Row) -> dict[str, str]:
    """Ce que voit le relecteur : ni verdict, ni commentaire, ni éclairage."""
    return {
        "id": row["id"],
        "locuteur": row["locuteur"],
        "citation": row["citation"],
        "ce_qui_est_affirme": (
            f"{row['indicateur']}, {claimed_value(row)}, période {row['periode']}, "
            f"périmètre {row['perimetre'] or 'non précisé'}"
        ),
        "valeur_officielle": row["valeur_officielle"],
        "source": row["source_reference"],
        "lien": row["source_url"],
        "verdict_relecteur": "",
        "commentaire_relecteur": "",
    }


@dataclass(frozen=True)
class Agreement:
    compared: int
    agreed: int
    kappa: float
    disagreements: list[tuple[str, str, str]]  # id, verdict de référence, verdict du relecteur

    @property
    def rate(self) -> float:
        return self.agreed / self.compared if self.compared else 0.0


def cohen_kappa(pairs: Sequence[tuple[str, str]]) -> float:
    """Accord au-delà du hasard : 1 accord parfait, 0 pas mieux que le hasard."""
    n = len(pairs)
    if n == 0:
        return 0.0
    observed = sum(a == b for a, b in pairs) / n
    first, second = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(first[label] * second[label] for label in first) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def measure(reference: Sequence[Row], review: Sequence[Row]) -> Agreement:
    verdicts = {r["id"]: r["verdict"] for r in reference}
    pairs = []
    for row in review:
        given = row.get("verdict_relecteur", "").strip().upper()
        if not given:
            continue
        if given not in VERDICTS:
            raise ValueError(f"{row['id']} : verdict inconnu {given!r}, attendu parmi {VERDICTS}")
        if row["id"] not in verdicts:
            raise ValueError(f"{row['id']} : absent du jeu de référence")
        pairs.append((row["id"], verdicts[row["id"]], given))
    agreed = sum(ref == given for _, ref, given in pairs)
    kappa = cohen_kappa([(ref, given) for _, ref, given in pairs])
    disagreements = [p for p in pairs if p[1] != p[2]]
    return Agreement(len(pairs), agreed, kappa, disagreements)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Relecture à l'aveugle du jeu de référence.")
    commands = parser.add_subparsers(dest="commande", required=True)
    export = commands.add_parser("exporter", help="écrire le fichier à relire")
    export.add_argument("--nombre", type=int, default=10)
    export.add_argument("--graine", type=int, default=2026)
    export.add_argument("--sortie", type=Path, default=REVIEW_FILE)
    score = commands.add_parser("mesurer", help="mesurer l'accord avec le jeu de référence")
    score.add_argument("fichier", type=Path, nargs="?", default=REVIEW_FILE)
    args = parser.parse_args(argv)

    reference = read_annotations(ANNOTATIONS_FILE)
    if args.commande == "exporter":
        if args.sortie.exists():
            print(f"{args.sortie} existe déjà, on ne l'écrase pas", file=sys.stderr)
            return 1
        rows = [blind_row(r) for r in sample(reference, args.nombre, args.graine)]
        with args.sortie.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, EXPORT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"{len(rows)} affirmations à relire dans {args.sortie}")
        return 0

    with args.fichier.open(newline="", encoding="utf-8") as f:
        review = list(csv.DictReader(f))
    result = measure(reference, review)
    print(f"{result.compared} verdicts comparés, {result.agreed} identiques ({result.rate:.0%})")
    print(f"kappa de Cohen : {result.kappa:.2f}")
    for annotation_id, ref, given in result.disagreements:
        print(f"  désaccord {annotation_id} : référence {ref}, relecteur {given}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
