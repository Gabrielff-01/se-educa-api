from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers

from config.api import ModelSerializerComRegras

from .models import Inscricao


class InscricaoPublicaSerializer(ModelSerializerComRegras):
    """O que a família manda pela tela "Fazer matrícula" (sem login).

    A senha chega aberta, passa pelas regras de senha do settings.py e é guardada criptografada.
    O ano letivo é sempre o atual (quem escolhe não é a família).
    """

    senha = serializers.CharField(write_only=True, min_length=8, max_length=128,
                                  error_messages={"min_length": "A senha precisa ter pelo menos 8 caracteres."})

    class Meta:
        model = Inscricao
        fields = [
            "aluno_nome", "data_nascimento", "sexo", "raca", "cpf", "bolsa_familia", "nis",
            "responsavel_nome", "responsavel_cpf", "responsavel_parentesco", "telefone", "email", "senha",
            "cep", "endereco", "numero", "complemento", "bairro", "cidade", "uf",
            "escola", "serie", "turno_preferido",
        ]

    def validate(self, attrs):
        attrs["ano_letivo"] = timezone.localdate().year
        attrs = super().validate(attrs)  # regras do model (CPF, oferta da escola, e-mail já usado...)
        try:
            validate_password(attrs["senha"])
        except DjangoValidationError as erro:
            raise serializers.ValidationError({"senha": erro.messages})
        attrs["senha"] = make_password(attrs["senha"])
        return attrs


class InscricaoSerializer(serializers.ModelSerializer):
    """O pedido como o DIES vê na análise (nunca devolve a senha)."""

    sexo_nome = serializers.CharField(source="get_sexo_display", read_only=True)
    raca_nome = serializers.CharField(source="get_raca_display", read_only=True)
    parentesco_nome = serializers.CharField(source="get_responsavel_parentesco_display", read_only=True)
    turno_nome = serializers.CharField(source="get_turno_preferido_display", read_only=True)
    status_nome = serializers.CharField(source="get_status_display", read_only=True)
    escola_nome = serializers.CharField(source="escola.nome", read_only=True)
    municipio_escola = serializers.CharField(source="escola.municipio", read_only=True)
    serie_nome = serializers.CharField(source="serie.nome", read_only=True)
    curso_nome = serializers.CharField(source="serie.curso.nome", read_only=True)
    analisada_por_nome = serializers.SerializerMethodField()
    idade = serializers.IntegerField(read_only=True)
    matricula_situacao = serializers.CharField(source="matricula.get_situacao_display", read_only=True, default=None)
    turma_nome = serializers.SerializerMethodField()

    class Meta:
        model = Inscricao
        exclude = ["senha"]

    def get_analisada_por_nome(self, inscricao):
        usuario = inscricao.analisada_por
        return (usuario.get_full_name() or usuario.username) if usuario else None

    def get_turma_nome(self, inscricao):
        turma = inscricao.matricula.turma if inscricao.matricula_id else None
        return f"{turma.serie.nome} {turma.letra}" if turma else None
