from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from config.api import ModelSerializerComRegras, erros_do_django_para_drf

from .models import (
    AtoAutorizativo,
    ItemMatriz,
    Matriz,
    Oferta,
    conferir_lotacoes,
    validar_carga_minima,
)


class AtoAutorizativoSerializer(ModelSerializerComRegras):
    escola_nome = serializers.CharField(source="escola.nome", read_only=True)
    curso_nome = serializers.CharField(source="curso.nome", read_only=True, default=None)
    tipo_nome = serializers.CharField(source="get_tipo_display", read_only=True)
    vigente = serializers.BooleanField(read_only=True)

    class Meta:
        model = AtoAutorizativo
        fields = [
            "id", "escola", "escola_nome", "curso", "curso_nome", "tipo", "tipo_nome",
            "numero", "orgao_emissor", "data_publicacao", "validade", "vigente", "observacao",
        ]


class OfertaSerializer(ModelSerializerComRegras):
    escola_nome = serializers.CharField(source="escola.nome", read_only=True)
    series_nomes = serializers.SerializerMethodField()

    class Meta:
        model = Oferta
        fields = ["id", "escola", "escola_nome", "ano_letivo", "series", "series_nomes"]

    def get_series_nomes(self, oferta):
        return [serie.nome for serie in oferta.series.all()]

    def validate(self, attrs):
        oferta = self.instance
        if oferta is not None:
            # Igual ao admin: escola e ano ficam travados, porque as turmas dependem deles.
            for campo in ("escola", "ano_letivo"):
                if campo in attrs and attrs[campo] != getattr(oferta, campo):
                    raise serializers.ValidationError({campo: "Não dá pra mudar depois de criada."})
            series = attrs.get("series")
            if series is not None:
                sem_serie = oferta.turmas().exclude(serie__in=series).select_related("serie", "escola")
                if sem_serie.exists():
                    nomes = ", ".join(str(turma) for turma in sem_serie)
                    raise serializers.ValidationError({
                        "series": f"Estas turmas ficariam sem a série delas na oferta: {nomes}. "
                                  "Marque a série delas ou apague essas turmas antes."
                    })
        return super().validate(attrs)


class ItemMatrizSerializer(serializers.ModelSerializer):
    materia_nome = serializers.CharField(source="materia.nome", read_only=True)

    class Meta:
        model = ItemMatriz
        fields = ["materia", "materia_nome", "aulas_semanais"]


class MatrizSerializer(ModelSerializerComRegras):
    """Matriz com as matérias dentro. O React manda tudo de uma vez:

    {"serie": 1, "ano_letivo": 2026, "jornada": "parcial", "duracao_aula_minutos": 50,
     "semanas_letivas": 40, "itens": [{"materia": 2, "aulas_semanais": 5}, ...]}
    """

    itens = ItemMatrizSerializer(many=True)
    serie_nome = serializers.CharField(source="serie.nome", read_only=True)
    curso_nome = serializers.CharField(source="serie.curso.nome", read_only=True)
    jornada_nome = serializers.CharField(source="get_jornada_display", read_only=True)
    total_aulas_semanais = serializers.IntegerField(read_only=True)
    carga_horaria_anual = serializers.FloatField(read_only=True)
    carga_minima = serializers.IntegerField(
        source="serie.curso.carga_horaria_minima_anual", read_only=True
    )
    cumpre_minimo = serializers.BooleanField(read_only=True)

    class Meta:
        model = Matriz
        fields = [
            "id", "serie", "serie_nome", "curso_nome", "ano_letivo", "jornada", "jornada_nome",
            "duracao_aula_minutos", "semanas_letivas", "itens", "total_aulas_semanais",
            "carga_horaria_anual", "carga_minima", "cumpre_minimo",
        ]

    def validate(self, attrs):
        matriz = self.instance
        if matriz is not None:
            # Igual ao admin: série, ano e jornada travados, porque as lotações dependem deles.
            for campo in ("serie", "ano_letivo", "jornada"):
                if campo in attrs and attrs[campo] != getattr(matriz, campo):
                    raise serializers.ValidationError({campo: "Não dá pra mudar depois de criada."})

        attrs = super().validate(attrs)  # regras do model (matriz repetida, semanas >= 40...)

        itens = attrs.get("itens")
        if itens is None:
            if matriz is None:
                raise serializers.ValidationError({"itens": "Informe as matérias da matriz."})
            itens = [  # PATCH sem itens: confere com as matérias que já estão salvas
                {"materia": item.materia, "aulas_semanais": item.aulas_semanais}
                for item in matriz.itens.select_related("materia")
            ]

        aulas_por_materia = {}
        for item in itens:
            if item["materia"].pk in aulas_por_materia:
                raise serializers.ValidationError(
                    {"itens": f"{item['materia']} aparece duas vezes. Deixe só uma linha."}
                )
            aulas_por_materia[item["materia"].pk] = item["aulas_semanais"]

        serie = self.valor(attrs, "serie")
        duracao = self.valor(attrs, "duracao_aula_minutos")
        semanas = self.valor(attrs, "semanas_letivas")
        try:
            validar_carga_minima(serie, duracao, semanas, sum(aulas_por_materia.values()))
            if matriz is not None:
                conferir_lotacoes(matriz, aulas_por_materia)
        except DjangoValidationError as erro:
            raise erros_do_django_para_drf(erro)
        return attrs

    def valor(self, attrs, campo):
        """O valor que vai ficar: o que veio agora, o que já estava salvo ou o padrão do model."""
        if campo in attrs:
            return attrs[campo]
        if self.instance is not None:
            return getattr(self.instance, campo)
        return Matriz._meta.get_field(campo).get_default()

    @transaction.atomic  # ou salva a matriz E as matérias, ou não salva nada
    def create(self, validated_data):
        itens = validated_data.pop("itens")
        matriz = Matriz.objects.create(**validated_data)
        ItemMatriz.objects.bulk_create(ItemMatriz(matriz=matriz, **item) for item in itens)
        return matriz

    @transaction.atomic
    def update(self, matriz, validated_data):
        itens = validated_data.pop("itens", None)
        matriz = super().update(matriz, validated_data)
        if itens is not None:  # troca a lista inteira de matérias
            matriz.itens.all().delete()
            ItemMatriz.objects.bulk_create(ItemMatriz(matriz=matriz, **item) for item in itens)
        return matriz
