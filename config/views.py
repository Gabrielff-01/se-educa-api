from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from academico.models import Aluno, Comunicado, Horario, Matricula, PlanoAula, Vinculo
from calendario.models import DIAS_LETIVOS_MINIMOS, Evento
from contas.models import Usuario
from regulacao.models import AtoAutorizativo, Matriz
from rede.models import Escola, Materia, Turma
from rh.models import Afastamento, Professor


def inicio(request):
    """Página inicial da API. O Render usa ela pra saber se o serviço está no ar."""
    return JsonResponse({"nome": "SE Educa API", "status": "ok", "api": "/api/", "admin": "/admin/"})


def lista(choices):
    """[("matutino", "Matutino"), ...] -> [{"valor": "matutino", "nome": "Matutino"}, ...]"""
    return [{"valor": valor, "nome": nome} for valor, nome in choices]


@api_view(["GET"])
@permission_classes([AllowAny])
def opcoes(request):
    """GET /api/opcoes/: as listas de escolha (turnos, tipos de ato...) para os <select> do React.

    Assim o nome bonito de cada opção fica num lugar só: no model.
    """
    return Response({
        "perfis": lista(Usuario.Perfil.choices),
        "setores": lista(Usuario.Setor.choices),
        "dependencias": lista(Escola.Dependencia.choices),
        "areas": lista(Materia.Area.choices),
        "turnos": lista(Turma.Turno.choices),
        "tipos_ato": lista(AtoAutorizativo.Tipo.choices),
        "jornadas": lista(Matriz.Jornada.choices),
        "tipos_evento": lista(Evento.Tipo.choices),
        "cargas": lista(Professor.Carga.choices),
        "vinculos": lista(Professor.Vinculo.choices),
        "tipos_afastamento": lista(Afastamento.Tipo.choices),
        "programas": lista(Aluno.Programa.choices[1:]),  # sem o "Nenhum"
        "parentescos": lista(Vinculo.Parentesco.choices),
        "situacoes_matricula": lista(Matricula.Situacao.choices),
        "status_plano": lista(PlanoAula.Status.choices),
        "alcances": lista(Comunicado.Alcance.choices),
        "dias_semana": lista(Horario.Dia.choices),
        "dias_letivos_minimos": DIAS_LETIVOS_MINIMOS,
    })
