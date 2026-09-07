"""Garde-fous du pipeline LLM.

Le mode d'échec principal de l'outil n'est pas de plafonner : c'est de
produire un document **partiellement** anonymisé sans le signaler. Ces
tests verrouillent le fait que chaque échec remonte dans
`result["warnings"]` — donc dans le rapport, l'UI et la sortie CLI.

Aucun de ces tests n'a besoin d'Ollama : les appels sont simulés.
"""

import threading
import unittest
from unittest import mock

from tests.outils import RACINE  # noqa: F401  (ajuste sys.path)
import anonymize
from anonymize import (
    run_pipeline, check_tag_vocabulary, post_check, split_into_chunks,
    _size_context, _run_llm_pass, Logger, SYSTEM_PROMPT_PASS2,
    check_tags_colles,
)

TEXTE = "La societe Nexans et Jean Dupont a Lyon travaillent ensemble.\n" * 4


def _pipeline(reponse_llm, passes=1, **kw):
    """Exécute le pipeline avec un Ollama simulé.

    `reponse_llm(texte)` renvoie (texte_retourne, succes).
    """
    with mock.patch.object(anonymize, "check_ollama",
                           return_value=(True, "ok", ["modele"])), \
         mock.patch.object(anonymize, "call_ollama_chat",
                           side_effect=lambda t, p, **k: reponse_llm(t)):
        return run_pipeline(text=TEXTE, filename="t", use_llm=True,
                            passes=passes, verbose=False, **kw)


class TestChunkNonTraite(unittest.TestCase):

    def test_echec_llm_remonte_un_avertissement(self):
        """Un chunk en timeout est conservé tel quel : la portion reste en
        clair. C'était une simple métrique dans le rapport."""
        r = _pipeline(lambda t: (t, False))
        self.assertTrue(any("NON trait" in w for w in r["warnings"]),
                        r["warnings"])
        self.assertEqual(r["stats"]["llm_erreurs"], 1)

    def test_le_texte_dorigine_est_conserve(self):
        r = _pipeline(lambda t: (t, False))
        self.assertIn("Nexans", r["text"])

    def test_le_rapport_contient_lavertissement(self):
        r = _pipeline(lambda t: (t, False))
        self.assertIn("NON trait", r["report"])


class TestRejetDintegrite(unittest.TestCase):
    """Un petit modèle peut réécrire le contenu ou recopier les exemples
    du prompt au lieu d'anonymiser. Observé avec qwen2.5:3b, qui
    remplaçait un paragraphe entier par une phrase d'exemple."""

    def test_reponse_trop_courte_est_rejetee(self):
        r = _pipeline(lambda t: ("beaucoup trop court", True))
        self.assertTrue(any("REJET" in w for w in r["warnings"]),
                        r["warnings"])
        self.assertEqual(r["stats"]["llm_rejets"], 1)

    def test_le_chunk_dorigine_est_conserve_intact(self):
        r = _pipeline(lambda t: ("beaucoup trop court", True))
        self.assertIn("Nexans", r["text"])
        self.assertNotIn("beaucoup trop court", r["text"])

    def test_reponse_trop_longue_est_rejetee(self):
        r = _pipeline(lambda t: (t + t, True))
        self.assertTrue(any("REJET" in w for w in r["warnings"]))

    def test_anonymisation_legitime_nest_pas_rejetee(self):
        """Aucun faux positif : remplacer des entités raccourcit un peu le
        texte, ce qui doit rester dans la plage acceptée."""
        r = _pipeline(lambda t: (t.replace("Nexans", "[ENTREPRISE_1]")
                                 .replace("Jean Dupont", "[PERSONNE_1]"),
                                 True))
        self.assertEqual(r["warnings"], [])
        self.assertIn("[ENTREPRISE_1]", r["text"])


