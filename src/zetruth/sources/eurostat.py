"""Connecteur vers l'API de diffusion d'Eurostat (Statistics API 1.0, JSON-stat 2.0).

Eurostat ne garde aucune version passée des données (« There is no history
available on data », FAQ de l'API). On ne peut donc connaître que la valeur
actuelle, datée par la dernière mise à jour du dataset. Si cette mise à jour
est postérieure au débat, la valeur a pu être révisée depuis, et value_as_of
renvoie None plutôt que de faire comme si on la connaissait.

Usage pour l'annotation :

    uv run python -m zetruth.sources.eurostat une_rt_m 2022-01 2022-04-20 \\
        geo=FR age=TOTAL sex=T unit=PC_ACT s_adj=SA
"""

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from zetruth.series.history import SeriesHistory, Vintage
from zetruth.sources.client import SourceClient, SourceUnavailableError
from zetruth.sources.registry import Registry, load_registry
from zetruth.sources.store import FetchRecord, ResponseStore

SOURCE_ID = "eurostat"
BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
CACHE_DIR = Path("data/cache/eurostat")
# Pas de quota documenté, on reste raisonnable.
MIN_SECONDS_BETWEEN_CALLS = 1.0
TIME_DIMENSION = "time"

_CODE = re.compile(r"^[A-Za-z0-9_.-]+$")


class EurostatResponseError(ValueError):
    pass


@dataclass(frozen=True)
class EurostatSeries:
    dataset_id: str
    dataset_label: str
    updated: datetime
    dimensions: dict[str, tuple[str, str]]  # dimension -> (code, libellé)
    values: dict[str, Decimal]
    flags: dict[str, str]  # période -> drapeau Eurostat (p provisoire, e estimé, b rupture...)

    def history(self) -> SeriesHistory:
        unit = self.dimensions.get("unit", ("", ""))[1]
        return SeriesHistory(
            series_id=self.dataset_id,
            title=self.dataset_label,
            unit=unit,
            vintages=(Vintage(self.updated.date(), dict(self.values)),),
        )


def series_url(dataset: str, filters: Mapping[str, str]) -> str:
    for code in (dataset, *filters, *filters.values()):
        if not _CODE.match(code):
            raise ValueError(f"code Eurostat invalide : {code!r}")
    params = {"format": "JSON", "lang": "FR", **dict(sorted(filters.items()))}
    return f"{BASE_URL}/{dataset}?{urlencode(params)}"


def cache_key(dataset: str, url: str) -> str:
    return f"{dataset}-{hashlib.sha256(url.encode()).hexdigest()[:16]}"


def _decode(content: bytes) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise EurostatResponseError(f"réponse JSON illisible : {e}") from None
    if not isinstance(data, dict):
        raise EurostatResponseError("réponse inattendue : un objet JSON était attendu")
    if "error" in data:
        raise EurostatResponseError(f"erreur Eurostat : {data['error']}")
    return data


def parse_series(content: bytes, dataset: str) -> EurostatSeries:
    """Lit une réponse JSON-stat qui doit désigner une seule série.

    Toutes les dimensions sauf le temps doivent avoir une seule valeur, sinon
    on ne saurait pas à quoi correspond chaque chiffre.
    """
    data = _decode(content)
    try:
        dims: list[str] = data["id"]
        sizes: list[int] = data["size"]
        categories = {d: data["dimension"][d]["category"] for d in dims}
        updated = datetime.fromisoformat(data["updated"])
        label = data["label"]
    except (KeyError, TypeError, ValueError) as e:
        raise EurostatResponseError(f"réponse JSON-stat incomplète : {e!r}") from None

    dimensions = {}
    for dim, size in zip(dims, sizes, strict=True):
        if dim == TIME_DIMENSION:
            continue
        if size != 1:
            raise EurostatResponseError(
                f"la requête doit désigner une seule série, {dim} a {size} valeurs : "
                "préciser ce filtre"
            )
        (code,) = categories[dim]["index"]
        dimensions[dim] = (code, categories[dim].get("label", {}).get(code, code))

    if TIME_DIMENSION not in dims:
        raise EurostatResponseError("réponse sans dimension temporelle")
    # Une seule série : la position dans le tableau est celle de la période.
    periods = sorted(categories[TIME_DIMENSION]["index"].items(), key=lambda item: item[1])
    period_at = {position: period for period, position in periods}

    values = {period_at[int(i)]: Decimal(str(v)) for i, v in data.get("value", {}).items()}
    flags = {period_at[int(i)]: f for i, f in data.get("status", {}).items()}
    return EurostatSeries(dataset, label, updated, dimensions, values, flags)


def eurostat_client(store: ResponseStore, registry: Registry) -> SourceClient:
    return SourceClient(SOURCE_ID, store, registry, MIN_SECONDS_BETWEEN_CALLS)


def fetch_series(
    client: SourceClient, dataset: str, filters: Mapping[str, str], refresh: bool = False
) -> tuple[EurostatSeries, FetchRecord]:
    url = series_url(dataset, filters)
    return client.get(
        cache_key(dataset, url), url, lambda content: parse_series(content, dataset), refresh
    )


def describe(series: EurostatSeries, record: FetchRecord, period: str, as_of: date) -> list[str]:
    lines = [f"{series.dataset_id} : {series.dataset_label}"]
    lines += [f"  {dim} : {label} ({code})" for dim, (code, label) in series.dimensions.items()]

    current = series.values.get(period)
    if current is None:
        lines.append(f"aucune valeur pour {period}")
    else:
        flag = f" [drapeau {series.flags[period]}]" if period in series.flags else ""
        lines.append(f"valeur actuelle : {current}{flag} (mise à jour du {series.updated.date()})")
        if series.history().value_as_of(period, as_of) is None:
            lines.append(
                f"attention : mise à jour postérieure au {as_of}, la valeur a pu être révisée "
                "depuis le débat (Eurostat ne garde pas les versions passées)"
            )
    lines.append(f"source : {record.url}")
    lines.append(f"consultée le : {record.fetched_at[:10]}")
    return lines


def _parse_filter(raw: str) -> tuple[str, str]:
    key, sep, value = raw.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError(f"filtre attendu sous la forme dimension=code : {raw!r}")
    return key, value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valeur d'une série Eurostat pour une période.")
    parser.add_argument("dataset", help="code du dataset, par exemple une_rt_m")
    parser.add_argument("periode", help="période au format du dataset : 2022-01, 2021-Q4, 2021")
    parser.add_argument("date", type=date.fromisoformat, help="date du débat, AAAA-MM-JJ")
    parser.add_argument("filtres", nargs="*", type=_parse_filter, help="dimension=code, ex. geo=FR")
    parser.add_argument(
        "--rafraichir", action="store_true", help="ignorer la copie locale et interroger Eurostat"
    )
    args = parser.parse_args(argv)

    client = eurostat_client(ResponseStore(CACHE_DIR), load_registry())
    try:
        series, record = fetch_series(client, args.dataset, dict(args.filtres), args.rafraichir)
    except (SourceUnavailableError, EurostatResponseError) as e:
        print(e, file=sys.stderr)
        return 1
    print("\n".join(describe(series, record, args.periode, args.date)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
