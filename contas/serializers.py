from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Usuario


class UsuarioSerializer(serializers.ModelSerializer):
    """O que o React precisa saber de quem está logado."""

    nome = serializers.SerializerMethodField()
    perfil_nome = serializers.CharField(source="get_perfil_display", read_only=True)
    setor_nome = serializers.CharField(source="get_setor_display", read_only=True)
    escola_nome = serializers.CharField(source="escola.nome", read_only=True, default=None)

    class Meta:
        model = Usuario
        fields = [
            "id", "username", "nome", "email", "perfil", "perfil_nome",
            "setor", "setor_nome", "escola", "escola_nome", "is_superuser",
        ]
        read_only_fields = fields

    def get_nome(self, usuario):
        return usuario.get_full_name() or usuario.username


class LoginSerializer(TokenObtainPairSerializer):
    """Login: confere usuário e senha e devolve os tokens JUNTO com os dados do usuário.

    Assim o React já sabe o perfil e abre a tela certa, sem pedir de novo.
    """

    default_error_messages = {"no_active_account": "Usuário ou senha incorretos."}

    def validate(self, attrs):
        dados = super().validate(attrs)  # {"refresh": "...", "access": "..."}
        dados["usuario"] = UsuarioSerializer(self.user).data
        return dados
