from rest_framework import serializers

from config.api import ModelSerializerComRegras

from .models import Olimpiada


def participacao_resumo(participacao, com_nota=True):
    """Uma linha da classificação (nota/posição só aparecem quando podem ser vistas)."""
    matricula = participacao.matricula
    turma = matricula.turma
    return {
        "id": participacao.pk,
        "aluno": participacao.aluno_id,
        "aluno_nome": participacao.aluno.nome,
        "turma_nome": f"{turma.serie.nome} {turma.letra}" if turma else matricula.serie.nome,
        "nota": participacao.nota if com_nota else None,
        "posicao": getattr(participacao, "posicao", None) if com_nota else None,
        "medalha": getattr(participacao, "medalha", "") if com_nota else "",
    }


class OlimpiadaSerializer(ModelSerializerComRegras):
    escola_nome = serializers.CharField(source="escola.nome", read_only=True)
    materia_nome = serializers.CharField(source="materia.nome", read_only=True, default=None)
    series_nomes = serializers.SerializerMethodField()
    status_nome = serializers.CharField(source="get_status_display", read_only=True)
    inscritos = serializers.IntegerField(read_only=True, default=0)
    minhas = serializers.SerializerMethodField()
    pode_participar = serializers.SerializerMethodField()

    class Meta:
        model = Olimpiada
        fields = ["id", "escola", "escola_nome", "nome", "materia", "materia_nome", "descricao", "ano_letivo",
                  "data_prova", "series", "series_nomes", "nota_maxima", "premiados", "status", "status_nome",
                  "inscritos", "minhas", "pode_participar", "resultado_em", "criada_em"]
        read_only_fields = ["escola", "ano_letivo", "resultado_em", "criada_em"]

    def get_series_nomes(self, olimpiada):
        return [serie.nome for serie in olimpiada.series.all()]

    def get_minhas(self, olimpiada):
        """Para aluno e responsável: as inscrições dos seus alunos nesta olimpíada
        (com nota e posição só depois do resultado publicado)."""
        alunos = self.context.get("meus_alunos")
        if not alunos:
            return []
        publicado = olimpiada.status == Olimpiada.Status.RESULTADO
        linhas = olimpiada.classificacao() if publicado else olimpiada.participacoes.select_related(
            "aluno", "matricula__turma__serie", "matricula__serie")
        return [participacao_resumo(p, com_nota=publicado) for p in linhas if p.aluno_id in alunos]

    def get_pode_participar(self, olimpiada):
        aluno = self.context.get("aluno")
        if aluno is None or olimpiada.status != Olimpiada.Status.INSCRICOES:
            return False
        if olimpiada.participacoes.filter(aluno=aluno).exists():
            return False
        matricula = olimpiada.matricula_valida(aluno)
        return bool(matricula and olimpiada.aceita_serie(matricula.serie_id))

    def validate(self, attrs):
        escola = self.context.get("escola")
        if self.instance is None:
            attrs["escola"] = escola
        if "data_prova" in attrs:
            attrs["ano_letivo"] = attrs["data_prova"].year
        olimpiada = self.instance
        if olimpiada is not None and olimpiada.participacoes.exists():
            if "data_prova" in attrs and attrs["data_prova"].year != olimpiada.ano_letivo:
                raise serializers.ValidationError({"data_prova": "Já tem aluno inscrito: a prova tem que ficar no mesmo ano letivo."})
            if "nota_maxima" in attrs and olimpiada.participacoes.filter(nota__gt=attrs["nota_maxima"]).exists():
                raise serializers.ValidationError({"nota_maxima": "Tem aluno com nota maior que essa. Corrija as notas antes."})
        return super().validate(attrs)
