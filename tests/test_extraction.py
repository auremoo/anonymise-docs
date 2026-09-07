"""Lecture des documents et extraction des images.

Le point critique : le numéro du placeholder `[IMAGE_N]` doit désigner le
fichier `IMAGE_N.ext`. Les tests le vérifient par la couleur des pixels,
pas par le nombre d'images — un simple comptage ne détecte pas un
décalage de numérotation.
"""

import tempfile
import unittest
from pathlib import Path

from tests.outils import (
    RACINE, A_PDF, A_DOCX, creer_pdf, creer_docx, couleur_du_fichier,
)
from anonymize import (
    read_file, read_file_bytes, read_file_with_images,
    read_file_bytes_with_images, save_images,
)


@unittest.skipUnless(A_PDF, "pymupdf non installé")
class TestPdf(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self._tmp.name)
        self.pdf = creer_pdf(self.dossier / "test.pdf")

    def tearDown(self):
        self._tmp.cleanup()

    def test_texte_extrait(self):
        texte, _ = read_file_with_images(self.pdf)
        self.assertIn("Nexans", texte)
        self.assertIn("10.20.30.40", texte)

    def test_nombre_dimages_et_de_placeholders(self):
        texte, images = read_file_with_images(self.pdf)
        self.assertEqual(len(images), 3)
        self.assertEqual(texte.count("[IMAGE_"), 3)

    def test_correspondance_placeholder_fichier(self):
        """IMAGE_1 doit être l'image de la page 1, etc."""
        _, images = read_file_with_images(self.pdf)
        sortie = self.dossier / "images"
        save_images(images, sortie)
        attendu = {"IMAGE_1": "rouge", "IMAGE_2": "vert", "IMAGE_3": "bleu"}
        for tag, couleur in attendu.items():
            fichier = sortie / f"{tag}.png"
            self.assertTrue(fichier.exists(), f"{tag} manquant")
            self.assertEqual(couleur_du_fichier(fichier), couleur, tag)

    def test_lecture_depuis_octets_identique(self):
        par_chemin, imgs1 = read_file_with_images(self.pdf)
        par_octets, imgs2 = read_file_bytes_with_images(
            self.pdf.read_bytes(), "test.pdf")
        self.assertEqual(par_chemin, par_octets)
        self.assertEqual(len(imgs1), len(imgs2))


@unittest.skipUnless(A_DOCX and A_PDF, "python-docx ou pymupdf non installé")
class TestDocx(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self._tmp.name)
        self.docx = creer_docx(self.dossier / "test.docx",
                               self.dossier / "src")

    def tearDown(self):
        self._tmp.cleanup()

    def test_image_de_cellule_de_tableau_extraite(self):
        """Le code ne parcourait que doc.paragraphs : une image dans une
        cellule n'était jamais extraite, et la numérotation glissait."""
        texte, images = read_file_with_images(self.docx)
        self.assertEqual(len(images), 4)
        self.assertEqual(texte.count("[IMAGE_"), 4)

    def test_correspondance_des_quatre_emplacements(self):
        _, images = read_file_with_images(self.docx)
        sortie = self.dossier / "images"
        save_images(images, sortie)
        attendu = {
            "IMAGE_1": "rouge",  # logo d'en-tête
            "IMAGE_2": "rouge",  # paragraphe
            "IMAGE_3": "vert",   # cellule de tableau
            "IMAGE_4": "bleu",   # paragraphe
        }
        for tag, couleur in attendu.items():
            fichier = sortie / f"{tag}.png"
            self.assertTrue(fichier.exists(), f"{tag} manquant")
            self.assertEqual(couleur_du_fichier(fichier), couleur, tag)

    def test_tableau_reste_a_sa_place(self):
        """Le contenu des tableaux était rejeté en fin de document, ce qui
        cassait le contexte que le LLM doit comprendre."""
        texte, _ = read_file_with_images(self.docx)
        self.assertLess(texte.index("Site |"),
                        texte.index("Derniere image"))

    def test_cellules_separees_lisiblement(self):
        texte, _ = read_file_with_images(self.docx)
        self.assertIn("Site | Bourg-en-Bresse", texte)

    def test_mode_texte_seul_garde_lordre(self):
        """Le mode sans extraction d'images doit utiliser le même parcours
        ordonné, sans émettre de placeholder."""
        texte = read_file(self.docx)
        self.assertNotIn("[IMAGE_", texte)
        self.assertLess(texte.index("Site |"),
                        texte.index("Derniere image"))

    def test_texte_seul_coherent_chemin_et_octets(self):
        self.assertEqual(
            read_file(self.docx),
            read_file_bytes(self.docx.read_bytes(), "test.docx"),
        )


class TestFormatsTexte(unittest.TestCase):

    def test_formats_simples_sans_images(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "notes.md"
            f.write_text("# Titre\nContact a@b.com\n", encoding="utf-8")
            texte, images = read_file_with_images(f)
            self.assertEqual(images, [])
            self.assertIn("a@b.com", texte)


class TestSauvegardeImages(unittest.TestCase):

    def test_liste_vide_ne_cree_pas_de_dossier(self):
        with tempfile.TemporaryDirectory() as d:
            cible = Path(d) / "images"
            self.assertEqual(save_images([], cible), [])
            self.assertFalse(cible.exists())

    def test_extensions_respectees(self):
        with tempfile.TemporaryDirectory() as d:
            cible = Path(d) / "images"
            noms = save_images([(b"aa", "png"), (b"bb", "jpg")], cible)
            self.assertEqual(noms, ["IMAGE_1.png", "IMAGE_2.jpg"])


if __name__ == "__main__":
    unittest.main()
