"""Passe 1 — patterns structurés.

Chaque test correspond à un bug réellement rencontré. Les cas « ne doit
PAS matcher » sont aussi importants que les autres : plusieurs bugs
consistaient à avaler du texte voisin ou à taguer un terme technique.
"""

import unittest

from tests.outils import RACINE  # noqa: F401  (ajuste sys.path)
from anonymize import RegexAnonymizer, run_pipeline, _looks_like_ipv6

BS = chr(92)  # antislash, pour lisibilité des chemins UNC


class TestPatterns(unittest.TestCase):

    def anonymiser(self, texte):
        a = RegexAnonymizer()
        return a.anonymize(texte), a

    # ── Emails et FQDN ───────────────────────────────────────

    def test_email_entier_est_tague(self):
        """Le pattern FQDN passait avant l'email : seul le domaine était
        tagué et la partie locale de l'adresse restait en clair."""
        out, a = self.anonymiser("Contact jean.dupont@acme-industrie.com svp")
        self.assertNotIn("jean.dupont", out)
        self.assertIn("[EMAIL_1]", out)
        self.assertIn("jean.dupont@acme-industrie.com", a.originals.values())

    def test_fqdn_interne_tague(self):
        out, _ = self.anonymiser("serveur scada-prod01.usine.local")
        self.assertIn("[SERVEUR_1]", out)

    # ── Adresses IP ──────────────────────────────────────────

    def test_ipv4_taguee(self):
        out, _ = self.anonymiser("adresse 10.20.30.40 du poste")
        self.assertIn("[IP_1]", out)

    def test_ipv6_reelle_taguee(self):
        out, _ = self.anonymiser("firewall 2001:db8:85a3:0:0:8a2e:370:7334")
        self.assertIn("[IP_1]", out)

    def test_heure_nest_pas_une_ip(self):
        """"12:30:45" matchait le pattern IPv6 et devenait [IP_1]."""
        for heure in ("12:30:45", "08:15:00", "1:2:3"):
            out, _ = self.anonymiser(f"redemarrage a {heure} precises")
            self.assertEqual(out, f"redemarrage a {heure} precises", heure)

    def test_validateur_ipv6(self):
        self.assertTrue(_looks_like_ipv6("2001:db8:85a3:0:0:8a2e:370:7334"))
        self.assertTrue(_looks_like_ipv6("fe80:0:0:0:0:0:0:1"))
        self.assertFalse(_looks_like_ipv6("12:30:45"))
        self.assertFalse(_looks_like_ipv6("1:2:3"))

    # ── Chemins ──────────────────────────────────────────────

    def test_chemin_unc_nabsorbe_pas_le_mot_suivant(self):
        """Le pattern acceptait les espaces dans le dernier segment et
        avalait le mot d'après : le texte disparaissait du document."""
        src = f"Chemin {BS}{BS}SRV{BS}Partage{BS}Projets et la suite"
        out, _ = self.anonymiser(src)
        self.assertIn("[CHEMIN_1]", out)
        self.assertIn("et la suite", out)

    def test_chemin_unc_avec_espace_intermediaire(self):
        """Un vrai chemin avec espace doit être capturé en entier."""
        src = f"{BS}{BS}SRV02{BS}Program Files{BS}app.exe"
        out, a = self.anonymiser(src + " termine ici")
        self.assertIn("[CHEMIN_1]", out)
        self.assertIn("termine ici", out)
        self.assertIn(src, a.originals.values())

    def test_chemin_linux(self):
        out, _ = self.anonymiser("script dans /home/aurelien/bin")
        self.assertIn("[CHEMIN_1]", out)

    # ── Credentials ──────────────────────────────────────────

    def test_credential_sarrete_a_la_virgule(self):
        """La valeur courait jusqu'au bout de la ligne et avalait la
        phrase qui suivait."""
        out, a = self.anonymiser("Password=Sup3rS3cret, puis redemarrez")
        self.assertIn("[SECRET_1]", out)
        self.assertIn("puis redemarrez", out)
        self.assertIn("Sup3rS3cret", a.originals.values())

    def test_connection_string_complete(self):
        out, a = self.anonymiser("Server=srv;Password=Abc123;Uid=Admin;")
        self.assertIn("[SECRET_1]", out)
        self.assertIn("[SECRET_2]", out)
        self.assertIn("Abc123", a.originals.values())

    def test_casse_du_secret_preservee(self):
        """La clé de mapping est normalisée en minuscules ; la valeur
        d'origine doit garder sa casse, sinon le mapping est inutilisable
        pour retrouver le mot de passe."""
        _, a = self.anonymiser("Pwd=SuP3rS3cReT")
        self.assertIn("SuP3rS3cReT", a.originals.values())

    # ── Références de contrat ────────────────────────────────

    def test_references_contrat_taguees(self):
        for src in ("contrat N°ABC-2024-0456 signe",
                    "commande N°CMD-2026-0912 emise",
                    "reference ABC-2024-0456 du dossier",
                    "No 2025-0148 en cours",
                    "affaire n°A45-2024-77 validee"):
            out, _ = self.anonymiser(src)
            self.assertIn("[REF_", out, src)

    def test_reference_nabsorbe_pas_un_mot(self):
        """Sans exigence de chiffre, "notifie" était découpé en
        "no" + "tifie" et le mot disparaissait."""
        out, _ = self.anonymiser("contrat N°ABC-2024-0456 notifie ce jour")
        self.assertIn("notifie ce jour", out)

    # ── Termes techniques : ne doivent JAMAIS être tagués ────

    def test_termes_techniques_preserves(self):
        for src in ("automates Siemens S7-1500 en Profinet",
                    "norme IEC 61850 pour les postes",
                    "habilitations B2V et BR exigees",
                    "WinCC 7.5 et TIA Portal V17",
                    "vues IHM et OPC UA",
                    "article 12 du contrat cadre",
                    "batiment B3 de l'usine",
                    "le document a ete notifie et signe",
                    "nos equipes sont notifiees"):
            out, _ = self.anonymiser(src)
            self.assertEqual(out, src, src)

    # ── Dates et téléphones ──────────────────────────────────

    def test_dates(self):
        for src in ("04/02/2026", "2026-02-04", "4 fevrier 2026"):
            out, _ = self.anonymiser(f"le {src} a midi")
            self.assertIn("[DATE_1]", out, src)

    def test_telephone(self):
        out, _ = self.anonymiser("joignable au 06 12 34 56 78")
        self.assertIn("[TEL_1]", out)


class TestStatistiques(unittest.TestCase):
    """La stat regex était calculée par soustraction du nombre de mots du
    dictionnaire, ce qui la faussait dès qu'un mot était absent du texte."""

    def test_stat_regex_coherente_avec_le_mapping(self):
        src = ("mail a@b.com, ip 10.0.0.1, date 04/02/2026,\n"
               "tel 06 12 34 56 78, contrat N°ABC-2024-0456\n")
        r = run_pipeline(text=src, filename="t",
                         custom_words={"Absent": "PERSONNE"}, use_llm=False, verbose=False)
        self.assertEqual(r["stats"]["regex_remplacements"],
                         len(r["mapping"]))

    def test_aucun_avertissement_sur_document_propre(self):
        r = run_pipeline(text="Texte sans rien de sensible.\n",
                         filename="t", use_llm=False, verbose=False)
        self.assertEqual(r["warnings"], [])


if __name__ == "__main__":
    unittest.main()
