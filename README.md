# zetruth

Vérification des affirmations factuelles pendant les débats politiques, à partir de sources officielles uniquement.

## Pourquoi

Pendant un débat télévisé, les chiffres s'enchaînent : chômage, dette, inflation, délinquance, votes à l'Assemblée. Personne n'a le temps de les vérifier sur le moment, et le fact-checking arrive en général le lendemain, quand plus personne ne regarde.

L'idée est de vérifier ces affirmations pendant le débat, en remontant systématiquement à la source primaire (INSEE, Eurostat, Légifrance, scrutins publics...) et en donnant le contexte nécessaire pour comprendre le chiffre.

## Le principe

On ne vérifie que des faits. « Il faut baisser les impôts » est une opinion, on n'y touche pas. « Les impôts ont augmenté de 10 % depuis 2017 » se vérifie.

On ne s'appuie que sur des sources officielles, listées à l'avance. Un article de presse ou une cellule de fact-checking peut aider à trouver la bonne source, mais ne sert jamais de preuve.

Si on ne peut pas trancher, on le dit. Un verdict faux est bien pire qu'une absence de verdict.

La même méthode s'applique à tous les intervenants, quel que soit leur bord.

## Les verdicts

Un simple vrai/faux ne suffit pas. Un chiffre exact présenté de façon à faire croire autre chose, ce n'est pas « vrai ». D'où six catégories :

| Verdict | Signification |
|---|---|
| VRAI | Correspond aux données officielles (valeur, période, périmètre). |
| FAUX | Contredit par la source officielle. |
| TROMPEUR | Chiffre exact, mais présenté pour mener à une conclusion fausse (période choisie, périmètre changé, contexte omis). |
| IMPRÉCIS | Bon ordre de grandeur, mais un écart au-delà de la tolérance prévue pour ce type de donnée. |
| INVÉRIFIABLE | Aucune source officielle ne permet de trancher. |
| NON FACTUEL | Opinion, promesse ou prédiction. Pas de verdict. |

Chaque verdict est accompagné de la citation exacte et de son auteur, de la valeur officielle avec sa source (organisme, série, date de publication, date de consultation), de l'écart constaté, du contexte historique et d'un niveau de confiance.

Quelques pièges qu'il faut gérer explicitement :

- le chômage au sens du BIT (INSEE) et les demandeurs d'emploi de catégorie A (France Travail) sont deux chiffres officiels différents
- les données sont révisées, un chiffre a pu être juste au moment où il a été publié
- France métropolitaine ou France entière, euros courants ou constants, brut ou net

## Sources utilisées

| Domaine | Sources |
|---|---|
| Économie et social | INSEE, DARES, DREES, France Travail |
| Finances publiques | Cour des comptes, Ministère de l'Économie, Banque de France, Haut Conseil des finances publiques |
| Droit | Légifrance, Journal officiel, Conseil constitutionnel, Conseil d'État |
| Parlement | Assemblée nationale, Sénat (scrutins publics, open data) |
| Données ouvertes | data.gouv.fr, vie-publique.fr |
| Sécurité, immigration | SSMSI, DGEF, OFPRA |
| International | Eurostat, OCDE, FMI, Banque mondiale, ONU |
| Énergie, climat | RTE, SDES, CITEPA |
| Santé | Santé publique France, DREES, Assurance maladie |

Les API officielles sont préférées au scraping. Chaque appel est tracé.

## Comment ça fonctionne

1. Transcription de l'audio et identification de qui parle
2. Découpage en phrases et repérage du sujet
3. Tri entre affirmations vérifiables et le reste (opinions, promesses, prédictions)
4. Mise en forme de l'affirmation : indicateur, valeur, unité, période, périmètre
5. Choix des sources adaptées au sujet
6. Récupération des données officielles
7. Comparaison des chiffres
8. Rédaction du verdict avec son contexte
9. Validation par un humain avant toute diffusion

La comparaison des chiffres se fait en code, pas par un modèle de langage. Un LLM peut aider à extraire l'affirmation ou à rédiger l'explication, mais il ne décide pas seul d'un verdict, et tout ce qu'il produit sans source est rejeté.

Tout est journalisé pour qu'un verdict puisse être rejoué à l'identique : transcription, requêtes, réponses des sources, versions des données, du modèle et du prompt.

## Avancement

Le projet en est au cadrage, il n'y a pas encore de code.

| Version | Objectif |
|---|---|
| V0 | Hors ligne, sur des transcriptions de débats passés, avec les indicateurs INSEE et Eurostat. Le but est de valider la méthode. |
| V1 | Quasi temps réel, en usage interne, avec validation humaine systématique. |
| V2 | Ajout des textes de loi, des votes parlementaires, de la sécurité, de l'immigration et des comparaisons internationales. |
| V3 | Ouverture au public, seulement après évaluation chiffrée, audit de neutralité et validation juridique. |

Le détail du travail est dans les [issues](https://github.com/Mac-Aurel/zetruth/issues), regroupées par version dans les [milestones](https://github.com/Mac-Aurel/zetruth/milestones).

## Évaluation

Rien ne sera considéré comme fiable sans mesure. Un jeu de référence d'affirmations tirées de vrais débats et annotées à la main sert à évaluer chaque étape : qualité de la transcription (surtout sur les nombres), détection des affirmations, exactitude des verdicts, taux d'abstention, latence. Les résultats sont aussi ventilés par intervenant pour vérifier que le système traite tout le monde de la même façon.

## Ce que ce projet n'est pas

Ce n'est pas l'ARCOM et ça n'a aucun pouvoir de sanction. Ce n'est pas non plus un outil pour juger des opinions ou pour favoriser un camp.

## Développement

Le projet utilise Python 3.12 ou plus et [uv](https://docs.astral.sh/uv/) pour les dépendances.

```bash
uv sync
cp .env.example .env
```

Vérifications (les mêmes que dans la CI) :

```bash
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
```
