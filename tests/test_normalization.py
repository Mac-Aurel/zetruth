from datetime import date

import pytest

from zetruth.indicators.catalog import load_catalog
from zetruth.normalization.countries import find_country, load_countries
from zetruth.normalization.mentions import Direction, find_mentions
from zetruth.normalization.normalize import (
    Debate,
    Target,
    clause,
    debate_for,
    load_debates,
    match_indicator,
    target_for,
)
from zetruth.normalization.numbers import find_numbers
from zetruth.series.periods import last_period_before, period_end
from zetruth.sources.registry import load_registry

CATALOG = load_catalog(load_registry())
DEBAT_2022 = Debate("Macron_Lepen_2", date(2022, 4, 20), date(2017, 5, 14))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("le chômage est à 7,4 %", [("7.4", None)]),
        ("1 100 euros", [("1100", None)]),
        ("six cents milliards d'euros", [("600", "milliards")]),
        ("1 million 200 000 Français", [("1.2", "millions")]),
        ("9 millions 800 000 pauvres", [("9.8", "millions")]),
        ("quatre et demi pour cent", [("4.5", None)]),
        ("cinq virgule cinq pour cent", [("5.5", None)]),
        ("soixante-quinze pour cent", [("75", None)]),
        ("quatre-vingt-dix euros", [("90", None)]),
        ("vingt et un ans", [("21", None)]),
        ("soixante et onze", [("71", None)]),
        ("deux mille quinze et deux mille dix-huit", [("2015", None), ("2018", None)]),
        ("un million d'emplois", [("1", "millions")]),
        ("une mesure, un français", []),
    ],
)
def test_lecture_des_nombres(text: str, expected: list[tuple[str, str | None]]) -> None:
    assert [(str(m.value), m.scale) for m in find_numbers(text)] == expected


def mention_of(sentence: str) -> list[tuple[str, str, str | None, str, str, str]]:
    return [
        (m.qualifier, str(m.value), str(m.upper) if m.upper else None, m.unit, m.direction, m.role)
        for m in find_mentions(sentence)
    ]


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        (
            "en baissant de plus de 2 points le chômage",
            [("plus_de", "2", None, "points", "baisse", "seul")],
        ),
        (
            "le chômage est passé de 9,6 à 7,4 %",
            [
                ("egal", "9.6", None, "%", "niveau", "depart"),
                ("egal", "7.4", None, "%", "niveau", "arrivee"),
            ],
        ),
        (
            "une inflation à peu près quatre à quatre et demi pour cent",
            [("entre", "4", "4.5", "%", "niveau", "seul")],
        ),
        (
            "il a créé 600 milliards d'euros de dette supplémentaire",
            [("egal", "600", None, "milliards d'euros", "hausse", "seul")],
        ),
        ("5,5 millions d'inscrits", [("egal", "5.5", None, "millions", "niveau", "seul")]),
        ("deux fois moins d'inflation", [("egal", "2", None, "fois", "niveau", "seul")]),
        ("en deux mille dix-sept, à vingt-huit ans", []),
    ],
)
def test_valeurs_chiffrees(sentence: str, expected: list[tuple[str, ...]]) -> None:
    assert mention_of(sentence) == expected


def test_le_sens_ne_deborde_pas_sur_la_valeur_suivante() -> None:
    mentions = find_mentions(
        "en baissant de plus de 2 points le chômage, 1 million 200 000 Français ont un travail"
    )

    assert [m.direction for m in mentions] == [Direction.BAISSE, Direction.NIVEAU]


@pytest.mark.parametrize(
    ("period", "end"),
    [("2021", date(2021, 12, 31)), ("2021-Q1", date(2021, 3, 31)), ("2024-02", date(2024, 2, 29))],
)
def test_fin_de_periode(period: str, end: date) -> None:
    assert period_end(period) == end


def test_code_de_periode_inconnu() -> None:
    with pytest.raises(ValueError):
        period_end("T4 2021")


@pytest.mark.parametrize(
    ("event", "frequency", "expected"),
    [
        (date(2017, 5, 14), "trimestrielle", "2017-Q1"),
        (date(2017, 5, 14), "mensuelle", "2017-04"),
        (date(2017, 5, 14), "annuelle", "2016"),
        (date(2017, 2, 1), "trimestrielle", "2016-Q4"),
        (date(2017, 1, 15), "mensuelle", "2016-12"),
    ],
)
def test_derniere_periode_avant_un_evenement(event: date, frequency: str, expected: str) -> None:
    assert last_period_before(event, frequency) == expected


def indicator_for(sentence: str) -> str | None:
    mentions = find_mentions(sentence)
    found = [
        match_indicator(
            m,
            sentence,
            CATALOG,
            mentions[i - 1].end if i else 0,
            mentions[i + 1].start if i + 1 < len(mentions) else None,
        )
        for i, m in enumerate(mentions)
    ]
    return ",".join(f.id if f else "aucun" for f in found)


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("le taux de chômage est de 7,4 %", "chomage_bit"),
        ("les chômeurs A, B, C étaient 5,5 millions", "demandeurs_emploi_abc"),
        ("l'inflation est de 4,5 %", "inflation_ipc"),
        ("la croissance est de 2,8 % et l'inflation de 4,4 %", "aucun,inflation_ipc"),
        ("un déficit de 85 milliards de la balance commerciale", "aucun"),
        ("une dette de 2 800 milliards d'euros", "dette_publique"),
        ("9,8 millions de pauvres", "aucun"),
        ("en baissant de plus de 2 points le chômage et donc l'inflation", "chomage_bit"),
    ],
)
def test_choix_de_l_indicateur(sentence: str, expected: str) -> None:
    assert indicator_for(sentence) == expected


