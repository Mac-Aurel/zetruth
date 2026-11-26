"""Valeurs chiffrées d'une phrase, avec leur unité, leur qualificatif et leur sens.

« en baissant de plus de 2 points le chômage » donne : plus_de 2 points, en
baisse. « passé de 9,6 à 7,4 % » donne deux niveaux, 9,6 % au départ et
7,4 % à l'arrivée. « à peu près quatre à quatre et demi pour cent » donne
une fourchette. Un nombre sans unité reconnue (une année, un âge) est ignoré.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from zetruth.model import Qualifier
from zetruth.normalization.numbers import NumberMatch, find_numbers


class Direction(StrEnum):
    NIVEAU = "niveau"
    HAUSSE = "hausse"
    BAISSE = "baisse"


class Role(StrEnum):
    SEUL = "seul"
    DEPART = "depart"  # « passé de X... »
    ARRIVEE = "arrivee"  # « ...à Y »


@dataclass(frozen=True)
class Mention:
    qualifier: Qualifier
    value: Decimal
    upper: Decimal | None
    unit: str
    direction: Direction
    role: Role
    start: int
    end: int


_PERCENT = re.compile(r"^\s*(?:%|pour ?cents?\b|pourcents?\b)", re.IGNORECASE)
_POINTS = re.compile(r"^\s*points?\b", re.IGNORECASE)
_EUROS = re.compile(r"^\s*(?:d['’]\s*euros|euros|€)", re.IGNORECASE)
_TIMES = re.compile(r"^\s*fois\b", re.IGNORECASE)

_QUALIFIERS = [
    (re.compile(r"(?:un peu |bien )?plus de\s*$|au[- ]delà de\s*$", re.I), Qualifier.PLUS_DE),
    (re.compile(r"moins de\s*$", re.I), Qualifier.MOINS_DE),
    (
        re.compile(
            r"(?:environ|à peu près|près de|quasiment|presque|autour de|grosso modo|"
            r"de l['’]ordre de)\s*$",
            re.I,
        ),
        Qualifier.ENVIRON,
    ),
]
_DECREASE = re.compile(r"baiss|diminu|recul|réduit|réduction", re.IGNORECASE)
_INCREASE = re.compile(r"augment|hausse|supplémentaire|rallong|créé|en plus\b", re.IGNORECASE)
_RANGE_LINK = re.compile(r"^\s*(?:à|et)\s*$", re.IGNORECASE)


def _unit(match: NumberMatch, after: str) -> str | None:
    if match.scale is not None:
        if match.scale == "milliards":
            return "milliards d'euros"
        return "millions d'euros" if _EUROS.match(after) else "millions"
    if _PERCENT.match(after):
        return "%"
    if _POINTS.match(after):
        return "points"
    if _EUROS.match(after):
        return "euros"
    if _TIMES.match(after):
        return "fois"
    return None


def _qualifier(before: str) -> Qualifier:
    for pattern, qualifier in _QUALIFIERS:
        if pattern.search(before):
            return qualifier
    return Qualifier.EGAL


def _direction(sentence: str, start: int, previous_end: int = 0) -> Direction:
    """Sens de la valeur, d'après les mots qui la précèdent jusqu'au nombre précédent."""
    window = sentence[max(previous_end, start - 60) : start]
    if _DECREASE.search(window):
        return Direction.BAISSE
    if _INCREASE.search(window):
        return Direction.HAUSSE
    return Direction.NIVEAU


def find_mentions(sentence: str) -> list[Mention]:
    numbers = find_numbers(sentence)
    mentions: list[Mention] = []
    i = 0
    while i < len(numbers):
        current = numbers[i]
        previous_end = numbers[i - 1].end if i > 0 else 0
        nxt = numbers[i + 1] if i + 1 < len(numbers) else None
        unit = _unit(current, sentence[current.end :])
        link = sentence[current.end : nxt.start] if nxt else ""

        # Deux nombres reliés par « à » ou « et », l'unité n'étant donnée qu'au second.
        if nxt is not None and unit is None and _RANGE_LINK.match(link):
            shared = _unit(nxt, sentence[nxt.end :])
            if shared is not None:
                before = sentence[: current.start].rstrip().lower()
                if before.endswith(("passé de", "passée de", "est de")) or before.endswith(" de"):
                    for number, role in ((current, Role.DEPART), (nxt, Role.ARRIVEE)):
                        mentions.append(
                            Mention(
                                Qualifier.EGAL, number.value, None, shared, Direction.NIVEAU,
                                role, number.start, number.end,
                            )
                        )  # fmt: skip
                else:
                    low, high = sorted((current.value, nxt.value))
                    mentions.append(
                        Mention(
                            Qualifier.ENTRE, low, high, shared,
                            _direction(sentence, current.start, previous_end),
                            Role.SEUL, current.start, nxt.end,
                        )
                    )  # fmt: skip
                i += 2
                continue

        if unit is not None:
            mentions.append(
                Mention(
                    _qualifier(sentence[: current.start]), current.value, None, unit,
                    _direction(sentence, current.start, previous_end),
                    Role.SEUL, current.start, current.end,
                )
            )  # fmt: skip
        i += 1
    return mentions
