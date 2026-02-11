# Anonymize Docs — Contexte projet

## Description

Pipeline d'anonymisation hybride (Regex + LLM local Ollama) pour nettoyer des documents sensibles avant de les envoyer à des IA cloud (Claude, ChatGPT, etc.).

**Domaine principal** : documents techniques industriels (SCADA, OT, cybersécurité industrielle, cahiers des charges, spécifications techniques).

## Architecture

Un seul script Python `anonymize.py` avec une pipeline séquentielle :

```
Fichier source → Lecture → Passe 1 (Regex) → Passe 2 (LLM NER) → Passe 3 (LLM vérif) → Sortie
```

### Composants internes

| Classe/Fonction | Rôle |
|----------------|------|
| `RegexAnonymizer` | Passe 1 — patterns structurés (IP, email, dates, FQDN, chemins, téléphones) |
| `call_ollama_chat()` | Appel Ollama via `/api/chat` avec system prompt |
| `split_into_chunks()` | Découpage intelligent (paragraphes > lignes) |
| `post_check()` | Vérification finale regex pour patterns résiduels |
| `Logger` | Traçabilité complète + génération du rapport |
| `read_file()` | Lecture multi-format (md, txt, docx, pdf, csv, json, xml, yaml...) |

### Fichiers de sortie

- `*_anonymise.md` — document nettoyé (partageable)
- `*_mapping.json` — table tag ↔ valeur originale (confidentiel)
- `*_rapport.md` — rapport détaillé d'exécution

## Stack technique

- **Python 3.10+**
- **Ollama** — runtime LLM local (`http://localhost:11434`)
- **Modèle par défaut** : `gpt-oss:20b`
- **Dépendances** : `requests`, `python-docx`, `pymupdf`

## Conventions

### Tags d'anonymisation

Format : `[CATEGORIE_N]` avec numérotation séquentielle par catégorie.

**Tags Regex** : `IP`, `EMAIL`, `TEL`, `DATE`, `SERVEUR`, `CHEMIN`
**Tags LLM** : `PERSONNE`, `ENTREPRISE`, `SITE`, `PROJET`, `LIEU`, `REF`

### Prompts LLM

Les prompts système sont dans les constantes `SYSTEM_PROMPT_PASS2` et `SYSTEM_PROMPT_PASS3` du script. Points critiques :

- `temperature: 0.05` — quasi-déterministe, pas de créativité
- Liste d'exclusion explicite pour termes techniques industriels (SCADA, WinCC, OPC UA, PLC, TIA Portal, Siemens, Schneider, Modbus, Profinet...)
- Le LLM ne doit retourner QUE le texte modifié, sans commentaire
- Les tags existants (regex) doivent être préservés intacts

### Langue

- Code et commentaires : français
- Logs console : français avec emojis
- Rapports : français

## Règles de développement

- **Pas de dépendance réseau** sauf Ollama local — c'est le principe fondamental du projet
- **Pas de données sensibles dans le repo** — les fichiers `*_mapping.json` et fichiers source ne doivent jamais être commités
- Le script doit fonctionner en mode regex seul (`--no-llm`) si Ollama n'est pas disponible
- Toute modification des prompts LLM doit être testée avec des documents contenant un mix de termes techniques et d'entités nommées
- Le rapport doit toujours être généré, même en cas d'erreurs LLM

## Commandes fréquentes

```bash
# Usage standard
python anonymize.py document.docx

# Regex seul (rapide, sans LLM)
python anonymize.py document.docx --no-llm

# 3 passes LLM (max qualité)
python anonymize.py document.docx --passes 3

# Modèle plus gros
python anonymize.py document.docx --model gpt-oss:120b

# Vérifier qu'Ollama tourne
curl http://localhost:11434/api/tags
```

## Fichiers à ne jamais commiter

```
*_mapping.json
*_anonymise.md
*_rapport.md
*.docx
*.pdf
```
