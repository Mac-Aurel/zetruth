"""Découpage d'un tour de parole en phrases.

Le même découpage sert à étiqueter le jeu de détection et à faire tourner
le détecteur : sans cela, on ne pourrait pas comparer les deux.
"""

import re

# Abréviations après lesquelles un point ne termine pas la phrase.
_ABBREVIATIONS = ("M", "Mme", "Mmes", "MM", "Mlle", "Dr", "Pr", "etc", "cf", "art", "n°", "p")
_BOUNDARY = re.compile(r"(?<=[.!?…])\s+(?=[«\"A-ZÀ-Ý0-9])")


def split_sentences(text: str) -> list[str]:
    pieces = _BOUNDARY.split(" ".join(text.split()))
    sentences: list[str] = []
    for piece in pieces:
        if sentences and _ends_with_abbreviation(sentences[-1]):
            sentences[-1] = f"{sentences[-1]} {piece}"
        else:
            sentences.append(piece)
    return [s for s in sentences if s]


def _ends_with_abbreviation(sentence: str) -> bool:
    last_word = sentence.rsplit(" ", 1)[-1].rstrip(".")
    return sentence.endswith(".") and last_word in _ABBREVIATIONS
