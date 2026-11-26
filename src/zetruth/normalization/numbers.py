"""Lecture des nombres dans une phrase en français.

Les transcriptions écrivent les nombres en chiffres (« 7,4 », « 1 100 ») ou
en lettres (« six cents », « quatre et demi », « cinq virgule cinq »). Les
mots « million » et « milliard » ne sont pas multipliés : ils deviennent
l'unité (« six cents milliards » donne 600 et l'unité milliards).
"""

import re
from dataclasses import dataclass
from decimal import Decimal

_UNITS = {
    "zéro": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
    "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13,
    "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20, "vingts": 20, "trente": 30,
    "quarante": 40, "cinquante": 50, "soixante": 60,
}  # fmt: skip
_SCALES = {"million", "millions", "milliard", "milliards"}

# Un nombre en chiffres : « 7,4 », « 1 100 », « 2 823,7 », « 12 ».
_DIGITS = r"\d{1,3}(?:[  ]\d{3})+(?:,\d+)?|\d+(?:,\d+)?"
_WORD = r"[a-zàâçéèêëîïôûùüÿœ]+"
_TOKEN = re.compile(rf"(?P<digits>{_DIGITS})|(?P<word>{_WORD})", re.IGNORECASE)


@dataclass(frozen=True)
class NumberMatch:
    value: Decimal
    start: int  # position du premier caractère dans la phrase
    end: int  # position après le dernier caractère
    scale: str | None = None  # « millions » ou « milliards » quand le nombre en est suivi


def _number_word(word: str) -> bool:
    return word in _UNITS or word in {"cent", "cents", "mille"}


def _words_value(words: list[str]) -> Decimal:
    total, current, previous = 0, 0, ""
    for word in words:
        if word in ("cent", "cents"):
            current = (current or 1) * 100
        elif word == "mille":
            total += (current or 1) * 1000
            current = 0
        elif word in ("vingt", "vingts") and previous == "quatre":
            current += 76  # quatre-vingt : 4 déjà compté, 4 x 20 = 80
        else:
            current += _UNITS[word]
        previous = word
    return Decimal(total + current)


Token = tuple[str, int, int, bool]
_TENS = {"vingt", "trente", "quarante", "cinquante", "soixante"}


def _is_article(tokens: list[Token], i: int) -> bool:
    """« un » ou « une » n'est un nombre que suivi d'un mot de quantité (« un million »)."""
    if tokens[i][0] not in ("un", "une"):
        return False
    following = tokens[i + 1][0] if i + 1 < len(tokens) else ""
    return following not in _SCALES and following not in ("virgule", "point", "sur", "mille")


def _after_pour(tokens: list[Token], i: int) -> bool:
    """Le « cent » de « pour cent » est une unité, pas un nombre."""
    return tokens[i][0] in ("cent", "cents") and i > 0 and tokens[i - 1][0] == "pour"


def _joins_tens(tokens: list[Token], i: int) -> bool:
    """« et » ne lie que « vingt et un », « soixante et onze »..."""
    return (
        tokens[i][0] == "et"
        and 0 < i < len(tokens) - 1
        and tokens[i - 1][0] in _TENS
        and tokens[i + 1][0] in ("un", "une", "onze")
    )


def find_numbers(sentence: str) -> list[NumberMatch]:
    tokens: list[Token] = [
        (m.group().lower(), m.start(), m.end(), m.group("digits") is not None)
        for m in _TOKEN.finditer(sentence.replace("-", " "))
    ]
    matches: list[NumberMatch] = []
    i = 0
    while i < len(tokens):
        text, start, end, is_digits = tokens[i]
        if is_digits:
            value = Decimal(text.replace(" ", "").replace(" ", "").replace(",", "."))
            i += 1
        elif _number_word(text) and not _is_article(tokens, i) and not _after_pour(tokens, i):
            words: list[str] = []
            while i < len(tokens) and not tokens[i][3]:
                word = tokens[i][0]
                if _after_pour(tokens, i):
                    break
                if _number_word(word):
                    words.append(word)
                elif not _joins_tens(tokens, i):
                    break
                end = tokens[i][2]
                i += 1
            value = _words_value(words)
        else:
            i += 1
            continue

        value, end, i = _decimal_part(tokens, i, value, end)
        scale = None
        if i < len(tokens) and tokens[i][0] in _SCALES:
            scale = "millions" if tokens[i][0].startswith("million") else "milliards"
            end = tokens[i][2]
            i += 1
            # « 1 million 200 000 » : le reste s'ajoute en fraction de l'échelle.
            unit = Decimal(1_000_000 if scale == "millions" else 1_000_000_000)
            if i < len(tokens) and tokens[i][3]:
                rest = Decimal(tokens[i][0].replace(" ", "").replace(" ", "").replace(",", "."))
                if rest < unit:
                    value += rest / unit
                    end = tokens[i][2]
                    i += 1
        matches.append(NumberMatch(value, start, end, scale))
    return matches


def _decimal_part(
    tokens: list[Token], i: int, value: Decimal, end: int
) -> tuple[Decimal, int, int]:
    """« et demi », « virgule cinq » : partie décimale écrite en lettres."""
    if i + 1 < len(tokens) and tokens[i][0] == "et" and tokens[i + 1][0] == "demi":
        return value + Decimal("0.5"), tokens[i + 1][2], i + 2
    if i + 1 < len(tokens) and tokens[i][0] == "virgule":
        nxt = tokens[i + 1]
        digits = nxt[0] if nxt[3] else (str(_UNITS[nxt[0]]) if nxt[0] in _UNITS else None)
        if digits is not None:
            return Decimal(f"{value}.{digits}"), nxt[2], i + 2
    return value, end, i
