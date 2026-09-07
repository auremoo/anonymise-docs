# Anonymize Docs — Contexte projet

## Description

Pipeline d'anonymisation hybride (Regex + LLM local Ollama) pour nettoyer des documents sensibles avant de les envoyer à des IA cloud (Claude, ChatGPT, etc.).

**Domaine principal** : documents techniques industriels (SCADA, OT, cybersécurité industrielle, cahiers des charges, spécifications techniques).

## Architecture

Deux points d'entrée : CLI (`anonymize.py`) et Web (`app.py` Streamlit, bilingue FR/EN).

```
                 ┌─────────────┐     ┌──────────────┐
                 │ CLI (main)  │     │ Streamlit    │
                 │ anonymize.py│     │ app.py (i18n)│
                 └──────┬──────┘     └─────┬────────┘
                        │                  │
                        ▼                  ▼
Fichier source → read_file_with_images()  read_file_bytes_with_images()
                        │                  │
                   text + images      text + images
                        │                  │
                        └────────┬─────────┘
                                 ▼
                          run_pipeline(text, cancel_flag, on_progress, ...)
                    Passe 0 (Custom) → Passe 1 (Regex) → Passe 2 (LLM) → Passe 3 (Vérif)
                                 │
                                 ▼
                    {text, mapping, report, stats}
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
            _anonymise.md  _mapping.json  _images/
                                          IMAGE_1.png
                                          IMAGE_2.jpg
```

### Composants internes (`anonymize.py`)

