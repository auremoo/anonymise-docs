"""Rangement des sorties : un dossier par document dans output/.

Écrites à plat, les sorties de plusieurs documents se mélangeaient dans
output/. Les tests d'interface redirigent output/ vers un temporaire via
ANONYMISE_OUTPUT_DIR : ils ne doivent jamais toucher au vrai dossier.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.outils import RACINE
import anonymize
from anonymize import ecrire_sorties

try:
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    A_STREAMLIT = True
except ImportError:
    A_STREAMLIT = False

APP = str(RACINE / "app.py")


def _resultat(texte):
    return {"text": texte, "mapping": {"[PERSONNE_1]": "Jean Dupont"},
            "report": f"# Rapport\n{texte}"}


class TestEcritureSorties(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.output = Path(self._tmp.name)

    def test_un_dossier_par_document(self):
        ecrire_sorties(self.output / "cdc", "cdc", _resultat("A"))
        ecrire_sorties(self.output / "spec", "spec", _resultat("B"),
                       images=[(b"png", "png")])
        self.assertEqual(sorted(p.name for p in self.output.iterdir()),
                         ["cdc", "spec"])
        self.assertEqual(
            sorted(p.name for p in (self.output / "cdc").iterdir()),
            ["cdc_anonymise.md", "cdc_mapping.json", "cdc_rapport.md"])
        self.assertTrue(
            (self.output / "spec" / "spec_images" / "IMAGE_1.png").is_file())
        self.assertEqual(
            (self.output / "spec" / "spec_anonymise.md").read_text(), "B")

    def test_retraiter_ecrase_sans_dupliquer(self):
        ecrire_sorties(self.output / "cdc", "cdc", _resultat("v1"))
        ecrire_sorties(self.output / "cdc", "cdc", _resultat("v2"))
        self.assertEqual(len(list((self.output / "cdc").iterdir())), 3)
        self.assertEqual(
            (self.output / "cdc" / "cdc_anonymise.md").read_text(), "v2")

    def test_mapping_lisible(self):
        ecrire_sorties(self.output / "cdc", "cdc", _resultat("A"))
        self.assertIn("Jean Dupont",
                      (self.output / "cdc" / "cdc_mapping.json").read_text())


@unittest.skipUnless(A_STREAMLIT, "streamlit non installé")
class TestPanneauFichiersProduits(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.output = Path(self._tmp.name)
        env = mock.patch.dict(os.environ,
                              {"ANONYMISE_OUTPUT_DIR": str(self.output)})
        env.start()
        self.addCleanup(env.stop)
        llm = mock.patch.object(anonymize, "check_llm",
                                return_value=(True, "ok", ["modele"]))
        llm.start()
        self.addCleanup(llm.stop)
        st.cache_data.clear()

    def _dater(self, dossier, age):
        t = time.time() - age
        for f in [dossier, *dossier.iterdir()]:
            os.utime(f, (t, t))

    def _panneau(self):
        at = AppTest.from_file(APP, default_timeout=90).run()
        self.assertEqual(list(at.exception), [])
        return [m.value for m in at.markdown]

    def test_dossiers_listes_du_plus_recent_au_plus_ancien(self):
        ecrire_sorties(self.output / "ancien", "ancien", _resultat("A"))
        ecrire_sorties(self.output / "recent", "recent", _resultat("B"))
        self._dater(self.output / "ancien", 3600)
        titres = [m for m in self._panneau() if m.startswith("**")]
        self.assertEqual(titres[0].split("/")[0], "**recent")
        self.assertEqual(titres[1].split("/")[0], "**ancien")

    def test_retraiter_un_document_le_remonte(self):
        """La date d'un dossier ne change pas quand un fichier existant
        est réécrit : c'est celle de son contenu qui compte."""
        ecrire_sorties(self.output / "a", "a", _resultat("A"))
        ecrire_sorties(self.output / "b", "b", _resultat("B"))
        self._dater(self.output / "a", 7200)
        self._dater(self.output / "b", 3600)
        dossier_a = self.output / "a"
        t_dossier = dossier_a.stat().st_mtime
        ecrire_sorties(dossier_a, "a", _resultat("A2"))
        os.utime(dossier_a, (t_dossier, t_dossier))  # le dossier reste vieux
        titres = [m for m in self._panneau() if m.startswith("**")]
        self.assertEqual(titres[0].split("/")[0], "**a")

    def test_anciens_fichiers_a_plat_toujours_visibles(self):
        """Les sorties produites avant le rangement par dossier restent
        téléchargeables."""
        (self.output / "vieux_anonymise.md").write_text("x")
        ecrire_sorties(self.output / "neuf", "neuf", _resultat("B"))
        panneau = self._panneau()
        self.assertTrue(any("Anciens fichiers" in m for m in panneau))
        self.assertTrue(any(m.startswith("**neuf/") for m in panneau))

    def test_fichiers_caches_ignores(self):
        """Le Finder dépose un .DS_Store dans output/ : il apparaissait
        comme un « ancien fichier » à télécharger."""
        ecrire_sorties(self.output / "doc", "doc", _resultat("A"))
        (self.output / ".DS_Store").write_bytes(b"\0")
        (self.output / "doc" / ".DS_Store").write_bytes(b"\0")
        panneau = self._panneau()
        self.assertFalse(any("Anciens fichiers" in m for m in panneau))
        self.assertFalse(any(".DS_Store" in m for m in panneau))

    def test_images_signalees(self):
        ecrire_sorties(self.output / "doc", "doc", _resultat("A"),
                       images=[(b"1", "png"), (b"2", "jpg")])
        at = AppTest.from_file(APP, default_timeout=90).run()
        self.assertTrue(any("2 image(s)" in c.value for c in at.caption))


if __name__ == "__main__":
    unittest.main()
