"""Lecture des séries de la BDM de l'INSEE avec leur historique de publications.

Le service SDMX renvoie, avec includeHistory=true, une série par publication,
datée par l'attribut LAST_UPDATE. Constaté en novembre 2026 : l'historique ne
remonte qu'au 18 mai 2017, et le service répond sans authentification.

Usage pour l'annotation :

    uv run python -m zetruth.sources.insee_bdm 001688527 2021-Q4 2022-04-20
"""

import argparse
import sys
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation

from zetruth.series.history import SeriesHistory, Vintage

BASE_URL = "https://api.insee.fr/series/BDM/V1/data/SERIES_BDM"
TIMEOUT_SECONDS = 60

Fetcher = Callable[[str], bytes]


class InseeResponseError(ValueError):
    pass


def http_fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
        content: bytes = response.read()
        return content


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


def fetch_history(series_id: str, fetch: Fetcher = http_fetch) -> SeriesHistory:
    return parse_history(fetch(history_url(series_id)), series_id)


def describe(history: SeriesHistory, period: str, as_of: date) -> list[str]:
    lines = [f"{history.series_id} : {history.title} ({history.unit})"]
    known = history.value_as_of(period, as_of)
    if known is None:
        earliest = history.earliest_publication()
        lines.append(
            f"aucune publication de {period} connue au {as_of} "
            f"(l'historique commence le {earliest})"
        )
    else:
        lines.append(f"valeur connue au {as_of} : {known.value} (publiée le {known.published_on})")
    for revision in history.revisions(period):
        lines.append(f"  publiée le {revision.published_on} : {revision.value}")
    lines.append(f"source : {history_url(history.series_id)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Valeur d'une série INSEE telle qu'elle était publiée à une date donnée."
    )
    parser.add_argument("serie", help="identifiant BDM (idbank), par exemple 001688527")
    parser.add_argument("periode", help="période au format de la série : 2021-Q4, 2022-03, 2021")
    parser.add_argument("date", type=date.fromisoformat, help="date du débat, AAAA-MM-JJ")
    args = parser.parse_args(argv)

    history = fetch_history(args.serie)
    print("\n".join(describe(history, args.periode, args.date)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
