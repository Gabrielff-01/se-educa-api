from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APITestCase

from academico.demo import CPF_ALUNO1, cpf_ficticio
from academico.models import Aluno, Matricula
from contas.models import Usuario
from rede.models import Escola, Turma

from .models import Inscricao


class Base(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())
        cls.ano = timezone.localdate().year
        # A família pede vaga no Atheneu (escola1), numa série e turno que têm turma.
        cls.escola = Usuario.objects.get(username="escola1").escola
        cls.turma = Turma.objects.filter(escola=cls.escola, ano_letivo=cls.ano).order_by("serie__ordem", "letra").first()
        cls.serie = cls.turma.serie

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
            "escola": self.escola.pk, "serie": self.serie.pk, "turno_preferido": self.turma.turno,
        }
        dados.update(mudancas)
        return self.client.post("/api/inscricoes/", dados, format="json")

    def identificar(self, usuario):
        return self.client.post("/api/auth/identificar/", {"usuario": usuario}, format="json")

    def login(self, usuario, senha="Matricula@2026"):
        return self.client.post("/api/auth/login/", {"username": usuario, "password": senha})


class InscricaoTest(Base):
    def test_familia_envia_e_a_escola_aprova_com_turma(self):
        # 1º passo: o CPF ainda não tem cadastro
        r = self.identificar("529.982.247-25")
        self.assertEqual((r.status_code, r.data["situacao"], r.data["cpf"]), (200, "novo", "52998224725"), r.data)
        # Sem login: lista as escolas e envia o pedido
        r = self.client.get("/api/inscricoes/escolas/")
        escola = next(e for e in r.data["escolas"] if e["id"] == self.escola.pk)
        serie = next(s for s in escola["series"] if s["id"] == self.serie.pk)
        self.assertIn(self.turma.turno, [t["valor"] for t in serie["turnos"]])
        r = self.pedido()
        self.assertEqual(r.status_code, 201, r.data)
        protocolo = r.data["protocolo"]
        self.assertNotIn("cpf", r.data)  # não devolve dado pessoal
        inscricao = Inscricao.objects.get(protocolo=protocolo)
        self.assertNotEqual(inscricao.senha, "Matricula@2026")  # guardada criptografada
        # Com pedido esperando, o CPF e o e-mail já levam pra senha; o login com o CPF mostra o andamento
        self.assertEqual(self.identificar("52998224725").data["situacao"], "pedido")
        self.assertEqual(self.identificar("teste.novo@exemplo.com").data["situacao"], "pedido")
        self.assertIn("em análise", str(self.login("529.982.247-25").data))

        # Antes da aprovação, o login explica o andamento (só com a senha certa)
        r = self.login("teste.novo@exemplo.com")
        self.assertEqual(r.status_code, 401)
        self.assertIn(f"em análise pela escola {self.escola.nome}", str(r.data))
        self.assertNotIn("escola", str(self.login("teste.novo@exemplo.com", "errada123").data))

        # Sem login ninguém lista; outra escola não vê; o DIES vê mas não aprova
        self.assertEqual(self.client.get("/api/inscricoes/").status_code, 401)
        self.entrar("escola2")
        self.assertNotIn(protocolo, [i["protocolo"] for i in self.client.get("/api/inscricoes/").data])
        self.assertEqual(self.client.post(f"/api/inscricoes/{inscricao.pk}/aprovar/").status_code, 404)
        self.entrar("dies1")
        self.assertIn(protocolo, [i["protocolo"] for i in self.client.get("/api/inscricoes/").data])
        self.assertEqual(self.client.post(f"/api/inscricoes/{inscricao.pk}/aprovar/").status_code, 403)

        # A escola aprova já escolhendo a turma
        self.entrar("escola1")
        r = self.client.get("/api/inscricoes/?status=aguardando")
        self.assertIn(protocolo, [i["protocolo"] for i in r.data])
        self.assertNotIn("senha", r.data[0])
        outra = Turma.objects.filter(escola=self.escola).exclude(serie=self.serie).first()
        if outra:
            r = self.client.post(f"/api/inscricoes/{inscricao.pk}/aprovar/", {"turma": outra.pk}, format="json")
            self.assertIn("turma", r.data)
        r = self.client.post(f"/api/inscricoes/{inscricao.pk}/aprovar/", {"turma": self.turma.pk}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        matricula = Matricula.objects.get(pk=r.data["matricula"])
        self.assertEqual((matricula.situacao, matricula.turma_id), ("confirmada", self.turma.pk))
        self.assertEqual(matricula.aluno.cpf, "52998224725")
        self.assertEqual(matricula.aluno.responsaveis.get().cpf, cpf_ficticio("111444777"))
        self.assertEqual(self.client.post(f"/api/inscricoes/{inscricao.pk}/aprovar/").status_code, 400)

        # Agora o aluno entra com o e-mail ou com o CPF
        self.client.force_authenticate(None)
        r = self.login("teste.novo@exemplo.com")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["usuario"]["perfil"], "aluno")
        self.assertEqual(self.login("529.982.247-25").status_code, 200)
        # E o CPF não faz outro pedido: vai pro login
        self.assertEqual(self.identificar("52998224725").data["situacao"], "tem_login")
        self.assertIn("já possui cadastro", str(self.pedido(email="outro@exemplo.com").data))

    def test_aprovar_sem_turma_vai_pra_enturmacao(self):
        inscricao = Inscricao.objects.get(protocolo=self.pedido().data["protocolo"])
        self.entrar("escola1")
        r = self.client.post(f"/api/inscricoes/{inscricao.pk}/aprovar/")
        self.assertEqual(r.status_code, 200, r.data)
        matricula = Matricula.objects.get(pk=r.data["matricula"])
        self.assertEqual((matricula.situacao, matricula.turma_id), ("em_analise", None))
        self.entrar("dies1")
        fila = self.client.get(f"/api/matriculas/?sem_turma=1&ano_letivo={self.ano}").data
        self.assertIn(matricula.pk, [m["id"] for m in fila])

    def test_recusa_aparece_no_login(self):
        inscricao = Inscricao.objects.get(protocolo=self.pedido().data["protocolo"])
        self.entrar("escola1")
        self.assertEqual(self.client.post(f"/api/inscricoes/{inscricao.pk}/recusar/", {}).status_code, 400)
        r = self.client.post(f"/api/inscricoes/{inscricao.pk}/recusar/", {"motivo": "Faltou a série certa."})
        self.assertEqual(r.data["status"], "recusada")
        self.client.force_authenticate(None)
        r = self.login("teste.novo@exemplo.com")
        self.assertIn("recusada pela escola", str(r.data))
        self.assertIn("Faltou a série certa.", str(r.data))
        # Depois de recusado, pode mandar um pedido novo com o mesmo CPF
        self.assertEqual(self.identificar("52998224725").data["situacao"], "pedido")  # recusado: login mostra o motivo
        self.assertEqual(self.pedido().status_code, 201)

    def test_regras_do_pedido(self):
        self.assertIn("usuario", self.identificar("111.111.111-11").data)
        self.assertIn("cpf", self.pedido(cpf="111.111.111-11").data)
        self.assertIn("nis", self.pedido(bolsa_familia=True).data)
        self.assertIn("senha", self.pedido(senha="12345678").data)  # senha fraca/comum
        # Série que a escola não tem turma (ex.: 6º ano numa escola só de Ensino Médio)
        sem_turma = next((t.serie for t in Turma.objects.filter(ano_letivo=self.ano).exclude(escola=self.escola)
                          if not Turma.objects.filter(escola=self.escola, serie=t.serie, ano_letivo=self.ano).exists()), None)
        if sem_turma:
            self.assertIn("escola", self.pedido(serie=sem_turma.pk, turno_preferido="").data)
        # Turno que a escola não tem para a série
        outro_turno = next(v for v, _ in Turma.Turno.choices
                           if not Turma.objects.filter(escola=self.escola, serie=self.serie, ano_letivo=self.ano, turno=v).exists())
        self.assertIn("turno_preferido", self.pedido(turno_preferido=outro_turno).data)
        # Mesmo CPF esperando análise: não duplica
        self.assertEqual(self.pedido().status_code, 201)
        self.assertEqual(self.pedido(email="outro@exemplo.com").status_code, 400)

    def test_escolas_so_com_turma(self):
        for escola in self.client.get("/api/inscricoes/escolas/").data["escolas"]:
            for serie in escola["series"]:
                self.assertTrue(Turma.objects.filter(escola_id=escola["id"], serie_id=serie["id"], ano_letivo=self.ano).exists())

    def test_email_que_ja_e_login(self):
        Usuario.objects.create_user("ja.existe@exemplo.com", password="x" * 10)
        self.assertIn("email", self.pedido(email="ja.existe@exemplo.com").data)

    def test_cpf_de_aluno_da_rede(self):
        self.assertEqual(Aluno.objects.filter(cpf="").count(), 0)  # o demo dá CPF a todo mundo
        r = self.identificar("123.456.789-09")
        self.assertEqual(r.data["situacao"], "tem_login")
        self.assertIn("já possui cadastro", r.data["mensagem"])
        self.assertEqual(self.identificar("aluno1").data["situacao"], "tem_login")
        self.assertEqual(self.identificar("ninguem.aqui").data["situacao"], "nao_encontrado")
        sem_login = Aluno.objects.filter(usuario__isnull=True).first()
        self.assertEqual(self.identificar(sem_login.cpf).data["situacao"], "sem_acesso")
        self.assertEqual(Aluno.objects.get(cpf=CPF_ALUNO1).usuario.username, "aluno1")
        self.assertEqual(self.login("123.456.789-09", "aluno").status_code, 200)  # entra com o CPF

    def test_demo_tem_pedidos_aguardando(self):
        self.assertEqual(Inscricao.objects.filter(status="aguardando").count(), 2)
        self.assertTrue(Inscricao.objects.filter(status="aguardando", escola=self.escola).exists())
        r = self.login("lucas.andrade@exemplo.com", "matricula123")
        self.assertIn("em análise pela escola", str(r.data))
