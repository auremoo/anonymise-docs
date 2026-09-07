"""Éditeur JSON du dictionnaire dans l'interface Streamlit.

Ces tests exécutent réellement `app.py` via `AppTest` (framework de test
de Streamlit), donc ils couvrent le câblage complet : saisie, clic,
écriture du fichier, relecture par le pipeline.

Le fichier dictionnaire est redirigé vers un temporaire : un test ne doit
jamais écrire dans le `sensitive-words.json` de l'utilisateur.
"""

import tempfile
import unittest
from pathlib import Path

from tests.outils import RACINE
import anonymize

try:
    from streamlit.testing.v1 import AppTest
    A_STREAMLIT = True
except ImportError:
    A_STREAMLIT = False

APP = str(RACINE / "app.py")


@unittest.skipUnless(A_STREAMLIT, "streamlit non installé")
class TestEditeurJson(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._dict_origine = anonymize.DICT_PATH
        anonymize.DICT_PATH = Path(self._tmp.name) / "dico.json"
        self.dico = anonymize.DICT_PATH

    def tearDown(self):
        anonymize.DICT_PATH = self._dict_origine
        self._tmp.cleanup()

    def _appliquer(self, texte_json):
        at = AppTest.from_file(APP, default_timeout=90).run()
        at.text_area(key="json_dico_zone").set_value(texte_json)
        bouton = [b for b in at.button if "Appliquer" in b.label][0]
        return bouton.click().run()

    def test_chargement_sans_exception(self):
        at = AppTest.from_file(APP, default_timeout=90).run()
        self.assertEqual(list(at.exception), [])

    def test_json_valide_est_enregistre(self):
        at = self._appliquer(
            '{"ENTREPRISE": ["Nexans", "Sogetrel"], '
            '"PERSONNE": ["Jean Dupont"], "REF": ["QU-OPE*"]}'
        )
        self.assertEqual(list(at.exception), [])
        self.assertTrue(self.dico.exists())
        self.assertEqual(
            anonymize.load_sensitive_words(self.dico),
            {"Nexans": "ENTREPRISE", "Sogetrel": "ENTREPRISE",
             "Jean Dupont": "PERSONNE", "QU-OPE*": "REF"},
        )

    def test_json_invalide_refuse_sans_ecraser(self):
        """Un JSON mal formé ne doit pas remplacer un dictionnaire
        existant : c'est la seule passe fiable du pipeline."""
        depart = {"Nexans": "ENTREPRISE"}
        anonymize.save_sensitive_words(depart, self.dico)

        at = self._appliquer('{"ENTREPRISE": "pas une liste"}')
        self.assertTrue(at.error, "aucune erreur affichée")
        self.assertIn("liste", at.error[0].value)
        self.assertEqual(anonymize.load_sensitive_words(self.dico), depart)

    def test_json_illisible_refuse(self):
        at = self._appliquer("{ ceci n'est pas du json")
        self.assertTrue(at.error)
        self.assertFalse(self.dico.exists())

    def test_editeur_prerempli_depuis_le_fichier(self):
        anonymize.save_sensitive_words(
            {"Nexans": "ENTREPRISE"}, self.dico)
        at = AppTest.from_file(APP, default_timeout=90).run()
        self.assertIn("Nexans", at.text_area(key="json_dico_zone").value)


if __name__ == "__main__":
    unittest.main()
