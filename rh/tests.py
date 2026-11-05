from io import StringIO

from django.core.management import call_command
from rest_framework.test import APITestCase

from contas.models import Usuario
from rede.models import Escola, Materia, Turma

from .models import Alocacao, Professor


class ProfessorAPITest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())

    def setUp(self):
        self.client.force_authenticate(Usuario.objects.get(username="rh1"))

    def test_cadastra_com_cpf_formatado(self):
        dados = {"nome": "Teste da Silva", "matricula": "200001-5", "cpf": "529.982.247-25",
                 "carga_horaria_semanal": 20, "vinculo": "temporario", "data_admissao": "2026-02-02"}
        resposta = self.client.post("/api/professores/", dados, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(resposta.data["cpf_formatado"], "529.982.247-25")
        self.assertEqual(resposta.data["limite_aulas"], 13)
        self.assertEqual(Professor.objects.get(matricula="200001-5").cpf, "52998224725")

    def test_cpf_invalido(self):
        dados = {"nome": "Teste", "matricula": "200002", "cpf": "111.111.111-11", "data_admissao": "2026-02-02"}
        resposta = self.client.post("/api/professores/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("cpf", resposta.data)

    def test_cpf_repetido_com_pontos(self):
        existente = Professor.objects.first()
        dados = {"nome": "Teste", "matricula": "200003", "cpf": existente.cpf_formatado, "data_admissao": "2026-02-02"}
        resposta = self.client.post("/api/professores/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("Já existe um professor com esse CPF.", str(resposta.data))

    def test_data_de_admissao_obrigatoria(self):
        dados = {"nome": "Sem Data", "matricula": "200004", "cpf": "529.982.247-25"}
        resposta = self.client.post("/api/professores/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(resposta.data["data_admissao"][0], "Informe a data de admissão.")
        resposta = self.client.post("/api/professores/", {**dados, "data_admissao": "2099-01-01"}, format="json")
        self.assertIn("futuro", str(resposta.data["data_admissao"]))

    def test_nao_reduz_carga_com_alocacao(self):
        carlos = Professor.objects.get(matricula="100001-1")  # 40 h no Atheneu
        resposta = self.client.patch(
            f"/api/professores/{carlos.pk}/", {"carga_horaria_semanal": 20}, format="json"
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("alocado em escolas somando 40 horas", resposta.data["carga_horaria_semanal"][0])


class Base(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())
        cls.atheneu = Escola.objects.get(codigo_inep="28012345")
        cls.murilo = Escola.objects.get(codigo_inep="28034567")

    def entrar(self, username):
        self.client.force_authenticate(Usuario.objects.get(username=username))

    def professor(self, matricula):
        return Professor.objects.get(matricula=matricula)

    def turma(self, escola, curso_ordem, serie_ordem, letra="A"):
        return Turma.objects.get(escola=escola, serie__curso__ordem=curso_ordem, serie__ordem=serie_ordem, letra=letra)

    def lotar(self, professor, turma, materia, aulas):
        dados = {"professor": professor.pk, "turma": turma.pk,
                 "materia": Materia.objects.get(nome=materia).pk, "aulas_semanais": aulas}
        return self.client.post("/api/lotacoes/", dados, format="json")


class AlocacaoTest(Base):
    """O RH só diz em qual escola o professor trabalha (e quantas horas lá)."""

    def test_rh_aloca_e_a_escola_nao(self):
        paulo = self.professor("100005-5")  # 40 h, ainda sem escola
        dados = {"professor": paulo.pk, "escola": self.murilo.pk, "horas_semanais": 40, "portaria": "0901/2026"}
        self.entrar("escola3")
        self.assertEqual(self.client.post("/api/alocacoes/", dados, format="json").status_code, 403)
        self.entrar("rh1")
        resposta = self.client.post("/api/alocacoes/", dados, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(resposta.data["funcao"], "professor")  # começa como professor; a escola muda
        self.assertEqual(resposta.data["limite_aulas"], 26)

    def test_soma_das_escolas_nao_passa_da_carga(self):
        mariana = self.professor("100004-4")  # 40 h: 20 no Atheneu + 20 no Gonçalo
        self.entrar("rh1")
        resposta = self.client.post("/api/alocacoes/", {
            "professor": mariana.pk, "escola": self.murilo.pk, "horas_semanais": 20}, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("Sobram 0 horas", resposta.data["horas_semanais"][0])

    def test_nao_tira_da_escola_com_turmas(self):
        carlos = Alocacao.objects.get(professor__matricula="100001-1", escola=self.atheneu)
        self.entrar("rh1")
        resposta = self.client.delete(f"/api/alocacoes/{carlos.pk}/")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("A escola precisa tirar as aulas dele antes", resposta.data["detail"])

    def test_escola_define_a_funcao(self):
        ana = Alocacao.objects.get(professor__matricula="100006-6")  # diretora do Atheneu
        url = f"/api/alocacoes/{ana.pk}/funcao/"
        self.entrar("escola2")  # outra escola nem enxerga
        self.assertEqual(self.client.post(url, {"funcao": "coordenador"}, format="json").status_code, 404)
        self.entrar("rh1")  # o RH aloca, mas a função é da escola
        self.assertEqual(self.client.post(url, {"funcao": "coordenador"}, format="json").status_code, 403)
        self.entrar("escola1")
        resposta = self.client.post(url, {"funcao": "coordenador", "portaria_funcao": "1000/2026"}, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(resposta.data["funcao_nome"], "Coordenador(a)")

    def test_quem_tem_turma_nao_vira_diretor(self):
        carlos = Alocacao.objects.get(professor__matricula="100001-1", escola=self.atheneu)
        self.entrar("escola1")
        resposta = self.client.post(f"/api/alocacoes/{carlos.pk}/funcao/", {"funcao": "diretor"}, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("Tire as turmas dele", resposta.data["funcao"])


class LotacaoTest(Base):
    """A escola escolhe turma, matéria e aulas, só com quem o RH alocou nela."""

    def test_rh_nao_lota_mais(self):
        self.entrar("rh1")
        resposta = self.lotar(self.professor("100001-1"), self.turma(self.atheneu, 3, 1, "B"), "Física", 2)
        self.assertEqual(resposta.status_code, 403)

    def test_escola_lota_quem_o_rh_alocou(self):
        paulo = self.professor("100005-5")
        turma = self.turma(self.murilo, 3, 1)
        self.entrar("escola3")
        resposta = self.lotar(paulo, turma, "Arte", 2)  # Paulo é licenciado em Artes Visuais
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("Peça ao RH para alocar", resposta.data["professor"][0])
        Alocacao.objects.create(professor=paulo, escola=self.murilo, horas_semanais=40)
        resposta = self.lotar(paulo, turma, "Arte", 2)
        self.assertEqual(resposta.status_code, 201, resposta.data)

    def test_escola_nao_lota_em_turma_de_outra_escola(self):
        Alocacao.objects.create(professor=self.professor("100005-5"), escola=self.murilo, horas_semanais=40)
        self.entrar("escola1")
        resposta = self.lotar(self.professor("100005-5"), self.turma(self.murilo, 3, 1), "Arte", 2)
        self.assertEqual(resposta.status_code, 403)

    def test_diretor_nao_recebe_turma(self):
        self.entrar("escola1")
        resposta = self.lotar(self.professor("100006-6"), self.turma(self.atheneu, 3, 3), "Física", 2)
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("está como Diretor(a)", resposta.data["professor"][0])

    def test_lotacao_passa_dos_dois_tercos(self):
        jose = self.professor("100003-3")  # 20 h no Atheneu: limite 13 aulas (já tem 6)
        self.entrar("escola1")
        for serie, letra, materia in [(3, "A", "Física"), (3, "A", "Química"), (2, "A", "Química"), (1, "B", "Física")]:
            resposta = self.lotar(jose, self.turma(self.atheneu, 3, serie, letra), materia, 2)
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("2/3 da carga", resposta.data["aulas_semanais"][0])
        self.assertIn("Com 20 horas aqui, o limite é 13", resposta.data["aulas_semanais"][0])

    def test_lotacao_alem_da_matriz(self):
        self.entrar("escola1")
        resposta = self.lotar(self.professor("100003-3"), self.turma(self.atheneu, 3, 1, "B"), "Física", 3)
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("Disponíveis: 2", resposta.data["aulas_semanais"][0])

    def test_so_lota_na_materia_que_a_formacao_habilita(self):
        self.entrar("escola1")
        carlos = self.professor("100001-1")  # Licenciatura em Matemática
        resposta = self.lotar(carlos, self.turma(self.atheneu, 3, 1, "B"), "Física", 2)
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("não tem formação que o habilite a lecionar Física", resposta.data["materia"][0])


class FormacaoTest(Base):
    """O RH cadastra a formação e as matérias que ela habilita."""

    def test_pos_graduacao_nao_habilita(self):
        self.entrar("rh1")
        dados = {"professor": self.professor("100005-5").pk, "nivel": "pos", "curso": "Mestrado em Educação",
                 "materias": [Materia.objects.get(nome="Física").pk]}
        resposta = self.client.post("/api/formacoes/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("LDB", resposta.data["materias"][0])
        resposta = self.client.post("/api/formacoes/", {**dados, "materias": []}, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)

    def test_licenciatura_habilita_e_aparece_no_professor(self):
        self.entrar("rh1")
        paulo = self.professor("100005-5")
        dados = {"professor": paulo.pk, "nivel": "licenciatura", "curso": "Licenciatura em Física",
                 "instituicao": "UFS", "ano_conclusao": 2020, "materias": [Materia.objects.get(nome="Física").pk]}
        self.assertEqual(self.client.post("/api/formacoes/", dados, format="json").status_code, 201)
        professor = self.client.get(f"/api/professores/{paulo.pk}/").data
        self.assertEqual(professor["habilitado_em"], ["Arte", "Física"])

    def test_nao_tira_habilitacao_de_materia_que_ele_da(self):
        self.entrar("rh1")
        formacao = self.professor("100001-1").formacoes.get()  # Carlos dá Matemática no Atheneu
        resposta = self.client.delete(f"/api/formacoes/{formacao.pk}/")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("Peça à escola para tirar essa turma", str(resposta.data))

    def test_escola_nao_mexe_na_formacao(self):
        self.entrar("escola1")
        dados = {"professor": self.professor("100001-1").pk, "nivel": "licenciatura", "curso": "X",
                 "materias": [Materia.objects.get(nome="Física").pk]}
        self.assertEqual(self.client.post("/api/formacoes/", dados, format="json").status_code, 403)
