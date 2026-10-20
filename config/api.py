"""Peças da API que todos os apps usam."""

import copy

from django.core.exceptions import NON_FIELD_ERRORS
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import ProtectedError, RestrictedError
from rest_framework import serializers
from rest_framework.settings import api_settings
from rest_framework.views import exception_handler


def erros_do_django_para_drf(erro):
    """Converte o ValidationError do Django (models) no formato que a API devolve."""
    if hasattr(erro, "message_dict"):
        erros = {}
        for campo, mensagens in erro.message_dict.items():
            if campo == NON_FIELD_ERRORS:
                campo = api_settings.NON_FIELD_ERRORS_KEY
            erros[campo] = mensagens
        return serializers.ValidationError(erros)
    return serializers.ValidationError({api_settings.NON_FIELD_ERRORS_KEY: erro.messages})


class ModelSerializerComRegras(serializers.ModelSerializer):
    """ModelSerializer que confere as MESMAS regras do admin.

    O DRF não chama o clean() do model. Sem isso, a API deixaria passar o que o
    admin bloqueia (turma de série não ofertada, professor acima de 2/3...).
    Aqui a gente monta o objeto com os dados recebidos e roda o full_clean(),
    que chama clean(), os validators dos campos e as UniqueConstraint.
    """

    def get_validators(self):
        # Os "já existe" das UniqueConstraint ficam com o full_clean() (mensagens do model).
        return []

    def validate(self, attrs):
        attrs = super().validate(attrs)
        model = self.Meta.model
        # Só os campos "de verdade" da tabela. Ficam de fora os muitos-para-muitos
        # (ex.: séries da oferta) e as listas aninhadas (ex.: itens da matriz).
        campos_da_tabela = {campo.name for campo in model._meta.concrete_fields}
        simples = {campo: valor for campo, valor in attrs.items() if campo in campos_da_tabela}
        fora = [campo.name for campo in model._meta.get_fields() if campo.name not in campos_da_tabela]

        if self.instance is not None:
            objeto = copy.copy(self.instance)  # cópia: se der erro, o original fica intacto
            for campo, valor in simples.items():
                setattr(objeto, campo, valor)
        else:
            objeto = model(**simples)

        try:
            objeto.full_clean(exclude=fora)
        except DjangoValidationError as erro:
            raise erros_do_django_para_drf(erro)

        # O clean() pode ajustar valores (letra "a" vira "A", CPF sem pontos...).
        for campo in simples:
            attrs[campo] = getattr(objeto, campo)
        return attrs


class FiltrosMixin:
    """Filtros simples pela URL. Ex.: /api/turmas/?escola=1&ano_letivo=2026

    Cada ViewSet diz quais filtros aceita em "filtros": {"nome na URL": "campo do banco"}.
    """

    filtros = {}

    def get_queryset(self):
        return self.aplicar_filtros(super().get_queryset())

    def aplicar_filtros(self, queryset):
        """Também dá pra chamar direto, quando o ViewSet monta o próprio get_queryset()."""
        for parametro, campo in self.filtros.items():
            valor = self.request.query_params.get(parametro)
            if valor not in (None, ""):
                queryset = queryset.filter(**{campo: valor})
        return queryset


def tratar_erros(exc, context):
    """Transforma erros do Django em respostas 400 com mensagem, em vez de erro 500."""
    if isinstance(exc, (ProtectedError, RestrictedError)):
        if isinstance(exc, ProtectedError):
            objetos = exc.protected_objects
        else:
            objetos = exc.restricted_objects
        ligados = sorted({str(objeto) for objeto in objetos})
        lista = ", ".join(ligados[:5]) + (" ..." if len(ligados) > 5 else "")
        exc = serializers.ValidationError(
            {"detail": f"Não dá pra apagar: ainda tem cadastro ligado a ele ({lista})."}
        )
    elif isinstance(exc, DjangoValidationError):
        exc = erros_do_django_para_drf(exc)
    return exception_handler(exc, context)
