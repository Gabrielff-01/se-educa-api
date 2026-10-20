"""Quem vê e quem mexe em quê nos dados acadêmicos.

Resumo:
- Secretaria (e admin): vê tudo.
- Escola: vê e cadastra só o da sua escola (matrículas, horários, merenda, boletins).
- Professor: vê as turmas onde está lotado; lança aula, chamada, notas, tarefas e planos
  só na matéria e turma da sua lotação.
- Aluno: vê só o próprio. Responsável: vê só os filhos.
"""

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

from contas.models import Usuario
from rede.models import Turma
from rh.models import Professor

from .models import Aluno, Matricula

Perfil = Usuario.Perfil


def eh_secretaria(usuario):
    return usuario.is_superuser or usuario.perfil == Perfil.SECRETARIA


def professor_de(usuario):
    """O cadastro de professor (RH) ligado ao login. None se não tiver."""
    if usuario.perfil != Perfil.PROFESSOR:
        return None
    return Professor.objects.filter(usuario=usuario).first()


def turmas_visiveis(usuario):
    turmas = Turma.objects.all()
    if eh_secretaria(usuario):
        return turmas
    if usuario.perfil == Perfil.ESCOLA:
        return turmas.filter(escola_id=usuario.escola_id)
    if usuario.perfil == Perfil.PROFESSOR:
        return turmas.filter(lotacoes__professor__usuario=usuario).distinct()
    if usuario.perfil == Perfil.ALUNO:
        return turmas.filter(matriculas__aluno__usuario=usuario).distinct()
    if usuario.perfil == Perfil.RESPONSAVEL:
        return turmas.filter(matriculas__aluno__responsaveis__usuario=usuario).distinct()
    return turmas.none()


def matriculas_visiveis(usuario):
    matriculas = Matricula.objects.all()
    if eh_secretaria(usuario):
        return matriculas
    if usuario.perfil == Perfil.ESCOLA:
        return matriculas.filter(escola_id=usuario.escola_id)
    if usuario.perfil == Perfil.PROFESSOR:
        return matriculas.filter(turma__in=turmas_visiveis(usuario))
    if usuario.perfil == Perfil.ALUNO:
        return matriculas.filter(aluno__usuario=usuario)
    if usuario.perfil == Perfil.RESPONSAVEL:
        return matriculas.filter(aluno__responsaveis__usuario=usuario)
    return matriculas.none()


def alunos_visiveis(usuario):
    alunos = Aluno.objects.all()
    if eh_secretaria(usuario):
        return alunos
    if usuario.perfil == Perfil.ALUNO:
        return alunos.filter(usuario=usuario)
    if usuario.perfil == Perfil.RESPONSAVEL:
        return alunos.filter(responsaveis__usuario=usuario)
    return alunos.filter(matriculas__in=matriculas_visiveis(usuario)).distinct()


def aluno_pedido(request):
    """O aluno de quem a tela quer ver os dados.

    - Aluno: sempre ele mesmo.
    - Outros: ?aluno=ID na URL (o responsável escolhe o filho; a escola, o aluno).
      Sem ?aluno, o responsável vê o primeiro filho.
    """
    usuario = request.user
    visiveis = alunos_visiveis(usuario)
    if usuario.perfil == Perfil.ALUNO:
        aluno = visiveis.first()
    elif request.query_params.get("aluno"):
        aluno = visiveis.filter(pk=request.query_params["aluno"]).first()
    elif usuario.perfil == Perfil.RESPONSAVEL:
        aluno = visiveis.order_by("nome").first()
    else:
        aluno = None
    if aluno is None:
        raise PermissionDenied("Nenhum aluno ligado a este usuário (ou você não pode ver esse aluno).")
    return aluno


def pode_cuidar_da_escola(usuario, escola_id):
    """Secretaria cuida de todas; a gestão da escola, só da sua."""
    if eh_secretaria(usuario):
        return True
    return usuario.perfil == Perfil.ESCOLA and usuario.escola_id == escola_id


def conferir_escola(usuario, escola_id):
    if not pode_cuidar_da_escola(usuario, escola_id):
        raise PermissionDenied("Você só pode mexer nos dados da sua escola.")


def conferir_professor_da_lotacao(usuario, professor_id):
    """Professor só lança no próprio nome (o admin pode tudo)."""
    if usuario.is_superuser:
        return
    professor = professor_de(usuario)
    if professor is None or professor.pk != professor_id:
        raise PermissionDenied("Só o professor da turma pode fazer isso.")


class SoLeituraOu(BasePermission):
    """Todo mundo logado lê; só os perfis listados mudam. As regras finas ficam nas views."""

    perfis = ()
    message = "Seu perfil não pode fazer isso."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_superuser or request.user.perfil in self.perfis


def so_editam(*perfis):
    return type("SoEditam", (SoLeituraOu,), {"perfis": perfis})


ESCOLA_OU_SECRETARIA = [so_editam(Perfil.ESCOLA, Perfil.SECRETARIA)]
SO_PROFESSOR = [so_editam(Perfil.PROFESSOR)]
