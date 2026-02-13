"""
Interface Streamlit pour l'anonymisation de documents.
Lancement : streamlit run app.py
"""

import io
import json
import time
import zipfile
import threading
import streamlit as st
import pandas as pd
from pathlib import Path

from anonymize import (
    read_file_bytes_with_images,
    read_file_bytes,
    run_pipeline,
    save_images,
    check_ollama,
    load_sensitive_words,
    save_sensitive_words,
)

# =============================================================================
# TRADUCTIONS
# =============================================================================

TEXTS = {
    "page_title": {
        "FR": "Anonymisation de documents",
        "EN": "Document Anonymization",
    },
    "main_title": {
        "FR": "Anonymisation de documents",
        "EN": "Document Anonymization",
    },
    "main_caption": {
        "FR": "Glissez un document, configurez les options, anonymisez.",
        "EN": "Drop a document, configure options, anonymize.",
    },
    "status": {"FR": "Statut", "EN": "Status"},
    "model_label": {"FR": "Modèle LLM", "EN": "LLM Model"},
    "model_help": {
        "FR": "Sélectionnez le modèle Ollama à utiliser",
        "EN": "Select the Ollama model to use",
    },
    "local_notice": {
        "FR": "Tout le traitement se fait **localement** via Ollama.\n"
              "Aucune donnée n'est envoyée à un service externe.",
        "EN": "All processing is done **locally** via Ollama.\n"
              "No data is sent to any external service.",
    },
    "upload_label": {
        "FR": "Glisser-déposer un fichier",
        "EN": "Drag and drop a file",
    },
    "upload_help": {
        "FR": "Formats supportés : ",
        "EN": "Supported formats: ",
    },
    "custom_words_title": {
        "FR": "Mots à anonymiser",
        "EN": "Words to anonymize",
    },
    "custom_words_caption": {
        "FR": "Ajoutez des mots/noms spécifiques à remplacer en priorité "
              "(avant regex et LLM).",
        "EN": "Add specific words/names to replace first "
              "(before regex and LLM).",
    },
    "col_word": {"FR": "Mot / Nom", "EN": "Word / Name"},
    "col_category": {"FR": "Catégorie", "EN": "Category"},
    "col_word_help": {
        "FR": "Le mot ou nom à anonymiser (ex: Jean Dupont, Acme Corp)",
        "EN": "The word or name to anonymize (e.g. John Doe, Acme Corp)",
    },
    "col_category_help": {
        "FR": "Type d'entité",
        "EN": "Entity type",
    },
    "options_title": {"FR": "Options", "EN": "Options"},
    "passes_label": {"FR": "Passes LLM", "EN": "LLM Passes"},
    "passes_help": {
        "FR": "1 = anonymisation seule, 2 = + vérification, "
              "3 = + re-vérification stricte",
        "EN": "1 = anonymize only, 2 = + verification, "
              "3 = + strict re-verification",
    },
    "regex_only": {
        "FR": "Regex uniquement (sans LLM)",
        "EN": "Regex only (no LLM)",
    },
    "regex_only_help": {
        "FR": "Plus rapide mais moins précis — pas de détection de "
              "noms/entreprises",
        "EN": "Faster but less accurate — no name/company detection",
    },
    "extract_images": {
        "FR": "Extraire les images",
        "EN": "Extract images",
    },
    "extract_images_help": {
        "FR": "Extraire les images du document (docx/pdf) dans un dossier "
              "séparé avec placeholders [IMAGE_N]",
        "EN": "Extract images from document (docx/pdf) into a separate "
              "folder with [IMAGE_N] placeholders",
    },
    "ollama_warning": {
        "FR": "Ollama n'est pas connecté. Activez 'Regex uniquement' ou "
              "lancez `ollama serve`.",
        "EN": "Ollama is not connected. Enable 'Regex only' or "
              "run `ollama serve`.",
    },
    "btn_anonymize": {"FR": "Anonymiser", "EN": "Anonymize"},
    "btn_stop": {"FR": "Arrêter", "EN": "Stop"},
    "starting": {"FR": "Démarrage...", "EN": "Starting..."},
    "running": {
        "FR": "Anonymisation en cours...",
        "EN": "Anonymization in progress...",
    },
    "done": {"FR": "Terminé !", "EN": "Done!"},
    "cancelled": {"FR": "Annulé.", "EN": "Cancelled."},
    "read_error": {
        "FR": "Erreur de lecture : ",
        "EN": "Read error: ",
    },
    "results_title": {"FR": "Résultats", "EN": "Results"},
    "metric_size": {"FR": "Taille", "EN": "Size"},
    "metric_custom": {"FR": "Custom", "EN": "Custom"},
    "metric_regex": {"FR": "Regex", "EN": "Regex"},
    "metric_llm": {"FR": "Passes LLM", "EN": "LLM Passes"},
    "metric_time": {"FR": "Durée", "EN": "Duration"},
    "metric_images": {"FR": "Images", "EN": "Images"},
    "preview_title": {"FR": "Prévisualisation", "EN": "Preview"},
    "tab_after": {"FR": "Après (anonymisé)", "EN": "After (anonymized)"},
    "tab_before": {"FR": "Avant (original)", "EN": "Before (original)"},
    "tab_report": {"FR": "Rapport", "EN": "Report"},
    "downloads_title": {"FR": "Téléchargements", "EN": "Downloads"},
    "dl_anon": {
        "FR": "Fichier anonymisé (.md)",
        "EN": "Anonymized file (.md)",
    },
    "dl_mapping": {"FR": "Mapping (.json)", "EN": "Mapping (.json)"},
    "dl_report": {"FR": "Rapport (.md)", "EN": "Report (.md)"},
    "dl_images": {"FR": "Images (.zip)", "EN": "Images (.zip)"},
    "output_saved": {
        "FR": "Fichiers sauvegardés dans",
        "EN": "Files saved to",
    },
    "llm_no_change": {
        "FR": "chunk(s) retourné(s) identiques par le LLM — "
              "le modèle ne semble pas anonymiser. "
              "Essayez un modèle plus grand ou vérifiez qu'il est adapté au NER.",
        "EN": "chunk(s) returned identical by LLM — "
              "the model does not seem to anonymize. "
              "Try a larger model or check it supports NER.",
    },
    "btn_save_dict": {
        "FR": "Sauvegarder le dictionnaire",
        "EN": "Save dictionary",
    },
    "dict_saved": {
        "FR": "Dictionnaire sauvegardé",
        "EN": "Dictionary saved",
    },
    "dict_loaded": {
        "FR": "mot(s) chargé(s) depuis le dictionnaire",
        "EN": "word(s) loaded from dictionary",
    },
    "deep_analysis": {
        "FR": "Analyse approfondie",
        "EN": "Deep analysis",
    },
    "deep_analysis_help": {
        "FR": "Le LLM réfléchit plus — plus précis pour les noms/prénoms "
              "mais plus lent",
        "EN": "LLM thinks deeper — more accurate for names "
              "but slower",
    },
}


