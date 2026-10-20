from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from auditoria.historico import RegistrarAlteracoesMixin, registrar
from config.api import FiltrosMixin
from contas.permissoes import edicao_do_setor

from .models import CalendarioLetivo, Evento
from .serializers import CalendarioLetivoSerializer, EventoSerializer

# Todo mundo logado lê; só o DIES cadastra, edita e apaga.
SO_DIES_EDITA = [edicao_do_setor("dies")]


class CalendarioLetivoViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    queryset = CalendarioLetivo.objects.select_related("escola").prefetch_related("eventos")
    serializer_class = CalendarioLetivoSerializer
    permission_classes = SO_DIES_EDITA
    filtros = {"ano_letivo": "ano_letivo", "escola": "escola_id"}

    @action(detail=True, methods=["post"])
    def adicionar_feriados(self, request, pk=None):
        """POST /api/calendarios/1/adicionar_feriados/ (o mesmo botão do admin)."""
        calendario = self.get_object()
        criados = calendario.adicionar_feriados()
        if criados:
            registrar(request.user, "criou", calendario, tipo="feriados",
                      descricao=f"{criados} feriado(s) no {calendario}")
        calendario = self.get_queryset().get(pk=calendario.pk)  # busca de novo, com os novos
        dados = self.get_serializer(calendario).data
        return Response({"criados": criados, "calendario": dados})


class EventoViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    queryset = Evento.objects.select_related("calendario")
    serializer_class = EventoSerializer
    permission_classes = SO_DIES_EDITA
    filtros = {"calendario": "calendario_id", "tipo": "tipo"}
