"""Détection des phrases qui contiennent une affirmation chiffrée vérifiable.

Méthode à base de règles, volontairement simple : elle sert de référence
avant d'envisager un modèle plus lourd, qui ne sera retenu que s'il fait
nettement mieux sur le jeu de détection.

Une phrase est retenue si elle contient un chiffre (en chiffres ou en
lettres) et qu'elle ne ressemble ni à une promesse, ni à une prédiction,
ni à une vraie question.
"""

import re
from dataclasses import dataclass

_NUMBER_WORDS = (
    "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze", "douze",
    "treize", "quatorze", "quinze", "seize", "vingt", "trente", "quarante", "cinquante",
    "soixante", "cent", "cents", "mille", "million", "millions", "milliard", "milliards",
    "moitié", "quart", "tiers", "double", "triple",
)  # fmt: skip
_FIGURE = re.compile(
    r"\d|%|\bpour ?cents?\b|\bpourcents?\b|\b(?:" + "|".join(_NUMBER_WORDS) + r")\b|\bun sur\b",
    re.IGNORECASE,
)

_MONTHS = "janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre"
# Chiffres qui ne sont pas des statistiques : un âge, une date, une quantité vague.
_NOT_A_STATISTIC = re.compile(
    r"\b(?:à|de)\s+(?:\d+|[a-zéèû]+(?:-[a-zéèû]+)*(?:\s+et\s+un)?)\s+ans?\b"
    r"|\b(?:le|du|au)\s+(?:\d+|premier|[a-zéèû]+(?:-[a-zéèû]+)*)\s+(?:" + _MONTHS + r")\b"
    r"|\bdes\s+(?:millions|milliers|centaines|dizaines)\s+(?=de\s|d['’])",
    re.IGNORECASE,
)

# Ce que l'intervenant propose de faire : une promesse, pas un fait.
_PROMISE = re.compile(
    r"\b(?:nous|on)\s+(?:allons|va|ferons|proposons|souhaitons|voulons|abaissons|doublerons|"
    r"supprimerons|baisserons|augmenterons|taxons|assumons)\b"
    r"|\bje\s+(?:propose|veux|souhaite|ferai)\b"
    r"|\b(?:nous|on)\s+\w+rons\b"
    r"|\bva\s+(?:augmenter|baisser|exonérer|permettre|coûter)\b"
    r"|\bmesure\s+qui\s+coûte\b",
    re.IGNORECASE,
)
# Ce qui arrivera, selon l'intervenant.
_PREDICTION = re.compile(
    r"\b(?:finira|finirons|va\s+entraîner|vont\s+augmenter|ne\s+marchera\s+pas|"
    r"ne\s+se\s+répercutera)\b",
    re.IGNORECASE,
)
# Un fait constaté dans la même phrase : « il y a », un passé composé.
_STATED_FACT = re.compile(
    r"\bil\s+y\s+a\b|\b(?:ai|avons|avez|a|ont)\s+(?:été|\w+(?:é|és|ée|ées|is|it))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Detection:
    check_worthy: bool
    reason: str


def has_figure(sentence: str) -> bool:
    return _FIGURE.search(sentence) is not None


def has_statistic(sentence: str) -> bool:
    """Un chiffre qui n'est ni un âge, ni une date, ni une quantité vague."""
    return has_figure(_NOT_A_STATISTIC.sub(" ", sentence))


def detect(sentence: str) -> Detection:
    if not has_statistic(sentence):
        return Detection(False, "aucun chiffre statistique")
    if sentence.rstrip().endswith("?"):
        return Detection(False, "question")
    # Une promesse ou une prédiction n'écarte pas la phrase si elle affirme aussi un fait.
    if _STATED_FACT.search(sentence):
        return Detection(True, "chiffre et fait constaté")
    if _PROMISE.search(sentence):
        return Detection(False, "promesse")
    if _PREDICTION.search(sentence):
        return Detection(False, "prédiction")
    return Detection(True, "chiffre affirmé")