class TestVocabulaireDeTags(unittest.TestCase):
    """mistral inventait des catégories ([MARQUE_TECHNIQUE_1] pour
    "Siemens"), signe qu'il anonymise des termes techniques protégés par
    la liste d'exclusion du prompt."""

    def test_categorie_inventee_detectee(self):
        r = _pipeline(lambda t: (t.replace("Nexans",
                                           "[MARQUE_TECHNIQUE_1]"), True))
        self.assertTrue(any("invent" in w for w in r["warnings"]),
                        r["warnings"])

    def test_vocabulaire_legitime_silencieux(self):
        self.assertEqual(
            check_tag_vocabulary(
                "[PERSONNE_1] chez [ENTREPRISE_2] via [IP_1], [IMAGE_3], "
                "[REF_1], [SECRET_1], [SITE_2], [PROJET_1], [LIEU_4]"),
            [])

    def test_categories_du_dictionnaire_acceptees(self):
        """Une catégorie définie par l'utilisateur est légitime."""
        self.assertEqual(
            check_tag_vocabulary("[MONCLIENT_1] ok", extra={"MONCLIENT"}),
            [])

    def test_plusieurs_categories_listees(self):
        avert = check_tag_vocabulary("[LOGICIEL_1] et [MARQUE_2]")
        self.assertEqual(len(avert), 1)
        self.assertIn("LOGICIEL", avert[0])
        self.assertIn("MARQUE", avert[0])


class TestTagsColles(unittest.TestCase):
    """Observé avec mistral : "automates S7-1500" devenait
    "[ENTREPRISE_1]-1500". La catégorie est légitime, donc le contrôle de
    vocabulaire ne voit rien — seule l'adjacence trahit la mutilation."""

    def test_reference_technique_mutilee_detectee(self):
        for texte in ("Les automates [ENTREPRISE_1]-1500 en Profinet",
                      "carte [ENTREPRISE_2]343-1 installee",
                      "site de [LIEU_1]-sur-Mer",
                      "prefixe[PERSONNE_1] colle"):
            self.assertTrue(check_tags_colles(texte), texte)

    def test_pas_de_faux_positif(self):
        """Un chemin tronqué par la passe regex ("[CHEMIN_1]/scripts") est
        normal, la ponctuation aussi."""
        for texte in ("script dans [CHEMIN_1]/scripts",
                      "Password=[SECRET_1];Uid=[SECRET_2];",
                      "contrat N°[REF_1] notifie",
                      "[PERSONNE_1] chez [ENTREPRISE_1] a [LIEU_1].",
                      "voir [IMAGE_1] puis [IMAGE_2]",
                      "([REF_1]) et [REF_2],"):
            self.assertEqual(check_tags_colles(texte), [], texte)

    def test_remonte_dans_les_avertissements(self):
        r = _pipeline(lambda t: (t.replace("Nexans", "[ENTREPRISE_9]-1500"),
                                 True))
        self.assertTrue(any("collé" in w for w in r["warnings"]),
                        r["warnings"])


class TestPasseDeVerification(unittest.TestCase):

    def test_aucun_changement_en_passe_3_nest_pas_une_alerte(self):
        """La passe 3 doit rendre le texte tel quel si rien n'a été
        oublié : c'est le résultat attendu, pas une anomalie."""
        r = _pipeline(lambda t: (t.replace("Nexans", "[ENTREPRISE_1]"), True),
                      passes=2)
        self.assertFalse(any("identique" in w for w in r["warnings"]),
                         r["warnings"])


class TestAnnulation(unittest.TestCase):

    def test_annulation_conserve_le_texte_et_le_signale(self):
        drapeau = threading.Event()
        drapeau.set()
        r = _pipeline(lambda t: (t, True), cancel_flag=drapeau)
        self.assertTrue(r["stats"]["annule"])
        self.assertIn("Nexans", r["text"])
        self.assertTrue(any("ANNUL" in w.upper() for w in r["warnings"]))

    def test_un_seul_message_stop_dans_le_journal(self):
        """Le message était logué une fois par chunk restant."""
        drapeau = threading.Event()
        drapeau.set()
        log = Logger()
        chunks = [f"chunk {i}" for i in range(6)]
        _run_llm_pass(chunks, "P", "Passe 2", log, "m", "u", 10,
                      drapeau, None, [0], len(chunks), parallel=3)
        stops = [e for e in log.entries if e["level"] == "STOP"]
        self.assertEqual(len(stops), 1)


