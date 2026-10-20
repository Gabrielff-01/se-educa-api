from django.utils import timezone
from rest_framework import serializers

from config.api import ModelSerializerComRegras

from .models import Afastamento, Lotacao, Professor


class ProfessorSerializer(ModelSerializerComRegras):
    cpf = serializers.CharField(write_only=True, max_length=14)  # na leitura vai formatado
    cpf_formatado = serializers.CharField(read_only=True)
    carga_nome = serializers.CharField(source="get_carga_horaria_semanal_display", read_only=True)
    vinculo_nome = serializers.CharField(source="get_vinculo_display", read_only=True)
    limite_aulas = serializers.IntegerField(read_only=True)
    aulas_ano_atual = serializers.SerializerMethodField()
    usuario_nome = serializers.CharField(source="usuario.username", read_only=True, default=None)
    afastamento_atual = serializers.SerializerMethodField()

    class Meta:
        model = Professor
        fields = [
            "id", "nome", "matricula", "cpf", "cpf_formatado", "usuario", "usuario_nome",
            "carga_horaria_semanal", "carga_nome", "vinculo", "vinculo_nome",
            "data_admissao", "ativo", "limite_aulas", "aulas_ano_atual", "afastamento_atual",
        ]
        read_only_fields = ["usuario"]  # o login é criado pela ação "criar_acesso"

    def get_aulas_ano_atual(self, professor):
        return professor.aulas_no_ano(timezone.localdate().year)

    def get_afastamento_atual(self, professor):
        hoje = timezone.localdate()
        atual = professor.afastamentos.filter(inicio__lte=hoje, fim__gte=hoje).first()
        if atual is None:
            return None
        return {"tipo_nome": atual.get_tipo_display(), "fim": atual.fim}


class LotacaoSerializer(ModelSerializerComRegras):
    professor_nome = serializers.CharField(source="professor.nome", read_only=True)
    turma_nome = serializers.SerializerMethodField()
    escola_nome = serializers.CharField(source="turma.escola.nome", read_only=True)
    ano_letivo = serializers.IntegerField(source="turma.ano_letivo", read_only=True)
    materia_nome = serializers.CharField(source="materia.nome", read_only=True)

    class Meta:
        model = Lotacao
        fields = [
            "id", "professor", "professor_nome", "turma", "turma_nome", "escola_nome",
            "ano_letivo", "materia", "materia_nome", "aulas_semanais",
        ]

    def get_turma_nome(self, lotacao):
        return f"{lotacao.turma.serie.nome} {lotacao.turma.letra}"


class AfastamentoSerializer(ModelSerializerComRegras):
    professor_nome = serializers.CharField(source="professor.nome", read_only=True)
    tipo_nome = serializers.CharField(source="get_tipo_display", read_only=True)
    vigente = serializers.BooleanField(read_only=True)

    class Meta:
        model = Afastamento
        fields = ["id", "professor", "professor_nome", "tipo", "tipo_nome", "inicio", "fim", "observacao", "vigente"]
