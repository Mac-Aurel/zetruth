"""Valeurs officielles d'un indicateur du catalogue, telles que connues à une date.

Pour chaque indicateur, on cherche la valeur publiée au plus tard le jour du
débat. Si l'historique de la source ne remonte pas assez loin, on prend la
dernière valeur publiée et on l'indique (known_at_debate=False) : le verdict
aura alors une confiance moindre.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from zetruth.indicators.catalog import Indicator
from zetruth.model import OfficialValue, ValueNature
from zetruth.series.periods import period_end
from zetruth.sources import eurostat, insee_bdm
from zetruth.sources.client import SourceClient
from zetruth.sources.store import FetchRecord


@dataclass(frozen=True)
class _Raw:
    value: Decimal
    published_on: date | None
    known_at_debate: bool
    record: FetchRecord
    scope: str | None


class IndicatorService:
    def __init__(
        self,
        catalog: Mapping[str, Indicator],
        clients: Mapping[str, SourceClient],
        refresh: bool = False,
    ) -> None:
        self.catalog = catalog
        self._clients = clients
        self._refresh = refresh

    def value(
        self,
        indicator_id: str,
        period: str,
        as_of: date,
        filters: Mapping[str, str] | None = None,
    ) -> OfficialValue | None:
        """Valeur de l'indicateur pour `period`, connue au plus tard le jour `as_of`.

        `filters` remplace des filtres Eurostat, par exemple geo=ES pour un
        autre pays. Renvoie None si la source n'a aucune valeur pour la période.
        """
        indicator = self.catalog[indicator_id]
        raw = self._raw(indicator, period, as_of, filters or {})
        if raw is None:
            return None
        return self._official(
            indicator,
            value=raw.value * indicator.factor,
            unit=indicator.unit,
            period=period,
            reference=self._reference(indicator),
            raws=(raw,),
        )

    def change(
        self, indicator_id: str, start: str, end: str, as_of: date, decrease: bool = False
    ) -> OfficialValue | None:
        """Évolution entre deux périodes : fin moins début, ou l'inverse pour une baisse."""
        indicator = self.catalog[indicator_id]
        first = self._raw(indicator, start, as_of, {})
        last = self._raw(indicator, end, as_of, {})
        if first is None or last is None:
            return None
        start_value, end_value = first.value * indicator.factor, last.value * indicator.factor
        delta = start_value - end_value if decrease else end_value - start_value
        return self._official(
            indicator,
            value=delta,
            unit=indicator.change_unit,
            period=f"{start}/{end}",
            reference=(
                f"{self._reference(indicator)} : {start_value} en {start}, {end_value} en {end}"
            ),
            raws=(first, last),
        )

    def with_competitors(self, indicator_id: str, period: str, as_of: date) -> list[OfficialValue]:
        """La valeur de l'indicateur, puis celles des définitions concurrentes disponibles."""
        ids = (indicator_id, *self.catalog[indicator_id].competitors)
        values = [self.value(iid, period, as_of) for iid in ids]
        if values[0] is None:
            return []
        return [v for v in values if v is not None]

    def latest_period(
        self,
        indicator_id: str,
        as_of: date,
        filters: Mapping[str, str] | None = None,
        euro_area: bool = False,
    ) -> tuple[str, bool] | None:
        """Dernière période publiée au plus tard le jour `as_of`, et si c'est certain.

        Certain quand l'historique des publications le dit. Sinon, estimé avec le
        délai de publication du catalogue ; sans délai connu, None.
        """
        indicator = self.catalog[indicator_id]
        client = self._clients[indicator.source]
        if indicator.source == "insee":
            assert indicator.series is not None
            history, _ = insee_bdm.fetch_history(client, indicator.series, self._refresh)
            known = [p for v in history.vintages if v.published_on <= as_of for p in v.values]
            if known:
                return max(known), True
            periods = {p for v in history.vintages for p in v.values}
        else:
            assert indicator.dataset is not None
            merged = {**indicator.filters, **(filters or {})}
            series, _ = eurostat.fetch_series(client, indicator.dataset, merged, self._refresh)
            periods = set(series.values)

        lag_days = indicator.publication_lag_days
        if euro_area and indicator.euro_area_lag_days is not None:
            lag_days = indicator.euro_area_lag_days
        if lag_days is None:
            return None
        lag = timedelta(days=lag_days)
        published = [p for p in periods if period_end(p) + lag <= as_of]
        return (max(published), False) if published else None

    def _raw(
        self, indicator: Indicator, period: str, as_of: date, filters: Mapping[str, str]
    ) -> _Raw | None:
        client = self._clients[indicator.source]
        if indicator.source == "insee":
            assert indicator.series is not None  # garanti par le catalogue
            history, record = insee_bdm.fetch_history(client, indicator.series, self._refresh)
            known = history.value_as_of(period, as_of)
            at_debate = known is not None
            if known is None:
                known = history.latest(period)
            if known is None:
                return None
            return _Raw(known.value, known.published_on, at_debate, record, indicator.scope)

        assert indicator.dataset is not None  # garanti par le catalogue
        merged = {**indicator.filters, **filters}
        series, record = eurostat.fetch_series(client, indicator.dataset, merged, self._refresh)
        current = series.values.get(period)
        if current is None:
            return None
        at_debate = series.history().value_as_of(period, as_of) is not None
        scope = series.dimensions["geo"][1] if "geo" in filters else indicator.scope
        return _Raw(current, None, at_debate, record, scope)

    @staticmethod
    def _reference(indicator: Indicator) -> str:
        if indicator.source == "insee":
            return f"{indicator.name}, série INSEE {indicator.series}"
        return f"{indicator.name}, Eurostat {indicator.dataset}"

    @staticmethod
    def _official(
        indicator: Indicator,
        value: Decimal,
        unit: str,
        period: str,
        reference: str,
        raws: tuple[_Raw, ...],
    ) -> OfficialValue:
        published = [r.published_on for r in raws]
        return OfficialValue(
            source_id=indicator.source,
            reference=reference,
            url=raws[-1].record.url,
            value=value,
            unit=unit,
            period=period,
            scope=raws[-1].scope,
            nature=ValueNature.CONSTATEE,
            published_on=None if None in published else max(p for p in published if p),
            consulted_on=min(date.fromisoformat(r.record.fetched_at[:10]) for r in raws),
            known_at_debate=all(r.known_at_debate for r in raws),
        )
