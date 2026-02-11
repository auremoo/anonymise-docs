#!/usr/bin/env python3
"""
Pipeline d'anonymisation hybride v2 : Regex + LLM local (Ollama /api/chat)
Usage CLI  : python anonymize.py <fichier> [--output fichier_sortie.md]
Usage Web  : streamlit run app.py

Dépendances :
  pip install requests python-docx pymupdf
"""

import re
import sys
import json
import time
import argparse
import datetime
from pathlib import Path
from collections import defaultdict
from typing import Callable

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from docx import Document
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    import fitz  # PyMuPDF
    HAS_PDF = True
except ImportError:
    HAS_PDF = False


# =============================================================================
# LOGGER — Tout est tracé
# =============================================================================

class Logger:
    """Collecte tous les événements pour le rapport final."""

    def __init__(self, on_progress: Callable[[str, float], None] | None = None):
        self.entries = []
        self.start_time = time.time()
        self.on_progress = on_progress
        self.stats = {
            "fichier_source": "",
            "taille_originale": 0,
            "taille_finale": 0,
            "custom_remplacements": 0,
            "regex_remplacements": 0,
            "llm_passes": 0,
            "llm_chunks_traites": 0,
            "llm_erreurs": 0,
            "verif_warnings": [],
            "duree_totale": 0,
        }

    def log(self, level: str, message: str, progress: float | None = None):
        timestamp = time.time() - self.start_time
        entry = {"t": round(timestamp, 2), "level": level, "msg": message}
        self.entries.append(entry)
        # Affichage console
        icons = {"INFO": "📄", "REGEX": "🔍", "CUSTOM": "🏷️", "LLM": "🤖",
                 "VERIF": "🔎", "OK": "✅", "WARN": "⚠️", "ERROR": "❌", "DONE": "✅"}
        icon = icons.get(level, "•")
        print(f"  {icon} [{timestamp:6.1f}s] {message}")
        # Callback pour l'UI
        if self.on_progress and progress is not None:
            self.on_progress(message, progress)

    def generate_report(self, regex_anon, llm_entity_map) -> str:
        """Génère le rapport Markdown complet."""
        self.stats["duree_totale"] = round(time.time() - self.start_time, 2)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            "# Rapport d'anonymisation",
            f"",
            f"**Date :** {now}  ",
            f"**Fichier source :** `{self.stats['fichier_source']}`  ",
            f"**Taille originale :** {self.stats['taille_originale']} caractères  ",
            f"**Taille finale :** {self.stats['taille_finale']} caractères  ",
            f"**Durée totale :** {self.stats['duree_totale']}s  ",
            "",
            "---",
            "",
        ]

        # Table mots custom
        if self.stats["custom_remplacements"] > 0:
            lines.append("## Passe 0 — Mots personnalisés")
            lines.append("")
            lines.append(f"**{self.stats['custom_remplacements']} remplacement(s)**")
            lines.append("")

        # Table regex
        lines.append("## Passe 1 — Regex (patterns structurés)")
        lines.append("")
        lines.append(f"**{self.stats['regex_remplacements']} remplacement(s)**")
        lines.append("")

        if regex_anon.mapping:
            lines.append("| Tag | Catégorie | Valeur originale |")
            lines.append("|-----|-----------|-----------------|")
            for key, tag in sorted(regex_anon.mapping.items(), key=lambda x: x[1]):
                cat, original = key.split("::", 1)
                lines.append(f"| `{tag}` | {cat} | `{original}` |")
            lines.append("")

        # Table LLM
        lines.append("## Passe 2 & 3 — LLM (entités nommées)")
        lines.append("")
        lines.append(f"**Passes LLM :** {self.stats['llm_passes']}  ")
        lines.append(f"**Chunks traités :** {self.stats['llm_chunks_traites']}  ")
        lines.append(f"**Erreurs LLM :** {self.stats['llm_erreurs']}  ")
        lines.append("")

        if llm_entity_map:
            lines.append("**Entités détectées par le LLM (extraction automatique) :**")
            lines.append("")
            lines.append("| Tag | Occurrences trouvées |")
            lines.append("|-----|---------------------|")
            for tag, count in sorted(llm_entity_map.items()):
                lines.append(f"| `{tag}` | {count} |")
            lines.append("")

        # Vérification
        lines.append("## Vérification post-anonymisation")
        lines.append("")
        if self.stats["verif_warnings"]:
            for w in self.stats["verif_warnings"]:
                lines.append(f"- ⚠️ {w}")
        else:
            lines.append("✅ Aucun pattern résiduel détecté.")
        lines.append("")

        # Log complet
        lines.append("---")
        lines.append("")
        lines.append("## Journal complet")
        lines.append("")
        lines.append("```")
        for e in self.entries:
            lines.append(f"[{e['t']:6.1f}s] [{e['level']:5s}] {e['msg']}")
        lines.append("```")

        return "\n".join(lines)


