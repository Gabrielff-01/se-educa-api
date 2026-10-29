from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from academico.acesso import conferir_escola, eh_secretaria

from auditoria.historico import RegistrarAlteracoesMixin, registrar
from config.api import FiltrosMixin
from contas.acessos import CriarAcessoSerializer, criar_login
from contas.models import Usuario
from contas.permissoes import SoSecretaria, edicao_do_setor, eh_do_setor

from .models import Afastamento, Alocacao, Lotacao, Professor
from .serializers import AfastamentoSerializer, AlocacaoSerializer, LotacaoSerializer, ProfessorSerializer

Perfil = Usuario.Perfil

# Dados de servidor (CPF, matrícula): só a Secretaria vê, e só o RH muda.
SO_RH_EDITA = [SoSecretaria, edicao_do_setor("rh")]


class SecretariaOuEscola(BasePermission):
    """Lê: Secretaria e gestão da escola. Muda: quem cada ViewSet disser em "quem_muda"."""

    message = "Seu perfil não pode fazer isso."

    def has_permission(self, request, view):
        usuario = request.user
        if not usuario.is_authenticated:
            return False
        if not (eh_secretaria(usuario) or (usuario.perfil == Perfil.ESCOLA and usuario.escola_id)):
            return False
        if request.method in SAFE_METHODS:
            return True
        return view.pode_mudar(usuario)


def ano_atual():
    return timezone.localdate().year


class ProfessorViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    queryset = Professor.objects.select_related("usuario")
    serializer_class = ProfessorSerializer
    permission_classes = SO_RH_EDITA
    filtros = {"vinculo": "vinculo", "carga": "carga_horaria_semanal"}

    @action(detail=True, methods=["post"])
    def criar_acesso(self, request, pk=None):
        """POST /api/professores/1/criar_acesso/ {"username": "...", "senha": "..."}"""
        professor = self.get_object()
        dados = CriarAcessoSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        usuario = criar_login(professor, Usuario.Perfil.PROFESSOR, dados.validated_data)
        registrar(request.user, "criou", usuario, tipo="login", descricao=f"Login {usuario.username} de {professor.nome}")
        return Response(self.get_serializer(professor).data)


class AlocacaoViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    """Em qual escola cada professor trabalha.

    GET    /api/alocacoes/?escola=ID      Secretaria vê todas; a escola, só as dela
    POST   /api/alocacoes/                RH aloca: {"professor", "escola", "horas_semanais", "portaria"}
    PATCH  /api/alocacoes/ID/             RH muda horas ou portaria
    DELETE /api/alocacoes/ID/             RH tira o professor da escola (se ele não tiver mais turmas lá)
    POST   /api/alocacoes/ID/funcao/      a escola define a função: {"funcao": "diretor", "portaria_funcao": "..."}
    """

    serializer_class = AlocacaoSerializer
    permission_classes = [SecretariaOuEscola]
    filtros = {"professor": "professor_id", "escola": "escola_id", "funcao": "funcao"}

    def pode_mudar(self, usuario):
        if self.action == "funcao":
            return True  # a regra fina (só a escola dele) fica na própria ação
        return eh_do_setor(usuario, "rh")

    def get_queryset(self):
        alocacoes = Alocacao.objects.select_related("professor", "escola")
        usuario = self.request.user
        if not eh_secretaria(usuario):
            alocacoes = alocacoes.filter(escola_id=usuario.escola_id)
        return self.aplicar_filtros(alocacoes)

    def perform_destroy(self, alocacao):
        turmas = Lotacao.objects.filter(
            professor_id=alocacao.professor_id, turma__escola_id=alocacao.escola_id,
            turma__ano_letivo__gte=ano_atual(),
        ).count()
        if turmas:
            raise serializers.ValidationError({"detail": (
                f"{alocacao.professor.nome} ainda tem {turmas} turma(s) na {alocacao.escola}. "
                "A escola precisa tirar as aulas dele antes."
            )})
        super().perform_destroy(alocacao)

    @action(detail=True, methods=["post"])
    def funcao(self, request, pk=None):
        alocacao = self.get_object()
        usuario = request.user
        if not (usuario.is_superuser or (usuario.perfil == Perfil.ESCOLA and usuario.escola_id == alocacao.escola_id)):
            raise PermissionDenied("Quem define a função é a escola onde o professor está.")
        funcao = request.data.get("funcao")
        if funcao not in Alocacao.Funcao.values:
            raise serializers.ValidationError({"funcao": "Escolha uma função da lista."})
        portaria = (request.data.get("portaria_funcao") or "").strip()[:30]
        if funcao != Alocacao.Funcao.PROFESSOR:
            aulas = alocacao.aulas_no_ano(ano_atual())
            if aulas:
                raise serializers.ValidationError({"funcao": (
                    f"{alocacao.professor.nome} tem {aulas} aulas por semana nas turmas daqui. "
                    "Tire as turmas dele antes de mudar a função."
                )})
        antes = alocacao.get_funcao_display()
        alocacao.funcao = funcao
        alocacao.portaria_funcao = portaria if funcao != Alocacao.Funcao.PROFESSOR else ""
        alocacao.save(update_fields=["funcao", "portaria_funcao"])
        if antes != alocacao.get_funcao_display():
            registrar(usuario, "editou", alocacao,
                      mudancas=[{"campo": "função", "antes": antes, "depois": alocacao.get_funcao_display()}])
        return Response(self.get_serializer(alocacao).data)


class LotacaoViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    """Turmas e aulas de cada professor. Quem cadastra é a escola (só na escola dela).

    O RH e o resto da Secretaria só leem (o RH vê as carências em /api/rh/carencias/).
    """

    serializer_class = LotacaoSerializer
    permission_classes = [SecretariaOuEscola]
    filtros = {
        "professor": "professor_id",
        "turma": "turma_id",
        "escola": "turma__escola_id",
        "ano_letivo": "turma__ano_letivo",
    }

    def pode_mudar(self, usuario):
        return usuario.is_superuser or usuario.perfil == Perfil.ESCOLA

    def get_queryset(self):
        lotacoes = Lotacao.objects.select_related("professor", "materia", "turma__escola", "turma__serie")
        usuario = self.request.user
        if not eh_secretaria(usuario):
            lotacoes = lotacoes.filter(turma__escola_id=usuario.escola_id)
        return self.aplicar_filtros(lotacoes)

    def perform_create(self, serializer):
        conferir_escola(self.request.user, serializer.validated_data["turma"].escola_id)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        turma = serializer.validated_data.get("turma")
        if turma is not None:
            conferir_escola(self.request.user, turma.escola_id)
        super().perform_update(serializer)
    # Apagar a lotação também tira as aulas dela do quadro de horários (on_delete=CASCADE no Horario).


class AfastamentoViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    queryset = Afastamento.objects.select_related("professor")
    serializer_class = AfastamentoSerializer
    permission_classes = SO_RH_EDITA
    filtros = {"professor": "professor_id", "tipo": "tipo"}

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("vigentes"):  # ?vigentes=1: só quem está afastado hoje
            hoje = timezone.localdate()
            queryset = queryset.filter(inicio__lte=hoje, fim__gte=hoje)
        return queryset
