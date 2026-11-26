"""Normalisation : d'une valeur chiffrée d'une phrase à une affirmation comparable.

Choix de l'indicateur : mots-clés du catalogue, puis compatibilité de l'unité.
Choix de la période : la dernière publiée le jour du débat pour un niveau ;
pour une évolution, de la dernière période entièrement écoulée avant l'entrée
en fonction du sortant jusqu'à la dernière publiée.

Dans le doute, on ne normalise pas et on dit pourquoi : une mauvaise
normalisation donnerait un verdict faux avec une apparence de rigueur.
"""

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from zetruth.indicators.catalog import Indicator
from zetruth.normalization.countries import Country, find_country
from zetruth.normalization.mentions import Direction, Mention, Role
from zetruth.series.periods import last_period_before

DEBATES_FILE = Path("data/reference/debats.toml")

# Une prévision ou une période explicite (« 2022 », « deux mille quinze ») ne
# se compare pas à la dernière valeur publiée.
_FORECAST = re.compile(
    r"prévision|prévu|projection|banque de france|\bfmi\b|selon l['’]ocde", re.IGNORECASE
)
_EXPLICIT_PERIOD = re.compile(
    r"\b(?:19|20)\d{2}\b|\bdeux mille\b|\bjanvier|février|\bmars\b|avril|\bmai\b|juin|juillet|"
    r"août|septembre|octobre|novembre|décembre|trimestre",
    re.IGNORECASE,
)
# « quand vous avez été élu » : la valeur annoncée est celle du début du mandat.
_AT_START = re.compile(
    r"quand vous avez été élue?s?|à votre (?:arrivée|élection)|en début de quinquennat|"
    r"quand vous êtes arrivée?s?",
    re.IGNORECASE,
)
# Comparaison relative (« deux fois moins que l'Espagne », « 60 % de moins que
# l'Allemagne ») : il faudrait deux valeurs et un calcul, pas encore géré.
_RELATIVE = re.compile(
    r"fois (?:moins|plus)|de (?:moins|plus) que|par rapport (?:à|au|aux)|"
    r"\b(?:moins|plus) (?:d['’]\w+ |de \w+ |\w+ )?que (?:l['’]|la |le |les |nos )",
    re.IGNORECASE,
)
# Valeurs ailleurs dans le monde : seules les séries Eurostat se déclinent par pays.
_ELSEWHERE = re.compile(r"autour de nous|partout|nos voisins|dans le monde", re.IGNORECASE)


@dataclass(frozen=True)
class Debate:
    name: str
    held_on: date
    incumbent_since: date | None = None
    title: str = ""


@dataclass(frozen=True)
class Target:
    """Ce qu'il faut aller chercher dans les sources pour juger une valeur annoncée."""

    indicator: Indicator
    evolution: bool
    decrease: bool
    start: str | None  # pour une évolution, ou pour un niveau de départ
    note: str | None = None
    country: Country | None = None  # valeur d'un autre pays que la France


def load_debates(path: Path = DEBATES_FILE) -> dict[str, Debate]:
    with path.open("rb") as f:
        raw = tomllib.load(f).get("debats", {})
    return {
        name: Debate(
            name, values["date"], values.get("mandat_sortant_depuis"), values.get("titre", name)
        )
        for name, values in raw.items()
    }


def debate_for(file_name: str, debates: Mapping[str, Debate]) -> Debate | None:
    return debates.get(file_name.split("--", 1)[0])


def _unit_matches(claimed: str, indicator_unit: str) -> bool:
    return claimed == indicator_unit or (claimed == "%" and indicator_unit.startswith("%"))


def _score(indicator: Indicator, text: str) -> int:
    if any(e in text for e in indicator.exclusions):
        return 0
    return sum(len(k) for k in indicator.keywords if k in text)


def _best(mention: Mention, text: str, catalog: Mapping[str, Indicator]) -> Indicator | None:
    evolution = mention.direction is not Direction.NIVEAU
    best: Indicator | None = None
    best_score = 0
    for indicator in catalog.values():
        unit = indicator.change_unit if evolution else indicator.unit
        if not _unit_matches(mention.unit, unit):
            continue
        score = _score(indicator, text)
        if score > best_score:
            best, best_score = indicator, score
    return best


_CLAUSE_END = re.compile(r",|;|\bet\b|\bmais\b|\bdonc\b", re.IGNORECASE)


def clause(mention: Mention, sentence: str, left_from: int = 0, right_to: int | None = None) -> str:
    """La proposition de la valeur : depuis le dernier « et », virgule ou « mais »
    qui la précède, jusqu'au prochain qui la suit, sans dépasser les valeurs voisines."""
    left = sentence[left_from : mention.start]
    starts = list(_CLAUSE_END.finditer(left))
    if starts:
        left = left[starts[-1].end() :]
    right = sentence[mention.end : right_to]
    if end := _CLAUSE_END.search(right):
        right = right[: end.start()]
    return f"{left}{sentence[mention.start : mention.end]}{right}"