def target_of(sentence: str, context: str = "") -> Target | str:
    mentions = find_mentions(sentence)
    return target_for(mentions[-1], sentence, DEBAT_2022, CATALOG, context)


def test_niveau_a_la_derniere_periode() -> None:
    target = target_of("le taux de chômage est de 7,4 %")

    assert isinstance(target, Target)
    assert (target.indicator.id, target.evolution, target.start) == ("chomage_bit", False, None)


def test_evolution_depuis_l_entree_en_fonction() -> None:
    target = target_of("vous avez créé 600 milliards d'euros de dette supplémentaire en cinq ans")

    assert isinstance(target, Target)
    assert (target.evolution, target.decrease, target.start) == (True, False, "2017-Q1")


def test_niveau_au_moment_de_l_election() -> None:
    target = target_of("les chômeurs A, B, C étaient 5,5 millions quand vous avez été élu")

    assert isinstance(target, Target)
    assert (target.evolution, target.start) == (False, "2017-Q1")


@pytest.mark.parametrize(
    ("sentence", "context", "reason"),
    [
        ("l'inflation de 4,4 %", "dans les prévisions de la Banque de France", "prévision"),
        ("l'inflation est de 4,5 % en mars 2022", "", "période explicite"),
        ("deux fois moins d'inflation qu'en Espagne", "", "comparaison relative"),
        ("la France a 60 % de moins d'inflation que l'Allemagne", "", "comparaison relative"),
        ("partout autour de nous l'inflation est de 8 %", "", "sans pays précis"),
        ("l'inflation est de 4,5 % en mars", "", "période explicite"),
        ("9,8 millions de pauvres", "", "aucun indicateur"),
    ],
)
def test_abstentions(sentence: str, context: str, reason: str) -> None:
    target = target_of(sentence, context)

    assert isinstance(target, str)
    assert reason in target


def test_evolution_sans_mandat_de_reference() -> None:
    sans_sortant = Debate("Macron_Lepen_1", date(2017, 5, 3))
    sentence = "le chômage a baissé de 2 points"

    target = target_for(find_mentions(sentence)[0], sentence, sans_sortant, CATALOG)

    assert isinstance(target, str)
    assert "sans mandat" in target


def test_debats_du_corpus() -> None:
    debates = load_debates()

    debate = debate_for("Macron_Lepen_2--Partie_1_Pouvoir_D_Achat.txt", debates)
    assert debate is not None
    assert (debate.name, debate.held_on, debate.incumbent_since) == (
        DEBAT_2022.name,
        DEBAT_2022.held_on,
        DEBAT_2022.incumbent_since,
    )
    assert debate.title.startswith("Débat Macron / Le Pen")
    assert debate_for("Inconnu--Partie_1.txt", debates) is None


COUNTRIES = load_countries()


def test_pays_cite() -> None:
    netherlands = find_country("douze pour cent aux pays-bas", COUNTRIES)
    poland = find_country("neuf pour cent en Pologne", COUNTRIES)

    assert netherlands is not None and poland is not None
    assert (netherlands.code, poland.code) == ("NL", "PL")
    assert netherlands.in_euro_area(date(2022, 4, 13))
    assert not poland.in_euro_area(date(2022, 4, 13))
    assert not COUNTRIES["HR"].in_euro_area(date(2022, 4, 13))
    assert COUNTRIES["HR"].in_euro_area(date(2023, 6, 1))
    assert find_country("en France", COUNTRIES) is None
    assert find_country("en Espagne et en Italie", COUNTRIES) is None


def test_proposition_d_une_valeur() -> None:
    sentence = "On attend le 1er janvier prochain et parce que là on a une inflation de 4 %."
    (mention,) = [m for m in find_mentions(sentence) if m.unit == "%"]

    assert clause(mention, sentence) == " parce que là on a une inflation de 4 %."


def targets(sentence: str, context: str = "") -> list[Target | str]:
    mentions = find_mentions(sentence)
    return [
        target_for(
            m,
            sentence,
            DEBAT_2022,
            CATALOG,
            context,
            mentions[i - 1].end if i else 0,
            mentions[i + 1].start if i + 1 < len(mentions) else None,
            COUNTRIES,
        )
        for i, m in enumerate(mentions)
    ]


def test_comparaisons_par_pays() -> None:
    sentence = "C'est douze pour cent aux pays-bas, neuf pour cent en pologne."

    found = targets(sentence, context="il y a une inflation très forte en France.")

    assert all(isinstance(t, Target) for t in found)
    netherlands, poland = (t for t in found if isinstance(t, Target))
    assert netherlands.indicator.id == poland.indicator.id == "inflation_ipch"
    assert netherlands.country is not None and netherlands.country.code == "NL"
    assert poland.country is not None and poland.country.code == "PL"
    assert netherlands.note == "sujet déduit de ce qui précède la phrase"


def test_pays_sans_serie_par_pays() -> None:
    (target,) = targets("le chômage est de 7 % en Espagne")

    assert isinstance(target, str)
    assert "aucune série par pays" in target


def test_une_annee_dans_une_autre_proposition_ne_bloque_pas() -> None:
    sentence = (
        "Des gens qui se sont présentés, en deux mille dix-sept, comme des experts, "
        "ont rallongé la dette de six cents milliards d'euros."
    )

    (target,) = targets(sentence)

    assert isinstance(target, Target)
    assert (target.indicator.id, target.evolution) == ("dette_publique", True)
