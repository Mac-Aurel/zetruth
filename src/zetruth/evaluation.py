"""Évaluation de bout en bout du pipeline sur le jeu de référence.

    uv run python -m zetruth.evaluation [--journal]

Avec --journal, chaque phrase vérifiée est enregistrée dans le journal d'audit
(data/audit/journal.jsonl) et peut être rejouée : python -m zetruth.audit rejouer

Pour chaque affirmation factuelle annotée d'un débat décrit dans
data/reference/debats.toml, on fait tourner le pipeline sur la phrase et on
compare son verdict à celui de l'annotation.

Résultats possibles, du meilleur au pire :
- juste : même verdict (pour un TROMPEUR annoté, VRAI marqué à revoir compte
  comme juste : la règle ne tranche jamais TROMPEUR seule) ;
- abstention : pas de verdict, avec la raison ;
- faux signalé : verdict différent, mais marqué à revoir, un humain le verra ;
- faux non signalé : verdict différent sans alerte. C'est l'erreur à éviter
  à tout prix : elle doit rester à zéro.
"""

import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from zetruth.audit import AuditLog, verify_and_record
from zetruth.corpus.fredsum import TRANSCRIPTS_DIR, Turn, load_turns
from zetruth.detection.sentences import split_sentences
from zetruth.indicators.__main__ import default_clients
from zetruth.indicators.catalog import load_catalog
from zetruth.indicators.values import IndicatorService
from zetruth.model import Utterance, VerdictLabel
from zetruth.normalization.countries import Country, load_countries
from zetruth.normalization.normalize import Debate, debate_for, load_debates
from zetruth.pipeline import Outcome, verify_sentence
from zetruth.reference.annotations import ANNOTATIONS_FILE, read_annotations
from zetruth.sources.client import SourceClient
from zetruth.sources.registry import load_registry
from zetruth.verdicts.tolerance import load_threshold

CONTEXT_TURNS = 2


class Result(StrEnum):
    JUSTE = "juste"
    ABSTENTION = "abstention"
    FAUX_SIGNALE = "faux signalé"
    FAUX_NON_SIGNALE = "faux non signalé"


@dataclass(frozen=True)
class Evaluated:
    annotation_id: str
    debate: str
    expected: str
    result: Result
    detail: str


def classify(expected: str, outcome: Outcome | None) -> tuple[Result, str]:
    if outcome is None:
        return (
            Result.JUSTE if expected == VerdictLabel.INVERIFIABLE else Result.ABSTENTION,
            "phrase non retenue ou valeur non trouvée",
        )
    verdict = outcome.verdict
    if verdict is None:
        result = Result.JUSTE if expected == VerdictLabel.INVERIFIABLE else Result.ABSTENTION
        return result, outcome.reason or ""
    got = verdict.label
    detail = f"{got} ({verdict.claim.indicator}, {verdict.claim.period})"
    if got == expected:
        return Result.JUSTE, detail
    if expected == VerdictLabel.TROMPEUR and got == VerdictLabel.VRAI and verdict.needs_review:
        return Result.JUSTE, detail + ", à revoir"
    if got == VerdictLabel.INVERIFIABLE:
        return Result.ABSTENTION, detail
    return (Result.FAUX_SIGNALE if verdict.needs_review else Result.FAUX_NON_SIGNALE), detail


def _matching(outcomes: Sequence[Outcome], value: str) -> Outcome | None:
    try:
        expected = Decimal(value)
    except InvalidOperation:
        return None
    return next((o for o in outcomes if o.mention.value == expected), None)


def evaluate(
    annotations: Sequence[Mapping[str, str]],
    turns_by_file: Mapping[str, Sequence[Turn]],
    debates: Mapping[str, Debate],
    service: IndicatorService,
    threshold: Decimal,
    countries: Mapping[str, Country] | None = None,
    journal: AuditLog | None = None,
    clients: Mapping[str, SourceClient] | None = None,
) -> list[Evaluated]:
    """Avec un journal, chaque phrase vérifiée y est enregistrée pour pouvoir la rejouer."""
    evaluated = []
    for row in annotations:
        debate = debate_for(row["fichier"], debates)
        turns = turns_by_file.get(row["fichier"])
        if row["type"] != "factuelle" or debate is None or turns is None:
            continue
        index = int(row["tour"])
        sentence = next(
            (s for s in split_sentences(turns[index].text) if row["citation"] in s), None
        )
        if sentence is None:
            continue
        before = turns[index].text.split(sentence, 1)[0]  # début du tour, avant la phrase
        previous = " ".join(t.text for t in turns[max(0, index - CONTEXT_TURNS) : index])
        context = f"{previous} {before}".strip()
        utterance = Utterance(
            source_file=row["fichier"], turn=index, speaker=row["locuteur"], quote=sentence
        )
        if journal is not None and clients is not None:
            outcomes, record = verify_and_record(
                utterance, debate, service, clients, threshold, context, countries
            )
            journal.append(record)
        else:
            outcomes = verify_sentence(utterance, debate, service, threshold, context, countries)
        result, detail = classify(row["verdict"], _matching(outcomes, row["valeur"]))
        evaluated.append(Evaluated(row["id"], debate.name, row["verdict"], result, detail))
    return evaluated


def main() -> int:
    annotations = read_annotations(ANNOTATIONS_FILE)
    files = {a["fichier"] for a in annotations}
    turns = {f: load_turns(TRANSCRIPTS_DIR / f) for f in files if (TRANSCRIPTS_DIR / f).exists()}
    if not turns:
        print("Transcriptions absentes : uv run python -m zetruth.corpus.fredsum", file=sys.stderr)
        return 1
    clients = default_clients()
    service = IndicatorService(load_catalog(load_registry()), clients)
    journal = AuditLog() if "--journal" in sys.argv[1:] else None
    evaluated = evaluate(
        annotations,
        turns,
        load_debates(),
        service,
        load_threshold(),
        load_countries(),
        journal,
        clients,
    )
    if journal is not None:
        print(f"verdicts enregistrés dans {journal.path}")

    for e in evaluated:
        print(f"{e.annotation_id:12} attendu {e.expected:12} {e.result:17} {e.detail}")
    for debate in sorted({e.debate for e in evaluated}):
        subset = [e for e in evaluated if e.debate == debate]
        counts = Counter(e.result for e in subset)
        print(f"\n{debate} : {len(subset)} affirmations")
        for result in Result:
            print(f"  {result:17} {counts[result]}")
    wrong = sum(e.result is Result.FAUX_NON_SIGNALE for e in evaluated)
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
