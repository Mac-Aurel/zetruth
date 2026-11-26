from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from anthropic.types.beta import BetaMessage

from zetruth.model import Qualifier, VerdictLabel
from zetruth.research import search
from zetruth.research.checks import (
    Proposal,
    ProposedComparison,
    ProposedEvidence,
    check_evidence,
    decide,
    read_pages,
)
from zetruth.research.search import Statement, research, server_tools
from zetruth.sources.registry import parse_registry

REGISTRY = parse_registry(
    {
        "sources": {
            "insee": {
                "nom": "INSEE",
                "urls": ["https://insee.fr/"],
                "domaines": ["economie"],
                "statut": "a_verifier",
            },
            "eurostat": {
                "nom": "Eurostat",
                "urls": ["https://ec.europa.eu/eurostat/"],
                "domaines": ["international"],
                "statut": "a_verifier",
            },
            "odoxa": {
                "nom": "Odoxa",
                "urls": ["https://odoxa.fr/"],
                "domaines": ["opinion"],
                "portee": "attribution",
                "statut": "a_verifier",
            },
        }
    }
)
THRESHOLD = Decimal("0.02")
PAGE_URL = "https://www.insee.fr/fr/statistiques/1"
PAGE = "Au quatrième trimestre 2021, le taux de chômage au sens du BIT\u00a0est de 7,4\u00a0%."
EXCERPT = "le taux de chômage au sens du BIT est de 7,4 %"


def fetch_block(url: str = PAGE_URL, text: str = PAGE) -> dict[str, Any]:
    return {
        "type": "web_fetch_tool_result",
        "tool_use_id": "srvtoolu_1",
        "content": {
            "type": "web_fetch_result",
            "url": url,
            "content": {
                "type": "document",
                "source": {"type": "text", "media_type": "text/plain", "data": text},
            },
        },
    }


def proposal(**overrides: Any) -> Proposal:
    values: dict[str, Any] = {
        "verdict": "VRAI",
        "attribution": False,
        "explication": "L'INSEE publie 7,4 %.",
        "contexte": "",
        "preuves": [ProposedEvidence(url=PAGE_URL, extrait=EXCERPT)],
        "comparaisons": [],
    }
    values.update(overrides)
    return Proposal(**values)


def comparison(claimed: str, official: str = "7.4", url: str = PAGE_URL) -> ProposedComparison:
    return ProposedComparison(
        qualificatif=Qualifier.EGAL,
        valeur_annoncee=claimed,
        valeur_max="",
        valeur_officielle=official,
        url=url,
    )


def test_seules_les_pages_lues_en_texte_sont_gardees() -> None:
    pdf = fetch_block("https://insee.fr/a.pdf")
    pdf["content"]["content"]["source"] = {"type": "base64", "data": "JVBER"}
    error = {"type": "web_fetch_tool_result", "content": {"type": "web_fetch_tool_error"}}

    pages = read_pages([[fetch_block(), pdf, error, {"type": "text", "text": "x"}]])

    assert list(pages) == ["https://insee.fr/fr/statistiques/1"]
    assert EXCERPT in pages["https://insee.fr/fr/statistiques/1"]


@pytest.mark.parametrize(
    ("url", "excerpt", "reason"),
    [
        ("https://www.lemonde.fr/x", EXCERPT, "hors liste blanche"),
        ("https://insee.fr/autre", EXCERPT, "page non lue"),
        (PAGE_URL, "7,4 %", "extrait trop court"),
        (PAGE_URL, "le taux de chômage au sens du BIT est de 7,2 %", "extrait absent"),
    ],
)
def test_une_preuve_non_verifiable_est_ecartee(url: str, excerpt: str, reason: str) -> None:
    pages = read_pages([[fetch_block()]])

    kept, rejected = check_evidence([ProposedEvidence(url=url, extrait=excerpt)], pages, REGISTRY)

    assert kept == []
    assert reason in rejected[0]


def test_une_preuve_citee_mot_pour_mot_est_retenue() -> None:
    finding = decide(proposal(), read_pages([[fetch_block()]]), REGISTRY, THRESHOLD)

    assert finding.label is VerdictLabel.VRAI
    assert finding.shown and finding.needs_review
    assert [e.source_id for e in finding.evidence] == ["insee"]


def test_sans_preuve_verifiee_on_ne_montre_rien() -> None:
    finding = decide(proposal(), {}, REGISTRY, THRESHOLD)

    assert finding.label is VerdictLabel.INVERIFIABLE
    assert not finding.shown
    assert finding.proposed_label is VerdictLabel.VRAI


