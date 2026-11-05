from django.contrib.auth.hashers import check_password
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
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
        try:
            dados = super().validate(attrs)  # {"refresh": "...", "access": "..."}
        except AuthenticationFailed:
            self.avisar_inscricao(attrs)
            raise
        dados["usuario"] = UsuarioSerializer(self.user).data
        return dados

    @staticmethod
    def avisar_inscricao(attrs):
        """Quem fez a matrícula pela internet e ainda não foi aprovado vê o andamento aqui.

        Só mostra se o e-mail E a senha baterem com o pedido (ninguém descobre o pedido dos outros).
        """
        from inscricoes.models import Inscricao  # aqui dentro: o app inscricoes depende do contas

        email = (attrs.get("username") or "").strip().lower()
        pedido = Inscricao.objects.filter(email=email).exclude(status=Inscricao.Status.APROVADA).first()
        if pedido is None or not check_password(attrs.get("password") or "", pedido.senha):
            return
        if pedido.status == Inscricao.Status.AGUARDANDO:
            raise AuthenticationFailed(
                f"Sua matrícula (protocolo {pedido.protocolo}) ainda está em análise pelo DIES. "
                "Assim que for aprovada, você entra com este e-mail e senha."
            )
        raise AuthenticationFailed(
            f"Sua matrícula (protocolo {pedido.protocolo}) foi recusada pelo DIES: {pedido.motivo_recusa} "
            "Você pode fazer um novo pedido na tela inicial."
        )
