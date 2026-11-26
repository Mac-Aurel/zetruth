"""Stockage des réponses brutes des sources, avec journal des appels.

Chaque réponse est gardée telle quelle, nommée par son empreinte SHA-256 :
une donnée utilisée pour un verdict peut toujours être retrouvée et relue,
même après un rafraîchissement. Le journal (un JSON par ligne) liste tous
les appels réseau dans l'ordre.

Arborescence :
    <racine>/raw/<sha256>         contenu brut
    <racine>/latest/<clé>.json    dernier appel pour cette clé
    <racine>/journal.jsonl        tous les appels
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

_SAFE_KEY = re.compile(r"^[\w.-]+$")


@dataclass(frozen=True)
class FetchRecord:
    key: str
    url: str
    fetched_at: str
    sha256: str
    size: int


class ResponseStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def journal_path(self) -> Path:
        return self.root / "journal.jsonl"

    def save(self, key: str, url: str, content: bytes, fetched_at: datetime) -> FetchRecord:
        digest = hashlib.sha256(content).hexdigest()
        record = FetchRecord(key, url, fetched_at.isoformat(), digest, len(content))

        raw_path = self.root / "raw" / digest
        if not raw_path.exists():
            _write_atomic(raw_path, content)
        _write_atomic(self._latest_path(key), json.dumps(asdict(record)).encode())
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open("a", encoding="utf-8") as journal:
            journal.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        return record

    def latest(self, key: str) -> tuple[bytes, FetchRecord] | None:
        path = self._latest_path(key)
        if not path.exists():
            return None
        record = FetchRecord(**json.loads(path.read_text(encoding="utf-8")))
        return self.read(record), record

    def read(self, record: FetchRecord) -> bytes:
        content = (self.root / "raw" / record.sha256).read_bytes()
        if hashlib.sha256(content).hexdigest() != record.sha256:
            raise ValueError(f"réponse stockée corrompue : {record.sha256}")
        return content

    def _latest_path(self, key: str) -> Path:
        if not _SAFE_KEY.match(key):
            raise ValueError(f"clé de stockage invalide : {key!r}")
        return self.root / "latest" / f"{key}.json"


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)


class PinnedStore(ResponseStore):
    """Copie locale figée sur des réponses précises, pour rejouer un verdict.

    latest() renvoie la réponse enregistrée dans le journal pour cette clé, même
    si une réponse plus récente a été téléchargée depuis. Rien ne peut être ajouté.
    """

    def __init__(self, root: Path, pinned: list[FetchRecord]) -> None:
        super().__init__(root)
        self._pinned = {record.key: record for record in pinned}

    def latest(self, key: str) -> tuple[bytes, FetchRecord] | None:
        record = self._pinned.get(key)
        if record is None:
            raise LookupError(f"réponse absente du journal pour {key!r}")
        return self.read(record), record

    def save(self, key: str, url: str, content: bytes, fetched_at: datetime) -> FetchRecord:
        raise RuntimeError("un rejeu ne télécharge rien")
