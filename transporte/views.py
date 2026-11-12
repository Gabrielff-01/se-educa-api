"""API do transporte escolar. Quem cadastra as rotas é a escola.

GET    /api/rotas/                 escola: as dela (com a lista de alunos); Secretaria: todas;
                                   aluno e responsável: as rotas que os seus alunos usam
POST   /api/rotas/                 escola cadastra {nome, turno, veiculo, placa, motorista, telefone, capacidade,
                                   ativa, observacao, paradas: [{local, referencia, horario}]} (paradas em ordem)
PATCH  /api/rotas/ID/              escola edita (paradas com "id" são as que já existiam)
DELETE /api/rotas/ID/              escola apaga (só sem aluno na rota)
POST   /api/rotas/ID/vincular/     escola põe o aluno na rota {aluno, parada} (se ele estava em outra, muda)
POST   /api/rotas/ID/desvincular/  escola tira o aluno {aluno}
GET    /api/rotas/minha/?aluno=ID  aluno e responsável: a rota do aluno e a parada dele (ou rota null)
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from academico.acesso import aluno_pedido, alunos_visiveis, eh_secretaria
from academico.models import Aluno
from auditoria.historico import registrar
from config.api import FiltrosMixin, erros_do_django_para_drf
from contas.models import Usuario

from .models import AlunoNaRota, Rota
from .serializers import RotaSerializer

Perfil = Usuario.Perfil


def rotas_visiveis(usuario):
    rotas = Rota.objects.all()
    if eh_secretaria(usuario):
        return rotas
    if usuario.perfil == Perfil.ESCOLA:
        return rotas.filter(escola_id=usuario.escola_id)
    if usuario.perfil in (Perfil.ALUNO, Perfil.RESPONSAVEL):
        return rotas.filter(alunos__aluno__in=alunos_visiveis(usuario)).distinct()
    return rotas.none()


class RotaViewSet(FiltrosMixin, viewsets.ModelViewSet):
    serializer_class = RotaSerializer
    filtros = {"escola": "escola_id", "turno": "turno", "ativa": "ativa"}

    def get_queryset(self):
        rotas = rotas_visiveis(self.request.user).select_related("escola", "cadastrada_por").prefetch_related("paradas")
        return self.aplicar_filtros(rotas)

    def get_serializer_context(self):
        contexto = super().get_serializer_context()
        usuario = self.request.user
        if usuario.is_authenticated:
            contexto["escola"] = usuario.escola if usuario.perfil == Perfil.ESCOLA else None
            contexto["ve_alunos"] = usuario.perfil == Perfil.ESCOLA or eh_secretaria(usuario)
        return contexto

    def so_a_escola(self, rota=None):
        usuario = self.request.user
        if usuario.perfil != Perfil.ESCOLA or not usuario.escola_id:
            raise PermissionDenied("Quem cadastra as rotas é a escola.")
        if rota is not None and rota.escola_id != usuario.escola_id:
            raise PermissionDenied("Essa rota é de outra escola.")

    def create(self, request, *args, **kwargs):
        self.so_a_escola()
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        rota = serializer.save(cadastrada_por=self.request.user)
        registrar(self.request.user, "criou", rota, descricao=f"Cadastrou a rota {rota.nome}")

    def perform_update(self, serializer):
        self.so_a_escola(serializer.instance)
        rota = serializer.save(cadastrada_por=self.request.user)
        registrar(self.request.user, "alterou", rota, descricao=f"Alterou a rota {rota.nome}")

    def perform_destroy(self, rota):
        self.so_a_escola(rota)
        if rota.alunos.exists():
            raise serializers.ValidationError({"detail": "Ainda tem aluno nesta rota. Tire os alunos antes de apagar."})
        registrar(self.request.user, "apagou", rota, descricao=f"Apagou a rota {rota.nome}")
        rota.delete()

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def vincular(self, request, pk=None):
        rota = self.get_object()
        self.so_a_escola(rota)
        aluno = Aluno.objects.filter(pk=request.data.get("aluno")).first()
        parada = rota.paradas.filter(pk=request.data.get("parada")).first()
        if aluno is None:
            raise serializers.ValidationError({"aluno": "Escolha o aluno."})
        if parada is None:
            raise serializers.ValidationError({"parada": "Escolha a parada onde o aluno embarca."})
        linha = AlunoNaRota.objects.filter(aluno=aluno).first() or AlunoNaRota(aluno=aluno)
        if linha.pk and linha.rota.escola_id != rota.escola_id:
            raise serializers.ValidationError({"aluno": f"{aluno.nome} está numa rota de outra escola."})
        linha.rota, linha.parada = rota, parada
        try:
            linha.full_clean()
        except DjangoValidationError as erro:
            raise erros_do_django_para_drf(erro)
        linha.save()
        registrar(request.user, "alterou", rota, descricao=f"{aluno.nome} na rota {rota.nome} ({parada.local})")
        return Response(self.get_serializer(rota).data)

    @action(detail=True, methods=["post"])
    def desvincular(self, request, pk=None):
        rota = self.get_object()
        self.so_a_escola(rota)
        linha = rota.alunos.filter(aluno_id=request.data.get("aluno")).select_related("aluno").first()
        if linha is None:
            raise serializers.ValidationError({"aluno": "Esse aluno não está nesta rota."})
        registrar(request.user, "alterou", rota, descricao=f"Tirou {linha.aluno.nome} da rota {rota.nome}")
        linha.delete()
        return Response(self.get_serializer(rota).data)

    @action(detail=False, methods=["get"])
    def minha(self, request):
        aluno = aluno_pedido(request)
        linha = AlunoNaRota.objects.filter(aluno=aluno).select_related("rota__escola", "parada").first()
        matricula = aluno.matricula_atual()
        return Response({
            "aluno": {"id": aluno.pk, "nome": aluno.nome},
            "escola_nome": matricula.escola.nome if matricula else None,
            "rota": self.get_serializer(linha.rota).data if linha else None,
            "parada": linha.parada_id if linha else None,
        })
