# Jeu de référence

Affirmations tirées de vrais débats, annotées à la main. C'est ce qui sert à mesurer chaque étape du pipeline, donc la qualité des annotations compte plus que leur nombre.

## Transcriptions

Les débats viennent de [FREDSum](https://github.com/linagora-labs/FREDSum) (licence CC BY-SA 4.0). Ils ne sont pas versionnés dans ce dépôt, on les télécharge :

```bash
uv run python -m zetruth.corpus.fredsum
```

Les extraits retenus sont listés dans `fredsum_selection.txt`. Le script les place dans `data/raw/fredsum/transcripts/` et crée pour chacun un CSV dans `data/raw/fredsum/tours/` avec un tour de parole par ligne, numéroté. C'est ce fichier qu'on lit pour annoter : le numéro de tour sert de repère, faute d'horodatage dans FREDSum.

Les présentateurs apparaissent souvent sous la forme `P1`, `P2`.

Si on publie un jour ce jeu de référence, il devra rester sous CC BY-SA 4.0 et citer l'article : Rennard et al., *FREDSum: A Dialogue Summarization Corpus for French Political Debates*, Findings of EMNLP 2023.

## Format de `affirmations.csv`

Une ligne par affirmation, encodage UTF-8, séparateur virgule.

| Colonne | Contenu |
|---|---|
| id | Identifiant unique, par exemple `hs-chomage-001` |
| fichier | Nom du fichier de transcription, par exemple `Hollande_Sarkozy--Partie_1_Chomage.txt` |
| tour | Numéro du tour dans le CSV des tours |
| locuteur | Nom tel qu'il apparaît dans la transcription |
| citation | Extrait copié mot pour mot du tour |
| type | `factuelle`, `opinion`, `promesse` ou `prediction` |
| sujet | Thème libre : chômage, dette, inflation... |
| indicateur | Ce qui est mesuré, le plus précisément possible (« taux de chômage au sens du BIT », pas « chômage ») |
| valeur | Valeur annoncée par l'intervenant |
| unite | %, points, milliards d'euros, personnes... |
| periode | Période concernée, par exemple `2007-2012` ou `T4 2016` |
| perimetre | France entière, métropole, zone euro... |
| verdict | `VRAI`, `FAUX`, `TROMPEUR`, `IMPRECIS`, `INVERIFIABLE` ou `NON_FACTUEL` |
| valeur_officielle | Valeur trouvée dans la source |
| source_organisme | Identifiant de la source dans `config/sources.toml` : `insee`, `eurostat`, `dares`... |
| source_reference | Identifiant de série, nom de la publication ou du texte |
| source_url | Lien vers la donnée elle-même, pas vers une page d'accueil. Doit appartenir à la source indiquée |
| date_publication | Date de publication de la donnée utilisée (AAAA-MM-JJ) |
| date_consultation | Date à laquelle on l'a consultée (AAAA-MM-JJ) |
| commentaire | Tout ce qui aide à comprendre le verdict : définition retenue, révision, contexte |

Ce qui est obligatoire :

- toujours : id, fichier, tour, locuteur, citation, type, verdict
- pour une affirmation factuelle : indicateur, valeur, periode
- pour un verdict autre que `INVERIFIABLE` : valeur_officielle, source_organisme, source_reference, source_url, date_consultation
- une opinion, une promesse ou une prédiction a toujours le verdict `NON_FACTUEL`

## Règles d'annotation

- On vérifie ce que l'intervenant a dit, pas ce qu'il voulait dire. Si la phrase est ambiguë, on le note en commentaire.
- La valeur officielle doit être celle qui était disponible à la date du débat. Si elle a été révisée depuis, on garde la version d'époque et on mentionne la révision en commentaire. Les archives de l'INSEE permettent de retrouver les anciennes publications.
- Les sources doivent faire partie de la liste blanche du projet. Un article de presse peut aider à trouver la source, mais ne se cite pas.
- Dans le doute, `INVERIFIABLE`. Ce n'est pas un échec, c'est une information utile pour l'évaluation.
- Une même phrase peut contenir plusieurs affirmations : on fait une ligne par affirmation, avec la même citation si besoin.

## Vérifier le fichier

```bash
uv run python -m zetruth.reference.annotations
```

Le script contrôle le format, les champs obligatoires, les dates, que la source fait partie de la liste blanche et que son URL lui appartient, et, si les transcriptions ont été téléchargées, que chaque citation figure bien mot pour mot dans le tour indiqué avec le bon locuteur.
