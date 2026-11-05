from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APITestCase

from academico.demo import cpf_ficticio
from academico.models import Matricula
from contas.models import Usuario
from rede.models import Escola

from .models import Inscricao


class Base(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())
        cls.ano = timezone.localdate().year
        cls.escola = Escola.objects.filter(ofertas__ano_letivo=cls.ano).distinct().first()
        cls.serie = cls.escola.ofertas.get(ano_letivo=cls.ano).series.first()

    def setUp(self):
        cache.clear()  # zera o limite de envios por hora entre um teste e outro

    def entrar(self, username):
        self.client.force_authenticate(Usuario.objects.get(username=username))

    def pedido(self, **mudancas):
        dados = {
            "aluno_nome": "Teste Aluno Novo", "data_nascimento": f"{self.ano - 15}-05-10", "sexo": "F",
            "raca": "parda", "cpf": "529.982.247-25", "bolsa_familia": False, "nis": "",
            "responsavel_nome": "Teste Mae Nova", "responsavel_cpf": cpf_ficticio("111444777"),
            "responsavel_parentesco": "mae", "telefone": "(79) 99999-0000", "email": "teste.novo@exemplo.com",
            "senha": "Matricula@2026", "cep": "49000-000", "endereco": "Rua Teste", "numero": "10",
            "complemento": "", "bairro": "Centro", "cidade": "Aracaju", "uf": "se",
            "escola": self.escola.pk, "serie": self.serie.pk, "turno_preferido": "",
        }
        dados.update(mudancas)
        return self.client.post("/api/inscricoes/", dados, format="json")


class InscricaoTest(Base):
    def test_familia_envia_sem_login_e_dies_aprova(self):
        # Sem login: lista as escolas e envia o pedido
        r = self.client.get("/api/inscricoes/escolas/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any(e["id"] == self.escola.pk for e in r.data["escolas"]))
        r = self.pedido()
        self.assertEqual(r.status_code, 201, r.data)
        protocolo = r.data["protocolo"]
        self.assertTrue(protocolo.startswith(f"{self.ano}-"))
        self.assertNotIn("cpf", r.data)  # não devolve dado pessoal
        inscricao = Inscricao.objects.get(protocolo=protocolo)
        self.assertEqual((inscricao.cpf, inscricao.uf, inscricao.ano_letivo), ("52998224725", "SE", self.ano))
        self.assertNotEqual(inscricao.senha, "Matricula@2026")  # guardada criptografada

        # Antes da aprovação, o login explica o andamento (só com a senha certa)
        r = self.client.post("/api/auth/login/", {"username": "teste.novo@exemplo.com", "password": "Matricula@2026"})
        self.assertEqual(r.status_code, 401)
        self.assertIn("em análise pelo DIES", str(r.data))
        r = self.client.post("/api/auth/login/", {"username": "teste.novo@exemplo.com", "password": "errada123"})
        self.assertNotIn("DIES", str(r.data))

        # Sem login ninguém lista; escola e DED também não
        self.assertEqual(self.client.get("/api/inscricoes/").status_code, 401)
        self.entrar("escola1")
        self.assertEqual(self.client.get("/api/inscricoes/").status_code, 403)

        self.entrar("dies1")
        r = self.client.get("/api/inscricoes/?status=aguardando")
        self.assertIn(protocolo, [i["protocolo"] for i in r.data])
        self.assertNotIn("senha", r.data[0])
        r = self.client.post(f"/api/inscricoes/{inscricao.pk}/aprovar/")
        self.assertEqual(r.status_code, 200, r.data)
        matricula = Matricula.objects.get(pk=r.data["matricula"])
        self.assertEqual((matricula.situacao, matricula.turma_id, matricula.escola_id), ("em_analise", None, self.escola.pk))
        self.assertEqual(matricula.aluno.responsaveis.get().cpf, cpf_ficticio("111444777"))
        # Cai na fila da Enturmação
        fila = self.client.get(f"/api/matriculas/?sem_turma=1&ano_letivo={self.ano}").data
        self.assertIn(matricula.pk, [m["id"] for m in fila])
        # Aprovado não aprova de novo
        self.assertEqual(self.client.post(f"/api/inscricoes/{inscricao.pk}/aprovar/").status_code, 400)

        # O mesmo aluno não pede de novo no mesmo ano
        self.client.force_authenticate(None)
        self.assertIn("já tem matrícula aprovada", str(self.pedido(email="outro.email@exemplo.com").data))

        # Agora o aluno entra com o e-mail e a senha que escolheu
        self.client.force_authenticate(None)
        r = self.client.post("/api/auth/login/", {"username": "teste.novo@exemplo.com", "password": "Matricula@2026"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["usuario"]["perfil"], "aluno")

    def test_recusa_aparece_no_login(self):
        r = self.pedido()
        inscricao = Inscricao.objects.get(protocolo=r.data["protocolo"])
        self.entrar("dies1")
        self.assertEqual(self.client.post(f"/api/inscricoes/{inscricao.pk}/recusar/", {}).status_code, 400)
        r = self.client.post(f"/api/inscricoes/{inscricao.pk}/recusar/", {"motivo": "Faltou a série certa."})
        self.assertEqual(r.data["status"], "recusada")
        self.client.force_authenticate(None)
        r = self.client.post("/api/auth/login/", {"username": "teste.novo@exemplo.com", "password": "Matricula@2026"})
        self.assertIn("Faltou a série certa.", str(r.data))
        # Depois de recusado, pode mandar um pedido novo com o mesmo CPF
        self.assertEqual(self.pedido().status_code, 201)

    def test_regras_do_pedido(self):
        self.assertIn("cpf", self.pedido(cpf="111.111.111-11").data)
        self.assertIn("nis", self.pedido(bolsa_familia=True).data)
        self.assertIn("senha", self.pedido(senha="12345678").data)  # senha fraca/comum
        # Série que a escola não oferece
        outra = Escola.objects.exclude(pk=self.escola.pk).first()
        ofertadas = set(self.escola.ofertas.get(ano_letivo=self.ano).series.values_list("pk", flat=True))
        fora = next((s for s in outra.ofertas.get(ano_letivo=self.ano).series.all() if s.pk not in ofertadas), None)
        if fora:
            self.assertIn("serie", self.pedido(serie=fora.pk).data)
        # Mesmo CPF esperando análise: não duplica
        self.assertEqual(self.pedido().status_code, 201)
        self.assertEqual(self.pedido(email="outro@exemplo.com").status_code, 400)

    def test_email_que_ja_e_login(self):
        Usuario.objects.create_user("ja.existe@exemplo.com", password="x" * 10)
        self.assertIn("email", self.pedido(email="ja.existe@exemplo.com").data)

    def test_demo_tem_pedidos_aguardando(self):
        self.assertEqual(Inscricao.objects.filter(status="aguardando").count(), 2)
        r = self.client.post("/api/auth/login/", {"username": "lucas.andrade@exemplo.com", "password": "matricula123"})
        self.assertIn("em análise", str(r.data))
