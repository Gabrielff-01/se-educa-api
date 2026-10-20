"""Grava o histórico de alterações ("ponto a ponto": quem mudou o quê e quando).

Todo ViewSet da API usa o RegistrarAlteracoesMixin. Ações especiais (lançar as notas
da turma inteira, fazer a chamada) chamam registrar() direto, com um resumo.
"""

import datetime
from decimal import Decimal

from django.db import models

from .models import Registro

# Campos que mudam sozinhos e só iam poluir o histórico.
IGNORAR = {"id", "atualizada_em", "criado_em", "criada_em", "fechado_em", "password", "last_login"}


def texto(valor):
    """Valor do banco em texto do jeito brasileiro (7.50 -> "7,5"; data -> 20/10/2026)."""
    if valor is None or valor == "":
        return "—"
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    if isinstance(valor, Decimal):
        return f"{valor.normalize():f}".replace(".", ",")
    if isinstance(valor, datetime.datetime):
        return f"{valor:%d/%m/%Y %H:%M}"
    if isinstance(valor, datetime.date):
        return f"{valor:%d/%m/%Y}"
    if isinstance(valor, datetime.time):
        return f"{valor:%H:%M}"
    return str(valor)


def foto(objeto):
    """{nome do campo: valor em texto} de todos os campos do objeto."""
    campos = {}
    for campo in objeto._meta.concrete_fields:
        if campo.name in IGNORAR:
            continue
        if isinstance(campo, models.ForeignKey):
            valor = getattr(objeto, campo.name, None)  # o objeto ligado (ex.: a turma)
        elif campo.choices:
            valor = getattr(objeto, f"get_{campo.name}_display")()
        else:
            valor = getattr(objeto, campo.attname)
        campos[str(campo.verbose_name)] = texto(valor)
    return campos


def comparar(antes, depois):
    return [
        {"campo": campo, "antes": antes.get(campo, "—"), "depois": valor}
        for campo, valor in depois.items()
        if antes.get(campo) != valor
    ]


def registrar(usuario, acao, objeto=None, *, tipo=None, descricao=None, mudancas=None):
    """Grava uma linha no histórico. Dá pra passar o objeto ou o tipo e a descrição."""
    Registro.objects.create(
        usuario=usuario if usuario and usuario.is_authenticated else None,
        acao=acao,
        tipo=tipo or str(objeto._meta.verbose_name),
        objeto_id=str(objeto.pk) if objeto is not None and objeto.pk else "",
        descricao=(descricao or str(objeto))[:200],
        mudancas=mudancas or [],
    )


class RegistrarAlteracoesMixin:
    """Coloque no ViewSet: cada criar, editar e apagar entra no histórico."""

    def perform_create(self, serializer):
        super().perform_create(serializer)
        registrar(self.request.user, Registro.Acao.CRIOU, serializer.instance)

    def perform_update(self, serializer):
        antes = foto(serializer.instance)
        super().perform_update(serializer)
        mudancas = comparar(antes, foto(serializer.instance))
        if mudancas:  # salvou sem mudar nada: não precisa registrar
            registrar(self.request.user, Registro.Acao.EDITOU, serializer.instance, mudancas=mudancas)

    def perform_destroy(self, instance):
        tipo = str(instance._meta.verbose_name)
        descricao = str(instance)
        objeto_id = instance.pk
        super().perform_destroy(instance)
        Registro.objects.create(
            usuario=self.request.user, acao=Registro.Acao.APAGOU, tipo=tipo,
            objeto_id=str(objeto_id), descricao=descricao[:200],
        )
