"""Appel au modèle : recherche sur les seuls sites de la liste blanche, puis proposition.

Le modèle dispose de la recherche web et de la lecture de pages (outils
exécutés par l'API d'Anthropic), limitées aux hôtes de config/sources.toml,
et d'un outil rendre_verdict pour donner sa proposition sous une forme fixe.
Chaque échange est enregistré sous son empreinte pour pouvoir être relu.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import anthropic
from pydantic import ValidationError

from zetruth.model import Qualifier, VerdictLabel
from zetruth.research.checks import Finding, Proposal, decide, read_pages
from zetruth.sources.registry import Registry

MODEL = "claude-opus-5-5"
PROMPT_VERSION = "1"
TRACE_DIR = Path("data/cache/recherche")
MAX_SEARCHES = 8
MAX_FETCHES = 8
MAX_CONTINUATIONS = 5

SYSTEM = """Tu vérifies une affirmation prononcée pendant un débat politique français.

Seules les sources officielles comptent. Les outils de recherche et de lecture
sont limités aux sites autorisés : cherche la source primaire (texte de loi,
scrutin public, série statistique, rapport officiel), puis lis la page avec
web_fetch pour en citer le texte exact.

Règles :
- Juge l'affirmation telle qu'elle pouvait être vérifiée le jour du débat. Une
  valeur publiée ou révisée après peut servir de contexte, pas de preuve.
- Grille : VRAI (conforme à la source), FAUX (contredit), TROMPEUR (exact mais
  présenté pour faire croire une chose fausse : périmètre, période, définition
  ou comparaison choisis), IMPRECIS (ordre de grandeur juste, valeur différente),
  INVERIFIABLE (aucune source officielle ne permet de trancher), NON_FACTUEL
  (opinion, promesse, prédiction).
- Un chiffre est VRAI seulement si la valeur officielle, arrondie à la précision
  employée par l'intervenant, est égale à ce qu'il dit. « Environ » ne donne
  aucune marge. « Plus de » et « moins de » doivent être vrais strictement.
- Quand deux définitions officielles existent (chômage BIT et demandeurs
  d'emploi par exemple), présenter l'une comme la seule est TROMPEUR.
- Chaque preuve est une page que tu as lue avec web_fetch, et son extrait est
  recopié mot pour mot depuis cette page (une ou deux phrases qui contiennent
  le fait ou le chiffre). Un extrait qui n'est pas dans la page sera rejeté.
- Pour chaque chiffre comparé, remplis une comparaison : valeurs écrites avec
  un point décimal, sans espace ni unité, valeur_max vide sauf fourchette.
- Mets attribution à true seulement si l'affirmation porte sur ce qu'une
  publication dit (« selon un sondage... »), pas sur le fait lui-même.
- Si tu ne trouves pas de source officielle qui tranche, réponds INVERIFIABLE
  sans preuve. Ne devine jamais.
- Le contexte explique l'évolution sur la période, les changements de méthode
  et ce qu'il faut savoir pour comprendre le chiffre ou le fait.

Termine en appelant rendre_verdict une seule fois."""

_STRING = {"type": "string"}
VERDICT_TOOL = {
    "name": "rendre_verdict",
    "description": "Donne la proposition de verdict, ses preuves et son contexte.",
    "strict": True,
    "eager_input_streaming": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": [v.value for v in VerdictLabel]},
            "attribution": {"type": "boolean"},
            "explication": _STRING,
            "contexte": _STRING,
            "preuves": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"url": _STRING, "extrait": _STRING},
                    "required": ["url", "extrait"],
                    "additionalProperties": False,
                },
            },
            "comparaisons": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "qualificatif": {"type": "string", "enum": [q.value for q in Qualifier]},
                        "valeur_annoncee": _STRING,
                        "valeur_max": _STRING,
                        "valeur_officielle": _STRING,
                        "url": _STRING,
                    },
                    "required": [
                        "qualificatif", "valeur_annoncee", "valeur_max", "valeur_officielle", "url"
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "verdict", "attribution", "explication", "contexte", "preuves", "comparaisons"
        ],
        "additionalProperties": False,
    },
}  # fmt: skip


@dataclass(frozen=True)
class Statement:
    """L'affirmation à rechercher et ce qu'il faut savoir pour la situer."""

    quote: str
    speaker: str
    debate: str
    held_on: date


def server_tools(registry: Registry) -> list[dict[str, Any]]:
    hosts = registry.hosts()
    # Appels directs (pas de filtrage par exécution de code) : le texte des pages
    # lues reste dans la réponse, ce qui permet de contrôler les extraits.
    common = {"allowed_domains": hosts, "allowed_callers": ["direct"]}
    return [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_SEARCHES, **common},
        {
            "type": "web_fetch_20260209",
            "name": "web_fetch",
            "max_uses": MAX_FETCHES,
            "max_content_tokens": 30000,
            **common,
        },
    ]


def user_message(statement: Statement) -> str:
    return (
        f"Débat : {statement.debate}, le {statement.held_on.isoformat()}\n"
        f"Intervenant : {statement.speaker}\n"
        f"Affirmation : « {statement.quote} »"
    )


def _save_trace(request: dict[str, Any], responses: list[dict[str, Any]]) -> str:
    body = json.dumps(
        {"prompt_version": PROMPT_VERSION, "request": request, "responses": responses},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode()
    digest = hashlib.sha256(body).hexdigest()
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    (TRACE_DIR / f"{digest}.json").write_bytes(body)
    return digest


def _abstain(reason: str, model: str, digest: str) -> Finding:
    return Finding(
        label=VerdictLabel.INVERIFIABLE,
        shown=False,
        explanation="",
        context="",
        evidence=[],
        rejected=[],
        notes=[reason],
        proposed_label=None,
        model=model,
        trace_sha256=digest,
    )


def research(
    statement: Statement,
    registry: Registry,
    threshold: Decimal,
    client: anthropic.Anthropic | None = None,
) -> Finding:
    client = client or anthropic.Anthropic()
    request: dict[str, Any] = {
        "model": MODEL,
        "max_tokens": 32000,
        "system": SYSTEM,
        "tools": [*server_tools(registry), VERDICT_TOOL],
        "output_config": {"effort": "high"},
        # En cas de refus du modèle, l'API relance la même demande sur un autre modèle.
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
    }
    messages: list[Any] = [{"role": "user", "content": user_message(statement)}]
    responses = []
    for _ in range(MAX_CONTINUATIONS + 1):
        with client.beta.messages.stream(**request, messages=messages) as stream:
            response = stream.get_final_message()
        responses.append(response.model_dump(mode="json"))
        if response.stop_reason != "pause_turn":
            break
        # Recherche interrompue par l'API : on renvoie le tour tel quel pour qu'elle reprenne.
        messages.append({"role": "assistant", "content": response.content})

    digest = _save_trace({**request, "messages": [messages[0]]}, responses)
    model = response.model
    if response.stop_reason == "refusal":
        return _abstain("le modèle a refusé de traiter la demande", model, digest)
    call = next(
        (b for b in response.content if b.type == "tool_use" and b.name == VERDICT_TOOL["name"]),
        None,
    )
    if call is None:
        return _abstain(f"pas de verdict rendu (arrêt : {response.stop_reason})", model, digest)
    try:
        proposal = Proposal.model_validate(call.input)
    except ValidationError as e:
        return _abstain(f"verdict mal formé : {e.errors()[0]['msg']}", model, digest)

    pages = read_pages([r["content"] for r in responses])
    finding = decide(proposal, pages, registry, threshold)
    return finding.model_copy(update={"model": model, "trace_sha256": digest})
