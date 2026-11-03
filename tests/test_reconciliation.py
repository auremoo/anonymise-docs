"""Réconciliation des réponses du LLM avec le texte envoyé.

La consigne donnée au LLM est de remplacer des entités par des tags et de
ne rien toucher d'autre. `reconcilier_reponse()` aligne sa réponse sur le
texte envoyé et ne garde que ce qu'il avait le droit de faire. Ces tests
couvrent les écarts réellement observés :

- numérotation par bloc : « Beltech » [ENTREPRISE_2] dans un bloc et
  [ENTREPRISE_1] dans le suivant, et un tag du LLM qui reprend celui d'une
  entité du dictionnaire (deux personnes fusionnées dans le mapping) ;
- mapping inutilisable : « ⟨détecté par LLM⟩ » au lieu de la valeur ;
- préambule « Voici le texte anonymisé : » qui faisait rejeter le bloc ;
- texte tronqué, résumé ou remplacé par un exemple du prompt.

Aucun de ces tests n'a besoin d'un moteur LLM : les réponses sont simulées.
"""

import unittest
from unittest import mock

from tests.outils import RACINE  # noqa: F401  (ajuste sys.path)
import anonymize
from anonymize import (
    RegexAnonymizer, reconcilier_reponse, run_pipeline, VALEUR_LLM_INCONNUE,
)

REMPLISSAGE = "Le contrat couvre la maintenance des automates du lot. " * 12


def _pipeline(texte, reponse_llm, **kw):
    """Pipeline complet avec un moteur simulé : `reponse_llm(bloc)`."""
    kw.setdefault("passes", 1)
    with mock.patch.object(anonymize, "check_ollama",
                           return_value=(True, "ok", ["m"])), \
         mock.patch.object(anonymize, "call_ollama_chat",
                           side_effect=lambda t, p, **k: (reponse_llm(t),
                                                          True)):
        return run_pipeline(texte, filename="t", verbose=False, **kw)


def _remplacer(*paires):
    """LLM simulé qui remplace des valeurs par des tags (bloc par bloc)."""
    def reponse(bloc):
        for valeur, tag in paires:
            bloc = bloc.replace(valeur, tag)
        return bloc
    return reponse


class TestNumerotationCommune(unittest.TestCase):

    def test_tag_du_llm_ne_reprend_pas_celui_du_dictionnaire(self):
        """Le dictionnaire donne [PERSONNE_1] à Jean Dupont ; le LLM, qui
        numérote à partir de 1, donnait aussi [PERSONNE_1] à Marie Curie.
        Le mapping annonçait alors « Jean Dupont » pour les deux."""
        texte = ("Jean Dupont valide le lot.\n\n" + REMPLISSAGE
                 + "\n\nMarie Curie signe le PV.")
        r = _pipeline(texte, _remplacer(("Marie Curie", "[PERSONNE_1]")),
                      custom_words={"Jean Dupont": "PERSONNE"},
                      chunk_size=400)
        self.assertEqual(r["mapping"]["[PERSONNE_1]"], "Jean Dupont")
        self.assertEqual(r["mapping"]["[PERSONNE_2]"], "Marie Curie")
        self.assertIn("[PERSONNE_2] signe le PV.", r["text"])

    def test_meme_entite_meme_tag_dun_bloc_a_lautre(self):
        """Mesuré avec qwen3.5 : « Beltech » [ENTREPRISE_2] dans le bloc 1,
        [ENTREPRISE_1] dans le bloc 2."""
        texte = ("Nexans et Beltech livrent.\n\n" + REMPLISSAGE
                 + "\n\nBeltech facture.")

        def reponse(bloc):
            if "Nexans" in bloc:
                return (bloc.replace("Nexans", "[ENTREPRISE_1]")
                        .replace("Beltech", "[ENTREPRISE_2]"))
            return bloc.replace("Beltech", "[ENTREPRISE_1]")

        r = _pipeline(texte, reponse, chunk_size=400)
        tag_beltech = [t for t, v in r["mapping"].items() if v == "Beltech"]
        self.assertEqual(len(tag_beltech), 1)
        self.assertEqual(r["text"].count(tag_beltech[0]), 2)
        self.assertNotIn("Beltech", r["text"])

    def test_deux_entites_un_meme_tag_local_sont_separees(self):
        """Deux sociétés différentes toutes deux [ENTREPRISE_1], chacune
        dans son bloc : elles ne doivent pas fusionner."""
        texte = "Nexans livre.\n\n" + REMPLISSAGE + "\n\nSogetrel installe."
        r = _pipeline(texte, _remplacer(("Nexans", "[ENTREPRISE_1]"),
                                        ("Sogetrel", "[ENTREPRISE_1]")),
                      chunk_size=400)
        valeurs = sorted(v for t, v in r["mapping"].items()
                         if t.startswith("[ENTREPRISE_"))
        self.assertEqual(valeurs, ["Nexans", "Sogetrel"])

    def test_reprise_dune_entite_deja_taguee(self):
        """« M. Dupont » tagué avec le tag de « Jean Dupont » : c'est une
        reprise légitime, pas une collision."""
        texte = "Jean Dupont valide. M. Dupont signe."
        r = _pipeline(texte, _remplacer(("M. Dupont", "[PERSONNE_1]")),
                      custom_words={"Jean Dupont": "PERSONNE"})
        self.assertEqual(r["text"], "[PERSONNE_1] valide. [PERSONNE_1] signe.")

    def test_numerotation_sure_en_parallele(self):
        """Le registre des tags est partagé entre les chunks traités en
        parallèle : chaque valeur doit garder un tag unique."""
        noms = [f"Societe{i:02d}" for i in range(12)]
        texte = "\n\n".join(f"{n} livre le lot. " + "mot " * 40
                            for n in noms)

        def reponse(bloc):
            for n in noms:
                bloc = bloc.replace(n, "[ENTREPRISE_1]")
            return bloc

        r = _pipeline(texte, reponse, chunk_size=200, parallel=4)
        valeurs = [v for t, v in r["mapping"].items()
                   if t.startswith("[ENTREPRISE_")]
        self.assertEqual(sorted(valeurs), noms)


