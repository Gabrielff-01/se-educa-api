"""Quem pode fazer o quê na API.

Regra geral do SE Educa:
- qualquer pessoa logada pode LER os cadastros da rede (escolas, turmas, calendário...);
- só o setor responsável pode CRIAR, EDITAR ou APAGAR.
  DIES: escolas, cursos, séries, matérias, turmas e calendário.
  DED: atos autorizativos, ofertas e matrizes.
  RH: professores e lotações.
- o superusuário (admin) pode tudo.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission


def eh_do_setor(usuario, *setores):
    """True se o usuário é da Secretaria e está em um dos setores (ou é superusuário)."""
    if not usuario.is_authenticated:
        return False
    if usuario.is_superuser:
        return True
    return usuario.perfil == usuario.Perfil.SECRETARIA and usuario.setor in setores


def edicao_do_setor(*setores):
    """Cria uma permissão: todo mundo logado lê, só esses setores mudam.

    Uso no ViewSet: permission_classes = [edicao_do_setor("dies")]
    """

    class EdicaoDoSetor(BasePermission):
        message = f"Só o setor {' / '.join(s.upper() for s in setores)} pode fazer isso."

        def has_permission(self, request, view):
            if not request.user.is_authenticated:
                return False
            if request.method in SAFE_METHODS:  # GET: só olhar
                return True
            return eh_do_setor(request.user, *setores)

    return EdicaoDoSetor


class SoSecretaria(BasePermission):
    """Dados de servidores (CPF, matrícula): só a Secretaria vê (LGPD)."""

    message = "Só a Secretaria pode ver esses dados."

    def has_permission(self, request, view):
        usuario = request.user
        if not usuario.is_authenticated:
            return False
        return usuario.is_superuser or usuario.perfil == usuario.Perfil.SECRETARIA