# =============================================================================
# PASSE 0 : Mots personnalisés
# =============================================================================

def apply_custom_words(
    text: str,
    custom_words: dict[str, str],
    regex_anon: "RegexAnonymizer",
) -> tuple[str, int]:
    """
    Remplace les mots custom avant la passe regex.
    custom_words = {"Jean Dupont": "PERSONNE", "Acme Corp": "ENTREPRISE", ...}
    Retourne (texte_modifié, nombre_de_remplacements).
    """
    count = 0
    # Trier par longueur décroissante pour éviter les remplacements partiels
    for word, category in sorted(custom_words.items(), key=lambda x: -len(x[0])):
        if not word.strip():
            continue
        tag = regex_anon._get_tag(category.upper(), word)
        text, n = re.subn(re.escape(word), tag, text, flags=re.IGNORECASE)
        count += n
    return text, count


# =============================================================================
# PASSE 1 : Regex
# =============================================================================

class RegexAnonymizer:

    def __init__(self):
        self.counters = defaultdict(int)
        self.mapping = {}

    def _get_tag(self, category: str, original: str) -> str:
        key = f"{category}::{original.strip().lower()}"
        if key not in self.mapping:
            self.counters[category] += 1
            self.mapping[key] = f"[{category}_{self.counters[category]}]"
        return self.mapping[key]

    def anonymize(self, text: str) -> str:
        # IPv4
        text = re.sub(
            r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b',
            lambda m: self._get_tag("IP", m.group(0)), text
        )
        # IPv6
        text = re.sub(
            r'\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b',
            lambda m: self._get_tag("IP", m.group(0)), text
        )
        # FQDN
        text = re.sub(
            r'\b[a-zA-Z][a-zA-Z0-9\-]*\.(?:[a-zA-Z0-9\-]+\.)*(?:local|lan|internal|corp|intra|net|com|fr|org|eu|io|de|uk|it|es)\b',
            lambda m: self._get_tag("SERVEUR", m.group(0)), text
        )
        # Emails
        text = re.sub(
            r'\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b',
            lambda m: self._get_tag("EMAIL", m.group(0)), text
        )
        # Téléphones (>=8 chiffres)
        text = re.sub(
            r'(?:\+?\d{1,3}[\s.\-]?)?(?:\(?\d{1,4}\)?[\s.\-]?){2,4}\d{2,4}',
            lambda m: self._get_tag("TEL", m.group(0)) if len(re.sub(r'\D', '', m.group(0))) >= 8 else m.group(0),
            text
        )
        # Dates FR (JJ/MM/AAAA, JJ.MM.AAAA, JJ-MM-AAAA)
        text = re.sub(
            r'\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b',
            lambda m: self._get_tag("DATE", m.group(0)), text
        )
        # Dates ISO (AAAA-MM-JJ)
        text = re.sub(
            r'\b\d{4}-\d{2}-\d{2}\b',
            lambda m: self._get_tag("DATE", m.group(0)), text
        )
        # Chemins UNC Windows
        text = re.sub(
            r'\\\\[a-zA-Z0-9\-_.]+(?:\\[a-zA-Z0-9\-_. ]+)+',
            lambda m: self._get_tag("CHEMIN", m.group(0)), text
        )
        # Chemins Linux absolus avec noms suspects (ex: /home/jdupont/)
        text = re.sub(
            r'/home/[a-zA-Z][a-zA-Z0-9._\-]+',
            lambda m: self._get_tag("CHEMIN", m.group(0)), text
        )
        return text


# =============================================================================
# PASSE 2 + 3 : LLM via Ollama /api/chat
# =============================================================================

