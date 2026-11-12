"""API das olimpíadas escolares.

GET    /api/olimpiadas/                  lista (escola: as dela; aluno e responsável: as da escola dos seus
                                         alunos; professor: as das escolas onde dá aula; Secretaria: todas)
                                         Filtros: ?status= ?escola= ?ano_letivo=
POST   /api/olimpiadas/                  escola cadastra {nome, materia, descricao, data_prova, series, nota_maxima, premiados}
PATCH  /api/olimpiadas/ID/               escola edita (inclusive o andamento: status inscricoes/andamento/resultado)
DELETE /api/olimpiadas/ID/               escola apaga (só sem aluno inscrito)
POST   /api/olimpiadas/ID/inscrever/     aluno se inscreve (sem corpo); escola inscreve {aluno: ID}
POST   /api/olimpiadas/ID/sair/          aluno cancela a inscrição; escola tira {aluno: ID}
POST   /api/olimpiadas/ID/notas/         escola lança {notas: [{participacao: ID, nota: 8.5 ou null}]}
GET    /api/olimpiadas/ID/classificacao/ escola e Secretaria: todos, em ordem de nota.
                                         Aluno e responsável: só depois do resultado, os medalhistas
                                         e a posição dos seus alunos.
"""

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from academico.acesso import alunos_visiveis, eh_secretaria, turmas_visiveis
from academico.models import Aluno, Matricula
from auditoria.historico import registrar
from config.api import FiltrosMixin
from contas.models import Usuario

from .models import Olimpiada, Participacao
from .serializers import OlimpiadaSerializer, participacao_resumo

Perfil = Usuario.Perfil


def olimpiadas_visiveis(usuario):
    olimpiadas = Olimpiada.objects.all()
    if eh_secretaria(usuario):
        return olimpiadas
    if usuario.perfil == Perfil.ESCOLA:
        return olimpiadas.filter(escola_id=usuario.escola_id)
    if usuario.perfil in (Perfil.ALUNO, Perfil.RESPONSAVEL):
        escolas = (Matricula.objects.filter(aluno__in=alunos_visiveis(usuario))
                   .exclude(situacao__in=Matricula.SITUACOES_ENCERRADAS).values("escola_id"))
        return olimpiadas.filter(escola_id__in=escolas)
    if usuario.perfil == Perfil.PROFESSOR:
        return olimpiadas.filter(escola_id__in=turmas_visiveis(usuario).values("escola_id"))
    return olimpiadas.none()


def aluno_do_usuario(usuario):
    if usuario.perfil != Perfil.ALUNO:
        return None
    return Aluno.objects.filter(usuario=usuario).first()


