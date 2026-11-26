"""Codes de période des séries : « 2021 », « 2021-Q4 », « 2022-03 »."""

import calendar
import re
from datetime import date

_ANNUAL = re.compile(r"^(\d{4})$")
_QUARTERLY = re.compile(r"^(\d{4})-Q([1-4])$")
_MONTHLY = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def period_end(period: str) -> date:
    """Dernier jour couvert par la période."""
    if m := _ANNUAL.match(period):
        return date(int(m[1]), 12, 31)
    if m := _QUARTERLY.match(period):
        year, month = int(m[1]), int(m[2]) * 3
        return date(year, month, calendar.monthrange(year, month)[1])
    if m := _MONTHLY.match(period):
        year, month = int(m[1]), int(m[2])
        return date(year, month, calendar.monthrange(year, month)[1])
    raise ValueError(f"code de période inconnu : {period!r}")


def last_period_before(event: date, frequency: str) -> str:
    """Dernière période entièrement écoulée avant l'événement.

    Règle du projet : une évolution « depuis l'élection » part de là. Pour une
    élection en mai 2017 : 2017-Q1, 2017-04 ou 2016 selon la fréquence.
    """
    if frequency == "annuelle":
        return str(event.year - 1)
    if frequency == "trimestrielle":
        quarter = (event.month - 1) // 3  # trimestre en cours, de 0 à 3
        if quarter == 0:
            return f"{event.year - 1}-Q4"
        return f"{event.year}-Q{quarter}"
    if frequency == "mensuelle":
        if event.month == 1:
            return f"{event.year - 1}-12"
        return f"{event.year}-{event.month - 1:02d}"
    raise ValueError(f"fréquence inconnue : {frequency!r}")
