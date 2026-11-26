"""Comparaison déterministe d'une affirmation normalisée aux valeurs officielles.

Aucun modèle de langage ici : le verdict découle de règles fixes.

1. Ce qui n'est pas factuel est NON_FACTUEL.
2. Sans valeur officielle, INVERIFIABLE.
3. Si l'unité, la période ou le périmètre (quand les deux sont connus) de
   l'affirmation ne correspondent pas à ceux de la valeur officielle
   principale (la première), on ne compare pas : INVERIFIABLE, avec la
   raison. Comparer des choses différentes donnerait un verdict faux avec
   une apparence de rigueur.
4. Sinon, la règle de config/tolerances.toml donne VRAI, IMPRECIS ou FAUX.
5. Si d'autres valeurs officielles mesurent la même chose (autre scénario,
   autre définition), chacune est une lecture possible et reçoit son propre
   verdict. Si toutes les lectures donnent le même verdict, il est net. Si
   elles divergent, le verdict est marqué à revoir et la divergence est
   écrite : un humain juge si l'intervenant a présenté une valeur comme la
   seule (TROMPEUR).

La valeur officielle doit déjà être la grandeur annoncée : pour « une baisse
de 2 points », c'est la baisse calculée, pas le niveau du chômage.
"""

from collections.abc import Sequence
from decimal import Decimal

from zetruth.model import (
    Claim,
    ClaimType,
    Confidence,
    OfficialValue,
    Reading,
    Verdict,
    VerdictLabel,
)
from zetruth.verdicts.tolerance import numeric_verdict


def _same(a: str | None, b: str | None) -> bool:
    def norm(text: str | None) -> str:
        return " ".join((text or "").casefold().split())

    return norm(a) == norm(b)


def _mismatches(claim: Claim, official: OfficialValue) -> list[str]:
    reasons = []
    if not _same(claim.unit, official.unit):
        reasons.append(f"unité annoncée {claim.unit!r}, unité officielle {official.unit!r}")
    if not _same(claim.period, official.period):
        reasons.append(f"période annoncée {claim.period!r}, période officielle {official.period!r}")
    # Un périmètre non précisé d'un côté ne bloque pas : on ne compare que s'ils sont connus.
    if claim.scope and official.scope and not _same(claim.scope, official.scope):
        reasons.append(f"périmètre annoncé {claim.scope!r}, périmètre officiel {official.scope!r}")
    return reasons


def _alternatives(primary: OfficialValue, others: Sequence[OfficialValue]) -> list[OfficialValue]:
    """Autres valeurs officielles qui mesurent la même chose (même unité, période, périmètre)."""
    return [
        other
        for other in others
        if _same(other.unit, primary.unit)
        and _same(other.period, primary.period)
        and _same(other.scope, primary.scope)
    ]


def compare(claim: Claim, official_values: Sequence[OfficialValue], threshold: Decimal) -> Verdict:
    if claim.type is not ClaimType.FACTUELLE:
        return Verdict(claim=claim, label=VerdictLabel.NON_FACTUEL, confidence=Confidence.HAUTE)

    values = tuple(official_values)
    if not values:
        return Verdict(
            claim=claim,
            label=VerdictLabel.INVERIFIABLE,
            confidence=Confidence.FAIBLE,
            limits="aucune valeur officielle trouvée dans les sources de la liste blanche",
        )

    primary = values[0]
    reasons = _mismatches(claim, primary)
    if reasons:
        return Verdict(
            claim=claim,
            label=VerdictLabel.INVERIFIABLE,
            official_values=values,
            confidence=Confidence.FAIBLE,
            limits="comparaison impossible : " + " ; ".join(reasons),
        )

    claimed = claim.claimed
    assert claimed is not None  # garanti par le modèle pour une affirmation factuelle
    readings = tuple(
        Reading(
            reference=v.reference,
            value=v.value,
            label=numeric_verdict(claimed, v.value, threshold),
        )
        for v in (primary, *_alternatives(primary, values[1:]))
    )
    divergent = len({r.label for r in readings}) > 1

    limits = []
    if not all(v.known_at_debate for v in values):
        limits.append("au moins une valeur a pu être révisée depuis le débat")
    if divergent:
        listed = ", ".join(f"{r.label} avec {r.reference} ({r.value})" for r in readings)
        limits.append(
            f"le verdict dépend de la définition ou du scénario retenu : {listed}. Vérifier si "
            "l'intervenant présente sa valeur comme la seule (TROMPEUR)"
        )
    elif len(readings) > 1:
        listed = ", ".join(f"{r.reference} ({r.value})" for r in readings[1:])
        limits.append(f"même verdict avec les autres définitions officielles : {listed}")

    return Verdict(
        claim=claim,
        label=readings[0].label,
        official_values=values,
        gap=claimed.value - primary.value,
        confidence=Confidence.HAUTE
        if all(v.known_at_debate for v in values)
        else Confidence.MOYENNE,
        limits=" ; ".join(limits) or None,
        needs_review=divergent,
        readings=readings,
    )