def match_indicator(
    mention: Mention,
    sentence: str,
    catalog: Mapping[str, Indicator],
    left_from: int = 0,
    right_to: int | None = None,
) -> Indicator | None:
    """L'indicateur le mieux désigné, parmi ceux dont l'unité convient.

    On ne regarde que la proposition de la valeur : les mots qui la précèdent
    depuis la valeur précédente (`left_from`), puis, à défaut, ceux qui la
    suivent jusqu'au prochain « et », virgule ou « mais » (sans dépasser la
    valeur suivante, `right_to`). Dans « la croissance est de 2,8 % et
    l'inflation de 4,4 % », 2,8 ne se rapporte pas à l'inflation. À score égal,
    le premier du catalogue l'emporte : les définitions concurrentes seront de
    toute façon récupérées et signalées.
    """
    left = sentence[left_from : mention.start].lower()
    right = sentence[mention.end : right_to].lower()
    if end := _CLAUSE_END.search(right):
        right = right[: end.start()]
    return _best(mention, left, catalog) or _best(mention, right, catalog)


# Pour retrouver le sujet d'une phrase qui ne le nomme pas (« C'est douze pour
# cent aux Pays-Bas »), on ne remonte pas plus loin que ces derniers caractères.
CONTEXT_FOR_TOPIC = 250


def target_for(
    mention: Mention,
    sentence: str,
    debate: Debate,
    catalog: Mapping[str, Indicator],
    context: str = "",
    left_from: int = 0,
    right_to: int | None = None,
    countries: Mapping[str, Country] | None = None,
) -> Target | str:
    """La cible à vérifier, ou la raison pour laquelle on ne normalise pas.

    `context` est ce qui a été dit juste avant : une prévision annoncée au tour
    précédent vaut pour la phrase, et le sujet de la phrase précédente peut
    servir quand la phrase ne le nomme pas.
    """
    own = clause(mention, sentence, left_from, right_to)
    if _FORECAST.search(f"{context} {sentence}"):
        return "prévision : pas comparable aux données publiées"
    if _EXPLICIT_PERIOD.search(own):
        return "période explicite dans la proposition, pas encore gérée"
    if _RELATIVE.search(own):
        return "comparaison relative entre deux valeurs, pas encore gérée"
    if _ELSEWHERE.search(own):
        return "valeur ailleurs qu'en France sans pays précis"

    country = find_country(own, countries) if countries else None
    usable = catalog
    if country is not None:
        usable = {k: v for k, v in catalog.items() if "geo" in v.filters}
    indicator = match_indicator(mention, sentence, usable, left_from, right_to)
    topic_note = None
    if indicator is None and context:
        indicator = _best(mention, context[-CONTEXT_FOR_TOPIC:].lower(), usable)
        topic_note = "sujet déduit de ce qui précède la phrase"
    if indicator is None:
        if country is not None:
            return f"aucune série par pays pour cette valeur ({country.name})"
        return f"aucun indicateur du catalogue pour cette valeur ({mention.unit})"

    if country is not None:
        if mention.role is not Role.SEUL or mention.direction is not Direction.NIVEAU:
            return "évolution dans un autre pays, pas encore gérée"
        return Target(
            indicator, evolution=False, decrease=False, start=None, note=topic_note,
            country=country,
        )  # fmt: skip

    at_start = mention.role is Role.SEUL and _AT_START.search(sentence) is not None
    if mention.role is Role.SEUL and mention.direction is Direction.NIVEAU and not at_start:
        return Target(indicator, evolution=False, decrease=False, start=None, note=topic_note)
    if debate.incumbent_since is None:
        return "évolution ou point de départ sans mandat de référence pour ce débat"

    start = last_period_before(debate.incumbent_since, indicator.frequency)
    note = "période supposée : depuis l'entrée en fonction du sortant"
    if at_start and mention.direction is Direction.NIVEAU:
        return Target(
            indicator, evolution=False, decrease=False, start=start,
            note="période : dernière donnée avant l'entrée en fonction du sortant",
        )  # fmt: skip
    if mention.role is Role.DEPART:
        return Target(indicator, evolution=False, decrease=False, start=start, note=note)
    if mention.role is Role.ARRIVEE:
        return Target(indicator, evolution=False, decrease=False, start=None)
    return Target(
        indicator,
        evolution=True,
        decrease=mention.direction is Direction.BAISSE,
        start=start,
        note=note,
    )
