from rest_framework import serializers

from academico.models import Presenca
from config.api import ModelSerializerComRegras
from contas.models import Usuario

from .models import TAMANHO_MAXIMO, Documento

# Formatos aceitos. Confere o começo do arquivo (a "assinatura"), e não só a extensão:
# assim um .exe renomeado para .pdf não passa.
FORMATOS = [
    (b"%PDF", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
]


def formato_do_arquivo(conteudo):
    return next((tipo for assinatura, tipo in FORMATOS if conteudo.startswith(assinatura)), None)


def nome_de(usuario):
    return (usuario.get_full_name() or usuario.username) if usuario else "—"


class DocumentoSerializer(ModelSerializerComRegras):
    # Só pra receber o envio: o arquivo em si nunca volta na lista (é baixado em /arquivo/).
    arquivo = serializers.FileField(write_only=True, error_messages={
        "required": "Anexe o arquivo.", "empty": "O arquivo está vazio.", "invalid": "Anexe o arquivo."})
    aluno_nome = serializers.CharField(source="aluno.nome", read_only=True)
    escola_nome = serializers.CharField(source="escola.nome", read_only=True)
    tipo_nome = serializers.CharField(source="get_tipo_display", read_only=True)
    status_nome = serializers.CharField(source="get_status_display", read_only=True)
    turma_nome = serializers.SerializerMethodField()
    enviado_por_nome = serializers.SerializerMethodField()
    analisado_por_nome = serializers.SerializerMethodField()
    faltas_no_periodo = serializers.SerializerMethodField()
    pode_cancelar = serializers.SerializerMethodField()

    class Meta:
        model = Documento
        fields = [
            "id", "aluno", "aluno_nome", "turma_nome", "escola", "escola_nome", "tipo", "tipo_nome", "descricao",
            "data_inicio", "data_fim", "faltas_no_periodo", "arquivo", "nome_arquivo", "tipo_arquivo", "tamanho",
            "status", "status_nome", "resposta", "enviado_por_nome", "enviado_em", "analisado_por_nome",
            "analisado_em", "pode_cancelar",
        ]
        read_only_fields = ["escola", "nome_arquivo", "tipo_arquivo", "tamanho", "status", "resposta",
                            "enviado_em", "analisado_em"]

    def validate_arquivo(self, arquivo):
        if arquivo.size > TAMANHO_MAXIMO:
            raise serializers.ValidationError("O arquivo passa de 5 MB. Tire uma foto menor ou mande em PDF.")
        conteudo = arquivo.read()
        tipo = formato_do_arquivo(conteudo)
        if tipo is None:
            raise serializers.ValidationError("Formato não aceito. Mande PDF, JPG ou PNG.")
        nome = (arquivo.name or "documento").replace("\\", "/").split("/")[-1][-150:]
        return {"conteudo": conteudo, "nome": nome, "tipo": tipo}

    def validate(self, attrs):
        # O arquivo vira os campos da tabela antes das regras do model (full_clean).
        arquivo = attrs.pop("arquivo", None)
        if arquivo:
            attrs.update(arquivo=arquivo["conteudo"], nome_arquivo=arquivo["nome"],
                         tipo_arquivo=arquivo["tipo"], tamanho=len(arquivo["conteudo"]))
        # A escola é a da matrícula atual do aluno (quem envia não escolhe).
        aluno = attrs.get("aluno")
        if aluno is not None and self.instance is None:
            matricula = aluno.matricula_atual()
            if matricula is None:
                raise serializers.ValidationError(
                    {"aluno": f"{aluno.nome} não tem matrícula ativa neste ano. Fale com a escola."})
            attrs["escola"] = matricula.escola
        return super().validate(attrs)

    def get_turma_nome(self, documento):
        matricula = documento.aluno.matricula_atual()
        turma = matricula.turma if matricula else None
        return f"{turma.serie.nome} {turma.letra}" if turma else None

    def get_enviado_por_nome(self, documento):
        """Ex.: "Maria José Souza (mãe)" ou "Ana Beatriz Souza (aluno)"."""
        usuario = documento.enviado_por
        if usuario is None:
            return "—"
        if usuario.perfil == Usuario.Perfil.RESPONSAVEL:
            vinculo = documento.aluno.vinculos.filter(responsavel__usuario=usuario).first()
            papel = vinculo.get_parentesco_display().lower() if vinculo else "responsável"
        elif usuario.perfil == Usuario.Perfil.ALUNO:
            papel = "aluno"
        else:
            papel = usuario.get_perfil_display().lower()
        return f"{nome_de(usuario)} ({papel})"

    def get_analisado_por_nome(self, documento):
        return nome_de(documento.analisado_por) if documento.analisado_por else None

    def get_pode_cancelar(self, documento):
        """Quem enviou pode cancelar enquanto a escola não analisou."""
        request = self.context.get("request")
        return bool(request and documento.enviado_por_id == request.user.pk
                    and documento.status == Documento.Status.AGUARDANDO)

    def get_faltas_no_periodo(self, documento):
        """Atestado/justificativa: quantas faltas o aluno tem nos dias cobertos (ajuda a escola a conferir)."""
        if not (documento.data_inicio and documento.data_fim):
            return None
        return Presenca.objects.filter(
            matricula__aluno=documento.aluno, presente=False,
            aula__data__range=(documento.data_inicio, documento.data_fim),
        ).count()
