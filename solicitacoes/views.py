"""API dos pedidos escola → DIES.

GET  /api/solicitacoes/                lista (escola: só os dela; DIES: de todas). Filtros ?status= ?tipo= ?escola=
POST /api/solicitacoes/                a escola abre um pedido (com a primeira mensagem)
GET  /api/solicitacoes/ID/             o pedido com a conversa
POST /api/solicitacoes/ID/mensagens/   {"texto": "..."} escola ou DIES respondem
POST /api/solicitacoes/ID/atender/     DIES: cria a turma / muda a capacidade e fecha o pedido
POST /api/solicitacoes/ID/recusar/     DIES: fecha o pedido explicando o motivo
"""

from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from auditoria.historico import registrar
from config.api import FiltrosMixin
from contas.models import Usuario
from contas.permissoes import eh_do_setor
from rede.models import Turma

from .models import Mensagem, Solicitacao
from .serializers import SolicitacaoSerializer


def eh_dies(usuario):
    return eh_do_setor(usuario, "dies")


class EscolaOuDies(BasePermission):
    message = "Só a gestão da escola e a DIES usam os pedidos."

    def has_permission(self, request, view):
        usuario = request.user
        if not usuario.is_authenticated:
            return False
        return eh_dies(usuario) or (usuario.perfil == Usuario.Perfil.ESCOLA and usuario.escola_id is not None)


class SolicitacaoViewSet(FiltrosMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                         mixins.CreateModelMixin, viewsets.GenericViewSet):
    serializer_class = SolicitacaoSerializer
    permission_classes = [EscolaOuDies]
    filtros = {"status": "status", "tipo": "tipo", "escola": "escola"}

    def get_queryset(self):
        pedidos = Solicitacao.objects.select_related("escola", "serie", "turma__serie", "criada_por")
        pedidos = pedidos.prefetch_related("mensagens__autor")
        if not eh_dies(self.request.user):
            pedidos = pedidos.filter(escola_id=self.request.user.escola_id)
        return self.aplicar_filtros(pedidos)

    def create(self, request, *args, **kwargs):
        if eh_dies(request.user):
            raise PermissionDenied("Quem abre o pedido é a escola. A DIES responde e atende.")
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        with transaction.atomic():
            texto = serializer.validated_data.pop("mensagem")
            pedido = serializer.save(criada_por=self.request.user)
            Mensagem.objects.create(solicitacao=pedido, autor=self.request.user, texto=texto)
        registrar(self.request.user, "criou", pedido)

    def responder(self, pedido):
        """Devolve o pedido atualizado (com a conversa nova)."""
        return Response(self.get_serializer(self.get_queryset().get(pk=pedido.pk)).data)

    def falar(self, pedido, autor, texto):
        Mensagem.objects.create(solicitacao=pedido, autor=autor, texto=texto)
        pedido.atualizada_em = timezone.now()
        pedido.save()  # guarda também a situação e a turma, quando mudaram

    @action(detail=True, methods=["post"])
    def mensagens(self, request, pk=None):
        pedido = self.get_object()
        texto = (request.data.get("texto") or "").strip()
        if not texto:
            raise serializers.ValidationError({"texto": "Escreva a mensagem."})
        if len(texto) > 1000:
            raise serializers.ValidationError({"texto": "Use no máximo 1000 caracteres."})
        self.falar(pedido, request.user, texto)
        return self.responder(pedido)

    def so_dies_e_aberto(self, pedido):
        if not eh_dies(self.request.user):
            raise PermissionDenied("Só a DIES atende ou recusa pedidos.")
        if pedido.status != Solicitacao.Status.ABERTA:
            raise serializers.ValidationError({"detail": f"Esse pedido já está {pedido.get_status_display().lower()}."})

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def atender(self, request, pk=None):
        """Faz o que a escola pediu. Turma nova: {"letra": "C"} (opcional, senão usa a próxima letra)."""
        pedido = self.get_object()
        self.so_dies_e_aberto(pedido)
        if pedido.tipo == Solicitacao.Tipo.NOVA_TURMA:
            aviso = self.criar_turma(pedido, (request.data.get("letra") or "").strip())
        elif pedido.tipo == Solicitacao.Tipo.CAPACIDADE:
            aviso = self.mudar_capacidade(pedido)
        else:
            aviso = "Pedido atendido."
        pedido.status = Solicitacao.Status.ATENDIDA
        resposta = (request.data.get("resposta") or "").strip()
        if resposta:
            self.falar(pedido, request.user, resposta)
        self.falar(pedido, None, aviso)
        registrar(request.user, "editou", pedido, descricao=f"Atendeu: {pedido.titulo} ({pedido.escola})")
        return self.responder(pedido)

    def criar_turma(self, pedido, letra):
        ano = timezone.localdate().year
        if not letra:  # próxima letra livre: A, B, C...
            usadas = set(Turma.objects.filter(escola=pedido.escola, serie=pedido.serie, ano_letivo=ano)
                         .values_list("letra", flat=True))
            letra = next(l for l in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if l not in usadas)
        turma = Turma(escola=pedido.escola, serie=pedido.serie, ano_letivo=ano, turno=pedido.turno,
                      letra=letra, capacidade=pedido.capacidade)
        turma.full_clean()  # mesmas regras da tela de turmas (série ofertada, letra repetida...)
        turma.save()
        pedido.turma = turma
        registrar(self.request.user, "criou", turma)
        return f"Pedido atendido: turma {turma.serie.nome} {turma.letra} criada com {turma.capacidade} vagas."

    def mudar_capacidade(self, pedido):
        turma = pedido.turma
        ocupadas = turma.matriculas.filter(situacao="confirmada").count()
        if pedido.capacidade < ocupadas:
            raise serializers.ValidationError(
                {"detail": f"A turma já tem {ocupadas} alunos; a capacidade não pode ficar em {pedido.capacidade}."})
        antes = turma.capacidade
        turma.capacidade = pedido.capacidade
        turma.full_clean()
        turma.save()
        registrar(self.request.user, "editou", turma,
                  mudancas=[{"campo": "capacidade", "antes": str(antes), "depois": str(turma.capacidade)}])
        return f"Pedido atendido: a {turma.serie.nome} {turma.letra} passou de {antes} para {turma.capacidade} vagas."

    @action(detail=True, methods=["post"])
    def recusar(self, request, pk=None):
        pedido = self.get_object()
        self.so_dies_e_aberto(pedido)
        motivo = (request.data.get("resposta") or "").strip()
        if not motivo:
            raise serializers.ValidationError({"resposta": "Explique para a escola por que o pedido foi recusado."})
        pedido.status = Solicitacao.Status.RECUSADA
        self.falar(pedido, request.user, motivo)
        self.falar(pedido, None, "Pedido recusado pela DIES.")
        registrar(request.user, "editou", pedido, descricao=f"Recusou: {pedido.titulo} ({pedido.escola})")
        return self.responder(pedido)