class OlimpiadaViewSet(FiltrosMixin, viewsets.ModelViewSet):
    serializer_class = OlimpiadaSerializer
    filtros = {"status": "status", "escola": "escola_id", "ano_letivo": "ano_letivo"}

    def get_queryset(self):
        olimpiadas = (olimpiadas_visiveis(self.request.user).select_related("escola", "materia")
                      .prefetch_related("series").annotate(inscritos=Count("participacoes")))
        return self.aplicar_filtros(olimpiadas)

    def get_serializer_context(self):
        contexto = super().get_serializer_context()
        usuario = self.request.user
        if usuario.is_authenticated:
            contexto["escola"] = usuario.escola if usuario.perfil == Perfil.ESCOLA else None
            contexto["aluno"] = aluno_do_usuario(usuario)
            if usuario.perfil in (Perfil.ALUNO, Perfil.RESPONSAVEL):
                contexto["meus_alunos"] = set(alunos_visiveis(usuario).values_list("pk", flat=True))
        return contexto

    def so_a_escola(self, olimpiada=None):
        """Quem cadastra e mexe na olimpíada é a escola dela."""
        usuario = self.request.user
        if usuario.perfil != Perfil.ESCOLA or not usuario.escola_id:
            raise PermissionDenied("Quem organiza a olimpíada é a escola.")
        if olimpiada is not None and olimpiada.escola_id != usuario.escola_id:
            raise PermissionDenied("Essa olimpíada é de outra escola.")

    def create(self, request, *args, **kwargs):
        self.so_a_escola()  # antes de conferir os campos: aluno e Secretaria nem chegam a validar
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        olimpiada = serializer.save(criada_por=self.request.user)
        registrar(self.request.user, "criou", olimpiada, descricao=f"Cadastrou a olimpíada {olimpiada.nome}")

    def perform_update(self, serializer):
        olimpiada = serializer.instance
        self.so_a_escola(olimpiada)
        novo = serializer.validated_data.get("status", olimpiada.status)
        extra = {}
        if novo == Olimpiada.Status.RESULTADO and olimpiada.status != novo:
            if not olimpiada.participacoes.filter(nota__isnull=False).exists():
                raise serializers.ValidationError({"status": "Lance a nota de pelo menos um aluno antes de publicar o resultado."})
            extra["resultado_em"] = timezone.now()
        elif novo != Olimpiada.Status.RESULTADO:
            extra["resultado_em"] = None
        olimpiada = serializer.save(**extra)
        registrar(self.request.user, "alterou", olimpiada,
                  descricao=f"Olimpíada {olimpiada.nome}: {olimpiada.get_status_display().lower()}")

    def perform_destroy(self, olimpiada):
        self.so_a_escola(olimpiada)
        if olimpiada.participacoes.exists():
            raise serializers.ValidationError({"detail": "Já tem aluno inscrito. Tire as inscrições antes de apagar."})
        registrar(self.request.user, "apagou", olimpiada, descricao=f"Apagou a olimpíada {olimpiada.nome}")
        olimpiada.delete()

    # ------------------------------------------------------------------ inscrições

    def aluno_da_acao(self, olimpiada):
        """Aluno: ele mesmo. Escola: o {aluno: ID} do corpo."""
        usuario = self.request.user
        if usuario.perfil == Perfil.ALUNO:
            aluno = aluno_do_usuario(usuario)
            if aluno is None:
                raise PermissionDenied("Seu login não está ligado a um aluno.")
            if olimpiada.status != Olimpiada.Status.INSCRICOES:
                raise serializers.ValidationError({"detail": "As inscrições desta olimpíada já fecharam."})
            return aluno
        self.so_a_escola(olimpiada)
        if olimpiada.status == Olimpiada.Status.RESULTADO:
            raise serializers.ValidationError({"detail": "O resultado já foi publicado. Volte para \"em andamento\" para mexer."})
        aluno = Aluno.objects.filter(pk=self.request.data.get("aluno")).first()
        if aluno is None:
            raise serializers.ValidationError({"aluno": "Escolha o aluno."})
        return aluno

    @action(detail=True, methods=["post"])
    def inscrever(self, request, pk=None):
        olimpiada = self.get_object()
        aluno = self.aluno_da_acao(olimpiada)
        matricula = olimpiada.matricula_valida(aluno)
        if matricula is None:
            raise serializers.ValidationError({"aluno": f"{aluno.nome} não tem matrícula confirmada em {olimpiada.escola} em {olimpiada.ano_letivo}."})
        if not olimpiada.aceita_serie(matricula.serie_id):
            raise serializers.ValidationError({"aluno": f"Esta olimpíada não é para {matricula.serie.nome}."})
        if olimpiada.participacoes.filter(aluno=aluno).exists():
            raise serializers.ValidationError({"aluno": f"{aluno.nome} já está inscrito(a)."})
        participacao = Participacao.objects.create(olimpiada=olimpiada, aluno=aluno, matricula=matricula)
        registrar(request.user, "criou", participacao, descricao=f"Inscreveu {aluno.nome} na olimpíada {olimpiada.nome}")
        return Response(self.get_serializer(self.get_queryset().get(pk=olimpiada.pk)).data, status=201)

    @action(detail=True, methods=["post"])
    def sair(self, request, pk=None):
        olimpiada = self.get_object()
        aluno = self.aluno_da_acao(olimpiada)
        participacao = olimpiada.participacoes.filter(aluno=aluno).first()
        if participacao is None:
            raise serializers.ValidationError({"aluno": f"{aluno.nome} não está inscrito(a)."})
        registrar(request.user, "apagou", participacao, descricao=f"Tirou {aluno.nome} da olimpíada {olimpiada.nome}")
        participacao.delete()
        return Response(self.get_serializer(self.get_queryset().get(pk=olimpiada.pk)).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def notas(self, request, pk=None):
        olimpiada = self.get_object()
        self.so_a_escola(olimpiada)
        if olimpiada.status != Olimpiada.Status.ANDAMENTO:
            raise serializers.ValidationError({"detail": "As notas são lançadas com a olimpíada \"em andamento\" (feche as inscrições antes)."})
        participacoes = {p.pk: p for p in olimpiada.participacoes.select_related("aluno")}
        erros = {}
        for item in request.data.get("notas") or []:
            participacao = participacoes.get(item.get("participacao"))
            if participacao is None:
                continue
            valor = item.get("nota")
            if valor in (None, ""):
                participacao.nota = None
            else:
                try:
                    participacao.nota = serializers.DecimalField(max_digits=5, decimal_places=1).to_internal_value(
                        str(valor).replace(",", "."))
                except serializers.ValidationError:
                    erros[participacao.pk] = "Nota inválida."
                    continue
                if participacao.nota < 0 or participacao.nota > olimpiada.nota_maxima:
                    erros[participacao.pk] = f"A nota vai de 0 a {olimpiada.nota_maxima}."
                    continue
            participacao.save(update_fields=["nota"])
        if erros:
            transaction.set_rollback(True)
            nomes = {p.pk: p.aluno.nome.split()[0] for p in participacoes.values()}
            raise serializers.ValidationError({"notas": " ".join(f"{nomes[pk]}: {msg}" for pk, msg in erros.items())})
        registrar(request.user, "alterou", olimpiada, descricao=f"Lançou as notas da olimpíada {olimpiada.nome}")
        return self.classificacao(request, pk)

    @action(detail=True, methods=["get"])
    def classificacao(self, request, pk=None):
        olimpiada = self.get_object()
        usuario = request.user
        linhas = olimpiada.classificacao()
        if usuario.perfil == Perfil.ESCOLA or eh_secretaria(usuario):
            return Response([participacao_resumo(p) for p in linhas])
        if olimpiada.status != Olimpiada.Status.RESULTADO:
            return Response([])
        # Família e professor: o pódio (quem ganhou medalha) e a posição dos seus alunos.
        meus = set(alunos_visiveis(usuario).values_list("pk", flat=True)) if usuario.perfil in (
            Perfil.ALUNO, Perfil.RESPONSAVEL) else set()
        return Response([participacao_resumo(p) for p in linhas if p.medalha or p.aluno_id in meus])
