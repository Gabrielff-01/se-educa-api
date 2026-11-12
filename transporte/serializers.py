from django.db import transaction
from django.db.models import ProtectedError
from rest_framework import serializers

from config.api import ModelSerializerComRegras

from .models import Parada, Rota


class ParadaSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)  # com id = parada que já existe (editar); sem id = nova

    class Meta:
        model = Parada
        fields = ["id", "ordem", "local", "referencia", "horario"]
        read_only_fields = ["ordem"]


class RotaSerializer(ModelSerializerComRegras):
    escola_nome = serializers.CharField(source="escola.nome", read_only=True)
    turno_nome = serializers.CharField(source="get_turno_display", read_only=True)
    veiculo_nome = serializers.CharField(source="get_veiculo_display", read_only=True)
    cadastrada_por_nome = serializers.SerializerMethodField()
    paradas = ParadaSerializer(many=True)
    ocupados = serializers.SerializerMethodField()
    alunos = serializers.SerializerMethodField()

    class Meta:
        model = Rota
        fields = ["id", "escola", "escola_nome", "nome", "turno", "turno_nome", "veiculo", "veiculo_nome", "placa",
                  "motorista", "telefone", "capacidade", "ativa", "observacao", "paradas", "ocupados", "alunos",
                  "cadastrada_por_nome", "atualizada_em"]
        read_only_fields = ["escola", "atualizada_em"]

    def get_cadastrada_por_nome(self, rota):
        usuario = rota.cadastrada_por
        return (usuario.get_full_name() or usuario.username) if usuario else None

    def get_ocupados(self, rota):
        return rota.alunos.count()

    def get_alunos(self, rota):
        """Só a escola (e a Secretaria) vê a lista de quem usa a rota."""
        if not self.context.get("ve_alunos"):
            return []
        linhas = rota.alunos.select_related("aluno", "parada")
        resultado = []
        for linha in linhas:
            matricula = linha.aluno.matricula_atual()
            resultado.append({
                "id": linha.pk, "aluno": linha.aluno_id, "aluno_nome": linha.aluno.nome,
                "turma_nome": matricula.turma and f"{matricula.turma.serie.nome} {matricula.turma.letra}" if matricula else None,
                "parada": linha.parada_id, "parada_local": linha.parada.local,
                "parada_horario": linha.parada.horario.strftime("%H:%M"),
            })
        return resultado

    def validate_paradas(self, paradas):
        if not paradas:
            raise serializers.ValidationError("Cadastre pelo menos uma parada.")
        horarios = [p["horario"] for p in paradas]
        if horarios != sorted(horarios):
            raise serializers.ValidationError("Os horários das paradas têm que ir em ordem (a 1ª parada é a mais cedo).")
        return paradas

    def validate(self, attrs):
        if self.instance is None:
            attrs["escola"] = self.context.get("escola")
        return super().validate(attrs)

    @transaction.atomic
    def create(self, validated_data):
        paradas = validated_data.pop("paradas")
        rota = Rota.objects.create(**validated_data)
        self.salvar_paradas(rota, paradas)
        return rota

    @transaction.atomic
    def update(self, rota, validated_data):
        paradas = validated_data.pop("paradas", None)
        rota = super().update(rota, validated_data)
        if paradas is not None:
            self.salvar_paradas(rota, paradas)
        return rota

    def salvar_paradas(self, rota, paradas):
        """Grava as paradas na ordem da lista: as com id são editadas, as sem id são criadas
        e as que sumiram da lista são apagadas (se nenhum aluno embarca nelas)."""
        existentes = {parada.pk: parada for parada in rota.paradas.all()}
        manter = []
        for ordem, dados in enumerate(paradas, start=1):
            parada = existentes.get(dados.pop("id", None)) or Parada(rota=rota)
            for campo, valor in dados.items():
                setattr(parada, campo, valor)
            parada.ordem = ordem
            parada.save()
            manter.append(parada.pk)
        for parada in rota.paradas.exclude(pk__in=manter):
            try:
                parada.delete()
            except ProtectedError:
                raise serializers.ValidationError({"paradas": f"Tem aluno embarcando em \"{parada.local}\". "
                                                              "Troque a parada desses alunos antes de tirar ela."})
