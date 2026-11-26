"""Pays cités dans une phrase (config/pays.toml)."""

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

COUNTRIES_FILE = Path("config/pays.toml")


@dataclass(frozen=True)
class Country:
    code: str
    name: str
    words: tuple[str, ...]
    euro_since: date | None = None

    def in_euro_area(self, on: date) -> bool:
        return self.euro_since is not None and self.euro_since <= on


def load_countries(path: Path = COUNTRIES_FILE) -> dict[str, Country]:
    with path.open("rb") as f:
        raw = tomllib.load(f)["pays"]
    countries = {}
    for code, values in raw.items():
        words = tuple(values["mots"])
        if not words or any(w != w.lower() for w in words):
            raise ValueError(f"{code} : mots manquants ou pas en minuscules")
        countries[code] = Country(code, values["nom"], words, values.get("zone_euro_depuis"))
    return countries


def find_country(text: str, countries: Mapping[str, Country]) -> Country | None:
    """Le pays cité dans le texte, s'il n'y en a qu'un. Plusieurs pays : None."""
    lowered = text.lower()
    found = {
        c.code: c
        for c in countries.values()
        for w in c.words
        if re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", lowered)
    }
    return next(iter(found.values())) if len(found) == 1 else None
