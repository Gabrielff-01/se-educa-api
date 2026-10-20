from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from auditoria.historico import RegistrarAlteracoesMixin, registrar
from config.api import FiltrosMixin
from contas.acessos import CriarAcessoSerializer, criar_login
from contas.models import Usuario
from contas.permissoes import SoSecretaria, edicao_do_setor

from .models import Afastamento, Lotacao, Professor
from .serializers import AfastamentoSerializer, LotacaoSerializer, ProfessorSerializer

# Dados de servidor (CPF, matrícula): só a Secretaria vê, e só o RH muda.
SO_RH_EDITA = [SoSecretaria, edicao_do_setor("rh")]


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


class LotacaoViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    queryset = Lotacao.objects.select_related(
        "professor", "materia", "turma__escola", "turma__serie"
    )
    serializer_class = LotacaoSerializer
    permission_classes = SO_RH_EDITA
    filtros = {
        "professor": "professor_id",
        "turma": "turma_id",
        "escola": "turma__escola_id",
        "ano_letivo": "turma__ano_letivo",
    }


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
