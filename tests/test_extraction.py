"""Lecture des documents et extraction des images.

Le point critique : le numéro du placeholder `[IMAGE_N]` doit désigner le
fichier `IMAGE_N.ext`. Les tests le vérifient par la couleur des pixels,
pas par le nombre d'images — un simple comptage ne détecte pas un
décalage de numérotation.
"""

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import outils
from tests.outils import (
    RACINE, A_PDF, A_DOCX, creer_pdf, creer_docx, couleur_du_fichier,
    png_uni,
)
from anonymize import (
    read_file, read_file_bytes, read_file_with_images,
    read_file_bytes_with_images, save_images, Logger,
)

if A_DOCX:
    from docx import Document
    from docx.shared import Inches


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
            "IMAGE_1": "jaune",  # logo d'en-tête
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


@unittest.skipUnless(A_DOCX and A_PDF, "python-docx ou pymupdf non installé")
class TestImagesRepetees(unittest.TestCase):
    """Une image répétée garde son numéro : un logo présent sur chacune des
    197 pages d'un PDF donnait 197 fichiers identiques à vérifier."""

    def test_logo_sur_chaque_page_du_pdf(self):
        doc = outils.fitz.open()
        logo = png_uni("rouge")
        for _ in range(3):
            page = doc.new_page()
            page.insert_text((50, 60), "Texte de la page.")
            page.insert_image(outils.fitz.Rect(50, 100, 110, 160), stream=logo)
        page.insert_image(outils.fitz.Rect(150, 100, 210, 160),
                          stream=png_uni("bleu"))
        donnees = doc.tobytes()
        doc.close()

        texte, images = read_file_bytes_with_images(donnees, "logo.pdf")
        self.assertEqual(len(images), 2)
        self.assertEqual(texte.count("[IMAGE_1]"), 3)
        self.assertEqual(texte.count("[IMAGE_2]"), 1)
        with tempfile.TemporaryDirectory() as d:
            save_images(images, Path(d))
            self.assertEqual(couleur_du_fichier(Path(d) / "IMAGE_1.png"),
                             "rouge")
            self.assertEqual(couleur_du_fichier(Path(d) / "IMAGE_2.png"),
                             "bleu")

    def test_meme_image_a_deux_endroits_du_docx(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "rouge.png"
            source.write_bytes(png_uni("rouge"))
            doc = Document()
            doc.add_picture(str(source), width=Inches(1))
            table = doc.add_table(rows=1, cols=1)
            table.cell(0, 0).paragraphs[0].add_run().add_picture(
                str(source), width=Inches(1))
            chemin = Path(d) / "double.docx"
            doc.save(str(chemin))
            texte, images = read_file_with_images(chemin)
        self.assertEqual(len(images), 1)
        self.assertEqual(texte.count("[IMAGE_1]"), 2)


class TestFormatsTexte(unittest.TestCase):

    def test_formats_simples_sans_images(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "notes.md"
            f.write_text("# Titre\nContact a@b.com\n", encoding="utf-8")
            texte, images = read_file_with_images(f)
            self.assertEqual(images, [])
            self.assertIn("a@b.com", texte)


class TestEncodages(unittest.TestCase):
    """Les fichiers texte produits sous Windows ne sont pas tous en UTF-8 :
    un CSV exporté par Excel était refusé (UnicodeDecodeError)."""

    def test_csv_excel_windows_1252(self):
        texte = "Société;Ville\nNexans;Orléans\n"
        self.assertEqual(
            read_file_bytes(texte.encode("cp1252"), "export.csv"), texte)

    def test_bom_utf8_retire(self):
        self.assertEqual(
            read_file_bytes("﻿Contact a@b.com".encode("utf-8"),
                            "notes.txt"),
            "Contact a@b.com")

    def test_utf16_de_powershell(self):
        texte = "Contact a@b.com\r\n"
        self.assertEqual(
            read_file_bytes(texte.encode("utf-16"), "journal.log"), texte)

    def test_utf8_inchange(self):
        texte = "Réunion à Orléans — 12 €"
        self.assertEqual(read_file_bytes(texte.encode("utf-8"), "a.md"),
                         texte)

    def test_extension_inconnue_binaire_refusee(self):
        """Le repli Windows-1252 accepte n'importe quels octets : il ne
        s'applique qu'aux formats texte connus."""
        with self.assertRaises(UnicodeDecodeError):
            read_file_bytes(b"\x89PNG\r\n\x1a\n\xff\x00", "image.bin")

    def test_cli_refuse_proprement(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "image.bin"
            f.write_bytes(b"\x89PNG\r\n\x1a\n\xff\x00")
            with mock.patch("builtins.print") as affiche, \
                    self.assertRaises(SystemExit):
                read_file(f)
        self.assertIn("Format non supporté", affiche.call_args.args[0])


class TestConsoleNonUtf8(unittest.TestCase):
    """Sortie redirigée sous Windows (`> journal.txt`) : cp1252, et le
    premier emoji arrêtait le traitement."""

    def test_emoji_sur_console_cp1252(self):
        flux = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with mock.patch("sys.stdout", flux):
            Logger().log("INFO", "Début du traitement")
        flux.flush()
        self.assertIn("Début du traitement",
                      flux.buffer.getvalue().decode("cp1252"))


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
