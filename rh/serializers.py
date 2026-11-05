from django.utils import timezone
from rest_framework import serializers

from config.api import ModelSerializerComRegras

from .models import Afastamento, Alocacao, Formacao, Lotacao, Professor


def resumo_formacao(formacao):
    """Formação em poucas palavras, para listas e fichas."""
    return {
        "id": formacao.id, "nivel": formacao.nivel, "nivel_nome": formacao.get_nivel_display(),
        "curso": formacao.curso, "instituicao": formacao.instituicao, "ano_conclusao": formacao.ano_conclusao,
        "habilita": formacao.habilita,
        "materias": [m.id for m in formacao.materias.all()],
        "materias_nomes": [m.nome for m in formacao.materias.all()],
    }


class FormacaoSerializer(ModelSerializerComRegras):
    """Formação do professor. {"professor", "nivel", "curso", "instituicao", "ano_conclusao", "materias": [ids]}"""

    nivel_nome = serializers.CharField(source="get_nivel_display", read_only=True)
    professor_nome = serializers.CharField(source="professor.nome", read_only=True)
    materias_nomes = serializers.SerializerMethodField()
    habilita = serializers.BooleanField(read_only=True)

    class Meta:
        model = Formacao
        fields = ["id", "professor", "professor_nome", "nivel", "nivel_nome", "curso", "instituicao",
                  "ano_conclusao", "materias", "materias_nomes", "habilita"]

    def get_materias_nomes(self, formacao):
        return [m.nome for m in formacao.materias.all()]

    def validate(self, attrs):
        if self.instance is not None and "professor" in attrs and attrs["professor"] != self.instance.professor:
            raise serializers.ValidationError({"professor": "Não dá pra passar a formação para outro professor."})
        attrs = super().validate(attrs)
        nivel = attrs.get("nivel", getattr(self.instance, "nivel", Formacao.Nivel.LICENCIATURA))
        materias = attrs.get("materias", list(self.instance.materias.all()) if self.instance else [])
        if nivel == Formacao.Nivel.POS and materias:
            raise serializers.ValidationError({"materias": (
                "Pós-graduação não habilita para dar aula na educação básica (LDB, art. 62). "
                "Marque as matérias na licenciatura do professor."
            )})
        if nivel != Formacao.Nivel.POS and not materias:
            raise serializers.ValidationError({"materias": "Marque as matérias que essa formação habilita."})
        if self.instance is not None:
            self.conferir_turmas(self.instance.professor, tirando=self.instance,
                                 novas=set(m.id for m in materias) if nivel != Formacao.Nivel.POS else set())
        return attrs

    @staticmethod
    def conferir_turmas(professor, tirando, novas=frozenset()):
        """Não deixa tirar a habilitação de uma matéria que o professor dá neste ano."""
        ano = timezone.localdate().year
        outras = set(
            Formacao.objects.filter(professor=professor, nivel__in=Formacao.NIVEIS_QUE_HABILITAM)
            .exclude(pk=tirando.pk).values_list("materias", flat=True)
        ) - {None}
        ficam = outras | set(novas)
        dando = Lotacao.objects.filter(professor=professor, turma__ano_letivo__gte=ano).exclude(materia_id__in=ficam)
        primeira = dando.select_related("materia", "turma__serie").first()
        if primeira:
            raise serializers.ValidationError({"materias": (
                f"{professor.nome} dá {primeira.materia} na {primeira.turma.serie} {primeira.turma.letra}. "
                "Peça à escola para tirar essa turma antes de mudar a formação."
            )})


