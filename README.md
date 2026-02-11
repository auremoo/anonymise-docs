# Anonymize Docs

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
| 1 | **Regex** | IPv4/v6, FQDN (.local, .corp...), emails, phone numbers, dates (FR/ISO), UNC paths, Linux home paths |
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
ollama pull gpt-oss:20b
```

> This is a ~12 GB download. For faster but less accurate results, you can use a smaller model:
> ```bash
> ollama pull gpt-oss:8b
> ```

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
| `--model` | `gpt-oss:20b` | Ollama model to use |
| `--output`, `-o` | `<name>_anonymise.md` | Output file path |
| `--ollama-url` | `http://localhost:11434` | Ollama API URL |
| `--no-llm` | `false` | Regex-only mode (no LLM) |
| `--chunk-size` | `4000` | Max characters per LLM chunk |
| `--passes` | `2` | LLM passes: 1, 2, or 3 |
| `--timeout` | `300` | Timeout per Ollama request (seconds) |

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
| `[PERSONNE_n]` | Person names | LLM |
| `[ENTREPRISE_n]` | Company / organization names | LLM |
| `[SITE_n]` | Site / building names | LLM |
| `[PROJET_n]` | Internal project names | LLM |
| `[LIEU_n]` | Physical addresses / cities | LLM |
| `[REF_n]` | Contract numbers, client refs | LLM |

## Web interface (Streamlit)

A graphical interface is available for drag & drop usage:

```bash
streamlit run app.py
```

Features:
- Drag & drop file upload
- Custom words/names to anonymize (with category selection)
- Real-time progress bar
- Before/after preview
- Download anonymized file, mapping, and report
- Ollama connection status indicator

The model is fixed to `gpt-oss:20b`.

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
| 1 | **Regex** | IPv4/v6, FQDN (.local, .corp...), emails, téléphones, dates (FR/ISO), chemins UNC, chemins Linux |
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
ollama pull gpt-oss:20b
ollama serve  # si pas déjà lancé
```

### 3. Installer les dépendances Python

```bash
pip install -r requirements.txt
```

## Utilisation

### Interface graphique (recommandé)

```bash
streamlit run app.py
```

Ouvre une interface dans le navigateur avec :
- Glisser-déposer de fichiers
- Saisie de mots/noms personnalisés à anonymiser
- Barre de progression en temps réel
- Prévisualisation avant/après
- Téléchargement des résultats

### Ligne de commande

```bash
# Utilisation simple
python anonymize.py document.docx

# Avec options
python anonymize.py rapport.pdf --passes 3
python anonymize.py notes.md --no-llm -o notes_clean.md
```

## Fichiers générés

| Fichier | Contenu | Partageable ? |
|---------|---------|---------------|
| `*_anonymise.md` | Document anonymisé | **Oui** — envoyez-le à Claude sans risque |
| `*_mapping.json` | Table de correspondance tag ↔ valeur originale | **Non** — gardez-le privé |
| `*_rapport.md` | Rapport détaillé de l'anonymisation | Optionnel |

## Workflow typique

```
1. python anonymize.py mon_cahier_des_charges.docx
2. Vérifier mon_cahier_des_charges_anonymise.md  ← contrôle qualité
3. Envoyer le fichier anonymisé à Claude / ChatGPT
4. Garder mon_cahier_des_charges_mapping.json en privé
```

## Licence

MIT
