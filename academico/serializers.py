from django.db import transaction
from rest_framework import serializers

from config.api import ModelSerializerComRegras
from rh.models import Professor

from .models import (
    Aluno,
    Aula,
    Cardapio,
    Comunicado,
    Fechamento,
    Horario,
    Matricula,
    Nota,
    PlanoAula,
    Presenca,
    Responsavel,
    Tarefa,
)


def nome_turma(turma):
    return f"{turma.serie.nome} {turma.letra}" if turma else None


class AlunoSerializer(ModelSerializerComRegras):
    programa_nome = serializers.CharField(source="get_programa_social_display", read_only=True)
    idade = serializers.IntegerField(read_only=True)
    responsaveis = serializers.SerializerMethodField()
    matricula_atual = serializers.SerializerMethodField()
    tem_acesso = serializers.SerializerMethodField()

    class Meta:
        model = Aluno
        fields = [
            "id", "codigo", "nome", "data_nascimento", "idade", "programa_social", "programa_nome",
            "nis", "necessidade_especial", "responsaveis", "matricula_atual", "tem_acesso",
        ]

    def get_responsaveis(self, aluno):
        return [
            {"id": v.responsavel_id, "nome": v.responsavel.nome, "parentesco": v.get_parentesco_display(),
             "parentesco_codigo": v.parentesco, "telefone": v.responsavel.telefone}
            for v in aluno.vinculos.select_related("responsavel")
        ]

    def get_matricula_atual(self, aluno):
        matricula = aluno.matricula_atual()
        if matricula is None:
            return None
        return {
            "id": matricula.id, "escola_nome": matricula.escola.nome, "serie_nome": matricula.serie.nome,
            "turma": matricula.turma_id, "turma_nome": nome_turma(matricula.turma),
            "situacao": matricula.situacao, "situacao_nome": matricula.get_situacao_display(),
        }

    def get_tem_acesso(self, aluno):
        return aluno.usuario_id is not None


class ResponsavelSerializer(ModelSerializerComRegras):
    cpf = serializers.CharField(write_only=True, max_length=14)
    cpf_formatado = serializers.SerializerMethodField()
    alunos = serializers.SerializerMethodField()
    tem_acesso = serializers.SerializerMethodField()

    class Meta:
        model = Responsavel
        fields = ["id", "nome", "cpf", "cpf_formatado", "telefone", "email", "alunos", "tem_acesso"]

    def get_tem_acesso(self, responsavel):
        return responsavel.usuario_id is not None

    def get_cpf_formatado(self, responsavel):
        c = responsavel.cpf
        return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}" if len(c) == 11 else c

    def get_alunos(self, responsavel):
        return [
            {"id": v.aluno_id, "nome": v.aluno.nome, "parentesco": v.get_parentesco_display()}
            for v in responsavel.vinculos.select_related("aluno")
        ]


class MatriculaSerializer(ModelSerializerComRegras):
    aluno_nome = serializers.CharField(source="aluno.nome", read_only=True)
    aluno_codigo = serializers.CharField(source="aluno.codigo", read_only=True)
    programa_social = serializers.CharField(source="aluno.programa_social", read_only=True)
    escola_nome = serializers.CharField(source="escola.nome", read_only=True)
    serie_nome = serializers.CharField(source="serie.nome", read_only=True)
    curso_nome = serializers.CharField(source="serie.curso.nome", read_only=True)
    turma_nome = serializers.SerializerMethodField()
    situacao_nome = serializers.CharField(source="get_situacao_display", read_only=True)

    class Meta:
        model = Matricula
        fields = [
            "id", "aluno", "aluno_nome", "aluno_codigo", "programa_social", "escola", "escola_nome",
            "serie", "serie_nome", "curso_nome", "ano_letivo", "turma", "turma_nome",
            "situacao", "situacao_nome", "data", "resultado_final", "media_final",
        ]

    def get_turma_nome(self, matricula):
        return nome_turma(matricula.turma)


class NovaMatriculaSerializer(serializers.Serializer):
    """Matrícula de um aluno novo, com o responsável, de uma vez só (tela da escola)."""

    aluno_nome = serializers.CharField(max_length=150)
    aluno_nascimento = serializers.DateField()
    programa_social = serializers.ChoiceField(choices=Aluno.Programa.choices, required=False, allow_blank=True)
    nis = serializers.CharField(max_length=11, required=False, allow_blank=True)
    necessidade_especial = serializers.CharField(max_length=120, required=False, allow_blank=True)
    responsavel_nome = serializers.CharField(max_length=150, required=False, allow_blank=True)
    responsavel_cpf = serializers.CharField(max_length=14, required=False, allow_blank=True)
    responsavel_telefone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    parentesco = serializers.ChoiceField(choices=[("mae", "Mãe"), ("pai", "Pai"), ("avo", "Avó / avô"),
                                                  ("tio", "Tia / tio"), ("outro", "Outro")], required=False)
    escola = serializers.IntegerField()
    serie = serializers.IntegerField()
    ano_letivo = serializers.IntegerField()
    turma = serializers.IntegerField(required=False, allow_null=True)
    situacao = serializers.ChoiceField(choices=Matricula.Situacao.choices, default=Matricula.Situacao.EM_ANALISE)


