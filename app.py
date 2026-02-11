"""
Interface Streamlit pour l'anonymisation de documents.
Lancement : streamlit run app.py
"""

import json
import streamlit as st
import pandas as pd
from pathlib import Path

from anonymize import (
    read_file_bytes,
    run_pipeline,
    check_ollama,
)

# =============================================================================
# CONFIG
# =============================================================================

MODEL = "gpt-oss:20b"
OLLAMA_URL = "http://localhost:11434"

CATEGORIES = [
    "PERSONNE",
    "ENTREPRISE",
    "SITE",
    "PROJET",
    "LIEU",
    "REF",
]

SUPPORTED_EXTENSIONS = [
    "md", "txt", "csv", "log", "conf", "ini",
    "yaml", "yml", "json", "xml", "docx", "pdf",
]

# =============================================================================
# PAGE CONFIG
# =============================================================================

st.set_page_config(
    page_title="Anonymisation de documents",
    page_icon="🔒",
    layout="wide",
)


# =============================================================================
# STATE
# =============================================================================

if "result" not in st.session_state:
    st.session_state.result = None
if "original_text" not in st.session_state:
    st.session_state.original_text = None
if "running" not in st.session_state:
    st.session_state.running = False


# =============================================================================
# SIDEBAR — Statut Ollama
# =============================================================================

with st.sidebar:
    st.header("Statut")
    connected, msg, models = check_ollama(OLLAMA_URL, MODEL)
    if connected and MODEL in " ".join(models):
        st.success(f"🟢 {msg}")
    elif connected:
        st.warning(f"🟡 {msg}")
        if models:
            st.caption(f"Modèles disponibles : {', '.join(models)}")
    else:
        st.error(f"🔴 {msg}")

    st.divider()
    st.caption("Tout le traitement se fait **localement** via Ollama.")
    st.caption("Aucune donnée n'est envoyée à un service externe.")


# =============================================================================
# MAIN
# =============================================================================

st.title("🔒 Anonymisation de documents")
st.caption("Glissez un document, configurez les options, anonymisez.")

# ── Upload ───────────────────────────────────────────────────

uploaded_file = st.file_uploader(
    "Glisser-déposer un fichier",
    type=SUPPORTED_EXTENSIONS,
    help="Formats supportés : " + ", ".join(f".{e}" for e in SUPPORTED_EXTENSIONS),
)

# ── Mots personnalisés ───────────────────────────────────────

st.subheader("Mots à anonymiser")
st.caption("Ajoutez des mots/noms spécifiques à remplacer en priorité (avant regex et LLM).")

if "custom_words_df" not in st.session_state:
    st.session_state.custom_words_df = pd.DataFrame(
        [{"Mot / Nom": "", "Catégorie": "PERSONNE"}],
        columns=["Mot / Nom", "Catégorie"],
    )

edited_df = st.data_editor(
    st.session_state.custom_words_df,
    column_config={
        "Mot / Nom": st.column_config.TextColumn(
            "Mot / Nom",
            help="Le mot ou nom à anonymiser (ex: Jean Dupont, Acme Corp)",
            width="large",
        ),
        "Catégorie": st.column_config.SelectboxColumn(
            "Catégorie",
            help="Type d'entité",
            options=CATEGORIES,
            width="medium",
        ),
    },
    num_rows="dynamic",
    use_container_width=True,
    key="custom_editor",
)

# ── Options ──────────────────────────────────────────────────

st.subheader("Options")

col1, col2 = st.columns(2)
with col1:
    passes = st.radio(
        "Passes LLM",
        options=[1, 2, 3],
        index=1,
        horizontal=True,
        help="1 = anonymisation seule, 2 = + vérification, 3 = + re-vérification stricte",
    )
with col2:
    no_llm = st.checkbox(
        "Regex uniquement (sans LLM)",
        value=False,
        help="Plus rapide mais moins précis — pas de détection de noms/entreprises",
    )

# ── Bouton Anonymiser ────────────────────────────────────────

st.divider()

can_run = uploaded_file is not None
if not connected and not no_llm:
    st.warning("Ollama n'est pas connecté. Activez 'Regex uniquement' ou lancez `ollama serve`.")
    can_run = can_run and False

if st.button("🚀 Anonymiser", type="primary", disabled=not can_run, use_container_width=True):
    # Préparer les mots custom
    custom_words = {}
    for _, row in edited_df.iterrows():
        word = str(row["Mot / Nom"]).strip()
        cat = str(row["Catégorie"]).strip()
        if word:
            custom_words[word] = cat

    # Lire le fichier
    try:
        file_bytes = uploaded_file.getvalue()
        text = read_file_bytes(file_bytes, uploaded_file.name)
    except Exception as e:
        st.error(f"Erreur de lecture : {e}")
        st.stop()

    st.session_state.original_text = text

    # Barre de progression
    progress_bar = st.progress(0, text="Démarrage...")
    status_text = st.empty()

    def on_progress(message: str, percent: float):
        progress_bar.progress(min(percent, 1.0), text=message)

    # Exécution
    with st.spinner("Anonymisation en cours..."):
        result = run_pipeline(
            text=text,
            filename=uploaded_file.name,
            custom_words=custom_words if custom_words else None,
            use_llm=not no_llm,
            model=MODEL,
            ollama_url=OLLAMA_URL,
            passes=passes,
            on_progress=on_progress,
        )

    progress_bar.progress(1.0, text="Terminé !")
    st.session_state.result = result

# ── Résultats ────────────────────────────────────────────────

if st.session_state.result is not None:
    result = st.session_state.result
    stats = result["stats"]

    st.divider()

    # Métriques
    st.subheader("Résultats")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Taille", f"{stats['taille_originale']} → {stats['taille_finale']}")
    col2.metric("Custom", stats["custom_remplacements"])
    col3.metric("Regex", stats["regex_remplacements"])
    col4.metric("Passes LLM", f"{stats['llm_passes']} ({stats['llm_chunks_traites']} chunks)")
    col5.metric("Durée", f"{stats['duree_totale']}s")

    if result["warnings"]:
        for w in result["warnings"]:
            st.warning(w)

    # Prévisualisation avant/après
    st.subheader("Prévisualisation")

    tab_after, tab_before, tab_report = st.tabs(["📄 Après (anonymisé)", "📝 Avant (original)", "📊 Rapport"])

    with tab_after:
        st.text_area(
            "Texte anonymisé",
            value=result["text"],
            height=400,
            label_visibility="collapsed",
        )

    with tab_before:
        st.text_area(
            "Texte original",
            value=st.session_state.original_text or "",
            height=400,
            disabled=True,
            label_visibility="collapsed",
        )

    with tab_report:
        st.markdown(result["report"])

    # Téléchargements
    st.subheader("Téléchargements")

    col1, col2, col3 = st.columns(3)

    filename_stem = Path(uploaded_file.name).stem if uploaded_file else "document"

    with col1:
        st.download_button(
            "⬇️ Fichier anonymisé (.md)",
            data=result["text"],
            file_name=f"{filename_stem}_anonymise.md",
            mime="text/markdown",
            use_container_width=True,
        )

    with col2:
        st.download_button(
            "⬇️ Mapping (.json)",
            data=json.dumps(result["mapping"], indent=2, ensure_ascii=False),
            file_name=f"{filename_stem}_mapping.json",
            mime="application/json",
            use_container_width=True,
        )

    with col3:
        st.download_button(
            "⬇️ Rapport (.md)",
            data=result["report"],
            file_name=f"{filename_stem}_rapport.md",
            mime="text/markdown",
            use_container_width=True,
        )