class TestMapping(unittest.TestCase):

    def test_valeur_dorigine_des_entites_du_llm(self):
        r = _pipeline("La societe Nexans a mandate Jean Dupont a Lyon.",
                      _remplacer(("Nexans", "[ENTREPRISE_1]"),
                                 ("Jean Dupont", "[PERSONNE_1]"),
                                 ("Lyon", "[LIEU_1]")))
        self.assertEqual(r["mapping"], {"[ENTREPRISE_1]": "Nexans",
                                        "[PERSONNE_1]": "Jean Dupont",
                                        "[LIEU_1]": "Lyon"})

    def test_le_rapport_liste_les_valeurs_a_relire(self):
        """« TGBT » tagué comme société n'est détectable par aucun contrôle :
        le rapport doit montrer ce que le LLM a remplacé."""
        r = _pipeline("Le TGBT alimente le local du site principal.",
                      _remplacer(("TGBT", "[ENTREPRISE_1]")))
        self.assertIn("| `[ENTREPRISE_1]` | `TGBT` | 1 |", r["report"])

    def test_ponctuation_interne_bien_alignee(self):
        """Le point de « M. » était aligné sur le point final de la phrase :
        la valeur devenait « M » et « Dupont » passait pour supprimé."""
        for entree, valeur in (("Contact : M. Dupont.", "M. Dupont"),
                               ("Voir J.D. Martin.", "J.D. Martin"),
                               ("Signé : Dr. A. Petit, le 3.", "Dr. A. Petit")):
            al = RegexAnonymizer()
            sortie = entree.replace(valeur, "[PERSONNE_1]")
            texte, bilan = reconcilier_reponse(entree, sortie, al)
            self.assertEqual(texte, sortie, entree)
            self.assertEqual(al.originals["[PERSONNE_1]"], valeur, entree)
            self.assertEqual(bilan["modifications"], [], entree)

    def test_liste_de_noms_valeur_par_tag(self):
        al = RegexAnonymizer()
        reconcilier_reponse("Presents : Jean, Marie, Paul.",
                            "Presents : [PERSONNE_1], [PERSONNE_2], "
                            "[PERSONNE_3].", al)
        self.assertEqual(sorted(al.originals.values()),
                         ["Jean", "Marie", "Paul"])

    def test_valeur_introuvable_reste_signalee(self):
        """Plusieurs tags pour un même passage : la valeur de chacun est
        inconnue, mais le tag reste unique et le texte anonymisé."""
        al = RegexAnonymizer()
        texte, _ = reconcilier_reponse(
            "Contact : Jean Dupont Nexans.", "Contact : [PERSONNE_1][ENTREPRISE_1].",
            al)
        self.assertNotIn("Dupont", texte)
        self.assertNotIn("Nexans", texte)
        self.assertEqual(set(al.originals.values()), {VALEUR_LLM_INCONNUE})


