from pathlib import Path

import pytest

from zetruth.corpus.fredsum import Turn, download, file_url, read_selection, split_turns


def test_un_tour_par_ligne() -> None:
    transcript = "P1 : Parlons du chômage.\n\nEmmanuel Macron : Il a baissé.\nMarine Le Pen : Non."

    assert split_turns(transcript) == [
        Turn(0, "P1", "Parlons du chômage."),
        Turn(1, "Emmanuel Macron", "Il a baissé."),
        Turn(2, "Marine Le Pen", "Non."),
    ]


def test_une_ligne_sans_locuteur_prolonge_le_tour_precedent() -> None:
    turns = split_turns("Nicolas Sarkozy : Le chômage\na baissé de 5 %.")

    assert turns == [Turn(0, "Nicolas Sarkozy", "Le chômage a baissé de 5 %.")]


def test_deux_tours_consecutifs_du_meme_locuteur_sont_fusionnes() -> None:
    turns = split_turns("Gérald Darmanin : Alors.\nGérald Darmanin : D'abord, l'inflation.")

    assert turns == [Turn(0, "Gérald Darmanin", "Alors. D'abord, l'inflation.")]


def test_les_noms_composes_et_accentues_sont_reconnus() -> None:
    turns = split_turns("Léa Salamé : Question.\nNathalie Saint-Cricq : Autre question.")

    assert [t.speaker for t in turns] == ["Léa Salamé", "Nathalie Saint-Cricq"]


def test_un_deux_points_au_milieu_d_une_phrase_n_est_pas_un_locuteur() -> None:
    turns = split_turns("François Hollande : Je vous le dis : le chômage a augmenté.")

    assert turns == [Turn(0, "François Hollande", "Je vous le dis : le chômage a augmenté.")]


def test_une_transcription_sans_locuteur_au_debut_est_refusee() -> None:
    with pytest.raises(ValueError, match="sans locuteur"):
        split_turns("texte orphelin\nP1 : Bonsoir.")


def test_le_telechargement_ne_refait_pas_les_fichiers_existants(tmp_path: Path) -> None:
    (tmp_path / "deja_la.txt").write_text("P1 : ancien", encoding="utf-8")
    requested: list[str] = []

    def fake_fetch(url: str) -> bytes:
        requested.append(url)
        return b"P1 : nouveau"

    paths = download(["deja_la.txt", "nouveau.txt"], tmp_path, fetch=fake_fetch, revision="abc")

    assert requested == [file_url("nouveau.txt", "abc")]
    assert [p.read_text(encoding="utf-8") for p in paths] == ["P1 : ancien", "P1 : nouveau"]


def test_un_contenu_illisible_n_est_pas_ecrit(tmp_path: Path) -> None:
    with pytest.raises(UnicodeDecodeError):
        download(["casse.txt"], tmp_path, fetch=lambda url: b"\xff\xfe\xfa")

    assert not (tmp_path / "casse.txt").exists()


def test_la_selection_ignore_commentaires_et_lignes_vides(tmp_path: Path) -> None:
    selection = tmp_path / "selection.txt"
    selection.write_text("# commentaire\n\na.txt\n  b.txt  \n", encoding="utf-8")

    assert read_selection(selection) == ["a.txt", "b.txt"]
