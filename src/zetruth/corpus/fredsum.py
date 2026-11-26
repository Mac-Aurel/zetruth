"""Téléchargement des transcriptions FREDSum et découpage en tours de parole.

FREDSum (Rennard et al., EMNLP 2023) est publié sous licence CC BY-SA 4.0.
On utilise la version GitHub, dont les noms de locuteurs sont standardisés,
à une révision figée pour que le corpus soit reproductible.
"""

import csv
import re
import sys
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

REVISION = "7ccfaa7247538b2ec083e2a49676ef5bcaa41ca8"
BASE_URL = "https://raw.githubusercontent.com/linagora-labs/FREDSum"
TIMEOUT_SECONDS = 30

SELECTION_FILE = Path("data/reference/fredsum_selection.txt")
RAW_DIR = Path("data/raw/fredsum")
TRANSCRIPTS_DIR = RAW_DIR / "transcripts"
TURNS_DIR = RAW_DIR / "tours"

# « Emmanuel Macron : ... » ou « P1 : ... » (présentateurs) en début de ligne.
_SPEAKER_TAG = re.compile(r"^([A-ZÀ-Ý][\w'’.-]*(?: [A-ZÀ-Ý][\w'’.-]*){0,3}) ?: (.*)$")

Fetcher = Callable[[str], bytes]


@dataclass(frozen=True)
class Turn:
    index: int
    speaker: str
    text: str


def http_fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
        content: bytes = response.read()
        return content


def file_url(name: str, revision: str = REVISION) -> str:
    return f"{BASE_URL}/{revision}/transcript/{name}"


def download(
    names: Iterable[str],
    dest_dir: Path,
    fetch: Fetcher = http_fetch,
    revision: str = REVISION,
) -> list[Path]:
    """Télécharge les transcriptions absentes. Relancer ne retélécharge rien."""
    paths = []
    for name in names:
        path = dest_dir / name
        if not path.exists():
            content = fetch(file_url(name, revision))
            content.decode("utf-8")  # on refuse d'écrire un fichier illisible
            dest_dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(content)
            tmp.replace(path)
        paths.append(path)
    return paths


def split_turns(transcript: str) -> list[Turn]:
    """Découpe une transcription en tours de parole, un tour par ligne.

    Une ligne sans nom en tête est la suite du tour précédent. Deux tours
    consécutifs du même locuteur sont fusionnés.
    """
    speakers: list[str] = []
    texts: list[str] = []
    for line in transcript.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _SPEAKER_TAG.match(line)
        if match:
            speaker, text = match.group(1), match.group(2).strip()
        elif speakers:
            speaker, text = speakers[-1], line
        else:
            raise ValueError(f"Transcription sans locuteur au début : {line[:60]!r}")

        if speakers and speakers[-1] == speaker:
            texts[-1] = f"{texts[-1]} {text}".strip()
        else:
            speakers.append(speaker)
            texts.append(text)
    return [Turn(i, s, t) for i, (s, t) in enumerate(zip(speakers, texts, strict=True))]


def load_turns(path: Path) -> list[Turn]:
    return split_turns(path.read_text(encoding="utf-8"))


def write_turns_csv(turns: list[Turn], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["tour", "locuteur", "texte"])
        writer.writerows((t.index, t.speaker, t.text) for t in turns)


def read_selection(path: Path) -> list[str]:
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def main() -> int:
    names = read_selection(SELECTION_FILE)
    for path in download(names, TRANSCRIPTS_DIR):
        turns = load_turns(path)
        write_turns_csv(turns, TURNS_DIR / path.with_suffix(".csv").name)
        speakers = sorted({t.speaker for t in turns})
        print(f"{path.name} : {len(turns)} tours, {', '.join(speakers)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
