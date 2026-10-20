"""Criar o login (usuário e senha) de um professor, aluno ou responsável já cadastrado."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework import serializers

from .models import Usuario


class CriarAcessoSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    senha = serializers.CharField(min_length=8, max_length=128, write_only=True)


@transaction.atomic
def criar_login(pessoa, perfil, dados, escola=None):
    """Cria o Usuario, liga em pessoa.usuario e devolve o usuário criado.

    pessoa = Professor, Aluno ou Responsavel (todos têm os campos nome e usuario).
    """
    if pessoa.usuario_id:
        raise serializers.ValidationError({"detail": f"{pessoa.nome} já tem login: {pessoa.usuario.username}."})
    username = dados["username"].strip().lower()
    if Usuario.objects.filter(username=username).exists():
        raise serializers.ValidationError({"username": "Esse usuário já existe. Escolha outro."})

    primeiro, _, resto = pessoa.nome.partition(" ")
    usuario = Usuario(username=username, first_name=primeiro, last_name=resto, perfil=perfil, escola=escola)
    try:
        Usuario.username_validator(username)
        validate_password(dados["senha"], usuario)  # as regras de senha do settings.py
    except ValidationError as erro:
        campo = "username" if "usuário" in " ".join(erro.messages).lower() else "senha"
        raise serializers.ValidationError({campo: erro.messages})
    usuario.set_password(dados["senha"])
    usuario.save()
    pessoa.usuario = usuario
    pessoa.save(update_fields=["usuario"])
    return usuario
