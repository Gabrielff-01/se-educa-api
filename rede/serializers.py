from rest_framework import serializers

from config.api import ModelSerializerComRegras

from .models import Curso, Escola, Materia, Regional, Serie, Turma


class RegionalSerializer(ModelSerializerComRegras):
    class Meta:
        model = Regional
        fields = ["id", "nome"]


class EscolaSerializer(ModelSerializerComRegras):
    regional_nome = serializers.CharField(source="regional.nome", read_only=True)
    dependencia_nome = serializers.CharField(source="get_dependencia_display", read_only=True)

    class Meta:
        model = Escola
        fields = [
            "id", "nome", "codigo_inep", "dependencia", "dependencia_nome",
            "regional", "regional_nome", "municipio", "bairro", "endereco",
            "latitude", "longitude", "ativa",
        ]


class SerieSerializer(ModelSerializerComRegras):
    curso_nome = serializers.CharField(source="curso.nome", read_only=True)

    class Meta:
        model = Serie
        fields = ["id", "curso", "curso_nome", "nome", "ordem"]


class CursoSerializer(ModelSerializerComRegras):
    series = SerieSerializer(many=True, read_only=True)

    class Meta:
        model = Curso
        fields = ["id", "nome", "ordem", "carga_horaria_minima_anual", "series"]


class MateriaSerializer(ModelSerializerComRegras):
    area_nome = serializers.CharField(source="get_area_display", read_only=True)

    class Meta:
        model = Materia
        fields = ["id", "nome", "area", "area_nome"]


class TurmaSerializer(ModelSerializerComRegras):
    escola_nome = serializers.CharField(source="escola.nome", read_only=True)
    serie_nome = serializers.CharField(source="serie.nome", read_only=True)
    curso_nome = serializers.CharField(source="serie.curso.nome", read_only=True)
    turno_nome = serializers.CharField(source="get_turno_display", read_only=True)
    nome = serializers.SerializerMethodField()
    alunos = serializers.IntegerField(read_only=True, default=0)  # vem do annotate na view

    class Meta:
        model = Turma
        fields = [
            "id", "nome", "escola", "escola_nome", "serie", "serie_nome", "curso_nome",
            "ano_letivo", "turno", "turno_nome", "letra", "sala", "capacidade", "alunos",
        ]

    def get_nome(self, turma):
        return f"{turma.serie.nome} {turma.letra}"  # Ex.: "1ª série A"
