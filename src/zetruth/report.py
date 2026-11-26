"""Rapport de vérification d'un débat, à partir du jeu de référence.

    uv run python -m zetruth.report                  # tous les débats, dans rapports/
    uv run python -m zetruth.report Macron_Lepen_2   # un débat, sur la sortie standard

Rédaction sans modèle de langage : chaque phrase du rapport vient d'un champ
vérifié (valeur, source, date, commentaire). Rien n'est reformulé, donc rien
ne peut être inventé.
"""

import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path

from zetruth.normalization.normalize import Debate, debate_for, load_debates
from zetruth.reference.annotations import ANNOTATIONS_FILE, read_annotations
from zetruth.sources.registry import Registry, UnknownSourceError, load_registry

Row = Mapping[str, str]

VERDICT_LABELS = {
    "VRAI": "Vrai",
    "FAUX": "Faux",
    "TROMPEUR": "Trompeur",
    "IMPRECIS": "Imprécis",
    "INVERIFIABLE": "Invérifiable",
}
VERDICT_ORDER = list(VERDICT_LABELS)
QUALIFIERS = {
    "egal": "",
    "environ": "environ ",
    "plus_de": "plus de ",
    "moins_de": "moins de ",
}
MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)  # fmt: skip


def french_date(day: date | str) -> str:
    if isinstance(day, str):
        day = date.fromisoformat(day)
    first = "1er" if day.day == 1 else str(day.day)
    return f"{first} {MONTHS[day.month - 1]} {day.year}"


_LEADING_NUMBER = re.compile(r"^([+-]?)(\d+)(?:\.(\d+))?")


def french_number(value: str) -> str:
    """« 160000 » devient « 160 000 », « 4.5 » devient « 4,5 ». Seul le nombre en tête change."""

    def fmt(match: re.Match[str]) -> str:
        sign, integer, decimals = match.groups()
        grouped = f"{int(integer):,}".replace(",", " ") if len(integer) > 4 else integer
        return sign + grouped + (f",{decimals}" if decimals else "")

    return _LEADING_NUMBER.sub(fmt, value, count=1)


# Décimale dans un texte, hors liens (« 1.0/data » dans une URL reste tel quel).
_DECIMAL_IN_TEXT = re.compile(r"(?<![\w/.])(\d+)\.(\d+)(?![\w/])")


def french_text(text: str) -> str:
    return _DECIMAL_IN_TEXT.sub(r"\1,\2", text)


def claimed_value(row: Row) -> str:
    if row["qualificatif"] == "entre":
        amount = f"entre {french_number(row['valeur'])} et {french_number(row['valeur_max'])}"
    else:
        amount = QUALIFIERS.get(row["qualificatif"], "") + french_number(row["valeur"])
    return f"{amount} {row['unite']}".strip()


GAP_VERDICTS = {"VRAI", "IMPRECIS", "FAUX"}


def _number(text: str) -> Decimal | None:
    match = _LEADING_NUMBER.match(text.strip())
    return Decimal(match.group(0)) if match else None


def gap_sentence(row: Row) -> str | None:
    """L'écart réel, pour distinguer une approximation d'une invention.

    Le verdict suit la règle de tolérance ; cette phrase donne la mesure.
    """
    official = _number(row["valeur_officielle"])
    claimed = _number(row["valeur"])
    if row["verdict"] not in GAP_VERDICTS or official is None or claimed is None:
        return None
    shown = french_number(str(official))
    qualifier = row["qualificatif"]
    if qualifier in ("plus_de", "moins_de"):
        satisfied = official > claimed if qualifier == "plus_de" else official < claimed
        if official == claimed:
            side = "égale à"
        else:
            side = "au-dessus de" if official > claimed else "en dessous de"
        verb = "est bien" if satisfied else "est"
        bound = french_number(row["valeur"])
        return f"Écart : la valeur officielle ({shown}) {verb} {side} {bound}."
    if qualifier == "entre":
        upper = _number(row["valeur_max"])
        inside = upper is not None and claimed <= official <= upper
        where = "dans" if inside else "hors de"
        return f"Écart : la valeur officielle ({shown}) est {where} la fourchette annoncée."
    if official == 0:
        return None
    relative = (claimed - official) / abs(official) * 100
    if row["verdict"] == "VRAI":
        return f"Écart : conforme à l'arrondi près (valeur exacte {shown})."
    side = "au-dessus de" if relative > 0 else "en dessous de"
    amount = french_number(f"{abs(relative):.1f}")
    return f"Écart : la valeur annoncée est {amount} % {side} la valeur officielle."


def source_name(row: Row, registry: Registry) -> str:
    try:
        return registry.get(row["source_organisme"]).name
    except UnknownSourceError:
        return row["source_organisme"]


def _summary(rows: Sequence[Row]) -> list[str]:
    speakers = sorted({r["locuteur"] for r in rows})
    header = "| Intervenant | " + " | ".join(VERDICT_LABELS[v] for v in VERDICT_ORDER) + " |"
    lines = [header, "|---" * (len(VERDICT_ORDER) + 1) + "|"]
    for speaker in speakers:
        counts = Counter(r["verdict"] for r in rows if r["locuteur"] == speaker)
        cells = " | ".join(str(counts[v]) for v in VERDICT_ORDER)
        lines.append(f"| {speaker} | {cells} |")
    return lines


