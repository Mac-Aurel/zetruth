"""De la phrase prononcée au verdict, sans modèle de langage.

détection (zetruth.detection) -> valeurs chiffrées (normalization.mentions)
-> cible : indicateur et période (normalization.normalize)
-> valeurs officielles (indicators.values) -> comparaison (verdicts.compare)

Chaque valeur chiffrée d'une phrase retenue donne un résultat : un verdict,
ou la raison pour laquelle on n'en donne pas.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from zetruth.detection.rules import detect
from zetruth.indicators.values import IndicatorService
from zetruth.model import (
    Claim,
    ClaimedValue,
    ClaimType,
    OfficialValue,
    Utterance,
    Verdict,
    VerdictLabel,
)
from zetruth.normalization.countries import Country
from zetruth.normalization.mentions import Mention, Role, find_mentions
from zetruth.normalization.normalize import Debate, Target, target_for
from zetruth.verdicts.compare import compare

# Au-delà de cet écart relatif, un verdict FAUX est marqué à revoir : un écart
# aussi grand vient plus souvent d'une erreur de normalisation (mauvais
# indicateur, niveau au lieu d'une hausse) que d'une affirmation aussi fausse.
LARGE_GAP = Decimal("0.5")


@dataclass(frozen=True)
class Outcome:
    sentence: str
    mention: Mention
    verdict: Verdict | None
    reason: str | None = None  # pourquoi il n'y a pas de verdict


def _official_values(
    target: Target, period: str, debate: Debate, service: IndicatorService
) -> list[OfficialValue]:
    iid = target.indicator.id
    if target.evolution:
        assert target.start is not None
        change = service.change(iid, target.start, period, debate.held_on, target.decrease)
        return [change] if change else []
    if target.country is not None:
        # Les définitions concurrentes du catalogue sont françaises : pas pour un autre pays.
        value = service.value(iid, period, debate.held_on, filters={"geo": target.country.code})
        return [value] if value else []
    primary = service.value(iid, period, debate.held_on)
    if primary is None:
        return []
    others = (service.value(a, period, debate.held_on) for a in target.alternatives)
    return [primary, *(v for v in others if v is not None)]


def verify_mention(
    mention: Mention,
    utterance: Utterance,
    debate: Debate,
    service: IndicatorService,
    threshold: Decimal,
    context: str = "",
    left_from: int = 0,
    right_to: int | None = None,
    countries: Mapping[str, Country] | None = None,
) -> Outcome:
    sentence = utterance.quote
    target = target_for(
        mention, sentence, debate, service.catalog, context, left_from, right_to, countries
    )
    if isinstance(target, str):
        return Outcome(sentence, mention, None, target)

    country = target.country
    latest = service.latest_period(
        target.indicator.id,
        debate.held_on,
        filters={"geo": country.code} if country else None,
        euro_area=country.in_euro_area(debate.held_on) if country else False,
    )
    if latest is None:
        return Outcome(sentence, mention, None, "période publiée le jour du débat inconnue")
    last, certain = latest

    if target.evolution:
        period = f"{target.start}/{last}"
        unit = target.indicator.change_unit
        values = _official_values(target, last, debate, service)
    else:
        period = target.start or last
        unit = target.indicator.unit
        values = _official_values(target, period, debate, service)

    direction = "baisse de " if target.decrease else ("hausse de " if target.evolution else "")
    claim = Claim(
        utterance=utterance,
        type=ClaimType.FACTUELLE,
        indicator=direction + target.indicator.name,
        claimed=ClaimedValue(qualifier=mention.qualifier, value=mention.value, upper=mention.upper),
        unit=unit,
        period=period,
        scope=country.name if country else target.indicator.scope,
    )
    verdict = compare(claim, values, threshold)

    notes = [n for n in (target.note, None if certain else "période du débat estimée") if n]
    review = verdict.needs_review
    if verdict.label is VerdictLabel.FAUX and values and _large_gap(mention.value, values[0].value):
        notes.append("écart très grand : vérifier l'indicateur et la période retenus")
        review = True
    if notes:
        limits = "; ".join(filter(None, [verdict.limits, *notes]))
        verdict = verdict.model_copy(update={"limits": limits, "needs_review": review})
    return Outcome(sentence, mention, verdict)


def _large_gap(claimed: Decimal, official: Decimal) -> bool:
    if official == 0:
        return claimed != 0
    return abs(claimed - official) / abs(official) > LARGE_GAP


def verify_sentence(
    utterance: Utterance,
    debate: Debate,
    service: IndicatorService,
    threshold: Decimal,
    context: str = "",
    countries: Mapping[str, Country] | None = None,
) -> list[Outcome]:
    """Tous les résultats d'une phrase, vide si le détecteur ne la retient pas.

    `context` : ce qui a été dit juste avant, pour repérer par exemple qu'on
    parle d'une prévision.
    """
    if not detect(utterance.quote).check_worthy:
        return []
    mentions = find_mentions(utterance.quote)
    outcomes = []
    left_from = 0
    for i, mention in enumerate(mentions):
        # « passé de 9,6 à 7,4 % » : la valeur d'arrivée partage la proposition du départ.
        if mention.role is not Role.ARRIVEE:
            left_from = mentions[i - 1].end if i else 0
        right_to = mentions[i + 1].start if i + 1 < len(mentions) else None
        outcomes.append(
            verify_mention(
                mention,
                utterance,
                debate,
                service,
                threshold,
                context,
                left_from,
                right_to,
                countries,
            )
        )
    return outcomes
