"""Catalogue des indicateurs (config/indicateurs.toml)."""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from zetruth.sources.registry import Registry

CATALOG_FILE = Path("config/indicateurs.toml")
SUPPORTED_SOURCES = frozenset({"insee", "eurostat"})
FREQUENCIES = frozenset({"mensuelle", "trimestrielle", "annuelle"})


class InvalidCatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Indicator:
    id: str
    name: str
    definition: str
    source: str
    unit: str
    change_unit: str
    frequency: str
    scope: str | None = None
    series: str | None = None  # INSEE
    dataset: str | None = None  # Eurostat
    filters: Mapping[str, str] = field(default_factory=dict)  # Eurostat
    factor: Decimal = Decimal(1)
    competitors: tuple[str, ...] = ()


def _parse(indicator_id: str, raw: Mapping[str, Any]) -> Indicator:
    required = ("nom", "definition", "source", "unite", "unite_evolution", "frequence")
    missing = [k for k in required if not raw.get(k)]
    if missing:
        raise InvalidCatalogError(f"{indicator_id} : champs manquants {missing}")
    source = raw["source"]
    if source not in SUPPORTED_SOURCES:
        raise InvalidCatalogError(f"{indicator_id} : source sans connecteur {source!r}")
    if source == "insee" and not str(raw.get("serie", "")).isdigit():
        raise InvalidCatalogError(f"{indicator_id} : identifiant de série INSEE manquant")
    if source == "eurostat" and not (raw.get("dataset") and raw.get("filtres")):
        raise InvalidCatalogError(f"{indicator_id} : dataset et filtres Eurostat requis")
    if raw["frequence"] not in FREQUENCIES:
        raise InvalidCatalogError(f"{indicator_id} : fréquence inconnue {raw['frequence']!r}")
    factor = Decimal(str(raw.get("facteur", 1)))
    if factor == 0:
        raise InvalidCatalogError(f"{indicator_id} : facteur nul")

    return Indicator(
        id=indicator_id,
        name=raw["nom"],
        definition=raw["definition"],
        source=source,
        unit=raw["unite"],
        change_unit=raw["unite_evolution"],
        frequency=raw["frequence"],
        scope=raw.get("perimetre"),
        series=raw.get("serie"),
        dataset=raw.get("dataset"),
        filters=dict(raw.get("filtres", {})),
        factor=factor,
        competitors=tuple(raw.get("concurrents", ())),
    )


def parse_catalog(data: Mapping[str, Any], registry: Registry) -> dict[str, Indicator]:
    raw_indicators = data.get("indicateurs")
    if not raw_indicators:
        raise InvalidCatalogError("aucun indicateur déclaré")
    catalog = {iid: _parse(iid, raw) for iid, raw in raw_indicators.items()}
    for indicator in catalog.values():
        registry.get(indicator.source)  # lève si la source sort de la liste blanche
        for competitor in indicator.competitors:
            if competitor not in catalog or competitor == indicator.id:
                raise InvalidCatalogError(f"{indicator.id} : concurrent inconnu {competitor!r}")
    return catalog


def load_catalog(registry: Registry, path: Path = CATALOG_FILE) -> dict[str, Indicator]:
    with path.open("rb") as f:
        return parse_catalog(tomllib.load(f), registry)
