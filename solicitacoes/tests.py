from io import StringIO

from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APITestCase

from academico.models import Aluno, Responsavel
from auditoria.models import Registro
from contas.models import Usuario
from rede.models import Turma

from .models import Solicitacao


class Base(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())
        cls.escola1 = Usuario.objects.get(username="escola1")
        cls.ano = timezone.localdate().year

    def entrar(self, username):
        self.client.force_authenticate(Usuario.objects.get(username=username))


class PedidosTest(Base):
    def test_escola_abre_pedido_de_turma_e_dies_atende(self):
        self.entrar("escola1")
        serie = Turma.objects.filter(escola=self.escola1.escola).first().serie
        r = self.client.post("/api/solicitacoes/", {
            "tipo": "nova_turma", "serie": serie.pk, "turno": "noturno", "capacidade": 30,
            "mensagem": "Precisamos de uma turma à noite."}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        pedido = r.data["id"]
        self.assertEqual(r.data["mensagens"][0]["lado"], "escola")

        # A escola não pode atender o próprio pedido
        self.assertEqual(self.client.post(f"/api/solicitacoes/{pedido}/atender/").status_code, 403)

        self.entrar("dies1")
        r = self.client.post(f"/api/solicitacoes/{pedido}/mensagens/", {"texto": "Vamos ver a sala."}, format="json")
        self.assertEqual(r.data["ultima_fala"], "dies")
        avisos = [n for n in self.client.get("/api/notificacoes/").data if n["tipo"] == "pedido"]
        self.assertIn("Precisamos de uma turma à noite.", avisos[0]["texto"])
        r = self.client.post(f"/api/solicitacoes/{pedido}/atender/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        # A escola é avisada da resposta e do atendimento (aviso do sistema, sem autor)
        self.entrar("escola1")
        avisos = [n["texto"] for n in self.client.get("/api/notificacoes/").data if n["tipo"] == "pedido"]
        self.assertTrue(any("Vamos ver a sala." in t for t in avisos))
        self.assertTrue(any("criada com 30 vagas" in t for t in avisos))
        self.entrar("dies1")
        self.assertEqual(r.data["status"], "atendida")
        turma = Turma.objects.get(pk=r.data["turma"])
        self.assertEqual((turma.turno, turma.capacidade, turma.escola_id), ("noturno", 30, self.escola1.escola_id))
        self.assertTrue(Registro.objects.filter(tipo="turma", objeto_id=str(turma.pk)).exists())
        # Atendido não atende de novo
        self.assertEqual(self.client.post(f"/api/solicitacoes/{pedido}/atender/").status_code, 400)

    def test_capacidade_nao_fica_menor_que_os_alunos(self):
        turma = Turma.objects.filter(escola=self.escola1.escola, matriculas__situacao="confirmada").first()
        self.entrar("escola1")
        r = self.client.post("/api/solicitacoes/", {"tipo": "capacidade", "turma": turma.pk, "capacidade": 1,
                                                    "mensagem": "Diminuir"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.entrar("dies1")
        r = self.client.post(f"/api/solicitacoes/{r.data['id']}/atender/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        turma.refresh_from_db()
        self.assertNotEqual(turma.capacidade, 1)

    def test_regras_do_pedido_e_quem_ve(self):
        self.entrar("escola1")
        r = self.client.post("/api/solicitacoes/", {"tipo": "nova_turma", "mensagem": "oi"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("serie", r.data)
        outra = Turma.objects.exclude(escola=self.escola1.escola).first()
        r = self.client.post("/api/solicitacoes/", {"tipo": "capacidade", "turma": outra.pk, "capacidade": 20,
                                                    "mensagem": "x"}, format="json")
        self.assertIn("turma", r.data)
        # Escola só vê os pedidos dela; DED e professor não usam pedidos
        self.assertTrue(all(p["escola"] == self.escola1.escola_id for p in self.client.get("/api/solicitacoes/").data))
        self.entrar("ded1")
        self.assertEqual(self.client.get("/api/solicitacoes/").status_code, 403)
        self.entrar("dies1")
        self.assertEqual(self.client.post("/api/solicitacoes/", {"tipo": "outro", "assunto": "a", "mensagem": "b"},
                                          format="json").status_code, 403)
        pedido = Solicitacao.objects.filter(status="aberta").first()
        self.assertIn("resposta", self.client.post(f"/api/solicitacoes/{pedido.pk}/recusar/", {}, format="json").data)
        r = self.client.post(f"/api/solicitacoes/{pedido.pk}/recusar/", {"resposta": "Sem sala."}, format="json")
        self.assertEqual(r.data["status"], "recusada")


class VinculoTest(Base):
    def test_escola_liga_e_desliga_responsavel(self):
        self.entrar("escola1")
        mae = Responsavel.objects.get(usuario__username="responsavel1")
        aluno = Aluno.objects.filter(matriculas__escola=self.escola1.escola, vinculos__isnull=True).first()
        url = f"/api/alunos/{aluno.pk}/"
        r = self.client.post(url + "vincular_responsavel/", {"responsavel": mae.pk, "parentesco": "mae"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["responsaveis"][0]["nome"], mae.nome)
        # De novo: já está ligado
        r = self.client.post(url + "vincular_responsavel/", {"responsavel": mae.pk, "parentesco": "mae"}, format="json")
        self.assertEqual(r.status_code, 400)

        # Pelo CPF: não existe -> pede o nome; com nome, cadastra e liga
        r = self.client.post(url + "vincular_responsavel/", {"cpf": "529.982.247-25", "parentesco": "pai"}, format="json")
        self.assertIn("nome", r.data)
        r = self.client.post(url + "vincular_responsavel/", {"cpf": "529.982.247-25", "parentesco": "pai",
                                                             "nome": "José Pai"}, format="json")
        self.assertEqual(len(r.data["responsaveis"]), 2)

        r = self.client.post(url + "desvincular_responsavel/", {"responsavel": mae.pk}, format="json")
        self.assertEqual([x["nome"] for x in r.data["responsaveis"]], ["José Pai"])
        self.assertTrue(Responsavel.objects.filter(pk=mae.pk).exists())  # o cadastro continua
        self.assertTrue(Registro.objects.filter(acao="apagou", tipo="vínculo familiar").exists())
