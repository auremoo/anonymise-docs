"""Backend LM Studio (API compatible OpenAI).

Aucun de ces tests n'a besoin de LM Studio : les réponses HTTP sont
simulées. Chaque réponse simulée reprend le format réellement renvoyé
par LM Studio avec qwen3.5-9b.
"""

import unittest
from unittest import mock

import requests

from tests.outils import RACINE  # noqa: F401  (ajuste sys.path)
import anonymize
from anonymize import (
    call_lmstudio_chat, check_lmstudio, call_llm_chat, run_pipeline,
    SYSTEM_PROMPT_PASS2,
)

TEXTE = "La societe Nexans a mandate Jean Dupont sur le site de Lyon."
ANONYME = "La societe [ENTREPRISE_1] a mandate [PERSONNE_1] sur le site de [LIEU_1]."


def _reponse(contenu="", finish="stop", status=200, raisonnement=""):
    r = mock.Mock(status_code=status)
    r.json.return_value = {"choices": [{
        "message": {"role": "assistant", "content": contenu,
                    "reasoning_content": raisonnement},
        "finish_reason": finish,
    }]}
    if status >= 400:
        r.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=r)
    return r


def _appel(*reponses, model="qwen/qwen3.5-9b"):
    """Exécute call_lmstudio_chat ; renvoie (résultat, liste des appels)."""
    with mock.patch.object(anonymize._SESSION, "post",
                           side_effect=list(reponses)) as post:
        res = call_lmstudio_chat(TEXTE, SYSTEM_PROMPT_PASS2, model=model)
    return res, post.call_args_list


class TestAppelLMStudio(unittest.TestCase):

    def test_reponse_normale(self):
        res, appels = _appel(_reponse(ANONYME))
        self.assertEqual(res, (ANONYME, True))
        self.assertTrue(appels[0].args[0].endswith("/v1/chat/completions"))
        payload = appels[0].kwargs["json"]
        self.assertIn("max_tokens", payload)
        self.assertNotIn("options", payload)  # format Ollama

    def test_reflexion_coupee_pour_qwen(self):
        """Mesuré : réflexion active = 3000 tokens de raisonnement en
        211 s et réponse vide. Le chunk restait en clair."""
        _, appels = _appel(_reponse(ANONYME))
        self.assertEqual(appels[0].kwargs["json"]["reasoning_effort"],
                         "none")

    def test_gpt_oss_garde_son_niveau_de_raisonnement(self):
        """gpt-oss ne connaît pas « none » ; son niveau est déjà fixé par
        « Reasoning: low » dans le prompt système."""
        _, appels = _appel(_reponse(ANONYME), model="openai/gpt-oss-20b")
        self.assertNotIn("reasoning_effort", appels[0].kwargs["json"])

    def test_parametre_refuse_on_retente_sans(self):
        res, appels = _appel(_reponse(status=400), _reponse(ANONYME))
        self.assertEqual(res, (ANONYME, True))
        self.assertEqual(len(appels), 2)
        self.assertNotIn("reasoning_effort", appels[1].kwargs["json"])

    def test_reponse_tronquee_est_un_echec(self):
        """Coupée par max_tokens, la réponse perd la fin du chunk. Au-delà
        de 60 % de la taille, le garde-fou d'intégrité la laissait
        passer : la fin du texte disparaissait du document."""
        res, _ = _appel(_reponse(ANONYME[:-10], finish="length"))
        self.assertEqual(res, (TEXTE, False))

    def test_reponse_vide_est_un_echec(self):
        """Cas réel : tout le budget passé à réfléchir, contenu vide."""
        res, _ = _appel(_reponse("", raisonnement="Thinking Process: ..."))
        self.assertEqual(res, (TEXTE, False))

    def test_reflexion_dans_le_contenu_retiree(self):
        res, _ = _appel(_reponse(f"<think>Nexans est une\nsociete</think>\n{ANONYME}"))
        self.assertEqual(res, (ANONYME, True))

    def test_bloc_de_code_retire(self):
        res, _ = _appel(_reponse(f"```\n{ANONYME}\n```"))
        self.assertEqual(res, (ANONYME, True))

    def test_serveur_absent(self):
        res, _ = _appel(requests.exceptions.ConnectionError())
        self.assertEqual(res, (TEXTE, False))

    def test_timeout(self):
        res, _ = _appel(requests.exceptions.Timeout())
        self.assertEqual(res, (TEXTE, False))