| Classe/Fonction | Rôle |
|----------------|------|
| `run_pipeline()` | Pipeline principal — appelable depuis CLI ou UI, retourne dict. Accepte `cancel_flag` (threading.Event) et `on_progress` callback |
| `_run_llm_pass()` | Helper DRY pour exécuter une passe LLM sur tous les chunks — parallélise les chunks via `parallel` (défaut 3), résultats réordonnés |
| `apply_custom_words()` | Passe 0 — remplacement de mots saisis par l'utilisateur, en un seul parcours (regex en alternance). Un `*` agit comme joker |
| `_motif_mot()` | Traduit un mot du dictionnaire en regex : tout est échappé sauf `*` |
| `normaliser_texte()` | Ramène la typographie docx/pdf à l'ASCII avant toute recherche (tirets unicode, espaces insécables, coupures de ligne) |
| `load_sensitive_words()` / `save_sensitive_words()` | Chargement/sauvegarde du dictionnaire persistant `sensitive-words.json` |
| `RegexAnonymizer` | Passe 1 — patterns structurés (IP, email, dates, FQDN, chemins, téléphones, credentials) |
| `call_ollama_chat()` | Appel Ollama via `/api/chat` avec system prompt — session HTTP réutilisée, `keep_alive: 10m` |
| `_size_context()` | Calcule `num_ctx`/`num_predict` selon la taille du chunk (évite d'allouer 32k tokens de cache KV pour 4k caractères) |
| `split_into_chunks()` | Découpage intelligent (paragraphes > lignes) |
| `post_check()` | Vérification finale regex pour patterns résiduels |
| `Logger` | Traçabilité complète + callback UI + génération du rapport + timer (`elapsed()`) |
| `read_file()` / `read_file_bytes()` | Lecture multi-format (fichier disque / bytes mémoire) — texte seulement |
| `read_file_with_images()` / `read_file_bytes_with_images()` | Lecture avec extraction d'images → (texte + placeholders `[IMAGE_N]`, liste images) |
| `save_images()` | Sauvegarde les images extraites dans un dossier numéroté (IMAGE_1.ext, IMAGE_2.ext...) |
| `_read_docx_with_images()` | Extraction images docx via python-docx XML (namespaces `w:`, `a:`, `r:`) |
| `_read_pdf_with_images()` | Extraction images PDF via pymupdf (`page.get_images()` + `doc.extract_image()`) |
| `check_ollama()` | Vérifie connexion Ollama et disponibilité modèle, retourne la liste des modèles |

### Interface Streamlit (`app.py`)

| Composant | Rôle |
|-----------|------|
| Language toggle | Radio FR/EN dans la sidebar, toutes les chaînes via `t("key")` |
| Model selector | Selectbox peuplé par `check_ollama()` (modèles installés) |
| File uploader | Drag & drop de documents (disabled pendant l'exécution) |
| Data editor | Tableau dynamique de mots custom à anonymiser (pré-rempli depuis `sensitive-words.json`) |
| Save dictionary | Bouton pour sauvegarder les mots custom dans `sensitive-words.json` |
| Éditeur JSON | Expander pour éditer/coller le dictionnaire en bloc — bien plus rapide que la saisie ligne par ligne. Validation stricte : un JSON mal formé est refusé sans écraser le fichier existant |
| Image extraction | Checkbox pour activer l'extraction d'images docx/pdf |
| Progress bar | Callback `on_progress` depuis `run_pipeline()` avec timer |
| Stop button | Met `cancel_flag.set()`, pipeline s'arrête entre les chunks |
| Tabs avant/après | Prévisualisation du résultat + rapport |
| Download buttons | Fichier anonymisé, mapping, rapport, images (zip) |

### Fichiers de sortie

- `*_anonymise.md` — document nettoyé (partageable)
- `*_mapping.json` — table tag ↔ valeur originale (confidentiel)
- `*_rapport.md` — rapport détaillé d'exécution
- `*_images/` — images extraites numérotées (à vérifier manuellement)

## Stack technique

- **Python 3.10+**
- **Ollama** — runtime LLM local (`http://localhost:11434`)
- **Modèle par défaut** : `mistral:latest` (sélectionnable dans l'UI)
- **Chunk par défaut** : 1500 caractères (voir mesures ci-dessous)

### Contrainte matérielle — mesuré sur RTX 500 Ada (4 Go de VRAM)

Le modèle doit **tenir dans la VRAM**, pas dans la RAM système. Ce qui
n'y tient pas tourne sur CPU, 10 à 50× plus lentement. Vérifier avec
`curl localhost:11434/api/ps` que `size_vram` ≈ `size`.

| Modèle | VRAM / total | 1 passe sur 3,8 Ko | Résultat |
|---|---|---|---|
| `qwen2.5:3b` | 2,4 / 2,4 Go (100 %) | 29 s | **Inutilisable** — réécrit le document, recopie les exemples du prompt, 6 entités en clair |
| `mistral:latest` | 3,0 / 9,3 Go (32 %) | 170 s (chunk 1500) | **Le moins mauvais** — texte préservé, 3 entités en clair, sur-anonymise des termes techniques |
| `gpt-oss:20b` | 3,4 / 15 Go (23 %) | 1934 s | Inexploitable — 2 chunks sur 4 en timeout, laissés en clair |

Mesures à n=1 : le LLM n'est pas déterministe (`temperature: 0.05` ≠ 0),
les entités détectées varient d'un run à l'autre.

**Conséquence pratique :** aucun modèle local testé sur cette machine
n'anonymise de façon fiable. La partie déterministe (regex + dictionnaire
`sensitive-words.json`) est la seule à garantir un résultat. Mettre les
entités qui comptent dans le dictionnaire ; traiter la passe LLM comme un
filet d'appoint, jamais comme une garantie.

### Mesure : dictionnaire + mistral sur le même document

| Catégorie | Résultat |
|---|---|
| 11 entités présentes dans `sensitive-words.json` | **11/11 remplacées** (passe 0, déterministe, insensible à la casse) |
| Références de contrat `N°ABC-2024-0456` | **taguées** (passe 1, regex `REF`) |
| Villes/lieux absents du dictionnaire | **en clair** — mistral n'en a rattrapé qu'1 sur 6 |
| 8 termes techniques (Siemens, Profinet, WinCC…) | **8/8 préservés** |

Le dictionnaire est le mécanisme fiable. Tout ce qui n'y est pas doit être
considéré comme susceptible de fuiter, quelle que soit la passe LLM.

### Débit mesuré et extrapolation

| Moteur | Débit (1 passe) |
|---|---|
| `gpt-oss:20b` | **2,3 car./s** (optimiste : calculé sur les 2 chunks qui ont abouti) |
| `mistral` | **25,3 car./s** |
| Regex + dictionnaire (`--no-llm`) | **2 400 000 car./s** |

Extrapolation pour un PDF de 197 pages (~2500 car./page, 2 passes) :

| Moteur | Durée |
|---|---|
| `gpt-oss:20b` | ~5 jours — et avec le timeout par défaut la majorité des chunks échouerait, sortant **en clair** |
| `mistral` | ~11 h |
| `--no-llm` + dictionnaire | **< 1 s** |

**Sur un document volumineux, la passe LLM n'est pas une option praticable
sur ce matériel.** Le mode `--no-llm` avec un dictionnaire bien garni
traite 197 pages instantanément et de façon déterministe.

### Taux de réussite mesuré (document de test, 14 entités)

| | À périmètre strictement égal | Résultat réel sur le document |
|---|---|---|
| `gpt-oss:20b` | 4/4 | **29 %** (2 chunks sur 4 en timeout) |
| `mistral` | 4/4 | **86 %** |

À périmètre égal les deux sont à égalité, mais sur **4 entités seulement** :
l'échantillon ne permet pas de les départager sur le rappel. La différence
de 29 % contre 86 % vient entièrement des chunks non traités, pas de la
qualité du modèle. Là où le 20b est réellement supérieur : il n'invente
pas de catégories de tags, contrairement à mistral (`[MARQUE_TECHNIQUE_1]`,
`[PRESTATION_1]`).

### Ce que le LLM sait distinguer (mesuré, mistral)

Document mélangeant références internes et acronymes techniques, **sans
dictionnaire ni aide de la regex** (Regex : 0) :

| Catégorie | Résultat |
|---|---|
| Références commerciales (`QU-WIN-123`, `DV2601659`, `24-0871`) | **4/4 taguées** — la regex n'en attrapait aucune |
| Termes techniques (SCADA, WinCC, OPC UA, Profinet, IEC 61850, B2V, PLC, IHM, VLAN 42, CP343-1) | **11/13 préservés** |
| Références de procédure (`PR-QSE-07`, `REF-INT-2024-88`) | **laissées en clair** |
| `S7-1500` | → `[ENTREPRISE_1]-1500` : « S7 » tagué comme société, référence mutilée |
| `TGBT` | → `[ENTREPRISE_2]` : un tableau général basse tension devient une société |

Le LLM apporte donc une vraie valeur sur les références que la regex ne
peut pas décrire, mais il se trompe dans les deux sens. `TGBT` remplacé
en entier n'est **détectable par aucun contrôle** — seule la relecture
l'attrape. Conclusion inchangée : les familles de références connues
vont dans le dictionnaire avec un joker (`QU-*`, `DV*`, `PR-*`).

### Effet de la taille de chunk (mistral, même document)

| chunk_size | Durée | Entités en clair |
|---|---|---|
| 4000 | 250 s | 5 |
| 1500 | 170 s | 3 |

Chunks plus petits = plus rapide (coût quadratique de l'attention) et
moins d'oublis en fin de chunk. Contrepartie : la numérotation des tags
LLM n'est pas cohérente entre chunks (chaque chunk repart de son propre
comptage), donc deux sociétés différentes peuvent devenir `[ENTREPRISE_1]`
dans deux chunks distincts.

### Extraction d'images — correspondance vérifiée

Le numéro du placeholder `[IMAGE_N]` et le nom de fichier `IMAGE_N.ext`
sont alignés par construction : l'index dans la liste `images` sert aux
deux. Vérifié par test sur des images de couleurs distinctes.

| Emplacement de l'image | docx | pdf |
|---|---|---|
| Paragraphe | oui | oui (par page) |
| **Cellule de tableau** | oui | — |
| En-tête / pied de page (logos) | oui | — |
| Tableau imbriqué | oui (récursif) | — |

`_docx_walk()` parcourt le corps dans **l'ordre du document** (paragraphes
et tableaux entrelacés). L'ancienne version listait `doc.paragraphs` puis
`doc.tables`, ce qui rejetait tout le contenu des tableaux en fin de
document et ne voyait aucune image de cellule. Les en-têtes ont leurs
propres relations d'images : une table de relations **par partie** du
docx est nécessaire, un même `rId` pouvant désigner deux images
différentes selon la partie.

Le mode sans extraction d'images utilise le même parcours ordonné avec
une table de relations vide (aucun placeholder émis).

### Garde-fous du pipeline

| Contrôle | Déclenchement |
|---|---|
| Rejet d'intégrité | Réponse LLM hors de 60–130 % de la taille d'entrée → chunk d'origine conservé et signalé (attrape la réécriture/troncature) |
| Vocabulaire de tags | `check_tag_vocabulary()` — catégorie inventée (`[MARQUE_TECHNIQUE_1]`…) = sur-anonymisation de termes techniques |
| Tags collés | `check_tags_colles()` — un tag suivi d'un fragment (`[ENTREPRISE_1]-1500`) révèle que le LLM n'a tagué qu'une partie d'une référence technique. La catégorie étant légitime, c'est le seul signal disponible |
| Fragments numériques | `check_fragments_numeriques()` — un nombre isolé après un tag (`[REF_1] 123`) peut être la fin d'une référence coupée par un espace insécable. Signal moins sûr : formulé comme une vérification |
| Chunks non traités | Timeout ou Ollama absent → portion restée en clair, avertissement en tête des warnings |

Ces trois cas remontent dans `result["warnings"]`, donc dans le rapport,
dans l'UI Streamlit et en fin de run CLI. **Un document peut être produit
en n'étant que partiellement anonymisé — c'est le mode d'échec principal
de l'outil et il doit rester visible.**

- **Streamlit** — interface web locale bilingue FR/EN
- **Dépendances** : `requests`, `python-docx`, `pymupdf`, `streamlit`, `pandas`

## Conventions

### Tags d'anonymisation

Format : `[CATEGORIE_N]` avec numérotation séquentielle par catégorie.

**Tags Regex** : `IP`, `EMAIL`, `TEL`, `DATE`, `SERVEUR`, `CHEMIN`, `SECRET`, `REF`
**Tags LLM** : `PERSONNE`, `ENTREPRISE`, `SITE`, `PROJET`, `LIEU`, `REF`
**Tags Extraction** : `IMAGE` (placeholders pour images extraites de docx/pdf)

### Prompts LLM

Les prompts système sont dans les constantes `SYSTEM_PROMPT_PASS2` et `SYSTEM_PROMPT_PASS3` du script. Points critiques :

- `temperature: 0.05` — quasi-déterministe, pas de créativité
- Liste d'exclusion explicite pour termes techniques industriels (SCADA, WinCC, OPC UA, PLC, TIA Portal, Siemens, Schneider, Modbus, Profinet...)
- Le LLM ne doit retourner QUE le texte modifié, sans commentaire
- Les tags existants (regex + IMAGE) doivent être préservés intacts

### Langue

- Code et commentaires : français
- Logs console : français avec emojis
- Rapports : français
- Interface Streamlit : bilingue FR/EN (dict `TEXTS` + fonction `t()`)

## Règles de développement

- **Pas de dépendance réseau** sauf Ollama local — c'est le principe fondamental du projet
- **Pas de données sensibles dans le repo** — les fichiers `*_mapping.json` et fichiers source ne doivent jamais être commités
- Le script doit fonctionner en mode regex seul (`--no-llm`) si Ollama n'est pas disponible
- Toute modification des prompts LLM doit être testée avec des documents contenant un mix de termes techniques et d'entités nommées
- Le rapport doit toujours être généré, même en cas d'erreurs LLM
- L'annulation via `cancel_flag` doit retourner un résultat partiel cohérent

## Normalisation typographique

`normaliser_texte()` est appliqué **une seule fois**, en entrée de
`run_pipeline()`, donc couvre le CLI comme l'interface. Sans lui, des
caractères invisibles à l'œil faisaient échouer silencieusement les
motifs et les mots du dictionnaire.

| Cas | Origine | Traitement |
|---|---|---|
| `QU—WIN—123`, `QU–WIN–123` | correction automatique de Word | tirets → `-` |
| `QU‐WIN‐123`, `QU‑WIN‑123`, `QU−WIN−123` | extraction PDF | tirets → `-` |
| Espace insécable, fine, largeur nulle | docx/pdf | → espace ou supprimé |
| Trait d'union optionnel (soft hyphen) | Word | supprimé |
| `QU-WIN-
123` | référence coupée en fin de ligne | recollé |

La règle de recollage n'agit que si la suite commence par un **chiffre ou
une majuscule** : une césure française ordinaire (`exploi-
tation`) est
laissée intacte.

### Limites assumées du joker

Deux cas ne sont pas couverts, et le sont volontairement — accepter des
espaces dans le joker ferait déborder `QU-*` sur le mot suivant, ce qui
est pire qu'un raté :

| Cas | Résultat | Filet |
|---|---|---|
| `QU-WIN 123` (espace insécable **interne**) | `[REF_1] 123` — le numéro reste | avertissement « nombre isolé » |
| `QU - WIN - 123` (espaces autour des tirets) | non détecté | aucun |

Ces deux limites sont figées par des tests, pour qu'elles restent connues.

## Dictionnaire : joker `*`

Un `*` dans un mot du dictionnaire couvre une série de références sans
les lister une par une :

| Entrée | Attrape | Ne franchit pas |
|---|---|---|
| `QU-OPE*` | `QU-OPE-1234`, `QU-OPE-5678`, `QU-OPE-1.2` | les espaces, la ponctuation finale |
| `DV*` | `DV2601659`, `DV2601660` | idem |

Chaque occurrence distincte reçoit **son propre tag** (`[REF_1]`,
`[REF_2]`...), donc les références restent distinguables dans le document
anonymisé. Un motif dont la partie littérale fait moins de 2 caractères
(`*`, `a*`) est **ignoré** : il anonymiserait le document entier.

## Tests

```bash
python -m unittest discover -s tests -t .
```

88 tests, sans dépendance externe et sans Ollama (les appels LLM sont
simulés). Les documents docx/pdf de test sont **générés à l'exécution** :
le `.gitignore` exclut `*.docx` et `*.pdf` pour éviter de commiter un
document sensible par accident.

| Fichier | Couvre |
|---|---|
| `test_regex.py` | Passe 1 — chaque test correspond à un bug rencontré, y compris les cas qui ne doivent **pas** matcher (termes techniques, mots avalés) |
| `test_dictionnaire.py` | Passe 0 — casse, joker `*`, tags fantômes, fichier de dictionnaire |
| `test_extraction.py` | docx/pdf — correspondance placeholder ↔ fichier vérifiée **par la couleur des pixels** (un simple comptage ne détecte pas un décalage de numérotation) |
| `test_garde_fous.py` | Rejet d'intégrité, catégories inventées, chunks non traités, annulation, ordre des chunks en parallèle |
| `test_interface_json.py` | Éditeur JSON de l'UI, exécuté via `AppTest` de Streamlit (saisie → clic → écriture → relecture) |

`run_pipeline(..., verbose=False)` coupe l'affichage console tout en
gardant le journal complet dans le rapport.

## Commandes fréquentes

```bash
# Lanceur tout-en-un (demarre Ollama si besoin + interface web)
python lancer.py
# ou double-clic sur lancer.bat

# Lanceur sans interface (demarre seulement Ollama)
python lancer.py --no-web

# Interface web seule
python -m streamlit run app.py

# CLI — usage standard (avec extraction d'images)
python anonymize.py document.docx

# CLI — regex seul (rapide, sans LLM)
python anonymize.py document.docx --no-llm

# CLI — avec dictionnaire personnalisé
python anonymize.py document.docx --dict mes_mots.json

# CLI — 3 passes LLM (max qualité)
python anonymize.py document.docx --passes 3

# CLI — nombre de chunks envoyés en parallèle à Ollama (défaut 3)
python anonymize.py document.docx --parallel 1

# Vérifier qu'Ollama tourne
curl http://localhost:11434/api/tags

# Installer les dépendances
pip install -r requirements.txt
```

## Fichiers à ne jamais commiter

```
*_mapping.json
*_anonymise.md
*_rapport.md
*_images/
sensitive-words.json
*.docx
*.pdf
```
