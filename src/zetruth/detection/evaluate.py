"""Évaluation de la détection sur le jeu de détection étiqueté à la main.

    uv run python -m zetruth.detection.evaluate

Compare la méthode à base de règles à une référence triviale (« la phrase
contient un chiffre »), sur les phrases dont l'affirmation est chiffrée.
"""

import csv
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from zetruth.corpus.fredsum import TRANSCRIPTS_DIR, load_turns
from zetruth.detection.rules import detect, has_figure
from zetruth.detection.sentences import split_sentences
from zetruth.reference.annotations import ANNOTATIONS_FILE, read_annotations

DETECTION_FILE = Path("data/reference/detection.csv")
# Jeu de contrôle : jamais regardé pour écrire ou corriger les règles.
CONTROL_FILE = Path("data/reference/detection_controle.csv")


@dataclass(frozen=True)
class Scores:
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float:
        found = self.true_positives + self.false_positives
        return self.true_positives / found if found else 0.0

    @property
    def recall(self) -> float:
        expected = self.true_positives + self.false_negatives
        return self.true_positives / expected if expected else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def is_expected(row: dict[str, str]) -> bool:
    """Phrase attendue : affirmation vérifiable et chiffrée (périmètre de la V0)."""
    return row["verifiable"] == "oui" and row["chiffree"] == "oui"


def score(rows: Sequence[dict[str, str]], predict: Callable[[str], bool]) -> Scores:
    tp = fp = fn = 0
    for row in rows:
        expected, predicted = is_expected(row), predict(row["texte"])
        tp += expected and predicted
        fp += predicted and not expected
        fn += expected and not predicted
    return Scores(tp, fp, fn)


def reference_sentences(
    annotations: Sequence[dict[str, str]], turn_texts: dict[tuple[str, int], str]
) -> list[str]:
    """Phrases qui contiennent une affirmation factuelle du jeu de référence.

    Ce jeu vient d'autres débats que le jeu de détection : il sert de contrôle
    sur des phrases qui n'ont pas servi à écrire les règles.
    """
    sentences = []
    for row in annotations:
        if row["type"] != "factuelle":
            continue
        text = turn_texts.get((row["fichier"], int(row["tour"])), "")
        matching = [s for s in split_sentences(text) if row["citation"] in s]
        sentences.extend(matching[:1])
    return sentences


def read_rows(path: Path = DETECTION_FILE) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


METHODS: dict[str, Callable[[str], bool]] = {
    "référence (contient un chiffre)": has_figure,
    "règles": lambda sentence: detect(sentence).check_worthy,
}


def print_scores(title: str, rows: Sequence[dict[str, str]]) -> None:
    expected = sum(map(is_expected, rows))
    print(f"{title} : {len(rows)} phrases, {expected} affirmations chiffrées attendues")
    for name, predict in METHODS.items():
        s = score(rows, predict)
        metrics = f"précision {s.precision:.2f}  rappel {s.recall:.2f}  F1 {s.f1:.2f}"
        counts = f"{s.true_positives} justes, {s.false_positives} en trop"
        print(f"  {name:32} {metrics}  ({counts}, {s.false_negatives} manquées)")


def main() -> int:
    rows = read_rows()
    methods = METHODS
    print_scores("Jeu de détection (a servi à régler les règles)", rows)
    if CONTROL_FILE.exists():
        print_scores("Jeu de contrôle (jamais regardé)", read_rows(CONTROL_FILE))

    annotations = read_annotations(ANNOTATIONS_FILE)
    turn_texts = {
        (name, t.index): t.text
        for name in {a["fichier"] for a in annotations}
        if (TRANSCRIPTS_DIR / name).exists()
        for t in load_turns(TRANSCRIPTS_DIR / name)
    }
    held_out = reference_sentences(annotations, turn_texts)
    if held_out:
        print(f"\nContrôle sur un autre débat (rappel sur {len(held_out)} affirmations annotées) :")
        for name, predict in methods.items():
            found = sum(predict(sentence) for sentence in held_out)
            print(f"{name:34} rappel {found / len(held_out):.2f}  ({found} sur {len(held_out)})")
        for sentence in held_out:
            if not detect(sentence).check_worthy:
                print(f"  manquée | {sentence[:110]}")

    print("\nErreurs des règles sur le jeu de détection :")
    for row in rows:
        d = detect(row["texte"])
        expected = is_expected(row)
        if d.check_worthy != expected:
            kind = "manquée" if expected else f"en trop ({row['type']})"
            where = f"{row['fichier'][:20]} {row['tour']}.{row['phrase']}"
            print(f"  {kind} | {where} | {row['texte'][:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
