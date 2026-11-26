"""Pré-calcul : télécharge à l'avance toutes les séries du catalogue.

    uv run python -m zetruth.indicators [--rafraichir]

Sans --rafraichir, une série déjà en copie locale n'est pas retéléchargée :
relancer la commande ne change rien.
"""

import argparse
import sys

from zetruth.indicators.catalog import Indicator, load_catalog
from zetruth.sources import eurostat, insee_bdm
from zetruth.sources.client import SourceClient, SourceUnavailableError
from zetruth.sources.registry import load_registry
from zetruth.sources.store import ResponseStore


def default_clients() -> dict[str, SourceClient]:
    registry = load_registry()
    return {
        "insee": insee_bdm.insee_client(ResponseStore(insee_bdm.CACHE_DIR), registry),
        "eurostat": eurostat.eurostat_client(ResponseStore(eurostat.CACHE_DIR), registry),
    }


def describe(indicator: Indicator, client: SourceClient, refresh: bool) -> str:
    if indicator.source == "insee":
        assert indicator.series is not None
        history, record = insee_bdm.fetch_history(client, indicator.series, refresh)
        periods = {p for v in history.vintages for p in v.values}
        last = max(periods) if periods else "aucune"
        first_pub = history.earliest_publication()
        return (
            f"{indicator.id} : {len(periods)} périodes, dernière {last}, "
            f"{len(history.vintages)} publications depuis le {first_pub} ({record.fetched_at[:10]})"
        )
    assert indicator.dataset is not None
    series, record = eurostat.fetch_series(client, indicator.dataset, indicator.filters, refresh)
    last = max(series.values) if series.values else "aucune"
    return (
        f"{indicator.id} : {len(series.values)} périodes, dernière {last}, "
        f"mise à jour du {series.updated.date()} ({record.fetched_at[:10]})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Télécharge les séries du catalogue.")
    parser.add_argument("--rafraichir", action="store_true", help="retélécharger toutes les séries")
    args = parser.parse_args(argv)

    clients = default_clients()
    catalog = load_catalog(load_registry())
    failures = 0
    for indicator in catalog.values():
        try:
            print(describe(indicator, clients[indicator.source], args.rafraichir))
        except (SourceUnavailableError, ValueError) as e:
            failures += 1
            print(f"{indicator.id} : échec, {e}", file=sys.stderr)
    print(f"{len(catalog) - failures} indicateurs disponibles sur {len(catalog)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