class TestAiguillage(unittest.TestCase):

    def test_call_llm_chat_choisit_le_moteur(self):
        with mock.patch.object(anonymize, "call_lmstudio_chat",
                               return_value=("L", True)) as lm, \
             mock.patch.object(anonymize, "call_ollama_chat",
                               return_value=("O", True)) as ol:
            self.assertEqual(call_llm_chat("t", "p", "m", "u",
                                           backend="lmstudio"), ("L", True))
            self.assertEqual(call_llm_chat("t", "p", "m", "u",
                                           backend="ollama"), ("O", True))
        lm.assert_called_once()
        ol.assert_called_once()

    def test_pipeline_lmstudio_passe_par_lmstudio(self):
        """Avec backend="lmstudio", aucun appel ne doit partir vers Ollama,
        et l'URL par défaut est celle de LM Studio."""
        with mock.patch.object(anonymize, "check_lmstudio",
                               return_value=(True, "ok", ["qwen"])) as chk, \
             mock.patch.object(anonymize, "call_lmstudio_chat",
                               side_effect=lambda t, p, **k: (
                                   t.replace("Nexans", "[ENTREPRISE_1]"),
                                   True)) as lm, \
             mock.patch.object(anonymize, "call_ollama_chat") as ol, \
             mock.patch.object(anonymize, "check_ollama") as chk_ol:
            r = run_pipeline(text=TEXTE, filename="t", use_llm=True,
                             backend="lmstudio", model="qwen/qwen3.5-9b",
                             passes=1, verbose=False)
        ol.assert_not_called()
        chk_ol.assert_not_called()
        self.assertEqual(chk.call_args.args[0], "http://localhost:1234")
        self.assertEqual(lm.call_args.kwargs["base_url"],
                         "http://localhost:1234")
        self.assertIn("[ENTREPRISE_1]", r["text"])
        self.assertIn("LM Studio", r["report"])

    def test_pipeline_lmstudio_absent_retombe_sur_regex(self):
        with mock.patch.object(anonymize, "check_lmstudio",
                               return_value=(False, "absent", [])), \
             mock.patch.object(anonymize, "call_lmstudio_chat") as lm:
            r = run_pipeline(text=TEXTE + " admin@acme.fr", filename="t",
                             use_llm=True, backend="lmstudio",
                             verbose=False)
        lm.assert_not_called()
        self.assertIn("[EMAIL_1]", r["text"])


def _get(v0=None, v1=None):
    """Simule requests.get : /api/v0/models puis /v1/models."""
    def reponse(corps):
        r = mock.Mock()
        if corps is None:
            r.raise_for_status.side_effect = requests.exceptions.HTTPError()
        else:
            r.json.return_value = {"data": corps}
        return r

    def get(url, **_):
        return reponse(v0 if "/api/v0/" in url else v1)
    return get


class TestVerificationLMStudio(unittest.TestCase):

    def test_modeles_embedding_ecartes(self):
        """LM Studio liste aussi ses modèles d'embedding, incapables de
        répondre à un chat : ils n'ont rien à faire dans le sélecteur."""
        v0 = [
            {"id": "qwen/qwen3.5-9b", "type": "vlm"},
            {"id": "mistral-7b", "type": "llm"},
            {"id": "text-embedding-nomic-embed-text-v1.5",
             "type": "embeddings"},
        ]
        with mock.patch.object(anonymize.requests, "get", _get(v0=v0)):
            ok, msg, modeles = check_lmstudio(model="qwen/qwen3.5-9b")
        self.assertTrue(ok)
        self.assertEqual(modeles, ["qwen/qwen3.5-9b", "mistral-7b"])
        self.assertIn("prêt", msg)

    def test_repli_sur_api_openai(self):
        v1 = [{"id": "qwen/qwen3.5-9b"},
              {"id": "nomic-ai/nomic-embed-text-v1.5-GGUF"}]
        with mock.patch.object(anonymize.requests, "get",
                               _get(v0=None, v1=v1)):
            ok, _, modeles = check_lmstudio()
        self.assertTrue(ok)
        self.assertEqual(modeles, ["qwen/qwen3.5-9b"])

    def test_serveur_absent(self):
        with mock.patch.object(
                anonymize.requests, "get",
                side_effect=requests.exceptions.ConnectionError()):
            ok, msg, modeles = check_lmstudio()
        self.assertFalse(ok)
        self.assertEqual(modeles, [])
        self.assertIn("lms server start", msg)

    def test_modele_absent_signale(self):
        with mock.patch.object(anonymize.requests, "get",
                               _get(v0=[{"id": "autre", "type": "llm"}])):
            ok, msg, _ = check_lmstudio(model="qwen/qwen3.5-9b")
        self.assertTrue(ok)
        self.assertIn("NON trouvé", msg)


if __name__ == "__main__":
    unittest.main()