SYSTEM_PROMPT_PASS2 = """Reasoning: low

Tu es un outil d'anonymisation. Remplace les entités nommées par des tags. Ne fais RIEN d'autre.

CATÉGORIES À REMPLACER :
- Noms de personnes (prénoms, noms, initiales "J. Dupont") → [PERSONNE_1], [PERSONNE_2]...
- Entreprises, organisations, clients, prestataires → [ENTREPRISE_1], [ENTREPRISE_2]...
- Sites, usines, bâtiments, agences → [SITE_1], [SITE_2]...
- Projets internes, noms de code → [PROJET_1], [PROJET_2]...
- Adresses, villes, rues, codes postaux → [LIEU_1], [LIEU_2]...
- Numéros de contrat, références client, n° de commande → [REF_1], [REF_2]...

RÈGLES :
1. Même entité = même tag partout (ex: "Dupont" → toujours [PERSONNE_1]).
2. NE modifie RIEN d'autre : pas de reformulation, correction, ajout ou suppression.
3. Préserve le formatage : markdown, listes, tableaux, retours à la ligne.
4. Tags existants ([IP_1], [EMAIL_1], [DATE_1], [TEL_1], [SERVEUR_1], [CHEMIN_1]) → INTACTS.
5. En cas de doute → NE remplace PAS.

NE SONT PAS DES ENTITÉS (ne pas remplacer) :
- Marques technologiques utilisées comme termes techniques :
  Siemens, Schneider Electric, Rockwell, ABB, Honeywell, Yokogawa, Emerson, Beckhoff,
  Cisco, Microsoft, VMware, Fortinet, Palo Alto, Veeam, Acronis, Dell, HP, Lenovo
- Logiciels et protocoles :
  SCADA, WinCC, TIA Portal, Step 7, PCS 7, Unity Pro, FactoryTalk, RSLogix,
  OPC UA, OPC DA, Modbus, Profinet, Profibus, EtherNet/IP, BACnet, DNP3, IEC 61850,
  SQL Server, Windows Server, Active Directory, VMware ESXi, Hyper-V, Linux, RHEL,
  Python, Docker, Kubernetes, Ansible, Terraform, Git, Jenkins, Grafana, Zabbix, PRTG
- Termes métier OT/IT :
  PLC, RTU, HMI, DCS, SIS, MES, ERP, CMMS, GMAO, SNMP, VPN, DMZ, VLAN, firewall,
  automate, variateur, IHM, superviseur, historian, API REST, base de données

EXEMPLE :
Entrée : "Jean Dupont de la société Acme a visité l'usine de Lyon le [DATE_1]."
Sortie : "[PERSONNE_1] de la société [ENTREPRISE_1] a visité l'usine de [LIEU_1] le [DATE_1]."

Retourne UNIQUEMENT le texte anonymisé. Aucun commentaire, aucune explication."""

SYSTEM_PROMPT_PASS3 = """Reasoning: low

Tu es un vérificateur d'anonymisation. Le texte a déjà été anonymisé mais il peut rester des oublis.

CHERCHE SPÉCIFIQUEMENT ces oublis fréquents :
- Prénoms isolés ("contactez Pierre", "signé Marie")
- Initiales ("J.D.", "M. Martin")
- Noms dans des adresses email partielles ou signatures
- Noms de villes ou rues non détectés ("basé à Strasbourg", "rue du Commerce")
- Références internes (n° contrat, n° client, n° badge, n° affaire)
- Noms de sociétés/clients non standard qui auraient été manqués

POUR CHAQUE OUBLI TROUVÉ :
- Utilise le tag suivant libre (ex: s'il y a déjà [PERSONNE_1] et [PERSONNE_2], utilise [PERSONNE_3])
- Si l'entité correspond à un tag existant, réutilise ce tag

NE TOUCHE PAS :
- Aux tags déjà en place ([PERSONNE_1], [IP_1], [LIEU_1], [ENTREPRISE_1], [REF_1], etc.)
- Aux termes techniques (SCADA, WinCC, OPC UA, PLC, Siemens, Schneider, etc.)
- Au formatage, à la structure, à la ponctuation

Si le texte est déjà bien anonymisé, retourne-le TEL QUEL, caractère pour caractère.

Retourne UNIQUEMENT le texte. Aucun commentaire."""


