"""Validation du fichier d'affirmations annotées (jeu de référence).

Le format est décrit dans data/reference/README.md.
"""

import csv
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from zetruth.corpus.fredsum import TRANSCRIPTS_DIR, Turn, load_turns

ANNOTATIONS_FILE = Path("data/reference/affirmations.csv")

COLUMNS = [
    "id",
    "fichier",
    "tour",
    "locuteur",
    "citation",
    "type",
    "sujet",
    "indicateur",
    "valeur",
    "unite",
    "periode",
    "perimetre",
    "verdict",
    "valeur_officielle",
    "source_organisme",
    "source_reference",
    "source_url",
    "date_publication",
    "date_consultation",
    "commentaire",
]

TYPES = {"factuelle", "opinion", "promesse", "prediction"}
FACTUAL_VERDICTS = {"VRAI", "FAUX", "TROMPEUR", "IMPRECIS", "INVERIFIABLE"}
NON_FACTUAL_VERDICT = "NON_FACTUEL"

ALWAYS_REQUIRED = ["id", "fichier", "tour", "locuteur", "citation", "type", "verdict"]
REQUIRED_IF_FACTUAL = ["indicateur", "valeur", "periode"]
REQUIRED_IF_SOURCED = [
    "valeur_officielle",
    "source_organisme",
    "source_reference",
    "source_url",
    "date_consultation",
]
DATE_COLUMNS = ["date_publication", "date_consultation"]

Row = Mapping[str, str]
TurnsByFile = Mapping[str, Sequence[Turn]]


def _missing(row: Row, columns: list[str]) -> list[str]:
    return [c for c in columns if not row.get(c, "").strip()]


def _check_verdict(row: Row) -> list[str]:
    kind, verdict = row["type"], row["verdict"]
    if kind not in TYPES:
        return [f"type inconnu {kind!r}, attendu parmi {sorted(TYPES)}"]
    if kind != "factuelle":
        if verdict != NON_FACTUAL_VERDICT:
            return [f"une affirmation de type {kind} doit avoir le verdict {NON_FACTUAL_VERDICT}"]
        return []
    if verdict not in FACTUAL_VERDICTS:
        return [f"verdict {verdict!r} invalide pour une affirmation factuelle"]

    errors = [f"champ obligatoire vide : {c}" for c in _missing(row, REQUIRED_IF_FACTUAL)]
    if verdict != "INVERIFIABLE":
        errors += [
            f"champ obligatoire vide (verdict sourcé) : {c}"
            for c in _missing(row, REQUIRED_IF_SOURCED)
        ]
    return errors


def _check_dates(row: Row) -> list[str]:
    errors = []
    for column in DATE_COLUMNS:
        value = row.get(column, "").strip()
        if not value:
            continue
        try:
            date.fromisoformat(value)
        except ValueError:
            errors.append(f"{column} doit être au format AAAA-MM-JJ, reçu {value!r}")
    return errors


def _check_against_transcript(row: Row, turns_by_file: TurnsByFile) -> list[str]:
    turns = turns_by_file.get(row["fichier"])
    if turns is None:
        return [f"fichier inconnu ou non téléchargé : {row['fichier']}"]
    index = int(row["tour"])
    if index >= len(turns):
        return [f"tour {index} absent, le fichier en compte {len(turns)}"]
    turn = turns[index]
    errors = []
    if turn.speaker != row["locuteur"]:
        errors.append(f"locuteur {row['locuteur']!r} différent de celui du tour ({turn.speaker!r})")
    if row["citation"] not in turn.text:
        errors.append("la citation ne figure pas mot pour mot dans le tour")
    return errors


def validate_row(row: Row, turns_by_file: TurnsByFile | None = None) -> list[str]:
    missing = _missing(row, ALWAYS_REQUIRED)
    if missing:
        return [f"champ obligatoire vide : {c}" for c in missing]
    if not row["tour"].isdigit():
        return [f"tour doit être un entier positif, reçu {row['tour']!r}"]

    errors = _check_verdict(row) + _check_dates(row)
    if turns_by_file is not None:
        errors += _check_against_transcript(row, turns_by_file)
    return errors


def validate_rows(rows: Sequence[Row], turns_by_file: TurnsByFile | None = None) -> list[str]:
    """Renvoie la liste des erreurs, vide si le fichier est valide."""
    errors = []
    seen_ids: set[str] = set()
    for line, row in enumerate(rows, start=2):  # ligne 1 = en-tête
        row_id = row.get("id", "")
        if row_id in seen_ids:
            errors.append(f"ligne {line} : id {row_id!r} en double")
        seen_ids.add(row_id)
        errors += [f"ligne {line} : {e}" for e in validate_row(row, turns_by_file)]
    return errors


def read_annotations(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        if header != COLUMNS:
            raise ValueError(f"colonnes attendues : {COLUMNS}, trouvées : {header}")
        return list(reader)


def load_downloaded_turns(rows: Sequence[Row], transcripts_dir: Path) -> dict[str, list[Turn]]:
    files = {row["fichier"] for row in rows if row.get("fichier")}
    return {
        name: load_turns(transcripts_dir / name)
        for name in files
        if (transcripts_dir / name).exists()
    }


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ANNOTATIONS_FILE
    rows = read_annotations(path)
    turns: TurnsByFile | None = None
    if TRANSCRIPTS_DIR.exists():
        turns = load_downloaded_turns(rows, TRANSCRIPTS_DIR)
    else:
        print("Transcriptions absentes, les citations ne sont pas vérifiées.")

    errors = validate_rows(rows, turns)
    for error in errors:
        print(error)
    print(f"{len(rows)} affirmations, {len(errors)} erreurs")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
