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
| `_run_llm_pass()` | Helper DRY pour exécuter une passe LLM sur tous les chunks |
| `apply_custom_words()` | Passe 0 — remplacement exact de mots saisis par l'utilisateur |
| `RegexAnonymizer` | Passe 1 — patterns structurés (IP, email, dates, FQDN, chemins, téléphones) |
| `call_ollama_chat()` | Appel Ollama via `/api/chat` avec system prompt |
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
| Data editor | Tableau dynamique de mots custom à anonymiser |
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
- **Modèle par défaut** : `gpt-oss:20b` (sélectionnable dans l'UI)
- **Streamlit** — interface web locale bilingue FR/EN
- **Dépendances** : `requests`, `python-docx`, `pymupdf`, `streamlit`, `pandas`

## Conventions

### Tags d'anonymisation

Format : `[CATEGORIE_N]` avec numérotation séquentielle par catégorie.

**Tags Regex** : `IP`, `EMAIL`, `TEL`, `DATE`, `SERVEUR`, `CHEMIN`
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

## Commandes fréquentes

```bash
# Interface web
streamlit run app.py

# CLI — usage standard (avec extraction d'images)
python anonymize.py document.docx

# CLI — regex seul (rapide, sans LLM)
python anonymize.py document.docx --no-llm

# CLI — 3 passes LLM (max qualité)
python anonymize.py document.docx --passes 3

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
*.docx
*.pdf
```