def call_ollama_chat(text: str, system_prompt: str, model: str = "gpt-oss:20b",
                     base_url: str = "http://localhost:11434", timeout: int = 300) -> tuple[str, bool]:
    """
    Appelle Ollama via /api/chat pour bénéficier du template harmony.
    Retourne (texte_résultat, succès_bool).
    """
    if not HAS_REQUESTS:
        return text, False

    try:
        response = requests.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Voici le texte à traiter :\n\n{text}"}
                ],
                "stream": False,
                "options": {
                    "temperature": 0.05,  # Quasi-déterministe
                    "top_p": 0.9,
                    "num_predict": 8192,
                    "num_ctx": 32768,      # Contexte généreux
                }
            },
            timeout=timeout
        )
        response.raise_for_status()
        data = response.json()
        result = data.get("message", {}).get("content", "")

        if not result.strip():
            return text, False

        return result.strip(), True

    except requests.exceptions.ConnectionError:
        return text, False
    except requests.exceptions.Timeout:
        return text, False
    except Exception:
        return text, False


# =============================================================================
# LECTURE DE FICHIERS
# =============================================================================

def read_file(filepath: Path) -> str:
    suffix = filepath.suffix.lower()
    if suffix in (".md", ".txt", ".csv", ".log", ".conf", ".ini", ".yaml", ".yml", ".json", ".xml"):
        return filepath.read_text(encoding="utf-8")
    elif suffix == ".docx":
        if not HAS_DOCX:
            print("❌ pip install python-docx", file=sys.stderr); sys.exit(1)
        doc = Document(str(filepath))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    parts.append(cell.text)
        return "\n".join(parts)
    elif suffix == ".pdf":
        if not HAS_PDF:
            print("❌ pip install pymupdf", file=sys.stderr); sys.exit(1)
        doc = fitz.open(str(filepath))
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    else:
        try:
            return filepath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"❌ Format non supporté : {suffix}", file=sys.stderr); sys.exit(1)


