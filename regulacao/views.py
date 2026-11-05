from rest_framework import serializers, viewsets

from auditoria.historico import RegistrarAlteracoesMixin
from config.api import FiltrosMixin
from contas.permissoes import edicao_do_setor

from .models import AtoAutorizativo, Matriz, Oferta
from .serializers import AtoAutorizativoSerializer, MatrizSerializer, OfertaSerializer

# Todo mundo logado lê; só o DED cadastra, edita e apaga ofertas e matrizes.
SO_DED_EDITA = [edicao_do_setor("ded")]
# Os atos autorizativos (autorização, reconhecimento...) passaram para o DIES, que cuida das escolas.
SO_DIES_EDITA = [edicao_do_setor("dies")]


class AtoAutorizativoViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    queryset = AtoAutorizativo.objects.select_related("escola", "curso")
    serializer_class = AtoAutorizativoSerializer
    permission_classes = SO_DIES_EDITA
    filtros = {"escola": "escola_id", "tipo": "tipo", "curso": "curso_id"}


class OfertaViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    queryset = Oferta.objects.select_related("escola").prefetch_related("series")
    serializer_class = OfertaSerializer
    permission_classes = SO_DED_EDITA
    filtros = {"escola": "escola_id", "ano_letivo": "ano_letivo"}

    def perform_destroy(self, oferta):
        # Turma não tem FK para Oferta, então o PROTECT não ajuda: bloqueamos aqui (igual ao admin).
        if oferta.turmas().exists():
            raise serializers.ValidationError(
                {"detail": "Essa oferta tem turmas. Apague as turmas antes."}
            )
        super().perform_destroy(oferta)  # apaga e grava no histórico


class MatrizViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    queryset = Matriz.objects.select_related("serie__curso", "escola").prefetch_related("itens__materia")
    serializer_class = MatrizSerializer
    permission_classes = SO_DED_EDITA
    filtros = {"serie": "serie_id", "ano_letivo": "ano_letivo", "jornada": "jornada", "escola": "escola_id"}