def _claim_section(row: Row, registry: Registry) -> list[str]:
    attribution = row.get("attribution") == "oui"
    lines = [
        f"### « {row['citation']} »",
        "",
        f"{row['locuteur']}, sur le thème : {row['sujet']}.",
        "",
        f"**Verdict : {VERDICT_LABELS[row['verdict']]}**",
        "",
        f"Ce qui est affirmé : {row['indicateur']}, {claimed_value(row)}, "
        f"période {row['periode']}, périmètre {row['perimetre'] or 'non précisé'}.",
    ]
    cited = row.get("source_citee", "").strip()
    if row["verdict"] == "INVERIFIABLE":
        lines += [
            "",
            "Aucune source officielle sur ce sujet ne permet de vérifier cette affirmation. "
            "En l'état, elle n'est pas établie et ne doit pas être tenue pour un fait.",
        ]
    citation = f"L'intervenant cite : {cited}." if cited else "L'intervenant ne cite aucune source."
    lines += ["", citation]
    if row["source_url"]:
        published = (
            f", publié le {french_date(row['date_publication'])}" if row["date_publication"] else ""
        )
        lines += [
            "",
            f"Ce que disent les sources : {french_text(french_number(row['valeur_officielle']))}.",
        ]
        if gap := gap_sentence(row):
            lines += ["", gap]
        lines += [
            "",
            f"Source : {source_name(row, registry)}, {row['source_reference']}{published}, "
            f"consulté le {french_date(row['date_consultation'])}.",
            f"Lien : {row['source_url']}",
        ]
        others = row.get("sources_complementaires", "").split()
        if others:
            lines.append("Autres liens : " + ", ".join(others))
    if attribution:
        lines += [
            "",
            "Le verdict porte sur ce que dit cette publication, pas sur le fait lui-même : "
            "un sondage mesure une opinion.",
        ]
    if row.get("nature_valeur") == "prevision":
        lines += ["", "La valeur officielle est une prévision, pas une donnée constatée."]
    if row.get("valeur_du_debat") == "non":
        lines += [
            "",
            "Attention : la valeur citée est la dernière publiée aujourd'hui. Celle connue le jour "
            "du débat a pu être légèrement différente.",
        ]
    if row["commentaire"]:
        lines += ["", f"Contexte : {french_text(row['commentaire'])}"]
    if row.get("eclairage"):
        lines += ["", f"Éclairage (pistes, pas des preuves) : {french_text(row['eclairage'])}"]
    return [*lines, ""]


def render(debate: Debate, rows: Sequence[Row], registry: Registry) -> str:
    factual = [r for r in rows if r["type"] == "factuelle"]
    others = [r for r in rows if r["type"] != "factuelle"]
    lines = [
        f"# {debate.title}, {french_date(debate.held_on)}",
        "",
        f"{len(factual)} affirmations factuelles vérifiées. Chaque verdict s'appuie sur une "
        "source officielle et sur la valeur connue le jour du débat. Une affirmation est vraie "
        "si la valeur officielle, arrondie à la précision avec laquelle elle a été énoncée, "
        "tombe juste ; imprécise jusqu'à 2 % d'écart ; fausse au-delà. Un chiffre exact présenté "
        "comme le seul alors que la source en donne plusieurs est trompeur. Une affirmation "
        "invérifiable n'est pas établie : aucune source officielle ne permet de la confirmer.",
        "",
        "## En résumé",
        "",
        *_summary(factual),
        "",
        "Ce tableau ne mesure pas l'honnêteté des intervenants : il ne porte que sur les "
        "affirmations retenues, qui ne sont pas un échantillon représentatif de tout le débat.",
        "",
        "## Les affirmations",
        "",
    ]
    for row in sorted(factual, key=lambda r: (r["fichier"], int(r["tour"]))):
        lines += _claim_section(row, registry)
    if others:
        lines += ["## Promesses et opinions repérées", "", "Elles ne se vérifient pas.", ""]
        lines += [f"- {r['locuteur']} : « {r['citation']} »" for r in others]
        lines.append("")
    return "\n".join(lines)


REPORTS_DIR = Path("rapports")


def report_for(name: str) -> str | None:
    """Rapport d'un débat du corpus, ou None s'il n'a aucune affirmation annotée."""
    debates = load_debates()
    debate = debates[name]
    rows = [
        r for r in read_annotations(ANNOTATIONS_FILE) if debate_for(r["fichier"], debates) == debate
    ]
    return render(debate, rows, load_registry()) if rows else None


def main(argv: list[str] | None = None) -> int:
    """Sans argument, écrit le rapport de chaque débat annoté dans rapports/."""
    args = sys.argv[1:] if argv is None else argv
    debates = load_debates()
    if args:
        if len(args) != 1 or args[0] not in debates:
            print(f"débat inconnu, attendu parmi {sorted(debates)}", file=sys.stderr)
            return 2
        report = report_for(args[0])
        if report is None:
            print(f"aucune affirmation annotée pour {args[0]}", file=sys.stderr)
            return 1
        print(report)
        return 0
    REPORTS_DIR.mkdir(exist_ok=True)
    for name in sorted(debates):
        report = report_for(name)
        if report is not None:
            (REPORTS_DIR / f"{name}.md").write_text(report, encoding="utf-8")
            print(f"rapports/{name}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