class AulaSerializer(ModelSerializerComRegras):
    """Uma aula do diário + a chamada.

    Para a chamada, mande "faltas": [ids das matrículas que faltaram]. Quem não está
    na lista ganha presença. Na leitura, "faltas" volta do mesmo jeito.
    """

    professor = serializers.PrimaryKeyRelatedField(queryset=Professor.objects.all(), required=False)
    turma_nome = serializers.SerializerMethodField()
    materia_nome = serializers.CharField(source="materia.nome", read_only=True)
    professor_nome = serializers.CharField(source="professor.nome", read_only=True)
    unidade = serializers.IntegerField(read_only=True)
    faltas = serializers.ListField(child=serializers.IntegerField(), required=False, write_only=True)
    faltosos = serializers.SerializerMethodField()
    presentes = serializers.SerializerMethodField()
    total_alunos = serializers.SerializerMethodField()

    class Meta:
        model = Aula
        fields = [
            "id", "turma", "turma_nome", "materia", "materia_nome", "professor", "professor_nome",
            "data", "quantidade", "conteudo", "unidade", "faltas", "faltosos", "presentes", "total_alunos",
        ]

    def get_turma_nome(self, aula):
        return nome_turma(aula.turma)

    def get_faltosos(self, aula):
        return [p.matricula_id for p in aula.presencas.all() if not p.presente]

    def get_presentes(self, aula):
        return sum(1 for p in aula.presencas.all() if p.presente)

    def get_total_alunos(self, aula):
        return len(aula.presencas.all())

    def validate(self, attrs):
        professor = self.context.get("professor")
        if professor is not None:
            attrs["professor"] = professor  # o professor logado sempre lança no próprio nome
        elif self.instance is None and "professor" not in attrs:
            raise serializers.ValidationError({"professor": "Informe o professor."})
        return super().validate(attrs)

    def validate_faltas(self, faltas):
        return list(dict.fromkeys(faltas))  # tira repetidos

    @transaction.atomic
    def create(self, validated_data):
        faltas = validated_data.pop("faltas", [])
        aula = super().create(validated_data)
        self.salvar_chamada(aula, faltas)
        return aula

    @transaction.atomic
    def update(self, instance, validated_data):
        faltas = validated_data.pop("faltas", None)
        aula = super().update(instance, validated_data)
        if faltas is not None:
            self.salvar_chamada(aula, faltas)
        return aula

    def salvar_chamada(self, aula, faltas):
        alunos = aula.turma.matriculas.filter(situacao=Matricula.Situacao.CONFIRMADA)
        ids = set(alunos.values_list("id", flat=True))
        de_fora = [i for i in faltas if i not in ids]
        if de_fora:
            raise serializers.ValidationError({"faltas": "Tem aluno na lista de faltas que não é dessa turma."})
        aula.presencas.exclude(matricula_id__in=ids).delete()
        for matricula_id in ids:
            Presenca.objects.update_or_create(
                aula=aula, matricula_id=matricula_id, defaults={"presente": matricula_id not in faltas}
            )


class NotaSerializer(serializers.ModelSerializer):
    aluno_nome = serializers.CharField(source="matricula.aluno.nome", read_only=True)
    materia_nome = serializers.CharField(source="materia.nome", read_only=True)

    class Meta:
        model = Nota
        fields = ["id", "matricula", "aluno_nome", "materia", "materia_nome", "unidade", "valor", "atualizada_em"]


class LancarNotasSerializer(serializers.Serializer):
    """As notas de uma turma inteira numa matéria e unidade. valor vazio = apagar a nota."""

    turma = serializers.IntegerField()
    materia = serializers.IntegerField()
    unidade = serializers.IntegerField(min_value=1, max_value=4)
    notas = serializers.ListField(child=serializers.DictField())


class FechamentoSerializer(ModelSerializerComRegras):
    turma_nome = serializers.SerializerMethodField()
    fechado_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = Fechamento
        fields = ["id", "turma", "turma_nome", "unidade", "fechado_por_nome", "fechado_em"]

    def get_turma_nome(self, fechamento):
        return nome_turma(fechamento.turma)

    def get_fechado_por_nome(self, fechamento):
        usuario = fechamento.fechado_por
        return (usuario.get_full_name() or usuario.username) if usuario else None


