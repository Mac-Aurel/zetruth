"""Validation du fichier d'affirmations annotées (jeu de référence).

Le format est décrit dans data/reference/README.md.
"""

import csv
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from zetruth.corpus.fredsum import TRANSCRIPTS_DIR, Turn, load_turns
from zetruth.model import (
    Claim,
    ClaimedValue,
    ClaimType,
    Qualifier,
    Utterance,
    ValueNature,
    VerdictLabel,
)
from zetruth.sources.registry import Registry, UnknownSourceError, load_registry

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
    "qualificatif",
    "valeur",
    "valeur_max",
    "unite",
    "periode",
    "perimetre",
    "nature_valeur",
    "verdict",
    "valeur_officielle",
    "source_organisme",
    "source_reference",
    "source_url",
    "sources_complementaires",
    "date_publication",
    "date_consultation",
    "valeur_du_debat",
    "commentaire",
]

ALWAYS_REQUIRED = ["id", "fichier", "tour", "locuteur", "citation", "type", "verdict"]
REQUIRED_IF_FACTUAL = ["indicateur", "qualificatif", "valeur", "periode"]
REQUIRED_IF_SOURCED = [
    "nature_valeur",
    "valeur_officielle",
    "source_organisme",
    "source_reference",
    "source_url",
    "date_consultation",
    "valeur_du_debat",
]
DATE_COLUMNS = ["date_publication", "date_consultation"]
YES_NO = {"oui", "non"}

Row = Mapping[str, str]
TurnsByFile = Mapping[str, Sequence[Turn]]


def _get(row: Row, column: str) -> str:
    return row.get(column, "").strip()


def _missing(row: Row, columns: list[str]) -> list[str]:
    return [c for c in columns if not _get(row, c)]


def _first_error(error: ValidationError) -> str:
    return str(error.errors()[0]["msg"]).removeprefix("Value error, ")


def to_claim(row: Row) -> Claim:
    """Affirmation normalisée telle qu'annotée, pour la comparer à celle du pipeline."""
    claimed = None
    if _get(row, "valeur"):
        claimed = ClaimedValue.model_validate(
            {
                "qualifier": _get(row, "qualificatif"),
                "value": _get(row, "valeur"),
                "upper": _get(row, "valeur_max") or None,
            }
        )
    return Claim(
        utterance=Utterance(
            source_file=_get(row, "fichier"),
            turn=int(_get(row, "tour")),
            speaker=_get(row, "locuteur"),
            quote=_get(row, "citation"),
        ),
        type=ClaimType(_get(row, "type")),
        subject=_get(row, "sujet") or None,
        indicator=_get(row, "indicateur") or None,
        claimed=claimed,
        unit=_get(row, "unite") or None,
        period=_get(row, "periode") or None,
        scope=_get(row, "perimetre") or None,
    )


def _check_claim(row: Row) -> list[str]:
    kind, verdict = _get(row, "type"), _get(row, "verdict")
    if kind not in set(ClaimType):
        return [f"type inconnu {kind!r}, attendu parmi {sorted(ClaimType)}"]
    if verdict not in set(VerdictLabel):
        return [f"verdict inconnu {verdict!r}, attendu parmi {sorted(VerdictLabel)}"]
    if kind != ClaimType.FACTUELLE:
        if verdict != VerdictLabel.NON_FACTUEL:
            return [f"une affirmation de type {kind} doit avoir le verdict NON_FACTUEL"]
        return []
    if verdict == VerdictLabel.NON_FACTUEL:
        return ["une affirmation factuelle ne peut pas être NON_FACTUEL"]

    errors = [f"champ obligatoire vide : {c}" for c in _missing(row, REQUIRED_IF_FACTUAL)]
    if verdict != VerdictLabel.INVERIFIABLE:
        errors += [
            f"champ obligatoire vide (verdict sourcé) : {c}"
            for c in _missing(row, REQUIRED_IF_SOURCED)
        ]
    if errors:
        return errors

    if _get(row, "qualificatif") not in set(Qualifier):
        return [f"qualificatif inconnu, attendu parmi {sorted(Qualifier)}"]
    try:
        to_claim(row)
    except ValidationError as e:
        errors.append(f"valeur annoncée invalide : {_first_error(e)}")
    nature = _get(row, "nature_valeur")
    if nature and nature not in set(ValueNature):
        errors.append(f"nature_valeur inconnue, attendu parmi {sorted(ValueNature)}")
    at_debate = _get(row, "valeur_du_debat")
    if at_debate and at_debate not in YES_NO:
        errors.append("valeur_du_debat doit valoir oui ou non")
    return errors


def _check_dates(row: Row) -> list[str]:
    errors = []
    for column in DATE_COLUMNS:
        value = _get(row, column)
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


def _check_source(row: Row, registry: Registry) -> list[str]:
    source_id, url = _get(row, "source_organisme"), _get(row, "source_url")
    errors = []
    if source_id:
        try:
            source = registry.get(source_id)
            if url and not source.covers(url):
                errors.append(f"source_url n'appartient pas à la source {source_id}")
        except (UnknownSourceError, ValueError) as e:
            errors.append(str(e))
    for extra_url in _get(row, "sources_complementaires").split():
        try:
            registry.for_url(extra_url)
        except (UnknownSourceError, ValueError) as e:
            errors.append(f"sources_complementaires : {e}")
    return errors


def validate_row(
    row: Row,
    turns_by_file: TurnsByFile | None = None,
    registry: Registry | None = None,
) -> list[str]:
    missing = _missing(row, ALWAYS_REQUIRED)
    if missing:
        return [f"champ obligatoire vide : {c}" for c in missing]
    if not row["tour"].isdigit():
        return [f"tour doit être un entier positif, reçu {row['tour']!r}"]

    errors = _check_claim(row) + _check_dates(row)
    if turns_by_file is not None:
        errors += _check_against_transcript(row, turns_by_file)
    if registry is not None:
        errors += _check_source(row, registry)
    return errors


def validate_rows(
    rows: Sequence[Row],
    turns_by_file: TurnsByFile | None = None,
    registry: Registry | None = None,
) -> list[str]:
    """Renvoie la liste des erreurs, vide si le fichier est valide."""
    errors = []
    seen_ids: set[str] = set()
    for line, row in enumerate(rows, start=2):  # ligne 1 = en-tête
        row_id = row.get("id", "")
        if row_id in seen_ids:
            errors.append(f"ligne {line} : id {row_id!r} en double")
        seen_ids.add(row_id)
        errors += [f"ligne {line} : {e}" for e in validate_row(row, turns_by_file, registry)]
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

    errors = validate_rows(rows, turns, load_registry())
    for error in errors:
        print(error)
    print(f"{len(rows)} affirmations, {len(errors)} erreurs")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
