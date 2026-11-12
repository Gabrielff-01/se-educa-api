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

    def test_matriz_da_escola_vale_no_lugar_da_rede(self):
        from rede.models import Turma
        from rh.models import matriz_da_turma
        murilo = Escola.objects.get(codigo_inep="28034567")
        atheneu = Escola.objects.get(codigo_inep="28012345")
        primeira = Serie.objects.get(curso__nome="Ensino Médio", ordem=1)
        turma_murilo = Turma.objects.filter(escola=murilo, serie=primeira).first()
        turma_atheneu = Turma.objects.filter(escola=atheneu, serie=primeira).first()
        self.assertEqual(matriz_da_turma(turma_murilo).escola, murilo)  # a própria (demo: 6 de Matemática)
        self.assertIsNone(matriz_da_turma(turma_atheneu).escola)  # a da rede

    def test_matriz_de_escola_que_nao_oferece_a_serie(self):
        murilo = Escola.objects.get(codigo_inep="28034567")  # só oferece Ensino Médio
        resposta = self.client.post("/api/matrizes/", {**self.dados(4), "escola": murilo.pk}, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("não oferece", str(resposta.data["escola"]))

    def test_uma_matriz_por_escola(self):
        murilo = Escola.objects.get(codigo_inep="28034567")
        primeira = Serie.objects.get(curso__nome="Ensino Médio", ordem=1)
        dados = {**self.dados(4), "serie": primeira.pk, "escola": murilo.pk}
        resposta = self.client.post("/api/matrizes/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("Essa escola já tem uma matriz", str(resposta.data))

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

    def test_nao_oferece_serie_sem_ato_do_curso(self):
        # O Atheneu só tem ato de Ensino Médio: não pode ganhar 6º ano (caso que o mentor achou).
        sexto = Serie.objects.get(curso__nome="Ensino Fundamental - Anos Finais", ordem=2)
        series = list(self.oferta.series.values_list("pk", flat=True)) + [sexto.pk]
        resposta = self.client.patch(f"/api/ofertas/{self.oferta.pk}/", {"series": series}, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("não tem ato autorizando Ensino Fundamental", str(resposta.data))

    def test_ato_vencido_aparece(self):
        resposta = self.client.get("/api/atos/")
        vencidos = [ato for ato in resposta.data if not ato["vigente"]]
        self.assertEqual(len(vencidos), 1)

    def test_ato_de_curso_sem_curso(self):
        dados = {"escola": self.oferta.escola_id, "tipo": "reconhecimento",
                 "numero": "Res. 1/2026", "data_publicacao": "2026-01-10"}
        # Os atos autorizativos passaram do DED para o DIES (pedido do mentor).
        self.assertEqual(self.client.post("/api/atos/", dados, format="json").status_code, 403)
        self.client.force_authenticate(Usuario.objects.get(username="dies1"))
        resposta = self.client.post("/api/atos/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("curso", resposta.data)