def read_file_bytes(data: bytes, filename: str) -> str:
    """Lit un fichier depuis des bytes en mémoire (pour Streamlit file_uploader)."""
    suffix = Path(filename).suffix.lower()
    if suffix in (".md", ".txt", ".csv", ".log", ".conf", ".ini", ".yaml", ".yml", ".json", ".xml"):
        return data.decode("utf-8")
    elif suffix == ".docx":
        if not HAS_DOCX:
            raise ImportError("python-docx requis : pip install python-docx")
        import io
        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    parts.append(cell.text)
        return "\n".join(parts)
    elif suffix == ".pdf":
        if not HAS_PDF:
            raise ImportError("pymupdf requis : pip install pymupdf")
        doc = fitz.open(stream=data, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    else:
        return data.decode("utf-8")


# =============================================================================
# DÉCOUPAGE
# =============================================================================

def split_into_chunks(text: str, max_chars: int = 4000) -> list[str]:
    """Découpe en essayant de couper aux doubles sauts de ligne, puis aux lignes."""
    if len(text) <= max_chars:
        return [text]

    # Essai découpe par paragraphes (double newline)
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2  # +2 pour \n\n
        if current_len + para_len > max_chars and current:
            chunks.append("\n\n".join(current))
            current = [para]
            current_len = para_len
        else:
            current.append(para)
            current_len += para_len

    if current:
        chunks.append("\n\n".join(current))

    # Vérifie que chaque chunk ne dépasse pas (sinon re-split par ligne)
    final_chunks = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            final_chunks.append(chunk)
        else:
            sub_current = []
            sub_len = 0
            for line in chunk.split("\n"):
                ll = len(line) + 1
                if sub_len + ll > max_chars and sub_current:
                    final_chunks.append("\n".join(sub_current))
                    sub_current = [line]
                    sub_len = ll
                else:
                    sub_current.append(line)
                    sub_len += ll
            if sub_current:
                final_chunks.append("\n".join(sub_current))

    return final_chunks


# =============================================================================
# VÉRIFICATION POST-ANONYMISATION
# =============================================================================

def post_check(text: str) -> list[str]:
    warnings = []

    # IPs
    ips = re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', text)
    if ips:
        warnings.append(f"IPs potentiellement restantes : {', '.join(set(ips))}")

    # Emails
    emails = re.findall(r'\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b', text)
    if emails:
        warnings.append(f"Emails potentiellement restants : {', '.join(set(emails))}")

    # FQDN
    fqdns = re.findall(
        r'\b[a-zA-Z][a-zA-Z0-9\-]*\.(?:[a-zA-Z0-9\-]+\.)*(?:local|lan|internal|corp|intra)\b', text
    )
    if fqdns:
        warnings.append(f"FQDN internes restants : {', '.join(set(fqdns))}")

    return warnings


def count_llm_tags(text: str) -> dict[str, int]:
    """Compte les tags LLM insérés pour le rapport."""
    tags = re.findall(r'\[(PERSONNE|ENTREPRISE|SITE|PROJET|LIEU|REF)_\d+\]', text)
    counts = defaultdict(int)
    for tag in tags:
        counts[tag] += 1
    # Regroupe par tag complet
    full_tags = re.findall(r'\[(?:PERSONNE|ENTREPRISE|SITE|PROJET|LIEU|REF)_\d+\]', text)
    tag_counts = defaultdict(int)
    for t in full_tags:
        tag_counts[t] += 1
    return dict(tag_counts)


# =============================================================================
# UTILITAIRES (pour l'UI)
# =============================================================================

def check_ollama(base_url: str = "http://localhost:11434",
                 model: str = "gpt-oss:20b") -> tuple[bool, str, list[str]]:
    """
    Vérifie la connexion Ollama et la disponibilité du modèle.
    Retourne (connecté, message, liste_modèles).
    """
    if not HAS_REQUESTS:
        return False, "Module 'requests' non installé", []
    try:
        r = requests.get(f"{base_url}/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        if any(model in m for m in models):
            return True, f"Ollama connecté — {model} prêt", models
        else:
            return True, f"Ollama connecté — {model} NON trouvé", models
    except requests.exceptions.ConnectionError:
        return False, "Ollama non joignable — lance 'ollama serve'", []
    except Exception as e:
        return False, f"Erreur Ollama : {e}", []


# =============================================================================
# PIPELINE PRINCIPAL (appelable depuis CLI ou UI)
# =============================================================================

def run_pipeline(
    text: str,
    filename: str = "document",
    custom_words: dict[str, str] | None = None,
    use_llm: bool = True,
    model: str = "gpt-oss:20b",
    ollama_url: str = "http://localhost:11434",
    chunk_size: int = 4000,
    passes: int = 2,
    timeout: int = 300,
    on_progress: Callable[[str, float], None] | None = None,
) -> dict:
    """
    Exécute la pipeline d'anonymisation complète.

    Retourne un dict avec :
      - text: texte anonymisé
      - mapping: dict tag → valeur originale
      - report: rapport markdown
      - warnings: liste de warnings
      - stats: statistiques d'exécution
    """
    log = Logger(on_progress=on_progress)
    log.stats["fichier_source"] = filename
    log.stats["taille_originale"] = len(text)

    log.log("INFO", f"Début anonymisation de {filename} ({len(text)} caractères)", progress=0.0)

    # ── Passe 0 : Mots personnalisés ──────────────────────────
    regex_anon = RegexAnonymizer()

    if custom_words:
        log.log("CUSTOM", f"Passe 0 : {len(custom_words)} mot(s) personnalisé(s)...", progress=0.05)
        text, custom_count = apply_custom_words(text, custom_words, regex_anon)
        log.stats["custom_remplacements"] = custom_count
        log.log("CUSTOM", f"{custom_count} remplacement(s) de mots personnalisés.")
        for word, cat in custom_words.items():
            if word.strip():
                log.log("CUSTOM", f"  [{cat.upper()}] ← {word}")

    # ── Passe 1 : Regex ────────────────────────────────────────
    log.log("REGEX", "Passe 1 : Anonymisation regex (IP, email, date, tél, FQDN, chemins)...", progress=0.1)
    text = regex_anon.anonymize(text)
    log.stats["regex_remplacements"] = len(regex_anon.mapping) - (len(custom_words) if custom_words else 0)
    log.log("REGEX", f"{log.stats['regex_remplacements']} patterns regex remplacés.")

    for key, tag in regex_anon.mapping.items():
        cat, val = key.split("::", 1)
        log.log("REGEX", f"  {tag} ← {val}")

    # ── Passes LLM ────────────────────────────────────────────
    llm_entity_map = {}

    if use_llm:
        # Vérification connexion Ollama
        log.log("LLM", f"Test connexion Ollama ({ollama_url})...", progress=0.15)
        connected, msg, _ = check_ollama(ollama_url, model)
        if not connected:
            log.log("ERROR", f"Connexion Ollama impossible : {msg}")
            log.log("ERROR", "Lance 'ollama serve' et réessaie.")
            # On continue en mode regex-only plutôt que de planter
            log.log("WARN", "Fallback en mode regex uniquement.")
            use_llm = False

    if use_llm:
        log.log("OK", f"Ollama OK. Modèle {model}.")
        chunks = split_into_chunks(text, chunk_size)
        total_chunks = len(chunks) * min(passes, 3)
        done_chunks = 0

        # --- Passe 2 : Anonymisation principale ---
        log.log("LLM", f"Passe 2 : Anonymisation NER ({len(chunks)} chunk(s), modèle {model})...",
                progress=0.2)
        log.stats["llm_passes"] += 1
        result_chunks = []
        for i, chunk in enumerate(chunks, 1):
            log.log("LLM", f"  Chunk [{i}/{len(chunks)}] ({len(chunk)} chars)...")
            result, success = call_ollama_chat(
                chunk, SYSTEM_PROMPT_PASS2,
                model=model, base_url=ollama_url, timeout=timeout
            )
            if success:
                log.log("OK", f"  Chunk [{i}/{len(chunks)}] traité.")
            else:
                log.log("ERROR", f"  Chunk [{i}/{len(chunks)}] erreur — texte original conservé.")
                log.stats["llm_erreurs"] += 1
            result_chunks.append(result)
            log.stats["llm_chunks_traites"] += 1
            done_chunks += 1
            progress = 0.2 + (done_chunks / total_chunks) * 0.65
            if on_progress:
                on_progress(f"Passe 2 — chunk {i}/{len(chunks)}", progress)

        text = "\n\n".join(result_chunks)

        # --- Passe 3 : Vérification LLM ---
        if passes >= 2:
            chunks2 = split_into_chunks(text, chunk_size)
            log.log("LLM", f"Passe 3 : Vérification NER ({len(chunks2)} chunk(s))...")
            log.stats["llm_passes"] += 1
            result_chunks2 = []
            for i, chunk in enumerate(chunks2, 1):
                log.log("LLM", f"  Vérif [{i}/{len(chunks2)}]...")
                result, success = call_ollama_chat(
                    chunk, SYSTEM_PROMPT_PASS3,
                    model=model, base_url=ollama_url, timeout=timeout
                )
                if success:
                    log.log("OK", f"  Vérif [{i}/{len(chunks2)}] OK.")
                else:
                    log.log("WARN", f"  Vérif [{i}/{len(chunks2)}] erreur — texte précédent conservé.")
                    log.stats["llm_erreurs"] += 1
                result_chunks2.append(result)
                log.stats["llm_chunks_traites"] += 1
                done_chunks += 1
                progress = 0.2 + (done_chunks / total_chunks) * 0.65
                if on_progress:
                    on_progress(f"Passe 3 vérif — chunk {i}/{len(chunks2)}", progress)

            text = "\n\n".join(result_chunks2)

        # --- Passe 4 optionnelle : re-vérif stricte ---
        if passes >= 3:
            chunks3 = split_into_chunks(text, chunk_size)
            log.log("LLM", f"Passe 4 : Re-vérification stricte ({len(chunks3)} chunk(s))...")
            log.stats["llm_passes"] += 1
            result_chunks3 = []
            for i, chunk in enumerate(chunks3, 1):
                log.log("LLM", f"  Strict [{i}/{len(chunks3)}]...")
                result, success = call_ollama_chat(
                    chunk, SYSTEM_PROMPT_PASS3,
                    model=model, base_url=ollama_url, timeout=timeout
                )
                result_chunks3.append(result)
                log.stats["llm_chunks_traites"] += 1
                done_chunks += 1
                progress = 0.2 + (done_chunks / total_chunks) * 0.65
                if on_progress:
                    on_progress(f"Passe 4 strict — chunk {i}/{len(chunks3)}", progress)
            text = "\n\n".join(result_chunks3)

        llm_entity_map = count_llm_tags(text)
        if llm_entity_map:
            log.log("LLM", "Tags LLM détectés dans le résultat :")
            for tag, count in sorted(llm_entity_map.items()):
                log.log("LLM", f"  {tag} × {count}")
    else:
        log.log("INFO", "Passe LLM ignorée.")

    # ── Vérification finale (regex) ────────────────────────────
    log.log("VERIF", "Vérification post-anonymisation (regex)...", progress=0.9)
    warnings = post_check(text)
    log.stats["verif_warnings"] = warnings
    if warnings:
        for w in warnings:
            log.log("WARN", w)
    else:
        log.log("OK", "Aucun pattern résiduel détecté.")

    log.stats["taille_finale"] = len(text)
    log.stats["duree_totale"] = round(time.time() - log.start_time, 2)

    # ── Construction du mapping ──────────────────────────────
    mapping_export = {}
    for key, tag in regex_anon.mapping.items():
        _, original = key.split("::", 1)
        mapping_export[tag] = original
    for tag in llm_entity_map:
        if tag not in mapping_export:
            mapping_export[tag] = "⟨détecté par LLM — valeur originale non tracée⟩"

    # ── Rapport ──────────────────────────────────────────────
    report = log.generate_report(regex_anon, llm_entity_map)

    log.log("DONE", "Anonymisation terminée.", progress=1.0)

    return {
        "text": text,
        "mapping": mapping_export,
        "report": report,
        "warnings": warnings,
        "stats": log.stats,
    }


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Anonymisation hybride v2 (Regex + LLM Ollama /api/chat, multi-passe)",
        epilog="""
Exemples :
  python anonymize.py cahier_des_charges.docx
  python anonymize.py rapport.pdf --model gpt-oss:120b
  python anonymize.py notes.md -o anonyme.md --no-llm
  python anonymize.py spec.docx --passes 3 --chunk-size 2000""",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("fichier", help="Fichier à anonymiser")
    parser.add_argument("--model", default="gpt-oss:20b", help="Modèle Ollama (défaut: gpt-oss:20b)")
    parser.add_argument("--output", "-o", help="Fichier de sortie (défaut: <nom>_anonymise.md)")
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="URL Ollama")
    parser.add_argument("--no-llm", action="store_true", help="Regex uniquement")
    parser.add_argument("--chunk-size", type=int, default=4000, help="Taille max par chunk (défaut: 4000)")
    parser.add_argument("--passes", type=int, default=2, choices=[1, 2, 3],
                        help="Nombre de passes LLM : 1=anonymisation, 2=+vérification, 3=+vérification stricte (défaut: 2)")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout par requête Ollama en secondes (défaut: 300)")

    args = parser.parse_args()
    filepath = Path(args.fichier)

    if not filepath.exists():
        print(f"❌ Fichier introuvable : {filepath}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  ANONYMISATION — {filepath.name}")
    print(f"{'='*60}\n")

    # Lecture
    text = read_file(filepath)

    # Exécution pipeline
    result = run_pipeline(
        text=text,
        filename=filepath.name,
        use_llm=not args.no_llm,
        model=args.model,
        ollama_url=args.ollama_url,
        chunk_size=args.chunk_size,
        passes=args.passes,
        timeout=args.timeout,
    )

    # Écriture des fichiers
    output_path = Path(args.output) if args.output else filepath.with_name(f"{filepath.stem}_anonymise.md")
    output_path.write_text(result["text"], encoding="utf-8")

    mapping_path = filepath.with_name(f"{filepath.stem}_mapping.json")
    mapping_path.write_text(json.dumps(result["mapping"], indent=2, ensure_ascii=False), encoding="utf-8")

    report_path = filepath.with_name(f"{filepath.stem}_rapport.md")
    report_path.write_text(result["report"], encoding="utf-8")

    # Résumé final
    s = result["stats"]
    print(f"\n{'='*60}")
    print(f"  RÉSUMÉ")
    print(f"{'='*60}")
    print(f"  📄 Source       : {filepath.name}")
    print(f"  📏 Taille       : {s['taille_originale']} → {s['taille_finale']} chars")
    if s["custom_remplacements"]:
        print(f"  🏷️  Custom       : {s['custom_remplacements']} remplacements")
    print(f"  🔍 Regex        : {s['regex_remplacements']} remplacements")
    print(f"  🤖 LLM          : {s['llm_passes']} passes, {s['llm_chunks_traites']} chunks")
    if s['llm_erreurs']:
        print(f"  ❌ Erreurs LLM  : {s['llm_erreurs']}")
    print(f"  ⚠️  Warnings     : {len(result['warnings'])}")
    print(f"  ⏱️  Durée        : {s['duree_totale']}s")
    print(f"  ✅ Sortie       : {output_path}")
    print(f"  📊 Rapport      : {report_path}")
    print(f"  🔑 Mapping      : {mapping_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