def t(key: str) -> str:
    """Get translated string for current language."""
    lang = st.session_state.get("lang", "FR")
    entry = TEXTS.get(key, {})
    return entry.get(lang, entry.get("FR", key))


# =============================================================================
# CONFIG
# =============================================================================

OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "gpt-oss:20b"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

CATEGORIES = [
    "PERSONNE", "ENTREPRISE", "SITE", "PROJET", "LIEU", "REF", "SECRET",
]

SUPPORTED_EXTENSIONS = [
    "md", "txt", "csv", "log", "conf", "ini",
    "yaml", "yml", "json", "xml", "docx", "pdf",
]

# =============================================================================
# PAGE CONFIG
# =============================================================================

st.set_page_config(
    page_title="Anonymize Docs",
    page_icon="\U0001f512",
    layout="wide",
)

# =============================================================================
# STATE
# =============================================================================

# Shared dict for background thread communication.
# The thread writes to this dict directly (not via st.session_state)
# which avoids Streamlit's "missing ScriptRunContext" warnings.
if "pipe" not in st.session_state:
    st.session_state.pipe = {
        "running": False,
        "result": None,
        "error": None,
        "msg": "",
        "pct": 0.0,
    }

if "original_text" not in st.session_state:
    st.session_state.original_text = None
if "images_data" not in st.session_state:
    st.session_state.images_data = None
if "cancel_flag" not in st.session_state:
    st.session_state.cancel_flag = threading.Event()
if "lang" not in st.session_state:
    st.session_state.lang = "FR"
if "filename_stem" not in st.session_state:
    st.session_state.filename_stem = ""

# Convenience reference (same dict object across reruns)
pipe = st.session_state.pipe

# =============================================================================
# SIDEBAR
# =============================================================================

