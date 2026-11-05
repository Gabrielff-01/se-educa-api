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


class FichaDaEscolaTest(APITestCase):
    """Dados cadastrais e a ficha da escola (no modelo do site da SEDUC)."""

    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())
        cls.atheneu = Escola.objects.get(codigo_inep="28012345")

    def entrar(self, username):
        self.client.force_authenticate(Usuario.objects.get(username=username))

    def test_cnpj_e_cep_guardam_so_os_numeros(self):
        self.entrar("dies1")
        url = f"/api/escolas/{self.atheneu.pk}/"
        resposta = self.client.patch(url, {"cnpj": "05.486.302/0001-36"}, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("dígitos verificadores", str(resposta.data["cnpj"]))
        resposta = self.client.patch(url, {"cnpj": "05.486.302/0001-35", "cep": "49044-156", "zona": "rural"},
                                     format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(resposta.data["cnpj"], "05486302000135")
        self.assertEqual(resposta.data["cnpj_formatado"], "05.486.302/0001-35")
        self.assertEqual(resposta.data["cep_formatado"], "49044-156")
        self.assertEqual(resposta.data["zona_nome"], "Rural")

    def test_ficha_mostra_turmas_equipe_e_resolucoes(self):
        self.entrar("dies1")
        ficha = self.client.get(f"/api/escolas/{self.atheneu.pk}/ficha/").data
        self.assertEqual(ficha["escola"]["nome"], self.atheneu.nome)
        self.assertEqual(ficha["resumo"]["turmas"], len(ficha["turmas"]))
        self.assertTrue(all({"serie_nome", "letra", "turno_nome"} <= set(t) for t in ficha["turmas"]))
        self.assertEqual(ficha["equipe_diretiva"][0]["funcao_nome"], "Diretor(a)")  # diretor vem primeiro
        self.assertEqual(ficha["equipe_diretiva"][0]["nome"], "Ana Cristina Rocha")
        self.assertTrue(ficha["resolucoes"])

    def test_ficha_so_da_propria_escola(self):
        self.entrar("escola2")
        self.assertEqual(self.client.get(f"/api/escolas/{self.atheneu.pk}/ficha/").status_code, 403)
        self.entrar("escola1")
        self.assertEqual(self.client.get(f"/api/escolas/{self.atheneu.pk}/ficha/").status_code, 200)

    def test_ficha_sem_vagas_e_com_formacao(self):
        self.entrar("dies1")
        ficha = self.client.get(f"/api/escolas/{self.atheneu.pk}/ficha/").data
        self.assertNotIn("vagas", ficha["resumo"])  # mentor pediu pra tirar as vagas
        carlos = next(p for p in ficha["professores"] if p["nome"] == "Carlos Eduardo Menezes")
        self.assertEqual(carlos["formacoes"][0]["materias_nomes"], ["Matemática"])


class EscolasDaRedeTest(APITestCase):
    """Tela "Escolas da rede" (lista e mapa) com as escolas do banco."""

    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())

    def lista(self, username):
        self.client.force_authenticate(Usuario.objects.get(username=username))
        resposta = self.client.get("/api/escolas/rede/")
        self.assertEqual(resposta.status_code, 200)
        return {e["nome"]: e for e in resposta.data}

    def test_todo_mundo_ve_series_e_contato(self):
        atheneu = self.lista("aluno1")["Colégio Estadual Atheneu Sergipense"]
        self.assertNotIn("vagas", atheneu)
        self.assertIn("1ª série", [s["serie_nome"] for s in atheneu["series"]])
        self.assertIn("Ensino Médio", atheneu["cursos"])
        self.assertIsNotNone(atheneu["latitude"])
        self.assertNotIn("alunos", atheneu)  # quantos alunos e servidores só a gestão vê

    def test_gestao_ve_alunos_e_servidores(self):
        atheneu = self.lista("dies1")["Colégio Estadual Atheneu Sergipense"]
        self.assertGreater(atheneu["alunos"], 0)
        self.assertGreater(atheneu["servidores"], 0)

    def test_localizacao_fora_de_sergipe(self):
        self.client.force_authenticate(Usuario.objects.get(username="dies1"))
        atheneu = Escola.objects.get(codigo_inep="28012345")
        url = f"/api/escolas/{atheneu.pk}/"
        trocada = self.client.patch(url, {"latitude": -37.05, "longitude": -10.91}, format="json")  # invertida
        self.assertEqual(trocada.status_code, 400)
        self.assertIn("fora de Sergipe", str(trocada.data))
        certa = self.client.patch(url, {"latitude": -10.91, "longitude": -37.05}, format="json")
        self.assertEqual(certa.status_code, 200, certa.data)


class MunicipiosTest(APITestCase):
    """Os 75 municípios de Sergipe, cada um na sua DRE. A escola herda a regional do município."""

    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())

    def setUp(self):
        self.client.force_authenticate(Usuario.objects.get(username="dies1"))

    def test_lista_por_regional(self):
        from .models import Municipio, Regional
        self.assertEqual(Municipio.objects.count(), 75)
        self.assertEqual(Regional.objects.get(nome="DRE 03").sede, "Itabaiana")
        dre3 = Regional.objects.get(nome="DRE 03")
        nomes = [m["nome"] for m in self.client.get(f"/api/municipios/?regional={dre3.pk}").data]
        self.assertIn("Itabaiana", nomes)
        self.assertNotIn("Aracaju", nomes)

    def test_escola_herda_a_regional_do_municipio(self):
        atheneu = Escola.objects.get(codigo_inep="28012345")
        resposta = self.client.patch(f"/api/escolas/{atheneu.pk}/", {"municipio": "aquidabã"}, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(resposta.data["municipio"], "Aquidabã")
        self.assertEqual(resposta.data["regional_nome"], "DRE 05")
        resposta = self.client.patch(f"/api/escolas/{atheneu.pk}/", {"municipio": "Gotham"}, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("município de Sergipe", str(resposta.data["municipio"]))

    def test_municipio_muda_de_dre_e_as_escolas_vao_junto(self):
        from .models import Municipio, Regional
        itabaiana = Municipio.objects.get(nome="Itabaiana")
        dre5 = Regional.objects.get(nome="DRE 05")
        resposta = self.client.patch(f"/api/municipios/{itabaiana.pk}/", {"regional": dre5.pk}, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(Escola.objects.get(codigo_inep="28034567").regional, dre5)  # Murilo Braga
