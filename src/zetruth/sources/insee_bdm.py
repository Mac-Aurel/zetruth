"""Connecteur vers la BDM (Banque de données macro-économiques) de l'INSEE.

Service SDMX 2.1. Avec includeHistory=true, il renvoie une série par
publication, datée par l'attribut LAST_UPDATE.

Constaté en novembre 2026, à confirmer dans la doc officielle :
- le service répond sans authentification ;
- l'historique des publications ne remonte qu'au 18 mai 2017 ;
- les docs INSEE et data.gouv.fr annoncent 30 appels par minute, on s'y tient.

Les réponses sont gardées en local (voir store.py) : une série déjà
téléchargée est relue sans appel réseau, sauf rafraîchissement demandé.

Usage pour l'annotation :

    uv run python -m zetruth.sources.insee_bdm 001688527 2021-Q4 2022-04-20
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from zetruth.series.history import SeriesHistory, Vintage
from zetruth.sources.client import SourceClient, SourceUnavailableError
from zetruth.sources.registry import Registry, load_registry
from zetruth.sources.store import FetchRecord, ResponseStore

SOURCE_ID = "insee"
BASE_URL = "https://api.insee.fr/series/BDM/V1/data/SERIES_BDM"
CACHE_DIR = Path("data/cache/insee")
MIN_SECONDS_BETWEEN_CALLS = 2.0  # 30 appels par minute


class InseeResponseError(ValueError):
    pass


def history_url(series_id: str) -> str:
    if not series_id.isdigit():
        raise ValueError(f"identifiant de série INSEE invalide : {series_id!r}")
    return f"{BASE_URL}/{series_id}?includeHistory=true"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_value(raw: str, series_id: str, period: str) -> Decimal:
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise InseeResponseError(f"{series_id} {period} : valeur illisible {raw!r}") from None


def parse_history(xml_content: bytes, series_id: str) -> SeriesHistory:
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        raise InseeResponseError(f"réponse XML illisible pour {series_id} : {e}") from None

    series_nodes = [n for n in root.iter() if _local_name(n.tag) == "Series"]
    if not series_nodes:
        raise InseeResponseError(f"aucune série {series_id} dans la réponse")

    vintages = []
    for node in series_nodes:
        if node.attrib.get("IDBANK") != series_id:
            raise InseeResponseError(f"série inattendue dans la réponse : {node.attrib}")
        values = {
            obs.attrib["TIME_PERIOD"]: _parse_value(
                obs.attrib["OBS_VALUE"], series_id, obs.attrib["TIME_PERIOD"]
            )
            for obs in node
            if _local_name(obs.tag) == "Obs" and obs.attrib.get("OBS_VALUE")
        }
        vintages.append(Vintage(date.fromisoformat(node.attrib["LAST_UPDATE"]), values))

    first = series_nodes[0].attrib
    return SeriesHistory(
        series_id=series_id,
        title=first.get("TITLE_FR", ""),
        unit=first.get("UNIT_MEASURE", ""),
        vintages=tuple(vintages),
    )


def insee_client(store: ResponseStore, registry: Registry) -> SourceClient:
    return SourceClient(SOURCE_ID, store, registry, MIN_SECONDS_BETWEEN_CALLS)


def fetch_history(
    client: SourceClient, series_id: str, refresh: bool = False
) -> tuple[SeriesHistory, FetchRecord]:
    """Historique d'une série et l'appel dont il provient (pour la traçabilité)."""
    return client.get(
        series_id,
        history_url(series_id),
        lambda content: parse_history(content, series_id),
        refresh=refresh,
    )


def describe(history: SeriesHistory, record: FetchRecord, period: str, as_of: date) -> list[str]:
    lines = [f"{history.series_id} : {history.title} ({history.unit})"]
    known = history.value_as_of(period, as_of)
    if known is None:
        lines.append(
            f"aucune publication de {period} connue au {as_of} "
            f"(l'historique commence le {history.earliest_publication()})"
        )
    else:
        lines.append(f"valeur connue au {as_of} : {known.value} (publiée le {known.published_on})")
    for revision in history.revisions(period):
        lines.append(f"  publiée le {revision.published_on} : {revision.value}")
    lines.append(f"source : {record.url}")
    lines.append(f"consultée le : {record.fetched_at[:10]}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Valeur d'une série INSEE telle qu'elle était publiée à une date donnée."
    )
    parser.add_argument("serie", help="identifiant BDM (idbank), par exemple 001688527")
    parser.add_argument("periode", help="période au format de la série : 2021-Q4, 2022-03, 2021")
    parser.add_argument("date", type=date.fromisoformat, help="date du débat, AAAA-MM-JJ")
    parser.add_argument(
        "--rafraichir", action="store_true", help="ignorer la copie locale et interroger l'INSEE"
    )
    args = parser.parse_args(argv)

    client = insee_client(ResponseStore(CACHE_DIR), load_registry())
    try:
        history, record = fetch_history(client, args.serie, refresh=args.rafraichir)
    except (SourceUnavailableError, InseeResponseError) as e:
        print(e, file=sys.stderr)
        return 1
    print("\n".join(describe(history, record, args.periode, args.date)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
