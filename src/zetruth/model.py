"""Modèle de données du pipeline : affirmation normalisée et verdict.

Les règles de la grille de verdicts sont portées par le modèle lui-même : un
verdict qui les enfreint ne peut pas être construit. En particulier, un
verdict VRAI, FAUX, TROMPEUR ou IMPRECIS sans valeur officielle sourcée est
refusé.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from zetruth.sources.registry import (
    ATTRIBUTION_ONLY,
    Registry,
    UnknownSourceError,
    normalize_url,
)


class ClaimType(StrEnum):
    FACTUELLE = "factuelle"
    OPINION = "opinion"
    PROMESSE = "promesse"
    PREDICTION = "prediction"


class VerdictLabel(StrEnum):
    VRAI = "VRAI"
    FAUX = "FAUX"
    TROMPEUR = "TROMPEUR"
    IMPRECIS = "IMPRECIS"
    INVERIFIABLE = "INVERIFIABLE"
    NON_FACTUEL = "NON_FACTUEL"


SOURCED_VERDICTS = frozenset(
    {VerdictLabel.VRAI, VerdictLabel.FAUX, VerdictLabel.TROMPEUR, VerdictLabel.IMPRECIS}
)


class Qualifier(StrEnum):
    """Comment l'intervenant énonce la valeur : « 4 % », « plus de 4 % », « entre 4 et 5 % »..."""

    EGAL = "egal"
    ENVIRON = "environ"
    PLUS_DE = "plus_de"
    MOINS_DE = "moins_de"
    ENTRE = "entre"


class ValueNature(StrEnum):
    CONSTATEE = "constatee"
    PREVISION = "prevision"


class Confidence(StrEnum):
    HAUTE = "haute"
    MOYENNE = "moyenne"
    FAIBLE = "faible"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class ClaimedValue(_Frozen):
    qualifier: Qualifier
    value: Decimal
    upper: Decimal | None = None

    @model_validator(mode="after")
    def _check_bounds(self) -> Self:
        if self.qualifier is Qualifier.ENTRE:
            if self.upper is None or self.upper <= self.value:
                raise ValueError("une fourchette demande une borne haute supérieure à la valeur")
        elif self.upper is not None:
            raise ValueError("une borne haute n'a de sens que pour une fourchette")
        return self


class Utterance(_Frozen):
    """Ce qui a été dit, par qui, et où le retrouver."""

    source_file: str = Field(min_length=1)
    turn: int = Field(ge=0)
    speaker: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    timestamp_seconds: float | None = Field(default=None, ge=0)


class Claim(_Frozen):
    """Affirmation normalisée : ce qu'il faut comparer à la source officielle."""

    utterance: Utterance
    type: ClaimType
    subject: str | None = None
    indicator: str | None = None
    claimed: ClaimedValue | None = None
    unit: str | None = None
    period: str | None = None
    scope: str | None = None
    # Vrai quand l'affirmation porte sur ce qu'une publication dit (« un
    # sondage Odoxa dit 75 % »), pas sur le fait lui-même.
    attribution: bool = False

    @model_validator(mode="after")
    def _factual_claims_are_complete(self) -> Self:
        if self.type is ClaimType.FACTUELLE:
            missing = [
                name
                for name in ("indicator", "claimed", "period")
                if getattr(self, name) in (None, "")
            ]
            if missing:
                raise ValueError(f"affirmation factuelle incomplète : {', '.join(missing)}")
        return self


class OfficialValue(_Frozen):
    source_id: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    url: str
    value: Decimal
    unit: str = Field(min_length=1)
    period: str = Field(min_length=1)
    scope: str | None = None
    nature: ValueNature
    published_on: date | None = None
    consulted_on: date
    # Faux quand la valeur disponible a pu être révisée depuis le débat
    # (Eurostat, séries INSEE sans historique suffisant).
    known_at_debate: bool

    @field_validator("url")
    @classmethod
    def _url_is_http(cls, url: str) -> str:
        normalize_url(url)  # lève si l'URL n'est pas http(s)
        return url


class Lead(_Frozen):
    """Piste : source non officielle (presse, sondage, rapport) citée pour éclairer.

    Elle n'est jamais une preuve et ne compte pas parmi les valeurs officielles.
    """

    publisher: str = Field(min_length=1)
    url: str
    summary: str = Field(min_length=1)

    @field_validator("url")
    @classmethod
    def _url_is_http(cls, url: str) -> str:
        normalize_url(url)
        return url


class Reading(_Frozen):
    """Une lecture possible de l'affirmation : une définition ou un scénario, et son verdict."""

    reference: str = Field(min_length=1)
    value: Decimal
    label: VerdictLabel


class Verdict(_Frozen):
    claim: Claim
    label: VerdictLabel
    official_values: tuple[OfficialValue, ...] = ()
    # Écart entre la valeur annoncée et la valeur officielle principale, dans
    # l'unité de l'indicateur.
    gap: Decimal | None = None
    context: str | None = None
    confidence: Confidence
    limits: str | None = None
    # Vrai quand un humain doit trancher, par exemple si la source donne
    # plusieurs valeurs et que l'intervenant n'en cite qu'une (TROMPEUR ?).
    needs_review: bool = False
    # Éclairage : ce que disent d'autres sources, sans valeur de preuve.
    leads: tuple[Lead, ...] = ()
    # Verdict selon chaque définition ou scénario officiel disponible. La
    # première lecture est celle du verdict principal.
    readings: tuple[Reading, ...] = ()

    @model_validator(mode="after")
    def _follows_the_verdict_grid(self) -> Self:
        factual = self.claim.type is ClaimType.FACTUELLE
        if not factual and self.label is not VerdictLabel.NON_FACTUEL:
            raise ValueError(f"une affirmation de type {self.claim.type} est NON_FACTUEL")
        if factual and self.label is VerdictLabel.NON_FACTUEL:
            raise ValueError("une affirmation factuelle ne peut pas être NON_FACTUEL")
        if self.label is VerdictLabel.NON_FACTUEL and self.official_values:
            raise ValueError("un verdict NON_FACTUEL ne s'appuie sur aucune valeur officielle")
        if self.label in SOURCED_VERDICTS and not self.official_values:
            raise ValueError(f"un verdict {self.label} doit citer au moins une valeur officielle")
        if self.confidence is Confidence.HAUTE and not all(
            v.known_at_debate for v in self.official_values
        ):
            raise ValueError(
                "confiance haute impossible avec une valeur qui a pu être révisée depuis le débat"
            )
        return self


def check_sources(verdict: Verdict, registry: Registry) -> list[str]:
    """Chaque valeur officielle doit venir d'une source de la liste blanche, à une de ses URL."""
    errors = []
    for official in verdict.official_values:
        try:
            source = registry.get(official.source_id)
        except UnknownSourceError as e:
            errors.append(str(e))
            continue
        if not source.covers(official.url):
            errors.append(f"{official.url} n'appartient pas à la source {official.source_id}")
        if source.scope == ATTRIBUTION_ONLY and not verdict.claim.attribution:
            errors.append(f"{official.source_id} ne peut vérifier qu'une attribution, pas un fait")
    return errors
