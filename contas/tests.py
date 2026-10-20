from io import StringIO

from django.core.management import call_command
from rest_framework.test import APITestCase

from .models import Usuario


class LoginTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())

    def test_login_devolve_tokens_e_perfil(self):
        resposta = self.client.post(
            "/api/auth/login/", {"username": "dies1", "password": "dies"}, format="json"
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("access", resposta.data)
        self.assertEqual(resposta.data["usuario"]["perfil"], "secretaria")
        self.assertEqual(resposta.data["usuario"]["setor"], "dies")

    def test_senha_errada(self):
        resposta = self.client.post(
            "/api/auth/login/", {"username": "dies1", "password": "errada"}, format="json"
        )
        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(resposta.data["detail"], "Usuário ou senha incorretos.")

    def test_token_funciona_no_eu(self):
        login = self.client.post(
            "/api/auth/login/", {"username": "escola1", "password": "escola"}, format="json"
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        resposta = self.client.get("/api/auth/eu/")
        self.assertEqual(resposta.data["username"], "escola1")
        self.assertEqual(resposta.data["escola_nome"], "Colégio Estadual Atheneu Sergipense")

    def test_sem_token_nao_entra(self):
        self.assertEqual(self.client.get("/api/escolas/").status_code, 401)


class PermissaoTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())

    def entrar_como(self, username):
        self.client.force_authenticate(Usuario.objects.get(username=username))

    def test_todos_leem_escolas(self):
        self.entrar_como("aluno1")
        self.assertEqual(self.client.get("/api/escolas/").status_code, 200)

    def test_rh_nao_cadastra_escola(self):
        self.entrar_como("rh1")
        resposta = self.client.post("/api/escolas/", {"nome": "X"}, format="json")
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(resposta.data["detail"], "Só o setor DIES pode fazer isso.")

    def test_aluno_nao_ve_professores(self):
        self.entrar_como("aluno1")
        self.assertEqual(self.client.get("/api/professores/").status_code, 403)

    def test_ded_ve_professores_mas_nao_edita(self):
        self.entrar_como("ded1")
        self.assertEqual(self.client.get("/api/professores/").status_code, 200)
        resposta = self.client.post("/api/professores/", {}, format="json")
        self.assertEqual(resposta.status_code, 403)

    def test_usuario_da_escola_precisa_de_escola(self):
        usuario = Usuario(username="x", perfil=Usuario.Perfil.ESCOLA)
        with self.assertRaises(Exception):
            usuario.full_clean()