with st.sidebar:
    # Language toggle
    lang = st.radio(
        "\U0001f310",
        ["FR", "EN"],
        index=0 if st.session_state.lang == "FR" else 1,
        horizontal=True,
        key="lang_radio",
    )
    st.session_state.lang = lang

    st.header(t("status"))

    # Check Ollama + get available models
    connected, msg, available_models = check_ollama(OLLAMA_URL, DEFAULT_MODEL)

    if connected and DEFAULT_MODEL in " ".join(available_models):
        st.success(f"\U0001f7e2 {msg}")
    elif connected:
        st.warning(f"\U0001f7e1 {msg}")
    else:
        st.error(f"\U0001f534 {msg}")

    # Model selector
    if available_models:
        default_idx = 0
        for i, m in enumerate(available_models):
            if DEFAULT_MODEL in m:
                default_idx = i
                break
        selected_model = st.selectbox(
            t("model_label"),
            options=available_models,
            index=default_idx,
            help=t("model_help"),
        )
    else:
        selected_model = DEFAULT_MODEL
        st.caption(f"Model: {DEFAULT_MODEL}")

    st.divider()
    st.caption(t("local_notice"))

# =============================================================================
# MAIN
# =============================================================================

st.title(f"\U0001f512 {t('main_title')}")
st.caption(t("main_caption"))

# ── Upload ───────────────────────────────────────────────────

uploaded_file = st.file_uploader(
    t("upload_label"),
    type=SUPPORTED_EXTENSIONS,
    help=t("upload_help") + ", ".join(f".{e}" for e in SUPPORTED_EXTENSIONS),
    disabled=pipe["running"],
)

# ── Custom words ─────────────────────────────────────────────

st.subheader(t("custom_words_title"))
st.caption(t("custom_words_caption"))

if "custom_words_df" not in st.session_state:
    # Load persistent dictionary on first run
    saved_words = load_sensitive_words()
    if saved_words:
        rows = [
            {t("col_word"): word, t("col_category"): cat}
            for word, cat in saved_words.items()
        ]
        st.session_state.custom_words_df = pd.DataFrame(
            rows, columns=[t("col_word"), t("col_category")],
        )
        st.session_state._dict_loaded_count = len(saved_words)
    else:
        st.session_state.custom_words_df = pd.DataFrame(
            [{t("col_word"): "", t("col_category"): "PERSONNE"}],
            columns=[t("col_word"), t("col_category")],
        )

# Show load notification once
if st.session_state.get("_dict_loaded_count", 0) > 0:
    st.info(
        f"{st.session_state._dict_loaded_count} {t('dict_loaded')}"
    )
    st.session_state._dict_loaded_count = 0

# Rebuild column names if language changed
col_word = t("col_word")
col_cat = t("col_category")

df = st.session_state.custom_words_df
if df.columns.tolist() != [col_word, col_cat]:
    df.columns = [col_word, col_cat]

edited_df = st.data_editor(
    df,
    column_config={
        col_word: st.column_config.TextColumn(
            col_word, help=t("col_word_help"), width="large",
        ),
        col_cat: st.column_config.SelectboxColumn(
            col_cat, help=t("col_category_help"),
            options=CATEGORIES, width="medium",
        ),
    },
    num_rows="dynamic",
    width="stretch",
    key="custom_editor",
    disabled=pipe["running"],
)

# Save dictionary button
if st.button(
    f"\U0001f4be {t('btn_save_dict')}",
    disabled=pipe["running"],
):
    words_to_save = {}
    for _, row in edited_df.iterrows():
        word = str(row[col_word]).strip()
        cat = str(row[col_cat]).strip()
        if word:
            words_to_save[word] = cat
    save_sensitive_words(words_to_save)
    st.success(f"{t('dict_saved')} ({len(words_to_save)} mots)")

# ── Options ──────────────────────────────────────────────────

st.subheader(t("options_title"))

col1, col2, col3, col4 = st.columns(4)
with col1:
    passes = st.radio(
        t("passes_label"),
        options=[1, 2, 3],
        index=1,
        horizontal=True,
        help=t("passes_help"),
        disabled=pipe["running"],
    )
with col2:
    no_llm = st.checkbox(
        t("regex_only"),
        value=False,
        help=t("regex_only_help"),
        disabled=pipe["running"],
    )
