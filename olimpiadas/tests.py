from io import StringIO

from django.core.management import call_command
from rest_framework.test import APITestCase

from academico.models import Matricula
from contas.models import Usuario

from .models import Olimpiada


class OlimpiadaTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())

    def entrar(self, username):
        self.client.force_authenticate(Usuario.objects.get(username=username))

    def nova(self, **extra):
        self.entrar("escola1")
        dados = {"nome": "Olimpíada de Física", "data_prova": "2026-12-01", "nota_maxima": "10", "premiados": 3, **extra}
        resposta = self.client.post("/api/olimpiadas/", dados, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        return resposta.data

    def test_fluxo_completo(self):
        olimpiada = self.nova()
        self.assertEqual(olimpiada["escola"], Usuario.objects.get(username="escola1").escola_id)
        self.assertEqual(olimpiada["ano_letivo"], 2026)
        base = f"/api/olimpiadas/{olimpiada['id']}"

        # O aluno se inscreve sozinho enquanto as inscrições estão abertas.
        self.entrar("aluno1")
        lista = self.client.get("/api/olimpiadas/").data
        self.assertTrue(next(o for o in lista if o["id"] == olimpiada["id"])["pode_participar"])
        self.assertEqual(self.client.post(f"{base}/inscrever/").status_code, 201)
        self.assertEqual(self.client.post(f"{base}/inscrever/").status_code, 400)  # não repete

        # A escola inscreve mais dois e fecha as inscrições.
        self.entrar("escola1")
        outros = Matricula.objects.filter(escola__usuarios__username="escola1", situacao="confirmada",
                                          ano_letivo=2026).exclude(aluno__usuario__username="aluno1")[:2]
        for matricula in outros:
            self.assertEqual(self.client.post(f"{base}/inscrever/", {"aluno": matricula.aluno_id}, format="json").status_code, 201)
        self.assertEqual(self.client.patch(f"{base}/", {"status": "andamento"}, format="json").status_code, 200)

        # Fechou: o aluno não sai mais sozinho.
        self.entrar("aluno1")
        self.assertEqual(self.client.post(f"{base}/sair/").status_code, 400)

        # Notas: acima da máxima é recusada; depois classificação com empate.
        self.entrar("escola1")
        linhas = self.client.get(f"{base}/classificacao/").data
        ids = [linha["id"] for linha in linhas]
        resposta = self.client.post(f"{base}/notas/", {"notas": [{"participacao": ids[0], "nota": "11"}]}, format="json")
        self.assertEqual(resposta.status_code, 400)
        notas = [{"participacao": ids[0], "nota": "9,5"}, {"participacao": ids[1], "nota": "9.5"}, {"participacao": ids[2], "nota": "7"}]
        resposta = self.client.post(f"{base}/notas/", {"notas": notas}, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual([linha["posicao"] for linha in resposta.data], [1, 1, 3])
        self.assertEqual([linha["medalha"] for linha in resposta.data], ["ouro", "ouro", "bronze"])

        # Antes do resultado o aluno não vê a classificação; depois vê.
        self.entrar("aluno1")
        self.assertEqual(self.client.get(f"{base}/classificacao/").data, [])
        self.entrar("escola1")
        self.assertEqual(self.client.patch(f"{base}/", {"status": "resultado"}, format="json").status_code, 200)
        self.entrar("aluno1")
        self.assertEqual(len(self.client.get(f"{base}/classificacao/").data), 3)
        minha = next(o for o in self.client.get("/api/olimpiadas/").data if o["id"] == olimpiada["id"])["minhas"][0]
        self.assertIsNotNone(minha["posicao"])

    def test_so_a_escola_cadastra(self):
        for usuario in ("aluno1", "professor1", "dies1"):
            self.entrar(usuario)
            resposta = self.client.post("/api/olimpiadas/", {"nome": "X", "data_prova": "2026-12-01"}, format="json")
            self.assertEqual(resposta.status_code, 403, usuario)

    def test_outra_escola_nao_mexe(self):
        olimpiada = self.nova()
        self.entrar("escola3")
        self.assertEqual(self.client.patch(f"/api/olimpiadas/{olimpiada['id']}/", {"nome": "Y"}, format="json").status_code, 404)

    def test_serie_que_nao_participa(self):
        from rede.models import Serie

        aluno1 = Usuario.objects.get(username="aluno1").aluno
        serie_dela = aluno1.matricula_atual().serie
        outra = Serie.objects.filter(curso=serie_dela.curso).exclude(pk=serie_dela.pk).first()
        olimpiada = self.nova(series=[outra.pk])
        self.entrar("aluno1")
        self.assertFalse(next(o for o in self.client.get("/api/olimpiadas/").data if o["id"] == olimpiada["id"])["pode_participar"])
        resposta = self.client.post(f"/api/olimpiadas/{olimpiada['id']}/inscrever/")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("não é para", str(resposta.data))

    def test_resultado_precisa_de_nota(self):
        olimpiada = self.nova()
        resposta = self.client.patch(f"/api/olimpiadas/{olimpiada['id']}/", {"status": "resultado"}, format="json")
        self.assertEqual(resposta.status_code, 400)

    def test_demo_e_aviso(self):
        matematica = Olimpiada.objects.get(nome="Olimpíada de Matemática do Atheneu")
        ana = Usuario.objects.get(username="aluno1").aluno
        posicao = next(p for p in matematica.classificacao() if p.aluno_id == ana.pk)
        self.assertEqual((posicao.posicao, posicao.medalha), (2, "prata"))
        self.entrar("aluno1")
        avisos = [n for n in self.client.get("/api/notificacoes/").data if n["tipo"] == "olimpiada"]
        self.assertTrue(any("2º lugar" in n["texto"] for n in avisos))
        # A escola1 é avisada das matrículas pela internet que chegaram para ela.
        self.entrar("escola1")
        self.assertTrue(any(n["tipo"] == "inscricao" for n in self.client.get("/api/notificacoes/").data))