class TestCeQueLeLlmNaPasLeDroitDeFaire(unittest.TestCase):

    def test_preambule_retire_et_bloc_anonymise(self):
        """La réponse gonflée par le préambule dépassait 130 % : le bloc
        entier était rejeté et Nexans restait en clair."""
        r = _pipeline(
            "Rapport pour Nexans, revue annuelle des automates.",
            lambda t: "Voici le texte anonymisé :\n\n"
                      + t.replace("Nexans", "[ENTREPRISE_1]"))
        self.assertEqual(r["text"],
                         "Rapport pour [ENTREPRISE_1], revue annuelle "
                         "des automates.")
        self.assertEqual(r["stats"].get("llm_rejets", 0), 0)
        self.assertEqual(r["stats"]["llm_ajouts_retires"], 1)

    def test_bloc_court_dense_en_entites_accepte(self):
        """« Nexans livre. » → « [ENTREPRISE_1] livre. » faisait 160 % de
        l'entrée (le tag est plus long que le nom) : rejeté, et Nexans
        restait en clair. Cas typique d'un dernier bloc ou d'une signature."""
        r = _pipeline("Cordialement,\nMarie Lefevre\nNexans",
                      _remplacer(("Marie Lefevre", "[PERSONNE_1]"),
                                 ("Nexans", "[ENTREPRISE_1]")))
        self.assertEqual(r["text"],
                         "Cordialement,\n[PERSONNE_1]\n[ENTREPRISE_1]")
        self.assertEqual(r["warnings"], [])

    def test_commentaire_final_retire(self):
        """Un commentaire peut citer la valeur d'origine : il ne doit pas
        finir dans le document."""
        r = _pipeline(
            "Rapport pour Nexans, revue annuelle des automates du site.",
            lambda t: t.replace("Nexans", "[ENTREPRISE_1]")
            + "\n\nNote : Nexans a été remplacé par [ENTREPRISE_1].")
        self.assertNotIn("Nexans", r["text"])
        self.assertNotIn("Note", r["text"])

    def test_tag_existant_renumerote_est_retabli(self):
        """La consigne est de laisser les tags existants intacts ; un tag
        renuméroté désignerait une autre valeur dans le mapping."""
        al = RegexAnonymizer()
        texte, bilan = reconcilier_reponse(
            "Écrire à [EMAIL_1] ou voir [IMAGE_2] pour Jean.",
            "Écrire à [EMAIL_3] ou voir [IMAGE_1] pour [PERSONNE_1].", al)
        self.assertEqual(texte, "Écrire à [EMAIL_1] ou voir [IMAGE_2] pour "
                                "[PERSONNE_1].")
        self.assertEqual(bilan["tags_restaures"], 2)

    def test_mise_en_page_retablie(self):
        al = RegexAnonymizer()
        entree = "Titre\n\n  - item Nexans\n  - item 2"
        texte, _ = reconcilier_reponse(
            entree, "Titre\n- item [ENTREPRISE_1]\n- item 2", al)
        self.assertEqual(texte, "Titre\n\n  - item [ENTREPRISE_1]\n  - item 2")

    def test_fin_tronquee_retablie_et_signalee(self):
        """Une réponse arrêtée à 75 % passait le contrôle de taille : la fin
        du bloc disparaissait du document."""
        texte = ("Nexans livre les automates. La recette usine est prevue "
                 "en semaine 12 avec validation du lot par le client final.")
        r = _pipeline(texte,
                      lambda t: t.replace("Nexans", "[ENTREPRISE_1]")
                      .split(" avec ")[0] + ".")
        self.assertIn("validation du lot par le client final.", r["text"])
        self.assertIn("[ENTREPRISE_1]", r["text"])
        self.assertTrue(any("RÉTABLIS" in w for w in r["warnings"]),
                        r["warnings"])

    def test_exemple_du_prompt_recopie_a_la_place_du_texte(self):
        """Observé avec qwen2.5:3b : un paragraphe remplacé par une phrase
        d'exemple du prompt, de longueur voisine, tags compris."""
        texte = ("La recette des automates du lot 3 est programmee pour "
                 "la fin du mois prochain sur site.")
        exemple = ("[PERSONNE_1] de la société [ENTREPRISE_1] a visité "
                   "l'usine de [LIEU_1] le [DATE_1] pour la recette.")
        r = _pipeline(texte, lambda t: exemple)
        self.assertEqual(r["text"], texte)
        self.assertTrue(any("RÉTABLIS" in w for w in r["warnings"])
                        or any("REJET" in w for w in r["warnings"]),
                        r["warnings"])

    def test_petite_retouche_gardee_mais_signalee(self):
        r = _pipeline("Pierre a realise la recette des automates du site.",
                      lambda t: t.replace("Pierre", "[PERSONNE_1]")
                      .replace("realise", "réalisé"))
        self.assertIn("réalisé", r["text"])
        self.assertTrue(any(w.startswith("À vérifier") and "realise" in w
                            for w in r["warnings"]), r["warnings"])

    def test_mot_absorbe_par_un_tag_voisin_nest_pas_une_retouche(self):
        """Le dictionnaire ne connaît que « Jean » : le LLM fait disparaître
        le nom resté en clair à côté du tag. C'est le résultat attendu."""
        r = _pipeline("Visite de Jean Dupont sur le site de production.",
                      lambda t: t.replace("[PERSONNE_1] Dupont",
                                          "[PERSONNE_1]"),
                      custom_words={"Jean": "PERSONNE"})
        self.assertEqual(r["text"],
                         "Visite de [PERSONNE_1] sur le site de production.")
        self.assertFalse(any("À vérifier" in w for w in r["warnings"]),
                         r["warnings"])

    def test_reponse_conforme_inchangee(self):
        al = RegexAnonymizer()
        entree = "Le client Acme (contrat [REF_1]) valide le lot."
        sortie = "Le client [ENTREPRISE_1] (contrat [REF_1]) valide le lot."
        texte, bilan = reconcilier_reponse(entree, sortie, al)
        self.assertEqual(texte, sortie)
        self.assertEqual(bilan, {"entites": 1, "tags_restaures": 0,
                                 "ajouts": [], "retablis": [],
                                 "modifications": []})


if __name__ == "__main__":
    unittest.main()
