"""Endereços do projeto.

/admin/  painel do Django (cadastros manuais)
/api/    API que o React usa. Abrindo no navegador (logado no admin) dá pra navegar nela.
"""

from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from academico import paineis
from academico.views import (
    AlunoViewSet,
    AulaViewSet,
    CardapioViewSet,
    ComunicadoViewSet,
    FechamentoViewSet,
    HorarioViewSet,
    MatriculaViewSet,
    NotaViewSet,
    PlanoAulaViewSet,
    ResponsavelViewSet,
    TarefaViewSet,
)
from auditoria.views import RegistroViewSet
from calendario.views import CalendarioLetivoViewSet, EventoViewSet
from contas.views import EuView, LoginView
from rede.views import (
    CursoViewSet,
    EscolaViewSet,
    MateriaViewSet,
    RegionalViewSet,
    SerieViewSet,
    TurmaViewSet,
)
from regulacao.views import AtoAutorizativoViewSet, MatrizViewSet, OfertaViewSet
from rh.views import AfastamentoViewSet, LotacaoViewSet, ProfessorViewSet
from solicitacoes.views import SolicitacaoViewSet

from .views import inicio, opcoes

admin.site.site_header = "SE Educa - Administração"
admin.site.site_title = "SE Educa"
admin.site.index_title = "Painel de cadastros"

# O router cria sozinho os endereços de cada ViewSet:
# /api/escolas/ (listar e criar) e /api/escolas/1/ (ver, editar e apagar).
router = DefaultRouter()
# DIES
router.register("regionais", RegionalViewSet)
router.register("escolas", EscolaViewSet)
router.register("cursos", CursoViewSet)
router.register("series", SerieViewSet)
router.register("materias", MateriaViewSet)
router.register("turmas", TurmaViewSet)
router.register("calendarios", CalendarioLetivoViewSet)
router.register("eventos", EventoViewSet)
# DED
router.register("atos", AtoAutorizativoViewSet)
router.register("ofertas", OfertaViewSet)
router.register("matrizes", MatrizViewSet)
# RH
router.register("professores", ProfessorViewSet)
router.register("lotacoes", LotacaoViewSet)
router.register("afastamentos", AfastamentoViewSet)
# Acadêmico (escola, professor, aluno e família)
router.register("alunos", AlunoViewSet, basename="aluno")
router.register("responsaveis", ResponsavelViewSet, basename="responsavel")
router.register("matriculas", MatriculaViewSet, basename="matricula")
router.register("aulas", AulaViewSet, basename="aula")
router.register("notas", NotaViewSet, basename="nota")
router.register("fechamentos", FechamentoViewSet, basename="fechamento")
router.register("tarefas", TarefaViewSet, basename="tarefa")
router.register("planos", PlanoAulaViewSet, basename="plano")
router.register("comunicados", ComunicadoViewSet, basename="comunicado")
router.register("horarios", HorarioViewSet, basename="horario")
router.register("cardapios", CardapioViewSet)
# Histórico de alterações
router.register("registros", RegistroViewSet, basename="registro")
# Pedidos escola → DIES (com conversa)
router.register("solicitacoes", SolicitacaoViewSet, basename="solicitacao")

urlpatterns = [
    path("", inicio),
    path("admin/", admin.site.urls),
    path("api/auth/login/", LoginView.as_view()),
    path("api/auth/refresh/", TokenRefreshView.as_view()),
    path("api/auth/eu/", EuView.as_view()),
    path("api/opcoes/", opcoes),
    # Telas de resumo (só leitura, calculadas na hora)
    path("api/meus-alunos/", paineis.meus_alunos),
    path("api/boletim/", paineis.boletim),
    path("api/historico/", paineis.historico),
    path("api/minhas-tarefas/", paineis.minhas_tarefas),
    path("api/agenda/", paineis.agenda),
    path("api/notificacoes/", paineis.notificacoes),
    path("api/painel/professor/", paineis.painel_professor),
    path("api/painel/escola/", paineis.painel_escola),
    path("api/escola/professores/", paineis.professores_da_escola),
    path("api/escola/diario/", paineis.diario_da_escola),
    path("api/escola/boletins/", paineis.boletins_da_escola),
    path("api/escola/programas/", paineis.programas_sociais),
    path("api/rede/matriculas/", paineis.rede_matriculas),
    path("api/rede/frequencia/", paineis.rede_frequencia),
    path("api/rede/carga-horaria/", paineis.rede_carga_horaria),
    path("api/rh/painel/", paineis.rh_painel),
    path("api/rh/carencias/", paineis.rh_carencias),
    path("api/", include(router.urls)),
]