with col3:
    deep_analysis = st.checkbox(
        t("deep_analysis"),
        value=False,
        help=t("deep_analysis_help"),
        disabled=pipe["running"] or no_llm,
    )
with col4:
    extract_imgs = st.checkbox(
        t("extract_images"),
        value=True,
        help=t("extract_images_help"),
        disabled=pipe["running"],
    )

# ── Buttons ──────────────────────────────────────────────────

st.divider()

can_run = uploaded_file is not None and not pipe["running"]
if not connected and not no_llm:
    st.warning(t("ollama_warning"))
    can_run = False

btn_col1, btn_col2 = st.columns([3, 1])

with btn_col1:
    run_clicked = st.button(
        f"\U0001f680 {t('btn_anonymize')}",
        type="primary",
        disabled=not can_run,
        width="stretch",
    )

with btn_col2:
    stop_clicked = st.button(
        f"\U0001f6d1 {t('btn_stop')}",
        disabled=not pipe["running"],
        width="stretch",
    )

if stop_clicked:
    st.session_state.cancel_flag.set()

# ── Start pipeline (background thread) ──────────────────────

if run_clicked:
    # Reset shared state
    pipe["running"] = True
    pipe["result"] = None
    pipe["error"] = None
    pipe["msg"] = t("starting")
    pipe["pct"] = 0.0

    st.session_state.images_data = None
    st.session_state.cancel_flag = threading.Event()

    # Prepare custom words
    custom_words = {}
    for _, row in edited_df.iterrows():
        word = str(row[col_word]).strip()
        cat = str(row[col_cat]).strip()
        if word:
            custom_words[word] = cat

    # Read file + extract images
    try:
        file_bytes = uploaded_file.getvalue()
        if extract_imgs:
            text, images = read_file_bytes_with_images(
                file_bytes, uploaded_file.name,
            )
        else:
            text = read_file_bytes(file_bytes, uploaded_file.name)
            images = []
    except Exception as e:
        st.error(f"{t('read_error')}{e}")
        pipe["running"] = False
        st.stop()

    st.session_state.original_text = text
    st.session_state.images_data = images
    filename_stem = Path(uploaded_file.name).stem
    st.session_state.filename_stem = filename_stem
    images_folder = f"{filename_stem}_images" if images else ""

    # Capture references for the thread (no st.session_state access)
    _pipe = pipe
    _cancel_flag = st.session_state.cancel_flag
    _text = text
    _filename = uploaded_file.name
    _custom_words = custom_words if custom_words else None
    _use_llm = not no_llm
    _model = selected_model
    _passes = passes
    _images = images
    _images_folder = images_folder
    _filename_stem = filename_stem
    _deep_analysis = deep_analysis

    def on_progress(message: str, percent: float):
        _pipe["msg"] = message
        _pipe["pct"] = min(percent, 1.0)

    def run_in_thread():
        try:
            result = run_pipeline(
                text=_text,
                filename=_filename,
                custom_words=_custom_words,
                use_llm=_use_llm,
                model=_model,
                ollama_url=OLLAMA_URL,
                passes=_passes,
                on_progress=on_progress,
                cancel_flag=_cancel_flag,
                images_count=len(_images),
                images_folder=_images_folder,
                deep_analysis=_deep_analysis,
            )
            _pipe["result"] = result

            # Auto-save to output/ folder
            OUTPUT_DIR.mkdir(exist_ok=True)
            (OUTPUT_DIR / f"{_filename_stem}_anonymise.md").write_text(
                result["text"], encoding="utf-8",
            )
            (OUTPUT_DIR / f"{_filename_stem}_mapping.json").write_text(
                json.dumps(
                    result["mapping"], indent=2, ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (OUTPUT_DIR / f"{_filename_stem}_rapport.md").write_text(
                result["report"], encoding="utf-8",
            )
            if _images:
                save_images(
                    _images, OUTPUT_DIR / f"{_filename_stem}_images",
                )
        except Exception as e:
            _pipe["error"] = str(e)
        finally:
            _pipe["running"] = False

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()
    st.rerun()

# ── Polling while pipeline runs ──────────────────────────────

if pipe["running"]:
    progress_container = st.empty()
    while pipe["running"]:
        msg = pipe["msg"] or t("starting")
        pct = pipe["pct"]
        progress_container.progress(min(max(pct, 0.0), 1.0), text=msg)
        time.sleep(0.5)
    # Pipeline finished — brief display of final state
    if st.session_state.cancel_flag.is_set():
        progress_container.progress(1.0, text=t("cancelled"))
    else:
        progress_container.progress(1.0, text=t("done"))
    time.sleep(1)
    st.rerun()  # One final rerun to show results with enabled controls

# ── Pipeline error ───────────────────────────────────────────

if pipe["error"]:
    st.error(f"Pipeline error: {pipe['error']}")
    pipe["error"] = None

# ── Results ──────────────────────────────────────────────────

if pipe["result"] is not None:
    result = pipe["result"]
    stats = result["stats"]
    images = st.session_state.images_data or []

    st.divider()
    st.subheader(t("results_title"))

    # Output saved notification
    filename_stem = st.session_state.filename_stem
    saved_files = (
        f"`output/{filename_stem}_anonymise.md`, "
        f"`output/{filename_stem}_mapping.json`, "
        f"`output/{filename_stem}_rapport.md`"
    )
    if images:
        saved_files += f", `output/{filename_stem}_images/`"
    st.success(f"{t('output_saved')} {saved_files}")

    # Metrics
    cols = st.columns(6)
    cols[0].metric(
        t("metric_size"),
        f"{stats['taille_originale']} \u2192 {stats['taille_finale']}",
    )
    cols[1].metric(t("metric_custom"), stats["custom_remplacements"])
    cols[2].metric(t("metric_regex"), stats["regex_remplacements"])
    cols[3].metric(
        t("metric_llm"),
        f"{stats['llm_passes']} ({stats['llm_chunks_traites']} chunks)",
    )
    cols[4].metric(t("metric_time"), f"{stats['duree_totale']}s")
    cols[5].metric(t("metric_images"), stats["images_trouvees"])

    # LLM error warnings
    if stats.get("llm_erreurs", 0) > 0:
        st.error(
            f"LLM: {stats['llm_erreurs']} erreur(s) — "
            "certains chunks n'ont pas été traités par le LLM. "
            "Vérifiez qu'Ollama est lancé et que le modèle répond."
        )

    if stats.get("llm_no_change", 0) > 0:
        st.warning(
            f"LLM: {stats['llm_no_change']} {t('llm_no_change')}"
        )

    if result["warnings"]:
        for w in result["warnings"]:
            st.warning(w)

    if stats.get("annule"):
        st.warning(t("cancelled"))

    # Preview tabs
    st.subheader(t("preview_title"))

    tab_after, tab_before, tab_report = st.tabs([
        f"\U0001f4c4 {t('tab_after')}",
        f"\U0001f4dd {t('tab_before')}",
        f"\U0001f4ca {t('tab_report')}",
    ])

    with tab_after:
        st.text_area(
            t("tab_after"),
            value=result["text"],
            height=400,
            label_visibility="collapsed",
        )

    with tab_before:
        st.text_area(
            t("tab_before"),
            value=st.session_state.original_text or "",
            height=400,
            disabled=True,
            label_visibility="collapsed",
        )

    with tab_report:
        st.markdown(result["report"])

    # Downloads
    st.subheader(t("downloads_title"))

    dl_cols = st.columns(4 if images else 3)

    with dl_cols[0]:
        st.download_button(
            f"\u2b07\ufe0f {t('dl_anon')}",
            data=result["text"],
            file_name=f"{filename_stem}_anonymise.md",
            mime="text/markdown",
            width="stretch",
        )

    with dl_cols[1]:
        st.download_button(
            f"\u2b07\ufe0f {t('dl_mapping')}",
            data=json.dumps(
                result["mapping"], indent=2, ensure_ascii=False,
            ),
            file_name=f"{filename_stem}_mapping.json",
            mime="application/json",
            width="stretch",
        )

    with dl_cols[2]:
        st.download_button(
            f"\u2b07\ufe0f {t('dl_report')}",
            data=result["report"],
            file_name=f"{filename_stem}_rapport.md",
            mime="text/markdown",
            width="stretch",
        )

    if images:
        # Create a zip of all images for download
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, (img_data, ext) in enumerate(images, 1):
                zf.writestr(f"IMAGE_{i}.{ext}", img_data)
        zip_buffer.seek(0)

        with dl_cols[3]:
            st.download_button(
                f"\u2b07\ufe0f {t('dl_images')}",
                data=zip_buffer.getvalue(),
                file_name=f"{filename_stem}_images.zip",
                mime="application/zip",
                width="stretch",
            )
