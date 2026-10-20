from io import StringIO

from django.core.management import call_command
from rest_framework.test import APITestCase

from contas.models import Usuario
from rede.models import Materia, Turma

from .models import Professor


class ProfessorAPITest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())

    def setUp(self):
        self.client.force_authenticate(Usuario.objects.get(username="rh1"))

    def test_cadastra_com_cpf_formatado(self):
        dados = {"nome": "Teste da Silva", "matricula": "200001-5", "cpf": "529.982.247-25",
                 "carga_horaria_semanal": 20, "vinculo": "temporario"}
        resposta = self.client.post("/api/professores/", dados, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(resposta.data["cpf_formatado"], "529.982.247-25")
        self.assertEqual(resposta.data["limite_aulas"], 13)
        self.assertEqual(Professor.objects.get(matricula="200001-5").cpf, "52998224725")

    def test_cpf_invalido(self):
        dados = {"nome": "Teste", "matricula": "200002", "cpf": "111.111.111-11"}
        resposta = self.client.post("/api/professores/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("cpf", resposta.data)

    def test_cpf_repetido_com_pontos(self):
        existente = Professor.objects.first()
        dados = {"nome": "Teste", "matricula": "200003", "cpf": existente.cpf_formatado}
        resposta = self.client.post("/api/professores/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("Já existe um professor com esse CPF.", str(resposta.data))

    def test_lotacao_passa_dos_dois_tercos(self):
        jose = Professor.objects.get(matricula="100003-3")  # 20 h: limite 13 aulas
        turma = Turma.objects.get(escola__codigo_inep="28034567", serie__ordem=1)
        for nome in ("Português", "Matemática"):  # 5 + 5 aulas
            materia = Materia.objects.get(nome=nome)
            dados = {"professor": jose.pk, "turma": turma.pk, "materia": materia.pk,
                     "aulas_semanais": 5}
            resposta = self.client.post("/api/lotacoes/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("2/3 da carga", resposta.data["aulas_semanais"][0])

    def test_lotacao_alem_da_matriz(self):
        carlos = Professor.objects.get(matricula="100001-1")
        turma = Turma.objects.get(escola__codigo_inep="28034567", serie__ordem=1)
        materia = Materia.objects.get(nome="Física")  # 2 aulas na matriz
        dados = {"professor": carlos.pk, "turma": turma.pk, "materia": materia.pk,
                 "aulas_semanais": 3}
        resposta = self.client.post("/api/lotacoes/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("Disponíveis: 2", resposta.data["aulas_semanais"][0])

    def test_nao_reduz_carga_com_aulas_demais(self):
        carlos = Professor.objects.get(matricula="100001-1")  # 20+ aulas lotadas
        resposta = self.client.patch(
            f"/api/professores/{carlos.pk}/", {"carga_horaria_semanal": 20}, format="json"
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("Remova lotações", resposta.data["carga_horaria_semanal"][0])
