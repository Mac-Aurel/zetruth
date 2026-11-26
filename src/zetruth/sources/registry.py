"""Référentiel des sources officielles (liste blanche fermée).

Une source absente du référentiel ne peut pas fonder un verdict : toute
recherche qui échoue lève UnknownSourceError plutôt que de renvoyer None.
"""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SOURCES_FILE = Path("config/sources.toml")

DOMAINS = frozenset(
    {
        "climat",
        "commerce_exterieur",
        "demographie",
        "donnees_ouvertes",
        "droit",
        "economie",
        "emploi",
        "energie",
        "finances_publiques",
        "immigration",
        "international",
        "opinion",
        "parlement",
        "sante",
        "securite",
        "social",
    }
)
STATUSES = frozenset({"a_verifier", "verifiee"})
EVIDENCE = "preuve"
ATTRIBUTION_ONLY = "attribution"
SCOPES = frozenset({EVIDENCE, ATTRIBUTION_ONLY})
REQUIRED_WHEN_VERIFIED = ("acces", "documentation", "conditions_usage", "date_verification")


class UnknownSourceError(LookupError):
    pass


class InvalidRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url_prefixes: tuple[str, ...]
    domains: frozenset[str]
    status: str
    # « preuve » : peut fonder un verdict sur un fait. « attribution » : ne
    # vérifie que ce que la source a elle-même publié (un sondage, par exemple).
    scope: str = EVIDENCE
    access: str | None = None
    documentation: str | None = None
    terms_of_use: str | None = None
    verified_on: date | None = None

    def covers(self, url: str) -> bool:
        # Même convention que les préfixes : on termine par « / » pour que
        # https://ec.europa.eu/eurostat soit couvert par .../eurostat/.
        normalized = normalize_url(url).rstrip("/") + "/"
        return any(normalized.startswith(prefix) for prefix in self.url_prefixes)


def normalize_url(url: str) -> str:
    """Met l'URL sous une forme comparable : https, hôte en minuscules, sans « www. »."""
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"URL invalide : {url!r}")
    host = parts.hostname.removeprefix("www.")
    return f"https://{host}{parts.path or '/'}"


class Registry:
    def __init__(self, sources: Mapping[str, Source]) -> None:
        self._sources = dict(sources)

    def __len__(self) -> int:
        return len(self._sources)

    def get(self, source_id: str) -> Source:
        try:
            return self._sources[source_id]
        except KeyError:
            raise UnknownSourceError(f"source hors liste blanche : {source_id!r}") from None

    def for_url(self, url: str) -> Source:
        for source in self._sources.values():
            if source.covers(url):
                return source
        raise UnknownSourceError(f"URL hors liste blanche : {url!r}")

    def for_domain(self, domain: str) -> list[Source]:
        if domain not in DOMAINS:
            raise ValueError(f"domaine inconnu : {domain!r}")
        return [s for s in self._sources.values() if domain in s.domains]


def _parse_source(source_id: str, raw: Mapping[str, Any]) -> Source:
    errors = []
    for key in ("nom", "urls", "domaines", "statut"):
        if not raw.get(key):
            errors.append(f"champ manquant : {key}")
    if errors:
        raise InvalidRegistryError(f"{source_id} : {', '.join(errors)}")

    unknown_domains = set(raw["domaines"]) - DOMAINS
    if unknown_domains:
        errors.append(f"domaines inconnus : {sorted(unknown_domains)}")
    if raw["statut"] not in STATUSES:
        errors.append(f"statut inconnu : {raw['statut']!r}")
    scope = raw.get("portee", EVIDENCE)
    if scope not in SCOPES:
        errors.append(f"portée inconnue : {scope!r}")
    if raw["statut"] == "verifiee":
        missing = [k for k in REQUIRED_WHEN_VERIFIED if not raw.get(k)]
        if missing:
            errors.append(f"source vérifiée sans : {', '.join(missing)}")
    verified_on = raw.get("date_verification")
    if verified_on is not None and not isinstance(verified_on, date):
        errors.append("date_verification doit être une date TOML (AAAA-MM-JJ, sans guillemets)")
    try:
        # Le « / » final évite qu'un préfixe couvre un autre chemin ou hôte
        # (https://insee.fr ne doit pas accepter https://insee.fr.exemple.com).
        prefixes = tuple(normalize_url(u).rstrip("/") + "/" for u in raw["urls"])
    except ValueError as e:
        errors.append(str(e))
        prefixes = ()
    if errors:
        raise InvalidRegistryError(f"{source_id} : {'; '.join(errors)}")

    return Source(
        id=source_id,
        name=raw["nom"],
        url_prefixes=prefixes,
        domains=frozenset(raw["domaines"]),
        status=raw["statut"],
        scope=scope,
        access=raw.get("acces"),
        documentation=raw.get("documentation"),
        terms_of_use=raw.get("conditions_usage"),
        verified_on=verified_on,
    )


def _check_no_overlap(sources: Mapping[str, Source]) -> None:
    """Deux sources ne peuvent pas revendiquer la même URL, sinon l'attribution est ambiguë."""
    owners: dict[str, str] = {}
    for source in sources.values():
        for prefix in source.url_prefixes:
            for other_prefix, owner in owners.items():
                if prefix.startswith(other_prefix) or other_prefix.startswith(prefix):
                    raise InvalidRegistryError(
                        f"{source.id} et {owner} se recouvrent : {prefix} / {other_prefix}"
                    )
            owners[prefix] = source.id


def parse_registry(data: Mapping[str, Any]) -> Registry:
    raw_sources = data.get("sources")
    if not raw_sources:
        raise InvalidRegistryError("aucune source déclarée")
    sources = {sid: _parse_source(sid, raw) for sid, raw in raw_sources.items()}
    _check_no_overlap(sources)
    return Registry(sources)


def load_registry(path: Path = SOURCES_FILE) -> Registry:
    with path.open("rb") as f:
        return parse_registry(tomllib.load(f))
