from rest_framework import serializers

from config.api import ModelSerializerComRegras
from contas.permissoes import eh_do_setor

from .models import Mensagem, Solicitacao


def nome_de(usuario):
    return (usuario.get_full_name() or usuario.username) if usuario else "Sistema"


class MensagemSerializer(serializers.ModelSerializer):
    autor_nome = serializers.SerializerMethodField()
    lado = serializers.SerializerMethodField()

    class Meta:
        model = Mensagem
        fields = ["id", "texto", "autor_nome", "lado", "criada_em"]

    def get_autor_nome(self, mensagem):
        return nome_de(mensagem.autor)

    def get_lado(self, mensagem):
        """De quem é a fala: "escola", "dies" ou "sistema" (avisos automáticos). Serve pro balão do chat."""
        if mensagem.autor is None:
            return "sistema"
        return "dies" if eh_do_setor(mensagem.autor, "dies") else "escola"


class SolicitacaoSerializer(ModelSerializerComRegras):
    # A primeira mensagem do pedido (a explicação da escola). Só na hora de criar.
    mensagem = serializers.CharField(write_only=True, max_length=1000,
                                     error_messages={"blank": "Explique o pedido para a DIES."})
    titulo = serializers.CharField(read_only=True)
    escola_nome = serializers.CharField(source="escola.nome", read_only=True)
    tipo_nome = serializers.CharField(source="get_tipo_display", read_only=True)
    status_nome = serializers.CharField(source="get_status_display", read_only=True)
    turno_nome = serializers.CharField(source="get_turno_display", read_only=True)
    criada_por_nome = serializers.SerializerMethodField()
    mensagens = MensagemSerializer(many=True, read_only=True)
    ultima_fala = serializers.SerializerMethodField()

    class Meta:
        model = Solicitacao
        fields = [
            "id", "escola", "escola_nome", "tipo", "tipo_nome", "titulo", "serie", "turno", "turno_nome",
            "turma", "capacidade", "assunto", "status", "status_nome", "criada_por_nome", "criada_em",
            "atualizada_em", "mensagem", "mensagens", "ultima_fala",
        ]
        read_only_fields = ["escola", "status"]

    def validate(self, attrs):
        # A escola é a de quem está logado (vem antes das regras, porque o campo é obrigatório).
        if self.instance is None and "request" in self.context:
            attrs["escola"] = self.context["request"].user.escola
        mensagem = attrs.pop("mensagem", None)  # não é campo da tabela
        attrs = super().validate(attrs)
        if mensagem is not None:
            attrs["mensagem"] = mensagem
        return attrs

    def get_criada_por_nome(self, solicitacao):
        return nome_de(solicitacao.criada_por)

    def get_ultima_fala(self, solicitacao):
        """Quem falou por último ("escola", "dies" ou "sistema"): a lista mostra "aguardando resposta"."""
        ultima = list(solicitacao.mensagens.all())[-1:]
        return MensagemSerializer().get_lado(ultima[0]) if ultima else None
