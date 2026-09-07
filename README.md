# Anonymize Docs

> Créé par Aurélien Moote - Moo - 2026. Logiciel libre (licence MIT) :
> réutilisable à condition de conserver la mention de l'auteur.

**Hybrid document anonymization pipeline (Regex + Local LLM) for sanitizing sensitive files before sending them to cloud AI services.**

> [Version française ci-dessous](#version-française)

---

## Why?

You want to use Claude, ChatGPT, or any cloud AI to analyze your documents — but they contain personal names, IPs, internal server names, emails, and other sensitive data. This tool **anonymizes everything locally** (nothing leaves your machine) so you can safely share the sanitized output.

## How it works

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Input file  │────▶│  Pass 1:     │────▶│  Pass 2:     │────▶│  Pass 3:     │
│  .docx .pdf  │     │  Regex       │     │  LLM (NER)   │     │  LLM verify  │
│  .md .txt    │     │  (IP, email, │     │  (names,     │     │  (catch      │
│  .csv .json  │     │   dates...)  │     │   companies) │     │   leftovers) │
└─────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
                                                                      │
                                              ┌───────────────────────┤
                                              ▼                       ▼
                                     ┌────────────────┐    ┌──────────────────┐
                                     │ _anonymise.md  │    │ _mapping.json    │
                                     │ (safe to share)│    │ (keep private!)  │
                                     └────────────────┘    └──────────────────┘
```

| Pass | Engine | What it catches |
|------|--------|----------------|
| 1 | **Regex** | IPv4/v6, FQDN (.local, .corp...), emails, phone numbers, dates (FR/ISO), UNC paths, Linux home paths, credentials/API keys |
| 2 | **Local LLM** | Person names, company names, site/building names, internal project names, physical addresses |
| 3 | **Local LLM** | Verification pass — catches anything missed by pass 2 |
| 4 | **Local LLM** (optional) | Strict re-verification (`--passes 3`) |

**All LLM processing runs locally via Ollama. No data is sent to any external service.**

## Output files

| File | Purpose | Share it? |
|------|---------|-----------|
| `<name>_anonymise.md` | Anonymized document | Yes — safe to send to cloud AI |
| `<name>_mapping.json` | Original ↔ tag correspondence table | **No** — keep private, used for de-anonymization |
| `<name>_rapport.md` | Detailed anonymization report with stats | Optional — useful for audit |
| `<name>_images/` | Extracted images (IMAGE_1.png, IMAGE_2.jpg...) | **Review first** — check for sensitive content |

### Image extraction

The `[IMAGE_N]` placeholder left in the text and the `IMAGE_N.ext` file on
disk always carry the same number, so you can match each placeholder to the
exact file it replaced.

| Image location | .docx | .pdf |
|---|---|---|
| Paragraph | yes | yes (per page) |
| Table cell | yes | — |
| Header / footer (logos) | yes | — |
| Nested table | yes (recursive) | — |

Images are never anonymized — they are only extracted so you can review
them yourself. A screenshot, a logo or a signature identifies a client as
surely as a name does.

## Installation

### Prerequisites

- **Python 3.10+**
- **Ollama** — local LLM runtime

### 1. Install Ollama

**Windows:**
Download from https://ollama.com/download and run the installer.

**Linux:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**macOS:**
```bash
brew install ollama
```

Verify installation:
```bash
ollama --version
```

### 2. Pull the LLM model

```bash
ollama pull mistral
```

> **The model must fit in your GPU's VRAM, not your system RAM.** Whatever
> does not fit runs on the CPU, 10 to 50 times slower. Check with
> `curl localhost:11434/api/ps` that `size_vram` is close to `size`.
>
> Measured on a 4 GB GPU (RTX 500 Ada), one LLM pass over a 3.8 KB document:
>
> | Model | On GPU | Duration | Outcome |
> |---|---|---|---|
> | `qwen2.5:3b` | 100 % | 29 s | Unusable — rewrites the document, copies the prompt's own examples |
> | `mistral` (7B) | 32 % | 170 s | Workable — text preserved, misses some entities |
> | `gpt-oss:20b` | 23 % | 1934 s | Best quality where it completes, but 2 of 4 chunks hit the timeout and were left in clear |
>
> With 8 GB of VRAM or more, `gpt-oss:20b` becomes the better choice: its
> tagging is more accurate and it does not invent tag categories.

Start Ollama (if not already running):
```bash
ollama serve
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

Or create a virtual environment:
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

### Basic usage

```bash
python anonymize.py document.docx
```

### With options

```bash
# Specify output file
python anonymize.py rapport.pdf -o rapport_clean.md

# Use a larger model for better accuracy
python anonymize.py cahier_des_charges.docx --model gpt-oss:120b

# Regex only (no LLM, fastest)
python anonymize.py notes.md --no-llm

# 3 LLM passes for maximum thoroughness
python anonymize.py spec.docx --passes 3

# Smaller chunks for limited GPU memory
python anonymize.py big_file.docx --chunk-size 2000
```

### All options

| Option | Default | Description |
|--------|---------|-------------|
| `--model` | `mistral:latest` | Ollama model to use |
| `--output`, `-o` | `<name>_anonymise.md` | Output file path |
| `--ollama-url` | `http://localhost:11434` | Ollama API URL |
| `--no-llm` | `false` | Regex-only mode (no LLM) |
| `--chunk-size` | `1500` | Max characters per LLM chunk. Smaller = fewer missed entities at the end of a chunk, and faster (attention cost is quadratic) |
| `--passes` | `2` | LLM passes: 1, 2, or 3 |
| `--timeout` | `300` | Timeout per Ollama request (seconds) |
| `--dict` | `sensitive-words.json` | Persistent dictionary of sensitive words (JSON). Case-insensitive; `*` acts as a wildcard (`QU-OPE*` covers `QU-OPE-1234`, `QU-OPE-5678`...) |
| `--parallel` | `3` | Chunks sent to Ollama concurrently. Only helps if `OLLAMA_NUM_PARALLEL` > 1 server-side |

In the web interface, the dictionary can also be edited as raw JSON
(faster than the row-by-row table for bulk entry). Invalid JSON is
rejected without overwriting the existing dictionary.

### Supported file formats

| Format | Extension | Requirement |
|--------|-----------|-------------|
| Markdown | `.md` | None |
| Plain text | `.txt`, `.log`, `.csv` | None |
| Config files | `.conf`, `.ini`, `.yaml`, `.yml` | None |
| Structured data | `.json`, `.xml` | None |
| Word documents | `.docx` | `python-docx` |
| PDF documents | `.pdf` | `pymupdf` |

## Typical workflow

```
1. python anonymize.py my_document.docx
2. Review my_document_anonymise.md  ← check quality
3. Send my_document_anonymise.md to Claude / ChatGPT / etc.
4. Keep my_document_mapping.json private for reference
```

## Tag reference

| Tag pattern | Category | Source |
|-------------|----------|--------|
| `[IP_n]` | IP addresses | Regex |
| `[EMAIL_n]` | Email addresses | Regex |
| `[TEL_n]` | Phone numbers | Regex |
| `[DATE_n]` | Dates | Regex |
| `[SERVEUR_n]` | FQDN / server names | Regex |
| `[CHEMIN_n]` | File paths (UNC, Linux) | Regex |
| `[SECRET_n]` | Credentials, connection strings, API keys | Regex |
| `[REF_n]` | Contract / order numbers (`N°ABC-2024-0456`) | Regex |
| `[PERSONNE_n]` | Person names | LLM |
| `[ENTREPRISE_n]` | Company / organization names | LLM |
| `[SITE_n]` | Site / building names | LLM |
| `[PROJET_n]` | Internal project names | LLM |
| `[LIEU_n]` | Physical addresses / cities | LLM |
| `[REF_n]` | Other client references | LLM |
| `[IMAGE_n]` | Image placeholders (docx/pdf) | Extraction |

## Web interface (Streamlit)

A graphical interface is available for drag & drop usage.

**Easiest way** — starts Ollama if it is not already running, then opens
the interface:

```bash
python lancer.py
```

On Windows you can simply double-click `lancer.bat`.

Or start the interface alone (Ollama must already be running):

```bash
python -m streamlit run app.py
```

The interface listens on `127.0.0.1` only: it is never reachable from the
network. If Ollama is unreachable, or running with no model installed, the
sidebar shows it in red and the Anonymize button is disabled until you
either install a model or tick "Regex only".

Features:
- Bilingual interface (FR/EN toggle)
- Drag & drop file upload
- Custom words/names to anonymize (with persistent `sensitive-words.json` dictionary)
- LLM model selector (auto-detects installed Ollama models)
- Real-time progress bar with elapsed time
- Stop button to cancel long-running anonymization
- Image extraction from docx/pdf (saved as numbered files, downloadable as zip)
- Before/after preview
- Download anonymized file, mapping, report, and images
- Ollama connection status indicator
- All controls disabled during processing

## LLM prompt design notes

The prompts used for the local LLM are critical for quality. Key principles:

1. **Low reasoning / low temperature (0.05)** — The LLM must not "think creatively", just find-and-replace entities
2. **Explicit exclusion list** — Technical terms (SCADA, WinCC, OPC UA, PLC, Siemens...) are explicitly listed as NOT-to-anonymize to prevent false positives in industrial documents
3. **Preserve existing tags** — The LLM is told to leave `[IP_1]`, `[EMAIL_1]` etc. intact
4. **No commentary** — The LLM must return only the processed text, no explanations
5. **Multi-pass** — Pass 2 anonymizes, Pass 3 verifies. This catches ~95% of residual entities

---

# Version française

## Pourquoi ?

Vous voulez utiliser Claude, ChatGPT, ou tout autre IA cloud pour analyser vos documents — mais ils contiennent des noms, IPs, serveurs internes, emails et autres données sensibles. Cet outil **anonymise tout localement** (rien ne quitte votre machine) pour que vous puissiez partager le résultat en toute sécurité.

## Fonctionnement

| Passe | Moteur | Ce qu'elle détecte |
|-------|--------|-------------------|
| 0 | **Dictionnaire** | Mots de `sensitive-words.json` — remplacement exact, insensible à la casse. **La seule passe fiable à 100 %** |
| 1 | **Regex** | IPv4/v6, FQDN (.local, .corp...), emails, téléphones, dates (FR/ISO), chemins UNC, chemins Linux, credentials/clés API, références de contrat (`N°ABC-2024-0456`) |
| 2 | **LLM local** | Noms de personnes, entreprises, sites/usines, projets internes, adresses physiques |
| 3 | **LLM local** | Passe de vérification — attrape les oublis de la passe 2 |
| 4 | **LLM local** (optionnel) | Re-vérification stricte (`--passes 3`) |

**Tout le traitement LLM se fait localement via Ollama. Aucune donnée n'est envoyée à un service externe.**

## Installation

### 1. Installer Ollama

**Windows :** Télécharger depuis https://ollama.com/download

**Linux :**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 2. Télécharger le modèle

```bash
ollama pull mistral
```

> **Le modèle doit tenir dans la VRAM du GPU, pas dans la RAM système.**
> Ce qui n'y tient pas tourne sur le CPU, 10 à 50× plus lentement.
> Vérifiez avec `curl localhost:11434/api/ps` que `size_vram` ≈ `size`.
>
> Mesuré sur un GPU 4 Go (RTX 500 Ada), une passe LLM sur 3,8 Ko :
>
> | Modèle | Sur GPU | Durée | Résultat |
> |---|---|---|---|
> | `qwen2.5:3b` | 100 % | 29 s | Inutilisable — réécrit le document, recopie les exemples du prompt |
> | `mistral` (7B) | 32 % | 170 s | Exploitable — texte préservé, rate des entités |
> | `gpt-oss:20b` | 23 % | 1934 s | Meilleure qualité là où il aboutit, mais 2 chunks sur 4 en timeout, laissés en clair |
>
> À partir de 8 Go de VRAM, `gpt-oss:20b` devient le meilleur choix :
> tagging plus juste et pas de catégories inventées.

Pas besoin de lancer `ollama serve` à la main : `lancer.py` le démarre.

### 3. Installer les dépendances Python

```bash
pip install -r requirements.txt
```

## Utilisation

### Interface graphique (recommandé)

**Le plus simple** — démarre Ollama s'il ne tourne pas, puis ouvre
l'interface :

```bash
python lancer.py
```

Sous Windows, double-cliquez simplement sur `lancer.bat`.

Ou l'interface seule (Ollama doit déjà tourner) :

```bash
python -m streamlit run app.py
```

L'interface n'écoute que sur `127.0.0.1` : elle n'est jamais joignable
depuis le réseau. Si Ollama est absent, ou lancé sans aucun modèle
installé, la barre latérale l'affiche en rouge et le bouton Anonymiser
reste désactivé jusqu'à ce que vous installiez un modèle ou cochiez
« Regex uniquement ».

Ouvre une interface dans le navigateur avec :
- Interface bilingue (FR/EN)
- Glisser-déposer de fichiers
- Saisie de mots/noms personnalisés à anonymiser (avec dictionnaire persistant `sensitive-words.json`)
- Sélection du modèle LLM (détection automatique des modèles Ollama installés)
- Barre de progression en temps réel avec chronomètre
- Bouton d'arrêt pour annuler un traitement long
- Extraction d'images depuis docx/pdf (fichiers numérotés, téléchargeables en zip)
- Prévisualisation avant/après
- Téléchargement des résultats (fichier anonymisé, mapping, rapport, images)

### Ligne de commande

```bash
# Utilisation simple
python anonymize.py document.docx

# Avec options
python anonymize.py rapport.pdf --passes 3
python anonymize.py notes.md --no-llm -o notes_clean.md

# Avec dictionnaire personnalisé
python anonymize.py document.docx --dict mes_mots.json
```

## Dictionnaire : joker `*`

Un `*` dans un mot du dictionnaire couvre une série de références sans
avoir à les lister :

| Entrée | Attrape |
|---|---|
| `QU-OPE*` | `QU-OPE-1234`, `QU-OPE-5678`, `QU-OPE-1.2` |
| `DV*` | `DV2601659`, `DV2601660` |

Le joker ne franchit ni les espaces ni la ponctuation finale, et chaque
référence reçoit son propre tag (`[REF_1]`, `[REF_2]`...) pour rester
distinguable. Un motif trop large (`*`, `a*`) est ignoré.

Le dictionnaire est **insensible à la casse** : `NEXANS`, `nexans` et
`Nexans` donnent le même tag.

Dans l'interface web, le dictionnaire s'édite aussi **directement en
JSON** (section « Éditer le dictionnaire en JSON ») : bien plus rapide que
le tableau ligne par ligne pour saisir ou coller beaucoup d'entrées. Le
format est celui du fichier :

```json
{
  "ENTREPRISE": ["Nexans", "Sogetrel"],
  "PERSONNE": ["Jean Dupont"],
  "REF": ["QU-OPE*"]
}
```

Un JSON mal formé est refusé avec le détail de l'erreur, **sans écraser**
le dictionnaire existant.

### Typographie

Le texte est normalisé à la lecture : les tirets unicode posés par Word
(`QU–WIN–123`) ou par l'extraction PDF (`QU‐WIN‐123`), les espaces
insécables, les traits d'union optionnels et les références coupées en
fin de ligne (`QU-WIN-
123`) sont ramenés à leur forme ASCII. Sans
cela, `QU-*` les laissait passer silencieusement.

Deux cas restent hors de portée du joker, volontairement : un espace
insécable **à l'intérieur** de la référence (`QU-WIN 123`, signalé par un
avertissement) et des espaces autour des tirets (`QU - WIN - 123`).
Accepter des espaces dans le joker le ferait déborder sur le mot suivant.

