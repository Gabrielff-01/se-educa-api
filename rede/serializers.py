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
    zona_nome = serializers.CharField(source="get_zona_display", read_only=True)
    cnpj_formatado = serializers.CharField(read_only=True)
    cep_formatado = serializers.CharField(read_only=True)

    class Meta:
        model = Escola
        fields = [
            "id", "nome", "codigo_inep", "cnpj", "cnpj_formatado", "dependencia", "dependencia_nome",
            "regional", "regional_nome", "telefone", "email", "numero_salas", "zona", "zona_nome", "comodato",
            "endereco", "numero", "complemento", "bairro", "municipio", "cep", "cep_formatado",
            "latitude", "longitude", "ativa",
        ]
        # O DRF tem mensagem própria para mínimo/máximo; aqui fica a explicação de Sergipe.
        extra_kwargs = {
            "latitude": {"error_messages": {
                "min_value": "Latitude fora de Sergipe (vai de -11,7 a -9,4). Confira se não trocou com a longitude.",
                "max_value": "Latitude fora de Sergipe (vai de -11,7 a -9,4). Confira se não trocou com a longitude.",
            }},
            "longitude": {"error_messages": {
                "min_value": "Longitude fora de Sergipe (vai de -38,3 a -36,3). Confira se não trocou com a latitude.",
                "max_value": "Longitude fora de Sergipe (vai de -38,3 a -36,3). Confira se não trocou com a latitude.",
            }},
        }


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
