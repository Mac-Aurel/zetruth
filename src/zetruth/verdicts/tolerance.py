"""Verdict numérique : comparaison d'une valeur annoncée à la valeur officielle.

La règle est décrite dans config/tolerances.toml. Elle ne produit que VRAI,
IMPRECIS ou FAUX : TROMPEUR et INVERIFIABLE demandent un jugement sur le
contexte, qui ne se réduit pas à un écart entre deux nombres.
"""

import tomllib
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from zetruth.model import ClaimedValue, Qualifier, VerdictLabel

TOLERANCES_FILE = Path("config/tolerances.toml")


def load_threshold(path: Path = TOLERANCES_FILE) -> Decimal:
    with path.open("rb") as f:
        raw = tomllib.load(f).get("seuil_imprecis")
    if not isinstance(raw, float | int) or isinstance(raw, bool):
        raise ValueError("seuil_imprecis doit être un nombre")
    threshold = Decimal(str(raw))
    if not Decimal(0) <= threshold < Decimal(1):
        raise ValueError(f"seuil_imprecis doit être entre 0 et 1, reçu {threshold}")
    return threshold


def round_like(official: Decimal, claimed: Decimal) -> Decimal:
    """Arrondit la valeur officielle à la précision de la valeur annoncée.

    « 5,5 » est énoncé au dixième : 5,51 devient 5,5. « 600 » est énoncé à
    l'unité : 571 reste 571. Arrondi commercial (0,5 vers le haut en valeur
    absolue), comme le font les publications statistiques.
    """
    exponent = claimed.as_tuple().exponent
    if not isinstance(exponent, int):
        raise ValueError(f"valeur annoncée non finie : {claimed}")
    quantum = Decimal(1).scaleb(min(exponent, 0))
    return official.quantize(quantum, rounding=ROUND_HALF_UP)


def _holds(claimed: ClaimedValue, official: Decimal) -> bool:
    match claimed.qualifier:
        case Qualifier.EGAL | Qualifier.ENVIRON:
            return round_like(official, claimed.value) == claimed.value
        case Qualifier.PLUS_DE:
            return official > claimed.value
        case Qualifier.MOINS_DE:
            return official < claimed.value
        case Qualifier.ENTRE:
            assert claimed.upper is not None  # garanti par le modèle
            return claimed.value <= official <= claimed.upper


def relative_gap(claimed: ClaimedValue, official: Decimal) -> Decimal:
    """Écart relatif entre la valeur officielle et la borne annoncée la plus proche."""
    nearest = claimed.value
    # Seule une fourchette a une borne haute (garanti par le modèle).
    if claimed.upper is not None and official > claimed.upper:
        nearest = claimed.upper
    if official == 0:
        return Decimal(0) if nearest == 0 else Decimal("Infinity")
    return abs(nearest - official) / abs(official)


def numeric_verdict(claimed: ClaimedValue, official: Decimal, threshold: Decimal) -> VerdictLabel:
    if _holds(claimed, official):
        return VerdictLabel.VRAI
    if relative_gap(claimed, official) <= threshold:
        return VerdictLabel.IMPRECIS
    return VerdictLabel.FAUX