class TestParallelisation(unittest.TestCase):

    # La réponse simulée garde la même longueur que l'entrée : sinon le
    # garde-fou d'intégrité la rejette (à juste titre) et le test ne
    # mesure plus l'ordre.
    @staticmethod
    def _reponse(texte):
        return texte.replace("chunk", "CHUNK"), True

    def test_ordre_des_chunks_preserve(self):
        """Les chunks partent en parallèle mais doivent être réassemblés
        dans l'ordre du document."""
        chunks = [f"chunk{i:02d} " + "mot " * 20 for i in range(12)]
        attendu = [c.replace("chunk", "CHUNK") for c in chunks]
        with mock.patch.object(
                anonymize, "call_ollama_chat",
                side_effect=lambda t, p, **k: self._reponse(t)):
            for parallele in (1, 4):
                log = Logger()
                res = _run_llm_pass(chunks, "P", "Passe 2", log, "m", "u", 10,
                                    None, None, [0], len(chunks),
                                    parallel=parallele)
                self.assertEqual(res, attendu, f"parallel={parallele}")

    def test_comptage_des_chunks_exact(self):
        chunks = [f"chunk{i:02d} " + "mot " * 20 for i in range(8)]
        with mock.patch.object(
                anonymize, "call_ollama_chat",
                side_effect=lambda t, p, **k: self._reponse(t)):
            log = Logger()
            _run_llm_pass(chunks, "P", "Passe 2", log, "m", "u", 10,
                          None, None, [0], len(chunks), parallel=3)
        self.assertEqual(log.stats["llm_chunks_traites"], 8)
        self.assertEqual(log.stats["llm_erreurs"], 0)
        self.assertEqual(log.stats.get("llm_rejets", 0), 0)


class TestDimensionnementContexte(unittest.TestCase):
    """num_ctx était figé à 32768 : un cache KV de 32k tokens alloué pour
    des chunks de quelques milliers de caractères."""

    def test_contexte_proportionnel_au_chunk(self):
        petit, _ = _size_context(SYSTEM_PROMPT_PASS2, "x" * 500)
        moyen, _ = _size_context(SYSTEM_PROMPT_PASS2, "x" * 4000)
        self.assertLess(petit, 32768)
        self.assertLessEqual(petit, moyen)

    def test_bornes_respectees(self):
        for taille in (0, 100, 4000, 50000):
            ctx, pred = _size_context(SYSTEM_PROMPT_PASS2, "x" * taille)
            self.assertGreaterEqual(ctx, 4096)
            self.assertLessEqual(ctx, 32768)
            self.assertGreaterEqual(pred, 512)
            self.assertLessEqual(pred, 8192)


class TestDecoupage(unittest.TestCase):

    def test_texte_court_reste_entier(self):
        self.assertEqual(split_into_chunks("court", 4000), ["court"])

    def test_chunks_sous_la_limite(self):
        texte = "\n\n".join(f"Paragraphe {i} " + "mot " * 60
                            for i in range(40))
        for chunk in split_into_chunks(texte, 1500):
            self.assertLessEqual(len(chunk), 1500)

    def test_aucun_contenu_perdu(self):
        texte = "\n\n".join(f"para{i}" for i in range(30))
        recolle = "\n\n".join(split_into_chunks(texte, 100))
        self.assertEqual(recolle.replace("\n", ""), texte.replace("\n", ""))


class TestVerificationFinale(unittest.TestCase):

    def test_post_check_signale_les_residus(self):
        avert = post_check("reste 10.0.0.1 et a@b.com et srv.corp")
        self.assertEqual(len(avert), 3)

    def test_post_check_silencieux_si_propre(self):
        self.assertEqual(post_check("Tout est [IP_1] et [EMAIL_1]."), [])


if __name__ == "__main__":
    unittest.main()
