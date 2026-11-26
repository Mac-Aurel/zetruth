from datetime import date
from decimal import Decimal

import pytest

from zetruth.series.history import PublishedValue, RevisionConflictError, SeriesHistory, Vintage


def history(*vintages: Vintage) -> SeriesHistory:
    return SeriesHistory("001", "Taux de chômage", "POURCENT", vintages)


def vintage(day: str, values: dict[str, str]) -> Vintage:
    return Vintage(date.fromisoformat(day), {k: Decimal(v) for k, v in values.items()})


CHOMAGE = history(
    vintage("2021-11-19", {"2021-Q3": "8.1"}),
    vintage("2022-02-18", {"2021-Q3": "8.0", "2021-Q4": "7.4"}),
    vintage("2023-02-14", {"2021-Q3": "8.0", "2021-Q4": "7.5"}),
)


def test_on_prend_la_valeur_connue_a_la_date_du_debat_pas_la_valeur_revisee() -> None:
    assert CHOMAGE.value_as_of("2021-Q4", date(2022, 4, 20)) == PublishedValue(
        "2021-Q4", Decimal("7.4"), date(2022, 2, 18)
    )
    assert CHOMAGE.latest("2021-Q4") == PublishedValue("2021-Q4", Decimal("7.5"), date(2023, 2, 14))


def test_une_publication_du_jour_meme_compte() -> None:
    known = CHOMAGE.value_as_of("2021-Q3", date(2022, 2, 18))

    assert known is not None
    assert known.value == Decimal("8.0")


def test_la_veille_d_une_revision_on_a_encore_l_ancienne_valeur() -> None:
    known = CHOMAGE.value_as_of("2021-Q3", date(2022, 2, 17))

    assert known == PublishedValue("2021-Q3", Decimal("8.1"), date(2021, 11, 19))


def test_rien_avant_la_premiere_publication() -> None:
    assert CHOMAGE.value_as_of("2021-Q3", date(2021, 11, 18)) is None
    assert CHOMAGE.value_as_of("2021-Q4", date(2021, 12, 31)) is None
    assert CHOMAGE.value_as_of("2012-Q1", date(2012, 5, 2)) is None


def test_les_revisions_ne_gardent_que_les_changements() -> None:
    assert [(r.published_on.isoformat(), str(r.value)) for r in CHOMAGE.revisions("2021-Q3")] == [
        ("2021-11-19", "8.1"),
        ("2022-02-18", "8.0"),
    ]


def test_l_ordre_des_publications_n_a_pas_d_importance() -> None:
    shuffled = history(*reversed(CHOMAGE.vintages))

    assert shuffled.value_as_of("2021-Q4", date(2022, 4, 20)) == CHOMAGE.value_as_of(
        "2021-Q4", date(2022, 4, 20)
    )
    assert shuffled.revisions("2021-Q3") == CHOMAGE.revisions("2021-Q3")


def test_deux_publications_identiques_le_meme_jour_sont_acceptees() -> None:
    doublon = history(
        vintage("2020-03-11", {"2019-Q4": "8.1"}), vintage("2020-03-11", {"2019-Q4": "8.1"})
    )

    assert doublon.latest("2019-Q4") == PublishedValue("2019-Q4", Decimal("8.1"), date(2020, 3, 11))


def test_deux_publications_contradictoires_le_meme_jour_sont_refusees() -> None:
    conflit = history(
        vintage("2020-03-11", {"2019-Q4": "8.1"}), vintage("2020-03-11", {"2019-Q4": "8.2"})
    )

    with pytest.raises(RevisionConflictError):
        conflit.latest("2019-Q4")


def test_premiere_publication() -> None:
    assert CHOMAGE.earliest_publication() == date(2021, 11, 19)
    assert history().earliest_publication() is None
