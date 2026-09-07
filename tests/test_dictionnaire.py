"""Passe 0 — dictionnaire de mots sensibles.

C'est la seule passe fiable à 100 % du pipeline (les modèles locaux
testés ratent des entités), donc son comportement doit être verrouillé.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tests.outils import RACINE  # noqa: F401  (ajuste sys.path)
from anonymize import (
    apply_custom_words,
    load_sensitive_words,
    save_sensitive_words,
    run_pipeline,
    RegexAnonymizer,
)


class TestCasse(unittest.TestCase):

    def test_toutes_les_variantes_de_casse_sont_remplacees(self):
        r = run_pipeline(text="NEXANS nexans NeXaNs Nexans", filename="t",
                         custom_words={"Nexans": "ENTREPRISE"},
                         use_llm=False, verbose=False)
        self.assertEqual(r["text"].strip(),
                         "[ENTREPRISE_1] [ENTREPRISE_1] "
                         "[ENTREPRISE_1] [ENTREPRISE_1]")

    def test_un_seul_tag_par_entite(self):
        """Les variantes de casse ne doivent pas créer un tag chacune."""
        r = run_pipeline(text="NEXANS nexans NeXaNs", filename="t",
                         custom_words={"Nexans": "ENTREPRISE"},
                         use_llm=False, verbose=False)
        self.assertEqual(len(r["mapping"]), 1)


class TestPasseZero(unittest.TestCase):

    def test_mot_absent_ne_cree_pas_de_tag(self):
        """Chaque mot du dictionnaire créait un tag même absent du texte,
        polluant le mapping de tags fantômes."""
        a = RegexAnonymizer()
        texte, n = apply_custom_words(
            "Rien de particulier ici.",
            {"Nexans": "ENTREPRISE", "Jean Dupont": "PERSONNE"}, a,
        )
        self.assertEqual(n, 0)
        self.assertEqual(a.mapping, {})

    def test_le_mot_le_plus_long_gagne(self):
        """"Jean Dupont" doit primer sur "Jean"."""
        a = RegexAnonymizer()
        texte, _ = apply_custom_words(
            "Jean Dupont arrive.",
            {"Jean": "PERSONNE", "Jean Dupont": "PERSONNE"}, a,
        )
        self.assertIn("[PERSONNE_1] arrive.", texte)
        self.assertEqual(len(a.mapping), 1)

    def test_un_mot_ne_matche_pas_dans_un_tag_deja_insere(self):
        """Le remplacement en un seul parcours empêche qu'un mot court
        vienne matcher à l'intérieur d'un tag posé par un mot précédent."""
        a = RegexAnonymizer()
        texte, _ = apply_custom_words(
            "Societe Personne et Nexans",
            {"Nexans": "ENTREPRISE", "PERSONNE": "PERSONNE"}, a,
        )
        # Aucun tag imbriqué du type [PERSONNE_1]_1]
        self.assertNotIn("]_", texte)

    def test_categorie_inconnue_ne_fait_pas_planter(self):
        a = RegexAnonymizer()
        texte, n = apply_custom_words("Acme est la.", {"Acme": "BIDON"}, a)
        self.assertEqual(n, 1)
        self.assertIn("[BIDON_1]", texte)


class TestJoker(unittest.TestCase):
    """Un `*` dans un mot couvre une série de références internes
    ("QU-OPE*" pour QU-OPE-1234, QU-OPE-5678...) sans les lister."""

    def anonymiser(self, motif, texte, categorie="REF"):
        return run_pipeline(text=texte, filename="t",
                            custom_words={motif: categorie},
                            use_llm=False, verbose=False)

    def test_serie_de_references(self):
        r = self.anonymiser(
            "QU-OPE*", "Voir QU-OPE-1234 et QU-OPE-5678 et QU-OPE-9999.")
        self.assertNotIn("QU-OPE", r["text"])
        # Chaque référence garde son propre tag : elles restent
        # distinguables dans le document anonymisé.
        self.assertEqual(len(r["mapping"]), 3)

    def test_prefixe_de_deux_caracteres(self):
        r = self.anonymiser("DV*", "Devis DV2601659 et DV2601660 recus.")
        self.assertNotIn("DV26", r["text"])
        self.assertEqual(len(r["mapping"]), 2)

    def test_ponctuation_finale_preservee(self):
        """Le joker acceptait le point final et l'avalait dans le tag."""
        r = self.anonymiser("QU-OPE*", "Dossier QU-OPE-9999.")
        self.assertTrue(r["text"].strip().endswith("."))
        self.assertEqual(list(r["mapping"].values()), ["QU-OPE-9999"])

    def test_joker_ne_franchit_pas_les_espaces(self):
        r = self.anonymiser("QU-OPE*", "QU-OPE-1234 puis autre chose.")
        self.assertIn("puis autre chose", r["text"])

    def test_point_interne_conserve(self):
        r = self.anonymiser("QU-OPE*", "Reference QU-OPE-1.2 revision B.")
        self.assertEqual(list(r["mapping"].values()), ["QU-OPE-1.2"])

    def test_motif_trop_large_ignore(self):
        """"*" ou "a*" anonymiseraient tout le document : ignorés."""
        for motif in ("*", "a*"):
            texte = "Un texte ordinaire sans rien de sensible."
            r = self.anonymiser(motif, texte)
            self.assertEqual(r["text"].strip(), texte, motif)

    def test_mot_sans_joker_inchange(self):
        r = self.anonymiser("Nexans", "NEXANS et nexans", "ENTREPRISE")
        self.assertEqual(r["text"].strip(),
                         "[ENTREPRISE_1] et [ENTREPRISE_1]")

    def test_categorie_respectee_avec_joker(self):
        r = self.anonymiser("QU-OPE*", "Dossier QU-OPE-1234 ouvert.", "PROJET")
        self.assertIn("[PROJET_1]", r["text"])


class TestFichierDictionnaire(unittest.TestCase):

    def test_aller_retour_sauvegarde_chargement(self):
        mots = {"Nexans": "ENTREPRISE", "Jean Dupont": "PERSONNE",
                "Sogetrel": "ENTREPRISE"}
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "dico.json"
            save_sensitive_words(mots, f)
            self.assertEqual(load_sensitive_words(f), mots)
            # Format attendu : {"CATEGORIE": ["mot", ...]}
            brut = json.loads(f.read_text(encoding="utf-8"))
            self.assertEqual(sorted(brut["ENTREPRISE"]),
                             ["Nexans", "Sogetrel"])

    def test_fichier_absent_retourne_dictionnaire_vide(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(
                load_sensitive_words(Path(d) / "inexistant.json"), {})

    def test_fichier_corrompu_ne_fait_pas_planter(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "casse.json"
            f.write_text("{ ceci n'est pas du json", encoding="utf-8")
            self.assertEqual(load_sensitive_words(f), {})


if __name__ == "__main__":
    unittest.main()
