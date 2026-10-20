from rest_framework import serializers, viewsets

from config.api import FiltrosMixin

from .models import Registro


class RegistroSerializer(serializers.ModelSerializer):
    usuario_nome = serializers.SerializerMethodField()
    acao_nome = serializers.CharField(source="get_acao_display", read_only=True)

    class Meta:
        model = Registro
        fields = ["id", "usuario", "usuario_nome", "acao", "acao_nome", "tipo", "objeto_id", "descricao",
                  "mudancas", "criado_em"]

    def get_usuario_nome(self, registro):
        usuario = registro.usuario
        return (usuario.get_full_name() or usuario.username) if usuario else "Sistema"


class RegistroViewSet(FiltrosMixin, viewsets.ReadOnlyModelViewSet):
    """GET /api/registros/: o histórico. A Secretaria vê tudo; os outros, só o que eles mesmos fizeram.

    Filtros: ?acao=criou, ?tipo=nota, ?usuario=3, ?limite=100 (padrão 100, máximo 500).
    """

    serializer_class = RegistroSerializer
    filtros = {"acao": "acao", "tipo": "tipo", "usuario": "usuario_id"}

    def get_queryset(self):
        usuario = self.request.user
        registros = Registro.objects.select_related("usuario")
        if not (usuario.is_superuser or usuario.perfil == usuario.Perfil.SECRETARIA):
            registros = registros.filter(usuario=usuario)
        registros = self.aplicar_filtros(registros)
        try:
            limite = min(int(self.request.query_params.get("limite", 100)), 500)
        except ValueError:
            limite = 100
        return registros[:limite]
