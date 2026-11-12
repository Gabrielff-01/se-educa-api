from io import StringIO

from django.core.management import call_command
from rest_framework.test import APITestCase

from academico.models import Matricula
from contas.models import Usuario

from .models import AlunoNaRota, Rota


class RotaTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())

    def entrar(self, username):
        self.client.force_authenticate(Usuario.objects.get(username=username))

    def dados(self, **extra):
        return {"nome": "Rota Teste", "turno": "matutino", "veiculo": "van", "placa": "abc1d23", "motorista": "Fulano",
                "capacidade": 2, "paradas": [{"local": "Praça", "referencia": "", "horario": "06:00"},
                                             {"local": "Escola", "referencia": "", "horario": "06:30"}], **extra}

    def test_escola_cadastra_e_edita(self):
        self.entrar("escola1")
        resposta = self.client.post("/api/rotas/", self.dados(), format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(resposta.data["placa"], "ABC1D23")
        self.assertEqual([p["ordem"] for p in resposta.data["paradas"]], [1, 2])
        self.assertTrue(resposta.data["cadastrada_por_nome"])
        # Edita: mantém a 1ª parada (com id), troca a 2ª
        primeira = resposta.data["paradas"][0]
        novas = [primeira, {"local": "Mercado", "referencia": "", "horario": "06:15"}, {"local": "Escola", "referencia": "", "horario": "06:40"}]
        editada = self.client.patch(f"/api/rotas/{resposta.data['id']}/", {"paradas": novas}, format="json")
        self.assertEqual(editada.status_code, 200, editada.data)
        self.assertEqual([p["local"] for p in editada.data["paradas"]], ["Praça", "Mercado", "Escola"])
        self.assertEqual(editada.data["paradas"][0]["id"], primeira["id"])

    def test_regras(self):
        self.entrar("escola1")
        fora_de_ordem = self.dados(paradas=[{"local": "A", "referencia": "", "horario": "07:00"}, {"local": "B", "referencia": "", "horario": "06:00"}])
        self.assertEqual(self.client.post("/api/rotas/", fora_de_ordem, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/rotas/", self.dados(placa="12345"), format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/rotas/", self.dados(paradas=[]), format="json").status_code, 400)
        for usuario in ("aluno1", "dies1", "professor1"):
            self.entrar(usuario)
            self.assertEqual(self.client.post("/api/rotas/", self.dados(), format="json").status_code, 403, usuario)

    def test_vincular_aluno_turno_e_lotacao(self):
        self.entrar("escola1")
        escola = Usuario.objects.get(username="escola1").escola_id
        rota = self.client.post("/api/rotas/", self.dados(), format="json").data
        parada = rota["paradas"][0]["id"]
        do_turno = Matricula.objects.filter(escola_id=escola, situacao="confirmada", turma__turno="matutino",
                                            aluno__transporte__isnull=True)
        outro_turno = Matricula.objects.filter(escola_id=escola, situacao="confirmada", turma__isnull=False).exclude(turma__turno="matutino").first()
        base = f"/api/rotas/{rota['id']}"
        for matricula in do_turno[:2]:
            resposta = self.client.post(f"{base}/vincular/", {"aluno": matricula.aluno_id, "parada": parada}, format="json")
            self.assertEqual(resposta.status_code, 200, resposta.data)
        cheia = self.client.post(f"{base}/vincular/", {"aluno": do_turno[2].aluno_id, "parada": parada}, format="json")
        self.assertIn("cheia", str(cheia.data))
        if outro_turno:
            resposta = self.client.post(f"{base}/vincular/", {"aluno": outro_turno.aluno_id, "parada": parada}, format="json")
            self.assertIn("turno", str(resposta.data))
        # Turnos de verdade: rota da tarde não leva aluno da manhã
        tarde = self.client.post("/api/rotas/", self.dados(nome="Rota da Tarde", turno="vespertino"), format="json").data
        resposta = self.client.post(f"/api/rotas/{tarde['id']}/vincular/",
                                    {"aluno": do_turno[2].aluno_id, "parada": tarde["paradas"][0]["id"]}, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("turno matutino", str(resposta.data))
        # Parada com aluno não pode sumir da rota
        resposta = self.client.patch(f"{base}/", {"paradas": [rota["paradas"][1]]}, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("embarcando", str(resposta.data))

    def test_aluno_ve_a_propria_rota(self):
        self.entrar("aluno1")
        minha = self.client.get("/api/rotas/minha/").data
        self.assertEqual(minha["rota"]["nome"], "Rota 1 · Santa Maria")
        self.assertEqual(minha["rota"]["alunos"], [])  # aluno não vê os colegas
        self.assertTrue(minha["parada"])
        # A escola3 não vê as rotas da escola1
        self.entrar("escola3")
        nomes = [r["nome"] for r in self.client.get("/api/rotas/").data]
        self.assertNotIn("Rota 1 · Santa Maria", nomes)
        self.assertEqual(Rota.objects.filter(escola__usuarios__username="escola3").count(), 2)
        self.assertTrue(AlunoNaRota.objects.filter(rota__nome="Rota Povoado Carrilho").exists())
