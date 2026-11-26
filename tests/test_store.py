import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from zetruth.sources.store import ResponseStore

MOMENT = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)


def test_une_reponse_enregistree_se_relit_a_l_identique(tmp_path: Path) -> None:
    store = ResponseStore(tmp_path)

    record = store.save("001", "https://insee.fr/x", b"<xml/>", MOMENT)

    assert store.latest("001") == (b"<xml/>", record)
    assert record.fetched_at == "2026-11-26T10:00:00+00:00"
    assert record.size == 6


def test_rien_en_stock_pour_une_cle_inconnue(tmp_path: Path) -> None:
    assert ResponseStore(tmp_path).latest("001") is None


def test_un_rafraichissement_garde_l_ancienne_reponse(tmp_path: Path) -> None:
    store = ResponseStore(tmp_path)
    old = store.save("001", "https://insee.fr/x", b"ancienne", MOMENT)
    new = store.save("001", "https://insee.fr/x", b"nouvelle", MOMENT)

    assert store.latest("001") == (b"nouvelle", new)
    assert store.read(old) == b"ancienne"


def test_chaque_appel_est_journalise(tmp_path: Path) -> None:
    store = ResponseStore(tmp_path)
    store.save("001", "https://insee.fr/a", b"a", MOMENT)
    store.save("002", "https://insee.fr/b", b"b", MOMENT)

    lines = store.journal_path.read_text(encoding="utf-8").splitlines()

    assert [json.loads(line)["url"] for line in lines] == [
        "https://insee.fr/a",
        "https://insee.fr/b",
    ]


def test_une_reponse_alteree_est_detectee(tmp_path: Path) -> None:
    store = ResponseStore(tmp_path)
    record = store.save("001", "https://insee.fr/x", b"original", MOMENT)
    (tmp_path / "raw" / record.sha256).write_bytes(b"modifie")

    with pytest.raises(ValueError, match="corrompue"):
        store.latest("001")


@pytest.mark.parametrize("key", ["../evil", "a/b", ""])
def test_une_cle_dangereuse_est_refusee(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError, match="clé de stockage invalide"):
        ResponseStore(tmp_path).save(key, "https://insee.fr/x", b"x", MOMENT)
