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

    def test_prefixe_couvrant_plusieurs_familles(self):
        """"QU-*" doit couvrir QU-WIN-xxx et QU-OPE-xxx d'un coup, sans
        toucher aux mots courants commençant par QU (QUALITE, QUI) — le
        tiret du motif suffit à les exclure."""
        r = self.anonymiser(
            "QU-*",
            "Le lot QU-WIN-123 et QU-OPE-456 remplacent QU-DOC-99, "
            "cf. paragraphe 4. Le terme QUALITE et le mot QUI restent.")
        for ref in ("QU-WIN", "QU-OPE", "QU-DOC"):
            self.assertNotIn(ref, r["text"])
        self.assertIn("QUALITE", r["text"])
        self.assertIn("QUI", r["text"])
        self.assertIn("cf. paragraphe 4", r["text"])
        self.assertEqual(len(r["mapping"]), 3)

    def test_meme_reference_meme_tag(self):
        """Deux occurrences de la même référence partagent leur tag ; deux
        références différentes restent distinguables."""
        r = self.anonymiser(
            "QU-*", "QU-WIN-123 puis QU-OPE-456 puis QU-WIN-123.")
        self.assertEqual(r["text"].count("[REF_1]"), 2)
        self.assertEqual(len(r["mapping"]), 2)

    def test_prefixe_court_avec_tiret_accepte(self):
        """Deux lettres suffisent si le préfixe contient un tiret ou un
        chiffre : c'est la signature d'une référence, pas d'un mot."""
        r = self.anonymiser("DV-*", "Devis DV-2601659 et DV-2601660 recus.")
        self.assertNotIn("2601659", r["text"])
        self.assertEqual(len(r["mapping"]), 2)

    def test_prefixe_avec_chiffre_accepte(self):
        r = self.anonymiser("B33*", "Lot B33-77 et B33-78.")
        self.assertNotIn("B33-77", r["text"])
        self.assertEqual(len(r["mapping"]), 2)

    def test_prefixe_de_quatre_lettres_accepte(self):
        r = self.anonymiser("ACME*", "Les societes ACMEA et ACMEB.")
        self.assertNotIn("ACMEA", r["text"])
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

class TestJokerTypographie(unittest.TestCase):
    """docx et pdf remplacent les tirets et espaces ASCII par des
    variantes unicode invisibles à l'œil, qui faisaient échouer
    silencieusement les motifs. `normaliser_texte()` les ramène à l'ASCII.
    """

    def anonymiser(self, texte):
        return run_pipeline(text=texte, filename="t",
                            custom_words={"QU-*": "REF"},
                            use_llm=False, verbose=False)

    def test_variantes_de_tirets_attrapees(self):
        variantes = {
            "cadratin (Word)": "QU—WIN—123",
            "demi-cadratin": "QU–WIN–123",
            "trait d'union unicode": "QU‐WIN‐123",
            "trait d'union insécable": "QU‑WIN‑123",
            "tiret numérique": "QU‒WIN‒123",
            "signe moins": "QU−WIN−123",
        }
        for nom, ref in variantes.items():
            r = self.anonymiser(f"Le lot {ref} est valide.")
            self.assertIn("[REF_1]", r["text"], nom)
            self.assertNotIn("WIN", r["text"], nom)
            self.assertNotIn("123", r["text"], nom)

    def test_trait_dunion_optionnel_supprime(self):
        r = self.anonymiser("Le lot QU-WIN­123 est valide.")
        self.assertNotIn("123", r["text"])

    def test_reference_coupee_en_fin_de_ligne(self):
        """"QU-WIN-\\n123" doit être recollé : sinon le numéro restait
        lisible juste après le tag."""
        r = self.anonymiser("Le lot QU-WIN-\n123 est valide.")
        self.assertIn("[REF_1]", r["text"])
        self.assertNotIn("123", r["text"])

    def test_cesure_de_mot_francais_non_recollee(self):
        """La règle ne recolle que si la suite commence par un chiffre ou
        une majuscule, pour ne pas fusionner une césure ordinaire."""
        from anonymize import normaliser_texte
        self.assertEqual(normaliser_texte("exploi-\ntation"),
                         "exploi-\ntation")


class TestJokerTropLarge(unittest.TestCase):
    """Bug observé en production : « QU* » au dictionnaire, insensible à la
    casse et sans ancrage, taguait le « qu » à l'intérieur des mots
    français — « Automatique » → « Automati[REF_30] », sur 143
    occurrences d'un document réel. Deux corrections : ancrage sur un
    début de mot, et rejet des jokers précédés de deux lettres seulement.
    """

    def anonymiser(self, motif, texte):
        return run_pipeline(text=texte, filename="t",
                            custom_words={motif: "REF"},
                            use_llm=False, verbose=False)

    PHRASE = ("Le systeme Automatique bloque Chaque acquisition "
              "et la qualite de QU-OPE-2558404.")

    def test_joker_de_deux_lettres_est_ignore(self):
        r = self.anonymiser("QU*", self.PHRASE)
        for mot in ("Automatique", "bloque", "Chaque", "acquisition",
                    "qualite"):
            self.assertIn(mot, r["text"], mot)

    def test_entree_ignoree_est_signalee(self):
        """Sans avertissement, l'entrée semblait active alors qu'elle
        n'anonymisait rien."""
        r = self.anonymiser("QU*", self.PHRASE)
        self.assertTrue(any("IGNORÉE" in w for w in r["warnings"]),
                        r["warnings"])
        self.assertTrue(any("QU*" in w for w in r["warnings"]))

    def test_meme_prefixe_avec_tiret_fonctionne(self):
        """La correction à appliquer : « QU-* » au lieu de « QU* »."""
        r = self.anonymiser("QU-*", self.PHRASE)
        self.assertIn("Automatique", r["text"])
        self.assertIn("acquisition", r["text"])
        self.assertNotIn("QU-OPE-2558404", r["text"])
        self.assertEqual(r["warnings"], [])

    def test_ancrage_sur_debut_de_mot(self):
        """Même un préfixe accepté ne doit pas matcher en milieu de mot."""
        r = self.anonymiser("CAPA-*", "La CAPA-12 et le mot RECAPA-99.")
        self.assertIn("RECAPA-99", r["text"])
        self.assertNotIn("CAPA-12", r["text"])

    def test_liste_des_entrees_ignorees(self):
        from anonymize import entrees_ignorees
        self.assertEqual(
            entrees_ignorees({"QU*": "REF", "DV*": "REF", "QU-*": "REF",
                              "B33*": "REF", "Nexans": "ENTREPRISE"}),
            ["DV*", "QU*"])


class TestJokerLimites(unittest.TestCase):
    """Deux cas que le joker ne couvre pas. Figés ici pour qu'ils restent
    connus : accepter des espaces dans le joker ferait déborder « QU-* »
    sur le mot suivant, ce qui est pire."""

    def anonymiser(self, texte):
        return run_pipeline(text=texte, filename="t",
                            custom_words={"QU-*": "REF"},
                            use_llm=False, verbose=False)

    def test_espace_insecable_laisse_un_fragment_mais_alerte(self):
        r = self.anonymiser("Le lot QU-WIN 123 est valide.")
        self.assertIn("123", r["text"])          # limite assumée
        self.assertTrue(any("nombre(s) isolé" in w for w in r["warnings"]),
                        r["warnings"])

    def test_espaces_autour_des_tirets_non_couverts(self):
        r = self.anonymiser("Le lot QU - WIN - 123 est valide.")
        self.assertNotIn("[REF_", r["text"])     # limite assumée


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
