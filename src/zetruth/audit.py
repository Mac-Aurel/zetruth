"""Journal d'audit : chaque verdict du pipeline doit pouvoir être rejoué à l'identique.

Un enregistrement par phrase vérifiée contient la phrase et son contexte, le
débat, les résultats (verdicts ou raisons d'abstention), l'empreinte de chaque
réponse des sources utilisée, l'empreinte des fichiers de règles et la version
du code. Les réponses brutes sont dans la copie locale (sources/store.py), sous
leur empreinte : le rejeu les relit sans aucun appel réseau.

    uv run python -m zetruth.audit rejouer [journal]
"""

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from zetruth import __version__
from zetruth.indicators.catalog import load_catalog
from zetruth.indicators.values import IndicatorService
from zetruth.model import Utterance, Verdict
from zetruth.normalization.countries import Country, load_countries
from zetruth.normalization.normalize import Debate
from zetruth.pipeline import Outcome, verify_sentence
from zetruth.sources.client import SourceClient
from zetruth.sources.registry import load_registry
from zetruth.sources.store import FetchRecord, PinnedStore

JOURNAL_FILE = Path("data/audit/journal.jsonl")
RULE_FILES = (
    Path("config/sources.toml"),
    Path("config/indicateurs.toml"),
    Path("config/tolerances.toml"),
    Path("config/pays.toml"),
    Path("data/reference/debats.toml"),
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RecordedOutcome(_Frozen):
    mention: dict[str, str]
    verdict: Verdict | None
    reason: str | None


class Fetch(_Frozen):
    source_id: str
    key: str
    url: str
    fetched_at: str
    sha256: str
    size: int

    def record(self) -> FetchRecord:
        return FetchRecord(self.key, self.url, self.fetched_at, self.sha256, self.size)


class AuditRecord(_Frozen):
    created_at: datetime
    code_version: str
    rules: dict[str, str]  # fichier de règles -> empreinte SHA-256
    debate: str
    debate_date: date
    incumbent_since: date | None
    utterance: Utterance
    context: str
    threshold: Decimal
    outcomes: list[RecordedOutcome]
    fetches: list[Fetch]


def file_fingerprints(paths: Sequence[Path] = RULE_FILES) -> dict[str, str]:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def code_version() -> str:
    """Version du paquet et commit git, avec « modifié » si des fichiers ne sont pas commités."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return f"{__version__}, commit inconnu"
    return f"{__version__}, commit {commit}{', modifié' if dirty else ''}"


def _mention(outcome: Outcome) -> dict[str, str]:
    m = outcome.mention
    return {
        "qualificatif": str(m.qualifier),
        "valeur": str(m.value),
        "valeur_max": "" if m.upper is None else str(m.upper),
        "unite": m.unit,
        "sens": str(m.direction),
        "role": str(m.role),
    }


def recorded(outcomes: Sequence[Outcome]) -> list[RecordedOutcome]:
    return [
        RecordedOutcome(mention=_mention(o), verdict=o.verdict, reason=o.reason) for o in outcomes
    ]


def verify_and_record(
    utterance: Utterance,
    debate: Debate,
    service: IndicatorService,
    clients: Mapping[str, SourceClient],
    threshold: Decimal,
    context: str = "",
    countries: Mapping[str, Country] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[list[Outcome], AuditRecord]:
    """Vérifie une phrase et produit l'enregistrement qui permet de la rejouer."""
    for client in clients.values():
        client.drain_used()
    outcomes = verify_sentence(utterance, debate, service, threshold, context, countries)
    # Une même réponse peut servir plusieurs fois (période, puis valeur) : une seule ligne.
    fetches = list(
        dict.fromkeys(
            Fetch(source_id=source_id, **asdict(record))
            for source_id, client in clients.items()
            for record in client.drain_used()
        )
    )
    record = AuditRecord(
        created_at=now(),
        code_version=code_version(),
        rules=file_fingerprints(),
        debate=debate.name,
        debate_date=debate.held_on,
        incumbent_since=debate.incumbent_since,
        utterance=utterance,
        context=context,
        threshold=threshold,
        outcomes=recorded(outcomes),
        fetches=fetches,
    )
    return outcomes, record


class AuditLog:
    """Journal en ajout seul, un enregistrement JSON par ligne."""

    def __init__(self, path: Path = JOURNAL_FILE) -> None:
        self.path = path

    def append(self, record: AuditRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")

    def read(self) -> list[AuditRecord]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [AuditRecord.model_validate_json(line) for line in lines if line.strip()]


@dataclass(frozen=True)
class Replay:
    identical: bool
    changed_rules: list[str]
    differences: list[str]


def _offline(url: str) -> bytes:
    raise RuntimeError(f"appel réseau interdit pendant un rejeu : {url}")


def replay(
    record: AuditRecord,
    cache_dirs: Mapping[str, Path],
    min_intervals: Mapping[str, float] | None = None,
) -> Replay:
    """Refait la vérification avec exactement les réponses enregistrées, sans réseau."""
    registry = load_registry()
    clients = {}
    for source_id, root in cache_dirs.items():
        pinned = [f.record() for f in record.fetches if f.source_id == source_id]
        clients[source_id] = SourceClient(
            source_id,
            PinnedStore(root, pinned),
            registry,
            (min_intervals or {}).get(source_id, 0),
            fetch=_offline,
        )
    service = IndicatorService(load_catalog(registry), clients)
    debate = Debate(record.debate, record.debate_date, record.incumbent_since)
    outcomes = verify_sentence(
        record.utterance, debate, service, record.threshold, record.context, load_countries()
    )

    current = file_fingerprints()
    changed = [f for f, digest in record.rules.items() if current.get(f) != digest]
    replayed = recorded(outcomes)
    differences = []
    if len(replayed) != len(record.outcomes):
        differences.append(f"{len(record.outcomes)} résultats enregistrés, {len(replayed)} rejoués")
    for before, after in zip(record.outcomes, replayed, strict=False):
        if before != after:
            differences.append(
                f"valeur {before.mention['valeur']} : "
                f"{_summary(before)} enregistré, {_summary(after)} rejoué"
            )
    return Replay(not differences, changed, differences)


def _summary(outcome: RecordedOutcome) -> str:
    if outcome.verdict is None:
        return f"abstention ({outcome.reason})"
    return json.dumps(
        {"verdict": outcome.verdict.label, "periode": outcome.verdict.claim.period},
        ensure_ascii=False,
    )


def main(argv: list[str] | None = None) -> int:
    from zetruth.sources import eurostat, insee_bdm

    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] != "rejouer":
        print("usage : python -m zetruth.audit rejouer [journal]", file=sys.stderr)
        return 2
    log = AuditLog(Path(args[1]) if len(args) > 1 else JOURNAL_FILE)
    records = log.read()
    if not records:
        print(f"journal vide : {log.path}")
        return 0
    cache_dirs = {"insee": insee_bdm.CACHE_DIR, "eurostat": eurostat.CACHE_DIR}
    failures = 0
    for record in records:
        result = replay(record, cache_dirs)
        status = "identique" if result.identical else "DIFFÉRENT"
        where = f"{record.debate} tour {record.utterance.turn}"
        print(f"{status:10} {where} : {record.utterance.quote[:70]}")
        for difference in result.differences:
            print(f"    {difference}")
        if result.changed_rules:
            print(f"    règles modifiées depuis : {', '.join(result.changed_rules)}")
        failures += not result.identical
    print(f"\n{len(records)} enregistrements, {len(records) - failures} identiques")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
