"""Traitement lancé depuis l'interface Streamlit, de bout en bout.

Exécute réellement `app.py` via `AppTest` : dépôt d'un fichier, clic sur
« Anonymiser », traitement en arrière-plan, affichage des résultats. Le
moteur LLM n'est pas sollicité (« Regex uniquement »), `output/` et le
dictionnaire sont redirigés vers un temporaire.
"""

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.outils import RACINE
import anonymize

try:
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    # Le dépôt de fichier simulé n'existe que dans les versions récentes.
    A_STREAMLIT = hasattr(AppTest, "file_uploader")
except ImportError:
    A_STREAMLIT = False

APP = str(RACINE / "app.py")
DOCUMENT = ("cdc.md",
            "Contact : admin@acme.fr, chef de projet Nexans.\n".encode(),
            "text/markdown")


@unittest.skipUnless(A_STREAMLIT, "streamlit récent non installé")
class TestTraitementDepuisLInterface(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.output = Path(self._tmp.name) / "output"
        for cible, valeur in (
                ("OUTPUT_DIR", self.output),
                ("DICT_PATH", Path(self._tmp.name) / "dico.json"),
                ("check_llm", mock.Mock(return_value=(True, "ok", ["m"])))):
            patch = mock.patch.object(anonymize, cible, valeur)
            patch.start()
            self.addCleanup(patch.stop)
        st.cache_data.clear()
        # Le traitement partagé entre sessions vit dans un cache de
        # ressources : il ne doit pas fuir d'un test à l'autre.
        st.cache_resource.clear()
        self.addCleanup(st.cache_resource.clear)

    def _lancer(self) -> AppTest:
        at = AppTest.from_file(APP, default_timeout=90).run()
        at.file_uploader[0].set_value(DOCUMENT)
        at = at.run()
        [c for c in at.checkbox if "Regex" in c.label][0].check()
        at = at.run()
        return [b for b in at.button if "Anonymiser" in b.label][0].click().run()

    @staticmethod
    def _attendre_la_fin(at: AppTest) -> AppTest:
        for _ in range(300):
            if not at.session_state["pipe"]["running"]:
                break
            time.sleep(0.1)
        return at.run()

    def test_traitement_complet(self):
        at = self._attendre_la_fin(self._lancer())
        self.assertEqual(list(at.exception), [])
        resultat = [z.value for z in at.text_area if "[EMAIL_1]" in z.value]
        self.assertTrue(resultat, "texte anonymisé non affiché")
        self.assertTrue((self.output / "cdc" / "cdc_anonymise.md").is_file())
        self.assertIn("[EMAIL_1]",
                      (self.output / "cdc" / "cdc_anonymise.md").read_text(
                          encoding="utf-8"))

    def test_page_rechargee_pendant_le_traitement(self):
        """Une session neuve (page rechargée) ne voyait plus le traitement
        en cours : ni progression, ni bouton Arrêter, et « Anonymiser »
        restait cliquable — un second traitement partait sur le même GPU."""
        vrai = anonymize.run_pipeline
        demarre = threading.Event()

        def pipeline_lent(**kw):
            demarre.set()
            kw["cancel_flag"].wait(30)
            return vrai(**{**kw, "verbose": False})

        with mock.patch.object(anonymize, "run_pipeline", pipeline_lent):
            premiere = self._lancer()
            self.assertTrue(demarre.wait(10))

            recharge = AppTest.from_file(APP, default_timeout=90).run()
            self.assertEqual(list(recharge.exception), [])
            arreter = [b for b in recharge.button if "Arrêter" in b.label][0]
            anonymiser = [b for b in recharge.button
                          if "Anonymiser" in b.label][0]
            self.assertFalse(arreter.disabled)
            self.assertTrue(anonymiser.disabled)
            self.assertTrue(recharge.get("progress"))

            # L'arrêt demandé depuis la page rechargée atteint le traitement.
            recharge = self._attendre_la_fin(arreter.click().run())
        self.assertIs(recharge.session_state["pipe"],
                      premiere.session_state["pipe"])
        self.assertTrue(recharge.session_state["pipe"]["result"]
                        ["stats"]["annule"])


if __name__ == "__main__":
    unittest.main()