class TarefaSerializer(ModelSerializerComRegras):
    professor = serializers.PrimaryKeyRelatedField(queryset=Professor.objects.all(), required=False)
    turma_nome = serializers.SerializerMethodField()
    materia_nome = serializers.CharField(source="materia.nome", read_only=True)
    professor_nome = serializers.CharField(source="professor.nome", read_only=True)
    entregas = serializers.SerializerMethodField()
    total_alunos = serializers.SerializerMethodField()

    class Meta:
        model = Tarefa
        fields = [
            "id", "turma", "turma_nome", "materia", "materia_nome", "professor", "professor_nome",
            "titulo", "descricao", "prazo", "criada_em", "entregas", "total_alunos",
        ]

    def get_turma_nome(self, tarefa):
        return nome_turma(tarefa.turma)

    def get_entregas(self, tarefa):
        return [e.matricula_id for e in tarefa.entregas.all()]

    def get_total_alunos(self, tarefa):
        return tarefa.turma.matriculas.filter(situacao=Matricula.Situacao.CONFIRMADA).count()

    def validate(self, attrs):
        professor = self.context.get("professor")
        if professor is not None:
            attrs["professor"] = professor
        elif self.instance is None and "professor" not in attrs:
            raise serializers.ValidationError({"professor": "Informe o professor."})
        return super().validate(attrs)


class PlanoAulaSerializer(ModelSerializerComRegras):
    professor = serializers.PrimaryKeyRelatedField(queryset=Professor.objects.all(), required=False)
    turma_nome = serializers.SerializerMethodField()
    materia_nome = serializers.CharField(source="materia.nome", read_only=True)
    status_nome = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = PlanoAula
        fields = [
            "id", "professor", "turma", "turma_nome", "materia", "materia_nome", "unidade",
            "tema", "objetivos", "status", "status_nome",
        ]

    def get_turma_nome(self, plano):
        return nome_turma(plano.turma)

    def validate(self, attrs):
        professor = self.context.get("professor")
        if professor is not None:
            attrs["professor"] = professor
        elif self.instance is None and "professor" not in attrs:
            raise serializers.ValidationError({"professor": "Informe o professor."})
        return super().validate(attrs)


class ComunicadoSerializer(ModelSerializerComRegras):
    alcance_nome = serializers.CharField(source="get_alcance_display", read_only=True)
    autor_nome = serializers.SerializerMethodField()
    para = serializers.SerializerMethodField()

    class Meta:
        model = Comunicado
        fields = [
            "id", "titulo", "texto", "alcance", "alcance_nome", "escola", "turma", "destinatario",
            "autor", "autor_nome", "para", "criado_em",
        ]
        read_only_fields = ["autor"]

    def validate(self, attrs):
        # O autor é quem está logado (vem antes das regras, porque o campo é obrigatório).
        if self.instance is None and "request" in self.context:
            attrs["autor"] = self.context["request"].user
        return super().validate(attrs)

    def get_autor_nome(self, comunicado):
        autor = comunicado.autor
        return (autor.get_full_name() or autor.username) if autor else "Sistema"

    def get_para(self, comunicado):
        if comunicado.alcance == Comunicado.Alcance.ESCOLA and comunicado.escola:
            return comunicado.escola.nome
        if comunicado.alcance == Comunicado.Alcance.TURMA and comunicado.turma:
            return f"{nome_turma(comunicado.turma)} · {comunicado.turma.escola.nome}"
        if comunicado.alcance == Comunicado.Alcance.PESSOA and comunicado.destinatario:
            return comunicado.destinatario.get_full_name() or comunicado.destinatario.username
        return "Rede estadual"


class HorarioSerializer(ModelSerializerComRegras):
    dia_nome = serializers.CharField(source="get_dia_semana_display", read_only=True)
    turma = serializers.IntegerField(source="lotacao.turma_id", read_only=True)
    turma_nome = serializers.SerializerMethodField()
    materia = serializers.IntegerField(source="lotacao.materia_id", read_only=True)
    materia_nome = serializers.CharField(source="lotacao.materia.nome", read_only=True)
    professor_nome = serializers.CharField(source="lotacao.professor.nome", read_only=True)
    sala = serializers.CharField(source="lotacao.turma.sala", read_only=True)

    class Meta:
        model = Horario
        fields = [
            "id", "lotacao", "dia_semana", "dia_nome", "inicio", "turma", "turma_nome",
            "materia", "materia_nome", "professor_nome", "sala",
        ]

    def get_turma_nome(self, horario):
        return nome_turma(horario.lotacao.turma)


class CardapioSerializer(ModelSerializerComRegras):
    dia_nome = serializers.CharField(source="get_dia_semana_display", read_only=True)

    class Meta:
        model = Cardapio
        fields = ["id", "escola", "dia_semana", "dia_nome", "almoco", "lanche"]
