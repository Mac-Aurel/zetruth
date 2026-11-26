"""Recherche par modèle de langage, en ligne de commande.

    uv run python -m zetruth.research verifier "phrase" --locuteur NOM --debat Macron_Lepen_2
    uv run python -m zetruth.research evaluer [--limite N]

Chaque affirmation coûte des appels payants (modèle et recherches web) :
l'évaluation complète du jeu de référence se lance en connaissance de cause.
"""

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from zetruth.model import VerdictLabel
from zetruth.normalization.normalize import Debate, debate_for, load_debates
from zetruth.reference.annotations import ANNOTATIONS_FILE, read_annotations
from zetruth.research.checks import Finding
from zetruth.research.search import Statement, research
from zetruth.sources.registry import load_registry
from zetruth.verdicts.tolerance import load_threshold


def show(finding: Finding) -> str:
    lines = [f"{finding.label}{'' if finding.shown else ' (rien à afficher)'}"]
    if finding.proposed_label and finding.proposed_label is not finding.label:
        lines.append(f"  proposé par le modèle : {finding.proposed_label}")
    lines += [f"  note : {n}" for n in finding.notes]
    if finding.explanation:
        lines.append(f"  explication : {finding.explanation}")
    lines += [f"  preuve ({e.source_id}) : {e.url}\n    « {e.excerpt} »" for e in finding.evidence]
    lines += [f"  écarté : {r}" for r in finding.rejected]
    lines.append(f"  modèle {finding.model}, trace {finding.trace_sha256[:12]}")
    return "\n".join(lines)


def _statement(quote: str, speaker: str, debate: Debate) -> Statement:
    return Statement(quote, speaker, debate.title, debate.held_on)


def evaluate(rows: Sequence[dict[str, str]], limit: int | None) -> int:
    registry, threshold, debates = load_registry(), load_threshold(), load_debates()
    factual = [r for r in rows if r["type"] == "factuelle" and debate_for(r["fichier"], debates)]
    counts: Counter[str] = Counter()
    for row in factual[:limit]:
        debate = debate_for(row["fichier"], debates)
        assert debate is not None
        finding = research(
            _statement(row["citation"], row["locuteur"], debate), registry, threshold
        )
        expected = VerdictLabel(row["verdict"])
        if not finding.shown:
            result = "abstention" if expected is not VerdictLabel.INVERIFIABLE else "juste"
        else:
            result = "juste" if finding.label is expected else "FAUX AFFICHÉ"
        counts[result] += 1
        print(f"{row['id']:14} attendu {expected:12} {result}")
        print(show(finding))
    total = sum(counts.values())
    print(f"\n{total} affirmations : " + ", ".join(f"{k} {v}" for k, v in counts.most_common()))
    return 1 if counts["FAUX AFFICHÉ"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m zetruth.research")
    sub = parser.add_subparsers(dest="commande", required=True)
    one = sub.add_parser("verifier")
    one.add_argument("phrase")
    one.add_argument("--locuteur", required=True)
    one.add_argument("--debat", required=True, help="nom du débat dans debats.toml")
    many = sub.add_parser("evaluer")
    many.add_argument("--limite", type=int)
    many.add_argument("--fichier", type=Path, default=ANNOTATIONS_FILE)
    args = parser.parse_args(argv)

    if args.commande == "evaluer":
        return evaluate(read_annotations(args.fichier), args.limite)
    debate = load_debates().get(args.debat)
    if debate is None:
        print(f"débat inconnu : {args.debat}", file=sys.stderr)
        return 2
    statement = _statement(args.phrase, args.locuteur, debate)
    print(show(research(statement, load_registry(), load_threshold())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