class ProfessorSerializer(ModelSerializerComRegras):
    cpf = serializers.CharField(write_only=True, max_length=14)  # na leitura vai formatado
    cpf_formatado = serializers.CharField(read_only=True)
    carga_nome = serializers.CharField(source="get_carga_horaria_semanal_display", read_only=True)
    vinculo_nome = serializers.CharField(source="get_vinculo_display", read_only=True)
    limite_aulas = serializers.IntegerField(read_only=True)
    aulas_ano_atual = serializers.SerializerMethodField()
    usuario_nome = serializers.CharField(source="usuario.username", read_only=True, default=None)
    afastamento_atual = serializers.SerializerMethodField()
    formacoes = serializers.SerializerMethodField()
    habilitado_em = serializers.SerializerMethodField()

    class Meta:
        model = Professor
        fields = [
            "id", "nome", "matricula", "cpf", "cpf_formatado", "usuario", "usuario_nome",
            "carga_horaria_semanal", "carga_nome", "vinculo", "vinculo_nome",
            "data_admissao", "ativo", "limite_aulas", "aulas_ano_atual", "afastamento_atual",
            "formacoes", "habilitado_em",
        ]
        read_only_fields = ["usuario"]  # o login é criado pela ação "criar_acesso"
        # Obrigatória no cadastro (pedido do mentor).
        extra_kwargs = {"data_admissao": {"required": True, "allow_null": False,
                                          "error_messages": {"required": "Informe a data de admissão.",
                                                             "null": "Informe a data de admissão."}}}

    def get_formacoes(self, professor):
        return [resumo_formacao(f) for f in professor.formacoes.all()]

    def get_habilitado_em(self, professor):
        """Nomes das matérias que a formação habilita (ex.: ["Física", "Química"])."""
        return sorted({nome for f in professor.formacoes.all() if f.habilita for nome in (m.nome for m in f.materias.all())})

    def get_aulas_ano_atual(self, professor):
        return professor.aulas_no_ano(timezone.localdate().year)

    def get_afastamento_atual(self, professor):
        hoje = timezone.localdate()
        atual = professor.afastamentos.filter(inicio__lte=hoje, fim__gte=hoje).first()
        if atual is None:
            return None
        return {"tipo_nome": atual.get_tipo_display(), "fim": atual.fim}


class AlocacaoSerializer(ModelSerializerComRegras):
    """Professor alocado numa escola. Sem CPF e sem matrícula: a escola também lê isto."""

    professor_nome = serializers.CharField(source="professor.nome", read_only=True)
    carga_professor = serializers.IntegerField(source="professor.carga_horaria_semanal", read_only=True)
    vinculo_nome = serializers.CharField(source="professor.get_vinculo_display", read_only=True)
    escola_nome = serializers.CharField(source="escola.nome", read_only=True)
    horas_nome = serializers.CharField(source="get_horas_semanais_display", read_only=True)
    funcao_nome = serializers.CharField(source="get_funcao_display", read_only=True)
    limite_aulas = serializers.IntegerField(read_only=True)
    aulas_ano_atual = serializers.SerializerMethodField()
    afastamento_atual = serializers.SerializerMethodField()

    class Meta:
        model = Alocacao
        fields = [
            "id", "professor", "professor_nome", "carga_professor", "vinculo_nome", "escola", "escola_nome",
            "horas_semanais", "horas_nome", "portaria", "desde", "funcao", "funcao_nome", "portaria_funcao",
            "limite_aulas", "aulas_ano_atual", "afastamento_atual",
        ]
        # A função é da escola: muda pela ação /funcao/, não no cadastro do RH.
        read_only_fields = ["funcao", "portaria_funcao"]

    def validate(self, attrs):
        # O RH pode corrigir horas e portaria, mas não trocar o professor ou a escola de uma alocação.
        if self.instance is not None:
            for campo in ("professor", "escola"):
                if campo in attrs and attrs[campo] != getattr(self.instance, campo):
                    raise serializers.ValidationError(
                        {campo: "Não dá pra trocar. Tire esta alocação e crie outra."})
        return super().validate(attrs)

    def get_aulas_ano_atual(self, alocacao):
        return alocacao.aulas_no_ano(timezone.localdate().year)

    def get_afastamento_atual(self, alocacao):
        hoje = timezone.localdate()
        atual = alocacao.professor.afastamentos.filter(inicio__lte=hoje, fim__gte=hoje).first()
        return {"tipo_nome": atual.get_tipo_display(), "fim": atual.fim} if atual else None


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
