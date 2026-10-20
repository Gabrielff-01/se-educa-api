from io import StringIO

from django.core.management import call_command
from rest_framework.test import APITestCase

from contas.models import Usuario
from rede.models import Escola, Materia, Serie

from .models import Matriz, Oferta


class MatrizAPITest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())

    def setUp(self):
        self.client.force_authenticate(Usuario.objects.get(username="ded1"))
        self.serie = Serie.objects.get(curso__nome="Ensino Fundamental - Anos Finais", ordem=2)
        self.materias = list(Materia.objects.order_by("nome")[:8])

    def dados(self, aulas_cada):
        return {
            "serie": self.serie.pk, "ano_letivo": 2026, "jornada": "parcial",
            "itens": [{"materia": m.pk, "aulas_semanais": aulas_cada} for m in self.materias],
        }

    def test_matriz_abaixo_do_minimo(self):
        resposta = self.client.post("/api/matrizes/", self.dados(2), format="json")  # 16 aulas
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("exige no mínimo 800 horas", str(resposta.data))

    def test_matriz_que_cumpre(self):
        dados = self.dados(3)  # 24 aulas x 50 min x 40 semanas = 800 h
        resposta = self.client.post("/api/matrizes/", dados, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(resposta.data["carga_horaria_anual"], 800)
        self.assertTrue(resposta.data["cumpre_minimo"])
        self.assertEqual(len(resposta.data["itens"]), 8)

    def test_materia_repetida(self):
        dados = self.dados(3)
        dados["itens"].append(dados["itens"][0])
        resposta = self.client.post("/api/matrizes/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("aparece duas vezes", str(resposta.data))

    def test_nao_tira_aula_de_materia_lotada(self):
        matriz = Matriz.objects.get(serie__curso__nome="Ensino Médio", serie__ordem=2)
        itens = [{"materia": i.materia_id, "aulas_semanais": i.aulas_semanais}
                 for i in matriz.itens.all()]
        matematica = Materia.objects.get(nome="Matemática").pk
        arte = Materia.objects.get(nome="Arte").pk
        for item in itens:
            if item["materia"] == matematica:
                item["aulas_semanais"] -= 3  # Carlos já está lotado com 5
            if item["materia"] == arte:
                item["aulas_semanais"] += 3  # mantém as horas pra só a lotação falhar
        resposta = self.client.patch(f"/api/matrizes/{matriz.pk}/", {"itens": itens}, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("lotadas com professores", str(resposta.data))

    def test_nao_muda_serie_depois_de_criada(self):
        matriz = Matriz.objects.get(serie__curso__nome="Ensino Médio", serie__ordem=3)
        resposta = self.client.patch(
            f"/api/matrizes/{matriz.pk}/", {"serie": self.serie.pk}, format="json"
        )
        self.assertEqual(resposta.status_code, 400)

    def test_dies_nao_cria_matriz(self):
        self.client.force_authenticate(Usuario.objects.get(username="dies1"))
        resposta = self.client.post("/api/matrizes/", self.dados(3), format="json")
        self.assertEqual(resposta.status_code, 403)


class OfertaAPITest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())

    def setUp(self):
        self.client.force_authenticate(Usuario.objects.get(username="ded1"))
        self.oferta = Oferta.objects.get(escola__codigo_inep="28012345", ano_letivo=2026)
        self.terceira = Serie.objects.get(curso__nome="Ensino Médio", ordem=3)

    def test_nao_desmarca_serie_com_turma(self):
        resposta = self.client.patch(
            f"/api/ofertas/{self.oferta.pk}/", {"series": [self.terceira.pk]}, format="json"
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("ficariam sem a série", str(resposta.data))

    def test_nao_muda_escola(self):
        outra = Escola.objects.get(codigo_inep="28034567")
        resposta = self.client.patch(
            f"/api/ofertas/{self.oferta.pk}/", {"escola": outra.pk}, format="json"
        )
        self.assertEqual(resposta.status_code, 400)

    def test_nao_apaga_oferta_com_turmas(self):
        resposta = self.client.delete(f"/api/ofertas/{self.oferta.pk}/")
        self.assertEqual(resposta.status_code, 400)

    def test_ato_vencido_aparece(self):
        resposta = self.client.get("/api/atos/")
        vencidos = [ato for ato in resposta.data if not ato["vigente"]]
        self.assertEqual(len(vencidos), 1)

    def test_ato_de_curso_sem_curso(self):
        dados = {"escola": self.oferta.escola_id, "tipo": "reconhecimento",
                 "numero": "Res. 1/2026", "data_publicacao": "2026-01-10"}
        resposta = self.client.post("/api/atos/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("curso", resposta.data)
