from rest_framework import serializers

from config.api import ModelSerializerComRegras

from .models import DIAS_LETIVOS_MINIMOS, CalendarioLetivo, Evento


class EventoSerializer(ModelSerializerComRegras):
    tipo_nome = serializers.CharField(source="get_tipo_display", read_only=True)
    ultimo_dia = serializers.DateField(read_only=True)
    letivo = serializers.SerializerMethodField()

    class Meta:
        model = Evento
        fields = [
            "id", "calendario", "tipo", "tipo_nome", "descricao",
            "data_inicio", "data_fim", "ultimo_dia", "letivo",
        ]

    def get_letivo(self, evento):
        """False para feriado, férias, recesso e planejamento (dias que saem da conta)."""
        return evento.tipo not in Evento.TIPOS_NAO_LETIVOS


class CalendarioLetivoSerializer(ModelSerializerComRegras):
    escola_nome = serializers.CharField(source="escola.nome", read_only=True, default=None)
    abrangencia = serializers.CharField(read_only=True)
    dias_letivos = serializers.IntegerField(read_only=True)
    dias_letivos_minimos = serializers.SerializerMethodField()
    cumpre_minimo = serializers.BooleanField(read_only=True)
    eventos = EventoSerializer(many=True, read_only=True)

    class Meta:
        model = CalendarioLetivo
        fields = [
            "id", "ano_letivo", "escola", "escola_nome", "abrangencia",
            "data_inicio", "data_fim", "dias_letivos", "dias_letivos_minimos",
            "cumpre_minimo", "eventos",
        ]

    def get_dias_letivos_minimos(self, calendario):
        return DIAS_LETIVOS_MINIMOS
