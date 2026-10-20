from io import StringIO

from django.core.management import call_command
from rest_framework.test import APITestCase

from contas.models import Usuario

from .models import Escola, Serie


class TurmaAPITest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())

    def setUp(self):
        self.client.force_authenticate(Usuario.objects.get(username="dies1"))
        self.atheneu = Escola.objects.get(codigo_inep="28012345")

    def test_cria_turma_com_letra_minuscula(self):
        serie = Serie.objects.get(curso__nome="Ensino Médio", ordem=2)
        dados = {"escola": self.atheneu.pk, "serie": serie.pk, "ano_letivo": 2026,
                 "turno": "vespertino", "letra": "c"}
        resposta = self.client.post("/api/turmas/", dados, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(resposta.data["letra"], "C")
        self.assertEqual(resposta.data["nome"], f"{serie.nome} C")

    def test_turma_de_serie_nao_ofertada(self):
        serie = Serie.objects.get(curso__nome="Ensino Fundamental - Anos Finais", ordem=1)
        dados = {"escola": self.atheneu.pk, "serie": serie.pk, "ano_letivo": 2026,
                 "turno": "matutino", "letra": "A"}
        resposta = self.client.post("/api/turmas/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("não oferece", resposta.data["serie"][0])

    def test_turma_repetida(self):
        serie = Serie.objects.get(curso__nome="Ensino Médio", ordem=1)
        dados = {"escola": self.atheneu.pk, "serie": serie.pk, "ano_letivo": 2026,
                 "turno": "matutino", "letra": "a"}
        resposta = self.client.post("/api/turmas/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("já tem essa turma", str(resposta.data))

    def test_nao_apaga_escola_com_turmas(self):
        resposta = self.client.delete(f"/api/escolas/{self.atheneu.pk}/")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("Não dá pra apagar", resposta.data["detail"])

    def test_inep_invalido(self):
        dados = {"nome": "Escola Teste", "codigo_inep": "12345678", "regional": 1,
                 "municipio": "Aracaju"}
        resposta = self.client.post("/api/escolas/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("começa com 28", resposta.data["codigo_inep"][0])

    def test_filtro_por_escola(self):
        resposta = self.client.get(f"/api/turmas/?escola={self.atheneu.pk}&ano_letivo=2026")
        self.assertTrue(resposta.data)
        self.assertTrue(all(t["escola"] == self.atheneu.pk for t in resposta.data))