def test_la_regle_de_comparaison_tranche_a_la_place_du_modele() -> None:
    pages = read_pages([[fetch_block()]])

    trop_gentil = decide(proposal(comparaisons=[comparison("7.1")]), pages, REGISTRY, THRESHOLD)
    exact = decide(proposal(comparaisons=[comparison("7.4")]), pages, REGISTRY, THRESHOLD)

    assert trop_gentil.label is VerdictLabel.FAUX
    assert "VRAI proposé, FAUX selon la règle" in trop_gentil.notes[0]
    assert exact.label is VerdictLabel.VRAI


def test_une_comparaison_sans_preuve_retenue_est_ignoree() -> None:
    pages = read_pages([[fetch_block()]])
    other = comparison("7", url="https://insee.fr/autre")

    finding = decide(proposal(comparaisons=[other]), pages, REGISTRY, THRESHOLD)

    assert finding.label is VerdictLabel.VRAI
    assert "n'est pas une preuve retenue" in finding.rejected[0]


def test_un_sondage_ne_prouve_qu_une_attribution() -> None:
    url = "https://odoxa.fr/sondage/1"
    text = "Selon notre enquête, 75 % des Français sont opposés à la réforme des retraites."
    pages = read_pages([[fetch_block(url, text)]])
    evidence = [ProposedEvidence(url=url, extrait="75 % des Français sont opposés à la réforme")]

    fait = decide(proposal(preuves=evidence), pages, REGISTRY, THRESHOLD)
    attribution = decide(proposal(preuves=evidence, attribution=True), pages, REGISTRY, THRESHOLD)

    assert fait.label is VerdictLabel.INVERIFIABLE
    assert attribution.label is VerdictLabel.VRAI


def test_les_domaines_autorises_sont_des_hotes_sans_chemin() -> None:
    search_tool, fetch_tool = server_tools(REGISTRY)

    assert search_tool["allowed_domains"] == ["ec.europa.eu", "insee.fr", "odoxa.fr"]
    assert fetch_tool["allowed_callers"] == ["direct"]


class FakeStream:
    def __init__(self, message: BetaMessage) -> None:
        self.message = message

    def __enter__(self) -> "FakeStream":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get_final_message(self) -> BetaMessage:
        return self.message


class FakeClient:
    """Rejoue des réponses de l'API dans l'ordre, et garde les demandes reçues."""

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.replies = [BetaMessage.model_validate(m) for m in messages]
        self.requests: list[dict[str, Any]] = []
        self.beta = self
        self.messages = self

    def stream(self, **request: Any) -> FakeStream:
        self.requests.append(request)
        return FakeStream(self.replies[len(self.requests) - 1])


def message(stop_reason: str, content: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "stop_reason": stop_reason,
        "content": content,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


VERDICT_CALL = {
    "type": "tool_use",
    "id": "toolu_1",
    "name": "rendre_verdict",
    "input": proposal(comparaisons=[comparison("7.4")]).model_dump(mode="json"),
}
STATEMENT = Statement(
    "Le chômage est à 7,4 %.", "Emmanuel Macron", "Macron / Le Pen", date(2022, 4, 20)
)


@pytest.fixture(autouse=True)
def trace_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(search, "TRACE_DIR", tmp_path)
    return tmp_path


def test_recherche_complete_avec_reprise_apres_pause(trace_dir: Path) -> None:
    client = FakeClient(
        [message("pause_turn", [fetch_block()]), message("tool_use", [VERDICT_CALL])]
    )

    finding = research(STATEMENT, REGISTRY, THRESHOLD, client)  # type: ignore[arg-type]

    assert finding.label is VerdictLabel.VRAI and finding.shown
    assert len(client.requests) == 2
    assert client.requests[1]["messages"][-1]["role"] == "assistant"
    assert (trace_dir / f"{finding.trace_sha256}.json").exists()


@pytest.mark.parametrize(
    ("reply", "note"),
    [
        (message("refusal", []), "refusé"),
        (message("end_turn", [{"type": "text", "text": "Je ne sais pas."}]), "pas de verdict"),
        (
            message("tool_use", [{**VERDICT_CALL, "input": {"verdict": "VRAI"}}]),
            "mal formé",
        ),
    ],
)
def test_sans_verdict_exploitable_on_s_abstient(reply: dict[str, Any], note: str) -> None:
    finding = research(STATEMENT, REGISTRY, THRESHOLD, FakeClient([reply]))  # type: ignore[arg-type]

    assert finding.label is VerdictLabel.INVERIFIABLE and not finding.shown
    assert note in finding.notes[0]
