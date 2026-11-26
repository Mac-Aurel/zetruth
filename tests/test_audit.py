from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from zetruth.audit import AuditLog, code_version, file_fingerprints, replay, verify_and_record
from zetruth.indicators.catalog import load_catalog
from zetruth.indicators.values import IndicatorService
from zetruth.model import Utterance, VerdictLabel
from zetruth.normalization.countries import load_countries
from zetruth.normalization.normalize import Debate
from zetruth.sources.client import SourceClient
from zetruth.sources.registry import load_registry
from zetruth.sources.store import FetchRecord, PinnedStore, ResponseStore

# Série réelle 001688527 (chômage BIT), publications jusqu'en 2023.
FIXTURE = (Path(__file__).parent / "fixtures" / "insee_bdm_historique.xml").read_bytes()
DEBAT = Debate("Macron_Lepen_2", date(2022, 4, 20), date(2017, 5, 14))
SEUIL = Decimal("0.02")
MOMENT = datetime(2026, 11, 26, tzinfo=UTC)
SENTENCE = "Le taux de chômage est de 7,4 %."


def record_one(tmp_path: Path, sentence: str = SENTENCE):  # type: ignore[no-untyped-def]
    registry = load_registry()
    client = SourceClient(
        "insee", ResponseStore(tmp_path / "insee"), registry, 0, fetch=lambda url: FIXTURE,
        now=lambda: MOMENT,
    )  # fmt: skip
    service = IndicatorService(load_catalog(registry), {"insee": client})
    utterance = Utterance(source_file="Macron_Lepen_2--x.txt", turn=3, speaker="X", quote=sentence)
    return verify_and_record(
        utterance, DEBAT, service, {"insee": client}, SEUIL, countries=load_countries(),
        now=lambda: MOMENT,
    )  # fmt: skip


def test_l_enregistrement_contient_tout_ce_qu_il_faut_pour_rejouer(tmp_path: Path) -> None:
    outcomes, record = record_one(tmp_path)

    assert outcomes[0].verdict is not None
    assert outcomes[0].verdict.label is VerdictLabel.VRAI
    assert record.outcomes[0].verdict == outcomes[0].verdict
    assert [f.key for f in record.fetches] == ["001688527"]
    assert record.rules == file_fingerprints()
    assert record.code_version.startswith("0.1.0")


def test_aller_retour_dans_le_journal(tmp_path: Path) -> None:
    _, record = record_one(tmp_path)
    log = AuditLog(tmp_path / "journal.jsonl")

    log.append(record)
    log.append(record)

    assert log.read() == [record, record]
    assert AuditLog(tmp_path / "absent.jsonl").read() == []


def test_le_rejeu_redonne_le_meme_verdict_sans_reseau(tmp_path: Path) -> None:
    _, record = record_one(tmp_path)

    result = replay(record, {"insee": tmp_path / "insee"})

    assert result.identical
    assert result.differences == []
    assert result.changed_rules == []


def test_le_rejeu_utilise_la_reponse_enregistree_pas_la_plus_recente(tmp_path: Path) -> None:
    _, record = record_one(tmp_path)
    # Une réponse plus récente arrive dans la copie locale après coup.
    ResponseStore(tmp_path / "insee").save("001688527", "https://insee.fr/x", b"<autre/>", MOMENT)

    assert replay(record, {"insee": tmp_path / "insee"}).identical


def test_une_regle_modifiee_depuis_est_signalee(tmp_path: Path) -> None:
    _, record = record_one(tmp_path)
    rules = {**record.rules, "config/tolerances.toml": "0" * 64}
    altered = record.model_copy(update={"rules": rules})

    result = replay(altered, {"insee": tmp_path / "insee"})

    assert result.changed_rules == ["config/tolerances.toml"]


def test_un_verdict_different_au_rejeu_est_signale(tmp_path: Path) -> None:
    _, record = record_one(tmp_path)
    verdict = record.outcomes[0].verdict
    assert verdict is not None
    tampered = record.outcomes[0].model_copy(
        update={"verdict": verdict.model_copy(update={"label": VerdictLabel.FAUX})}
    )

    changed = record.model_copy(update={"outcomes": [tampered]})
    result = replay(changed, {"insee": tmp_path / "insee"})

    assert not result.identical
    assert "valeur 7.4" in result.differences[0]


def test_une_reponse_alteree_sur_le_disque_fait_echouer_le_rejeu(tmp_path: Path) -> None:
    _, record = record_one(tmp_path)
    (tmp_path / "insee" / "raw" / record.fetches[0].sha256).write_bytes(b"falsifie")

    with pytest.raises(ValueError, match="corrompue"):
        replay(record, {"insee": tmp_path / "insee"})


def test_une_reponse_absente_du_journal_fait_echouer_le_rejeu(tmp_path: Path) -> None:
    _, record = record_one(tmp_path)

    with pytest.raises(LookupError, match="absente du journal"):
        replay(record.model_copy(update={"fetches": []}), {"insee": tmp_path / "insee"})


def test_un_rejeu_ne_telecharge_rien(tmp_path: Path) -> None:
    store = PinnedStore(tmp_path, [])

    with pytest.raises(RuntimeError, match="ne télécharge rien"):
        store.save("k", "https://insee.fr/x", b"x", MOMENT)
    with pytest.raises(LookupError):
        store.latest("k")


def test_drain_used(tmp_path: Path) -> None:
    client = SourceClient(
        "insee", ResponseStore(tmp_path), load_registry(), 0, fetch=lambda url: b"x"
    )
    url = "https://api.insee.fr/series/BDM/V1/data/SERIES_BDM/1"

    client.get("1", url, lambda content: content)
    client.get("1", url, lambda content: content)

    used = client.drain_used()
    assert [r.key for r in used] == ["1", "1"]
    assert all(isinstance(r, FetchRecord) for r in used)
    assert client.drain_used() == []


def test_version_du_code() -> None:
    assert "commit" in code_version()
