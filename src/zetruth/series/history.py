"""Historique des publications d'une série statistique.

Les données officielles sont révisées : une valeur peut avoir été juste au
moment où un intervenant l'a citée, puis corrigée ensuite. Pour juger une
affirmation, on compare donc à la valeur connue à la date du débat, pas à
la valeur actuelle.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


class RevisionConflictError(ValueError):
    """Deux publications du même jour donnent des valeurs différentes."""


@dataclass(frozen=True)
class Vintage:
    """Une publication de la série : les valeurs telles qu'elles étaient ce jour-là."""

    published_on: date
    values: dict[str, Decimal]


@dataclass(frozen=True)
class PublishedValue:
    period: str
    value: Decimal
    published_on: date


@dataclass(frozen=True)
class SeriesHistory:
    series_id: str
    title: str
    unit: str
    vintages: tuple[Vintage, ...]

    def value_as_of(self, period: str, as_of: date) -> PublishedValue | None:
        """Dernière valeur publiée pour `period` au plus tard le jour `as_of`.

        Une publication du jour même compte : les instituts publient le matin,
        les débats ont lieu le soir. Renvoie None si aucune publication connue
        n'est antérieure, ce qui arrive quand l'historique ne remonte pas assez
        loin.
        """
        candidates = [v for v in self.vintages if v.published_on <= as_of and period in v.values]
        return self._latest(period, candidates)

    def latest(self, period: str) -> PublishedValue | None:
        return self._latest(period, [v for v in self.vintages if period in v.values])

    def revisions(self, period: str) -> list[PublishedValue]:
        """Chaque changement de valeur pour `period`, du plus ancien au plus récent."""
        changes: list[PublishedValue] = []
        for vintage in sorted(self.vintages, key=lambda v: v.published_on):
            value = vintage.values.get(period)
            if value is not None and (not changes or changes[-1].value != value):
                changes.append(PublishedValue(period, value, vintage.published_on))
        return changes

    def earliest_publication(self) -> date | None:
        return min((v.published_on for v in self.vintages), default=None)

    @staticmethod
    def _latest(period: str, vintages: list[Vintage]) -> PublishedValue | None:
        if not vintages:
            return None
        last_day = max(v.published_on for v in vintages)
        values = {v.values[period] for v in vintages if v.published_on == last_day}
        if len(values) > 1:
            raise RevisionConflictError(
                f"publications contradictoires le {last_day} pour {period} : {sorted(values)}"
            )
        return PublishedValue(period, values.pop(), last_day)
