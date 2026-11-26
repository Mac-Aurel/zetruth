"""Contrôles déterministes sur la proposition du modèle.

Le modèle ne décide pas seul. Une preuve n'est retenue que si :
- son URL appartient à une source de la liste blanche ;
- la page a réellement été lue pendant la recherche ;
- l'extrait cité figure mot pour mot dans le texte de cette page.

Un verdict sourcé sans preuve retenue devient INVERIFIABLE et n'est pas
affiché. Quand le modèle donne une valeur annoncée et une valeur officielle,
la règle de comparaison du projet (verdicts.tolerance) tranche à sa place.
"""

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from zetruth.model import SOURCED_VERDICTS, ClaimedValue, Qualifier, VerdictLabel
from zetruth.sources.registry import ATTRIBUTION_ONLY, Registry, UnknownSourceError, normalize_url
from zetruth.verdicts.tolerance import numeric_verdict

# En dessous, un extrait ne prouve rien (« 3,2 % » se trouve sur n'importe quelle page).
MIN_EXCERPT = 20


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProposedEvidence(_Frozen):
    url: str
    extrait: str


class ProposedComparison(_Frozen):
    qualificatif: Qualifier
    valeur_annoncee: str
    valeur_max: str  # vide sauf pour une fourchette
    valeur_officielle: str
    url: str


class Proposal(_Frozen):
    """Ce que le modèle rend, tel que défini par l'outil rendre_verdict."""

    verdict: VerdictLabel
    attribution: bool
    explication: str
    contexte: str
    preuves: list[ProposedEvidence]
    comparaisons: list[ProposedComparison]


class Evidence(_Frozen):
    source_id: str
    scope: str
    url: str
    excerpt: str


class Finding(_Frozen):
    """Résultat d'une recherche après contrôles. `shown` : peut être présenté au public
    après validation humaine. Sinon, on ne montre rien de cette affirmation."""

    label: VerdictLabel
    shown: bool
    explanation: str
    context: str
    evidence: list[Evidence]
    rejected: list[str]  # preuves ou comparaisons écartées, et pourquoi
    notes: list[str]
    proposed_label: VerdictLabel | None
    needs_review: bool = True  # validation humaine obligatoire avant toute diffusion
    model: str = ""
    trace_sha256: str = ""


def _flatten(text: str) -> str:
    text = text.replace("\u2019", "'").replace("\u00a0", " ").replace("\u202f", " ")
    return re.sub(r"\s+", " ", text).strip()


def read_pages(contents: Sequence[Sequence[Mapping[str, Any]]]) -> dict[str, str]:
    """Texte des pages lues par web_fetch dans les réponses, par URL normalisée.

    Les documents non textuels (PDF en base64) ne sont pas gardés : on ne
    saurait pas y vérifier un extrait.
    """
    pages = {}
    for content in contents:
        for block in content:
            if block.get("type") != "web_fetch_tool_result":
                continue
            result = block.get("content") or {}
            if result.get("type") != "web_fetch_result":
                continue
            source = (result.get("content") or {}).get("source") or {}
            if source.get("type") == "text" and result.get("url"):
                pages[normalize_url(result["url"])] = _flatten(source.get("data", ""))
    return pages


def check_evidence(
    proposed: Sequence[ProposedEvidence], pages: Mapping[str, str], registry: Registry
) -> tuple[list[Evidence], list[str]]:
    kept, rejected = [], []
    for item in proposed:
        try:
            url = normalize_url(item.url)
            source = registry.for_url(item.url)
        except (ValueError, UnknownSourceError) as e:
            rejected.append(f"{item.url} : {e}")
            continue
        excerpt = _flatten(item.extrait)
        if url not in pages:
            rejected.append(f"{item.url} : page non lue pendant la recherche")
        elif len(excerpt) < MIN_EXCERPT:
            rejected.append(f"{item.url} : extrait trop court pour prouver quoi que ce soit")
        elif excerpt not in pages[url]:
            rejected.append(f"{item.url} : extrait absent de la page")
        else:
            kept.append(
                Evidence(source_id=source.id, scope=source.scope, url=item.url, excerpt=excerpt)
            )
    return kept, rejected


def _decimal(text: str) -> Decimal:
    cleaned = text.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"nombre illisible : {text!r}") from None


def recompute(
    comparisons: Sequence[ProposedComparison], evidence_urls: set[str], threshold: Decimal
) -> tuple[list[VerdictLabel], list[str]]:
    """Verdicts chiffrés refaits en code, pour les comparaisons appuyées sur une preuve retenue."""
    labels, rejected = [], []
    for c in comparisons:
        if normalize_url(c.url) not in evidence_urls:
            rejected.append(
                f"comparaison {c.valeur_annoncee} : sa source n'est pas une preuve retenue"
            )
            continue
        try:
            claimed = ClaimedValue(
                qualifier=c.qualificatif,
                value=_decimal(c.valeur_annoncee),
                upper=_decimal(c.valeur_max) if c.valeur_max.strip() else None,
            )
            official = _decimal(c.valeur_officielle)
        except (ValueError, ValidationError) as e:
            rejected.append(f"comparaison {c.valeur_annoncee} : {e}")
            continue
        labels.append(numeric_verdict(claimed, official, threshold))
    return labels, rejected


_SEVERITY = [VerdictLabel.VRAI, VerdictLabel.IMPRECIS, VerdictLabel.FAUX]


def decide(
    proposal: Proposal, pages: Mapping[str, str], registry: Registry, threshold: Decimal
) -> Finding:
    evidence, rejected = check_evidence(proposal.preuves, pages, registry)
    # Un institut de sondage ne prouve que ce qu'il a publié.
    usable = [e for e in evidence if proposal.attribution or e.scope != ATTRIBUTION_ONLY]
    if len(usable) < len(evidence):
        rejected.append("source à portée « attribution » pour une affirmation qui n'en est pas une")
    label, notes = proposal.verdict, []

    if label in SOURCED_VERDICTS and not usable:
        label = VerdictLabel.INVERIFIABLE
        notes.append(f"{proposal.verdict} proposé, mais aucune preuve officielle vérifiée")

    computed, refused = recompute(
        proposal.comparaisons, {normalize_url(e.url) for e in usable}, threshold
    )
    rejected += refused
    if computed and label in _SEVERITY:
        # Plusieurs valeurs comparées : la plus sévère l'emporte.
        strictest = max(computed, key=_SEVERITY.index)
        if strictest is not label:
            notes.append(f"{label} proposé, {strictest} selon la règle de comparaison")
            label = strictest

    return Finding(
        label=label,
        shown=label in SOURCED_VERDICTS,
        explanation=proposal.explication,
        context=proposal.contexte,
        evidence=usable,
        rejected=rejected,
        notes=notes,
        proposed_label=proposal.verdict,
    )
