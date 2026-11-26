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
| indicateur | Ce qui est mesuré, le plus précisément possible (« taux de chômage au sens du BIT », pas « chômage »). Pour une hausse ou une baisse, le dire dans l'indicateur (« baisse du taux de chômage ») et mettre une valeur positive |
| qualificatif | Comment la valeur est énoncée : `egal`, `environ`, `plus_de`, `moins_de` ou `entre` |
| valeur | Valeur annoncée, en nombre (point décimal) : « plus de 2 points » donne qualificatif `plus_de` et valeur `2` |
| valeur_max | Borne haute, seulement pour `entre` |
| unite | %, points, milliards d'euros, personnes... |
| periode | Période concernée, par exemple `2007-2012` ou `T4 2016` |
| perimetre | France entière, métropole, zone euro... |
| nature_valeur | `constatee` pour une donnée mesurée, `prevision` pour une projection (Banque de France, FMI...) |
| verdict | `VRAI`, `FAUX`, `TROMPEUR`, `IMPRECIS`, `INVERIFIABLE` ou `NON_FACTUEL` |
| valeur_officielle | Valeur trouvée dans la source |
| source_organisme | Identifiant de la source dans `config/sources.toml` : `insee`, `eurostat`, `dares`... |
| source_reference | Identifiant de série, nom de la publication ou du texte |
| source_url | Lien vers la donnée elle-même, pas vers une page d'accueil. Doit appartenir à la source indiquée |
| sources_complementaires | Autres URL utilisées, séparées par des espaces (par exemple le second pays d'une comparaison). Chacune doit appartenir à une source de la liste blanche |
| date_publication | Date de publication de la donnée utilisée (AAAA-MM-JJ) |
| date_consultation | Date à laquelle on l'a consultée (AAAA-MM-JJ) |
| valeur_du_debat | `oui` si la valeur officielle est celle connue le jour du débat, `non` si elle a pu être révisée depuis (Eurostat, série INSEE sans historique suffisant) |
| commentaire | Tout ce qui aide à comprendre le verdict : définition retenue, révision, contexte |

Ce qui est obligatoire :

- toujours : id, fichier, tour, locuteur, citation, type, verdict
- pour une affirmation factuelle : indicateur, qualificatif, valeur, periode
- pour un verdict autre que `INVERIFIABLE` : nature_valeur, valeur_officielle, source_organisme, source_reference, source_url, date_consultation, valeur_du_debat
- une opinion, une promesse ou une prédiction a toujours le verdict `NON_FACTUEL`

## Règles d'annotation

- On vérifie ce que l'intervenant a dit, pas ce qu'il voulait dire. Si la phrase est ambiguë, on le note en commentaire.
- La valeur officielle doit être celle qui était disponible à la date du débat. Si elle a été révisée depuis, on garde la version d'époque et on mentionne la révision en commentaire. Voir plus bas pour retrouver ces valeurs.
- Les sources doivent faire partie de la liste blanche du projet. Un article de presse peut aider à trouver la source, mais ne se cite pas.
- Point de départ d'une évolution (« depuis votre élection », « sous votre quinquennat », « en cinq ans ») : la dernière donnée entièrement antérieure à l'événement cité. Pour l'élection de mai 2017, c'est le T1 2017, le T2 contenant déjà des semaines du nouveau mandat. Point d'arrivée : la dernière donnée publiée le jour du débat.
- Un chiffre exact présenté comme « la » valeur alors que la source en donne plusieurs (plusieurs scénarios de prévision, plusieurs définitions) sans que l'intervenant le dise est `TROMPEUR`. On se place du côté de celui qui écoute : s'il repart avec une idée fausse de ce que dit la source, le verdict n'est pas `VRAI`.
- Ces règles s'appliquent à tous les intervenants, sans exception.
- Dans le doute, `INVERIFIABLE`. Ce n'est pas un échec, c'est une information utile pour l'évaluation.
- Une même phrase peut contenir plusieurs affirmations : on fait une ligne par affirmation, avec la même citation si besoin. « Le chômage est passé de 9,6 à 7,4 % » donne deux lignes.

## Retrouver la valeur publiée à la date du débat

Pour une série de la BDM de l'INSEE, l'outil suivant donne la valeur telle qu'elle était publiée à une date, et toutes ses révisions :

```bash
uv run python -m zetruth.sources.insee_bdm 001688527 2021-Q4 2022-04-20
```

Les arguments sont l'identifiant de la série (idbank, visible sur la page de la série sur insee.fr), la période et la date du débat.

La réponse de l'INSEE est gardée dans `data/cache/insee/`, les appels suivants sur la même série ne passent plus par le réseau. Pour forcer une nouvelle interrogation, ajouter `--rafraichir`. L'outil affiche l'URL interrogée et la date de consultation, à reporter dans source_url et date_consultation.

Limite importante : l'historique de l'API ne commence que le 18 mai 2017, et pas pour toutes les séries. Pour les débats plus anciens (Hollande / Sarkozy 2012, Macron / Le Pen du 3 mai 2017), il faut retrouver à la main la publication de l'époque, par exemple la note Informations rapides correspondante dans les archives de l'INSEE, et mettre son lien dans source_url.

Pour Eurostat, même principe, avec le code du dataset et un filtre par dimension :

```bash
uv run python -m zetruth.sources.eurostat une_rt_m 2022-01 2022-04-20 geo=FR age=TOTAL sex=T unit=PC_ACT s_adj=SA
```

Si un filtre manque, l'outil dit lequel préciser. Eurostat ne garde aucune version passée de ses données : on n'obtient que la valeur actuelle. Si sa date de mise à jour est postérieure au débat, l'outil le signale, et il faut le noter en commentaire (ou chercher la publication de l'époque).

## Vérifier le fichier

```bash
uv run python -m zetruth.reference.annotations
```

Le script contrôle le format, les champs obligatoires, les dates, que la source fait partie de la liste blanche et que son URL lui appartient, et, si les transcriptions ont été téléchargées, que chaque citation figure bien mot pour mot dans le tour indiqué avec le bon locuteur.
