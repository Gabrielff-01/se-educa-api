from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APITestCase

from auditoria.models import Registro
from calendario.models import Evento
from contas.models import Usuario
from rede.models import Escola, Serie, Turma
from rh.models import Lotacao, Professor

from .models import Aluno, Fechamento, Horario, Matricula, Nota


class Base(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())
        cls.carlos = Professor.objects.get(usuario__username="professor1")
        # A lotação de Carlos em Matemática na 1ª série A (unidade 4 aberta, metade das notas lançadas).
        cls.lotacao = Lotacao.objects.filter(
            professor=cls.carlos, materia__nome="Matemática", turma__serie__ordem=1, turma__letra="A",
            turma__serie__curso__nome__icontains="médio",
        ).select_related("turma", "materia").first()
        cls.turma = cls.lotacao.turma

    def entrar(self, username):
        self.client.force_authenticate(Usuario.objects.get(username=username))

    def alunos_da_turma(self):
        return list(self.turma.matriculas.filter(situacao="confirmada").order_by("pk"))


class NotasTest(Base):
    def test_professor_lanca_notas_e_fica_no_historico(self):
        self.entrar("professor1")
        alunos = self.alunos_da_turma()
        dados = {"turma": self.turma.pk, "materia": self.lotacao.materia_id, "unidade": 4,
                 "notas": [{"matricula": m.pk, "valor": "8,5"} for m in alunos]}
        resposta = self.client.post("/api/notas/lancar/", dados, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(Nota.objects.filter(matricula__in=alunos, materia=self.lotacao.materia, unidade=4,
                                             valor="8.5").count(), len(alunos))
        registro = Registro.objects.filter(tipo="notas").latest("criado_em")
        self.assertIn("4ª unidade", registro.descricao)
        self.assertTrue(registro.mudancas)

    def test_nota_acima_de_10_nao_salva_nada(self):
        self.entrar("professor1")
        primeiro, segundo = self.alunos_da_turma()[:2]
        antes = Nota.objects.count()
        dados = {"turma": self.turma.pk, "materia": self.lotacao.materia_id, "unidade": 4,
                 "notas": [{"matricula": primeiro.pk, "valor": "7"}, {"matricula": segundo.pk, "valor": "11"}]}
        resposta = self.client.post("/api/notas/lancar/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn(str(segundo.pk), resposta.data["alunos"])
        self.assertEqual(Nota.objects.count(), antes)  # a nota 7 também não foi salva

    def test_unidade_fechada_nao_aceita_nota(self):
        self.entrar("professor1")
        aluno = self.alunos_da_turma()[0]
        dados = {"turma": self.turma.pk, "materia": self.lotacao.materia_id, "unidade": 1,
                 "notas": [{"matricula": aluno.pk, "valor": "5"}]}
        resposta = self.client.post("/api/notas/lancar/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("fechada", str(resposta.data))

    def test_professor_fora_da_materia_leva_403(self):
        self.entrar("professor1")
        outra = Lotacao.objects.filter(turma=self.turma).exclude(professor=self.carlos).first()
        dados = {"turma": self.turma.pk, "materia": outra.materia_id, "unidade": 4, "notas": []}
        resposta = self.client.post("/api/notas/lancar/", dados, format="json")
        self.assertEqual(resposta.status_code, 403)

    def test_aluno_nao_lanca_nota(self):
        self.entrar("aluno1")
        dados = {"turma": self.turma.pk, "materia": self.lotacao.materia_id, "unidade": 4, "notas": []}
        resposta = self.client.post("/api/notas/lancar/", dados, format="json")
        self.assertEqual(resposta.status_code, 403)


class DiarioTest(Base):
    def test_chamada_com_faltas(self):
        self.entrar("professor1")
        hoje = timezone.localdate()
        # um dia letivo recente sem aula registrada
        calendario = self.turma.escola  # só para deixar claro de qual escola é
        dia = hoje
        from calendario.models import calendario_da_escola
        cal = calendario_da_escola(calendario, self.turma.ano_letivo)
        while not cal.eh_dia_letivo(dia) or self.turma.aulas.filter(materia=self.lotacao.materia, data=dia).exists():
            dia -= timedelta(days=1)
        faltoso = self.alunos_da_turma()[0]
        dados = {"turma": self.turma.pk, "materia": self.lotacao.materia_id, "data": dia.isoformat(),
                 "quantidade": 2, "conteudo": "Função afim", "faltas": [faltoso.pk]}
        resposta = self.client.post("/api/aulas/", dados, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(resposta.data["faltosos"], [faltoso.pk])
        self.assertEqual(resposta.data["total_alunos"], len(self.alunos_da_turma()))

    def test_aula_no_futuro(self):
        self.entrar("professor1")
        dados = {"turma": self.turma.pk, "materia": self.lotacao.materia_id,
                 "data": (timezone.localdate() + timedelta(days=3)).isoformat(), "quantidade": 1}
        resposta = self.client.post("/api/aulas/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)

    def test_aula_em_feriado(self):
        self.entrar("professor1")
        feriado = Evento.objects.filter(
            tipo=Evento.Tipo.FERIADO, data_inicio__lt=timezone.localdate(), data_inicio__week_day__in=[2, 3, 4, 5, 6],
        ).first()
        dados = {"turma": self.turma.pk, "materia": self.lotacao.materia_id,
                 "data": feriado.data_inicio.isoformat(), "quantidade": 1}
        resposta = self.client.post("/api/aulas/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("letivo", str(resposta.data))


class FechamentoTest(Base):
    def test_fecha_unidade_3_mas_nao_a_4_incompleta(self):
        self.entrar("escola1")
        self.assertFalse(Fechamento.objects.filter(turma=self.turma, unidade=3).exists())
        resposta = self.client.post("/api/fechamentos/", {"turma": self.turma.pk, "unidade": 3}, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        resposta = self.client.post("/api/fechamentos/", {"turma": self.turma.pk, "unidade": 4}, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("Matemática", str(resposta.data))

    def test_nao_pula_unidade(self):
        self.entrar("escola1")
        resposta = self.client.post("/api/fechamentos/", {"turma": self.turma.pk, "unidade": 4}, format="json")
        self.assertEqual(resposta.status_code, 400)


class HorarioTest(Base):
    def test_conflito_de_horario_da_turma(self):
        self.entrar("escola1")
        ocupado = Horario.objects.filter(lotacao__turma=self.turma).exclude(lotacao=self.lotacao).first()
        dados = {"lotacao": self.lotacao.pk, "dia_semana": ocupado.dia_semana, "inicio": ocupado.inicio.isoformat()}
        resposta = self.client.post("/api/horarios/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)


class MatriculaTest(Base):
    def test_nova_matricula_cria_aluno_e_responsavel(self):
        self.entrar("escola1")
        escola = Usuario.objects.get(username="escola1").escola
        serie = self.turma.serie
        dados = {
            "aluno_nome": "Teste da Silva", "aluno_nascimento": "2010-05-05", "programa_social": "bolsa_familia",
            "nis": "12345678901", "responsavel_nome": "Mãe do Teste", "responsavel_cpf": "529.982.247-25",
            "responsavel_telefone": "79999990000", "parentesco": "mae", "escola": escola.pk, "serie": serie.pk,
            "ano_letivo": self.turma.ano_letivo,
        }
        resposta = self.client.post("/api/matriculas/nova/", dados, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        aluno = Aluno.objects.get(nome="Teste da Silva")
        self.assertEqual(aluno.responsaveis.get().nome, "Mãe do Teste")
        self.assertTrue(aluno.codigo)

    def test_bolsa_familia_exige_nis(self):
        self.entrar("escola1")
        escola = Usuario.objects.get(username="escola1").escola
        dados = {"aluno_nome": "Sem NIS", "aluno_nascimento": "2010-05-05", "programa_social": "bolsa_familia",
                 "responsavel_nome": "X", "responsavel_cpf": "529.982.247-25", "parentesco": "mae",
                 "escola": escola.pk, "serie": self.turma.serie_id, "ano_letivo": self.turma.ano_letivo}
        resposta = self.client.post("/api/matriculas/nova/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertFalse(Aluno.objects.filter(nome="Sem NIS").exists())

    def test_serie_nao_ofertada(self):
        self.entrar("escola1")
        escola = Usuario.objects.get(username="escola1").escola
        nao_ofertada = Serie.objects.exclude(ofertas__escola=escola).first()
        aluno = Aluno.objects.create(nome="Fulano", data_nascimento="2012-01-01")
        dados = {"aluno": aluno.pk, "escola": escola.pk, "serie": nao_ofertada.pk, "ano_letivo": 2026}
        resposta = self.client.post("/api/matriculas/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)

    def test_escola_nao_mexe_em_matricula_de_outra(self):
        self.entrar("escola1")
        minha = Usuario.objects.get(username="escola1").escola_id
        de_outra = Matricula.objects.exclude(escola_id=minha).first()
        resposta = self.client.patch(f"/api/matriculas/{de_outra.pk}/", {"situacao": "cancelada"}, format="json")
        self.assertIn(resposta.status_code, (403, 404))


class AcessoTest(Base):
    def test_aluno_ve_so_ele(self):
        self.entrar("aluno1")
        resposta = self.client.get("/api/boletim/")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["aluno"]["nome"], "Ana Beatriz Souza")
        # 3 matrículas: 2026 e o histórico de 2024 e 2025, todas dela
        nomes = {m["aluno_nome"] for m in self.client.get("/api/matriculas/").data}
        self.assertEqual(nomes, {"Ana Beatriz Souza"})

    def test_responsavel_ve_os_filhos_e_nao_outros(self):
        self.entrar("responsavel1")
        filhos = self.client.get("/api/meus-alunos/").data
        self.assertEqual(len(filhos), 2)
        estranho = Aluno.objects.exclude(pk__in=[f["id"] for f in filhos]).first()
        self.assertEqual(self.client.get(f"/api/boletim/?aluno={estranho.pk}").status_code, 403)
        self.assertEqual(self.client.get(f"/api/boletim/?aluno={filhos[1]['id']}").status_code, 200)

    def test_professor_so_manda_comunicado_para_suas_turmas(self):
        self.entrar("professor1")
        geral = {"titulo": "Oi", "texto": "Para todos", "alcance": "rede"}
        self.assertEqual(self.client.post("/api/comunicados/", geral, format="json").status_code, 403)
        turma = {"titulo": "Prova", "texto": "Sexta", "alcance": "turma", "turma": self.turma.pk}
        resposta = self.client.post("/api/comunicados/", turma, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        # e o aluno da turma recebe como notificação nova
        self.entrar("aluno1")
        notificacoes = self.client.get("/api/notificacoes/").data
        self.assertTrue(any(n["titulo"] == "Prova" and n["nova"] for n in notificacoes))
        self.client.post("/api/notificacoes/")
        self.assertFalse(any(n["nova"] for n in self.client.get("/api/notificacoes/").data))


class HistoricoTest(Base):
    def test_editar_turma_registra_o_antes_e_depois(self):
        self.entrar("dies1")
        resposta = self.client.patch(f"/api/turmas/{self.turma.pk}/", {"sala": "Lab 2"}, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        registro = Registro.objects.latest("criado_em")
        self.assertEqual(registro.acao, "editou")
        self.assertTrue(any(m["depois"] == "Lab 2" for m in registro.mudancas))
        self.assertEqual(len(self.client.get("/api/registros/").data) > 0, True)

    def test_professor_ve_so_o_que_ele_fez(self):
        self.entrar("professor1")
        for registro in self.client.get("/api/registros/").data:
            self.assertEqual(registro["usuario_nome"], "Carlos Eduardo Menezes")


class RhTest(Base):
    def test_afastamento_sobreposto(self):
        self.entrar("rh1")
        fernanda = Professor.objects.get(matricula="100002-2")
        hoje = timezone.localdate()
        dados = {"professor": fernanda.pk, "tipo": "ferias", "inicio": hoje.isoformat(),
                 "fim": (hoje + timedelta(days=3)).isoformat()}
        resposta = self.client.post("/api/afastamentos/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)

    def test_criar_acesso_do_professor(self):
        self.entrar("rh1")
        paulo = Professor.objects.get(matricula="100005-5")
        resposta = self.client.post(f"/api/professores/{paulo.pk}/criar_acesso/",
                                    {"username": "paulo.dias", "senha": "Sergipe@2026"}, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        paulo.refresh_from_db()
        self.assertEqual(paulo.usuario.perfil, "professor")
        self.assertTrue(paulo.usuario.check_password("Sergipe@2026"))

    def test_paineis_do_rh(self):
        self.entrar("rh1")
        painel = self.client.get("/api/rh/painel/")
        self.assertEqual(painel.status_code, 200)
        carencias = self.client.get("/api/rh/carencias/")
        self.assertEqual(carencias.status_code, 200)
        tipos = {c["tipo"] for c in carencias.data}
        self.assertEqual(tipos, {"sem_professor", "substituicao"})


class PaineisTest(Base):
    def test_todos_os_paineis_abrem(self):
        rotas = {
            "professor1": ["/api/painel/professor/", "/api/agenda/"],
            "escola1": ["/api/painel/escola/", "/api/escola/professores/", "/api/escola/diario/",
                        "/api/escola/boletins/", "/api/escola/programas/"],
            "dies1": ["/api/rede/matriculas/", "/api/rede/frequencia/", "/api/rede/carga-horaria/"],
            "aluno1": ["/api/historico/", "/api/minhas-tarefas/", "/api/agenda/", "/api/cardapios/"],
        }
        for username, urls in rotas.items():
            self.entrar(username)
            for url in urls:
                with self.subTest(usuario=username, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_turmas_tem_sala_e_alunos(self):
        self.entrar("escola1")
        turma = self.client.get(f"/api/turmas/{self.turma.pk}/").data
        self.assertTrue(turma["sala"])
        self.assertGreater(turma["alunos"], 0)


class CadastrosTest(Base):
    def test_professor_cria_tarefa_e_plano(self):
        self.entrar("professor1")
        prazo = (timezone.localdate() + timedelta(days=5)).isoformat()
        tarefa = {"turma": self.turma.pk, "materia": self.lotacao.materia_id, "titulo": "Lista 9",
                  "descricao": "Exercícios 1 a 10", "prazo": prazo}
        resposta = self.client.post("/api/tarefas/", tarefa, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        plano = {"turma": self.turma.pk, "materia": self.lotacao.materia_id, "unidade": 4, "tema": "Logaritmos",
                 "objetivos": "Entender log", "status": "planejado"}
        resposta = self.client.post("/api/planos/", plano, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)

    def test_escola_edita_cardapio_e_afastamento_novo(self):
        self.entrar("escola1")
        cardapio = self.client.get("/api/cardapios/").data[0]
        resposta = self.client.patch(f"/api/cardapios/{cardapio['id']}/", {"almoco": "Galinha caipira"}, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.entrar("rh1")
        paulo = Professor.objects.get(matricula="100005-5")
        dados = {"professor": paulo.pk, "tipo": "ferias", "inicio": "2026-12-14", "fim": "2026-12-31"}
        resposta = self.client.post("/api/afastamentos/", dados, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
