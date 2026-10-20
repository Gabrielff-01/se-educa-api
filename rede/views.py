from django.db.models import Count, Q
from rest_framework import viewsets

from auditoria.historico import RegistrarAlteracoesMixin
from config.api import FiltrosMixin
from contas.permissoes import edicao_do_setor

from .models import Curso, Escola, Materia, Regional, Serie, Turma
from .serializers import (
    CursoSerializer,
    EscolaSerializer,
    MateriaSerializer,
    RegionalSerializer,
    SerieSerializer,
    TurmaSerializer,
)

# Todo mundo logado lê; só o DIES cadastra, edita e apaga.
SO_DIES_EDITA = [edicao_do_setor("dies")]


class RegionalViewSet(RegistrarAlteracoesMixin, viewsets.ModelViewSet):
    queryset = Regional.objects.all()
    serializer_class = RegionalSerializer
    permission_classes = SO_DIES_EDITA


class EscolaViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    queryset = Escola.objects.select_related("regional")
    serializer_class = EscolaSerializer
    permission_classes = SO_DIES_EDITA
    filtros = {"regional": "regional_id", "municipio": "municipio__iexact"}


class CursoViewSet(RegistrarAlteracoesMixin, viewsets.ModelViewSet):
    queryset = Curso.objects.prefetch_related("series__curso")
    serializer_class = CursoSerializer
    permission_classes = SO_DIES_EDITA


class SerieViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    queryset = Serie.objects.select_related("curso")
    serializer_class = SerieSerializer
    permission_classes = SO_DIES_EDITA
    filtros = {"curso": "curso_id"}


class MateriaViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    queryset = Materia.objects.all()
    serializer_class = MateriaSerializer
    permission_classes = SO_DIES_EDITA
    filtros = {"area": "area"}


class TurmaViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    # "alunos" = quantos alunos com matrícula confirmada estão na turma.
    queryset = Turma.objects.select_related("escola", "serie__curso").annotate(
        alunos=Count("matriculas", filter=Q(matriculas__situacao="confirmada"))
    )
    serializer_class = TurmaSerializer
    permission_classes = SO_DIES_EDITA
    filtros = {
        "escola": "escola_id",
        "serie": "serie_id",
        "ano_letivo": "ano_letivo",
        "turno": "turno",
    }