## Extraction des images

Le placeholder `[IMAGE_N]` laissé dans le texte et le fichier `IMAGE_N.ext`
sur le disque portent toujours le même numéro : la correspondance est exacte,
vous pouvez retrouver quel fichier remplace quel emplacement.

| Emplacement de l'image | .docx | .pdf |
|---|---|---|
| Paragraphe | oui | oui (par page) |
| Cellule de tableau | oui | — |
| En-tête / pied de page (logos) | oui | — |
| Tableau imbriqué | oui (récursif) | — |

Les images ne sont **jamais** anonymisées : elles sont seulement extraites
pour que vous les relisiez. Une capture d'écran, un logo ou une signature
identifie un client aussi sûrement qu'un nom.

## Fichiers générés

| Fichier | Contenu | Partageable ? |
|---------|---------|---------------|
| `*_anonymise.md` | Document anonymisé | **Oui** — envoyez-le à Claude sans risque |
| `*_mapping.json` | Table de correspondance tag ↔ valeur originale | **Non** — gardez-le privé |
| `*_rapport.md` | Rapport détaillé de l'anonymisation | Optionnel |
| `*_images/` | Images extraites (IMAGE_1.png, IMAGE_2.jpg...) | **À vérifier** — contrôlez le contenu sensible |

## Workflow typique

```
1. python anonymize.py mon_cahier_des_charges.docx
2. Vérifier mon_cahier_des_charges_anonymise.md  ← contrôle qualité
3. Envoyer le fichier anonymisé à Claude / ChatGPT
4. Garder mon_cahier_des_charges_mapping.json en privé
```

## Tests

```bash
python -m unittest discover -s tests -t .
```

88 tests, aucune dépendance supplémentaire, aucun besoin d'Ollama (les
appels LLM sont simulés). Les documents docx/pdf de test sont générés à
l'exécution — aucun fichier binaire n'est stocké dans le dépôt.

## Auteur & licence / Author & License

**Auteur / Author** : Aurélien Moote - Moo - 2026

Copyright (c) 2026 Aurélien Moote ("Moo") — Logiciel libre sous licence **MIT**.
Réutilisable à condition de conserver la mention de l'auteur.

Free software under the **MIT License**.
Reuse permitted provided the author attribution is kept.
