"""API do acadêmico: cadastros (alunos, matrículas...) e lançamentos (aulas, notas...).

As telas de resumo (boletim, painéis) ficam em paineis.py.
"""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from auditoria.historico import RegistrarAlteracoesMixin, registrar, texto
from config.api import FiltrosMixin, erros_do_django_para_drf
from contas.acessos import CriarAcessoSerializer, criar_login
from contas.models import Usuario
from rede.models import Escola, Materia, Serie, Turma
from rh.models import Lotacao

from .acesso import (
    ESCOLA_OU_SECRETARIA,
    SO_PROFESSOR,
    alunos_visiveis,
    conferir_escola,
    conferir_professor_da_lotacao,
    eh_secretaria,
    matriculas_visiveis,
    professor_de,
    turmas_visiveis,
)
from .models import (
    Aluno,
    Aula,
    Cardapio,
    Comunicado,
    Entrega,
    Fechamento,
    Horario,
    Matricula,
    Nota,
    PlanoAula,
    Responsavel,
    Tarefa,
    Vinculo,
)
from .serializers import (
    AlunoSerializer,
    AulaSerializer,
    CardapioSerializer,
    ComunicadoSerializer,
    FechamentoSerializer,
    HorarioSerializer,
    LancarNotasSerializer,
    MatriculaSerializer,
    NotaSerializer,
    NovaMatriculaSerializer,
    PlanoAulaSerializer,
    ResponsavelSerializer,
    TarefaSerializer,
)

Perfil = Usuario.Perfil


def validar(objeto, prefixo=""):
    """full_clean() com os erros no formato da API. prefixo junta o nome do formulário (aluno_nome...)."""
    try:
        objeto.full_clean()
    except DjangoValidationError as erro:
        drf = erros_do_django_para_drf(erro)
        if prefixo:
            drf = serializers.ValidationError({f"{prefixo}{campo}": msg for campo, msg in drf.detail.items()})
        raise drf


class Base(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    """Todo ViewSet daqui registra no histórico e aceita filtros pela URL."""


# --------------------------------------------------------------------------- pessoas


class AlunoViewSet(Base):
    serializer_class = AlunoSerializer
    permission_classes = ESCOLA_OU_SECRETARIA
    filtros = {"programa": "programa_social"}

    def get_queryset(self):
        alunos = alunos_visiveis(self.request.user).prefetch_related("vinculos__responsavel")
        busca = self.request.query_params.get("busca")
        if busca:
            alunos = alunos.filter(Q(nome__icontains=busca) | Q(codigo__icontains=busca))
        return self.aplicar_filtros(alunos)

    @action(detail=True, methods=["post"])
    def criar_acesso(self, request, pk=None):
        """POST /api/alunos/1/criar_acesso/ {"username": "...", "senha": "..."}"""
        aluno = self.get_object()
        dados = CriarAcessoSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        matricula = aluno.matricula_atual()
        usuario = criar_login(aluno, Perfil.ALUNO, dados.validated_data, escola=matricula.escola if matricula else None)
        registrar(request.user, "criou", usuario, tipo="login", descricao=f"Login {usuario.username} de {aluno.nome}")
        return Response(self.get_serializer(aluno).data)


    @action(detail=True, methods=["post"])
    @transaction.atomic
    def vincular_responsavel(self, request, pk=None):
        """POST /api/alunos/1/vincular_responsavel/ liga um responsável ao aluno.

        Já cadastrado:  {"responsavel": 3, "parentesco": "mae"}
        Pelo CPF:       {"cpf": "...", "parentesco": "pai", "nome": "...", "telefone": "..."}
                        acha o cadastro pelo CPF ou, se não existir, cadastra com o nome.
        """
        aluno = self.get_object()
        dados = request.data
        if dados.get("responsavel"):
            responsavel = responsaveis_visiveis(request.user).filter(pk=dados["responsavel"]).first()
            if responsavel is None:
                raise serializers.ValidationError({"responsavel": "Responsável não encontrado."})
        else:
            cpf = "".join(c for c in str(dados.get("cpf") or "") if c.isdigit())
            if not cpf:
                raise serializers.ValidationError({"cpf": "Informe o CPF do responsável."})
            # Com o CPF completo a escola acha o cadastro mesmo se o outro filho estuda em outra escola.
            responsavel = Responsavel.objects.filter(cpf=cpf).first()
            if responsavel is None:
                nome = (dados.get("nome") or "").strip()
                if not nome:
                    raise serializers.ValidationError(
                        {"nome": "Esse CPF ainda não está cadastrado. Preencha o nome para cadastrar."})
                responsavel = Responsavel(nome=nome, cpf=cpf, telefone=(dados.get("telefone") or "").strip())
                validar(responsavel)
                responsavel.save()
                registrar(request.user, "criou", responsavel)
        vinculo = Vinculo(responsavel=responsavel, aluno=aluno, parentesco=dados.get("parentesco") or "")
        validar(vinculo)
        vinculo.save()
        registrar(request.user, "criou", vinculo)
        return Response(self.get_serializer(aluno).data)

    @action(detail=True, methods=["post"])
    def desvincular_responsavel(self, request, pk=None):
        """POST /api/alunos/1/desvincular_responsavel/ {"responsavel": 3}: desfaz a ligação (o cadastro continua)."""
        aluno = self.get_object()
        vinculo = aluno.vinculos.filter(responsavel_id=request.data.get("responsavel")).select_related(
            "responsavel", "aluno").first()
        if vinculo is None:
            raise serializers.ValidationError({"responsavel": "Esse responsável não está ligado ao aluno."})
        registrar(request.user, "apagou", vinculo)
        vinculo.delete()
        return Response(self.get_serializer(aluno).data)


def responsaveis_visiveis(usuario):
    if eh_secretaria(usuario):
        return Responsavel.objects.all()
    if usuario.perfil == Perfil.RESPONSAVEL:
        return Responsavel.objects.filter(usuario=usuario)
    return Responsavel.objects.filter(alunos__in=alunos_visiveis(usuario)).distinct()


class ResponsavelViewSet(Base):
    serializer_class = ResponsavelSerializer
    permission_classes = ESCOLA_OU_SECRETARIA

    def get_queryset(self):
        responsaveis = responsaveis_visiveis(self.request.user)
        busca = self.request.query_params.get("busca")
        if busca:  # pelo nome do responsável, do aluno ou pelo CPF (só números)
            numeros = "".join(c for c in busca if c.isdigit())
            filtro = Q(nome__icontains=busca) | Q(alunos__nome__icontains=busca)
            if numeros:
                filtro |= Q(cpf__contains=numeros)
            responsaveis = responsaveis.filter(filtro).distinct()
        return responsaveis.order_by("nome")

    @action(detail=True, methods=["post"])
    def vincular(self, request, pk=None):
        """POST /api/responsaveis/1/vincular/ {"aluno": 5, "parentesco": "mae"}"""
        responsavel = self.get_object()
        aluno = alunos_visiveis(request.user).filter(pk=request.data.get("aluno")).first()
        if aluno is None:
            raise serializers.ValidationError({"aluno": "Aluno não encontrado."})
        vinculo = Vinculo(responsavel=responsavel, aluno=aluno, parentesco=request.data.get("parentesco", ""))
        validar(vinculo)
        vinculo.save()
        registrar(request.user, "criou", vinculo)
        return Response(self.get_serializer(responsavel).data)

    @action(detail=True, methods=["post"])
    def criar_acesso(self, request, pk=None):
        responsavel = self.get_object()
        dados = CriarAcessoSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        usuario = criar_login(responsavel, Perfil.RESPONSAVEL, dados.validated_data)
        registrar(request.user, "criou", usuario, tipo="login",
                  descricao=f"Login {usuario.username} de {responsavel.nome}")
        return Response(self.get_serializer(responsavel).data)


# ------------------------------------------------------------------------- matrícula


class MatriculaViewSet(Base):
    serializer_class = MatriculaSerializer
    permission_classes = ESCOLA_OU_SECRETARIA
    filtros = {
        "escola": "escola_id",
        "turma": "turma_id",
        "serie": "serie_id",
        "ano_letivo": "ano_letivo",
        "situacao": "situacao",
        "aluno": "aluno_id",
        "regional": "escola__regional_id",
    }

    def get_queryset(self):
        matriculas = matriculas_visiveis(self.request.user).select_related(
            "aluno", "escola", "serie__curso", "turma__serie"
        )
        if self.request.query_params.get("sem_turma"):  # fila de enturmação (só do ano atual em diante)
            matriculas = matriculas.filter(turma__isnull=True, ano_letivo__gte=timezone.localdate().year).exclude(
                situacao__in=Matricula.SITUACOES_ENCERRADAS)
        busca = self.request.query_params.get("busca")
        if busca:
            matriculas = matriculas.filter(Q(aluno__nome__icontains=busca) | Q(aluno__codigo__icontains=busca))
        return self.aplicar_filtros(matriculas)

    def perform_create(self, serializer):
        conferir_escola(self.request.user, serializer.validated_data["escola"].pk)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        escola = serializer.validated_data.get("escola", serializer.instance.escola)
        conferir_escola(self.request.user, escola.pk)
        super().perform_update(serializer)

    def perform_destroy(self, matricula):
        conferir_escola(self.request.user, matricula.escola_id)
        if matricula.notas.exists() or matricula.presencas.exists():
            raise serializers.ValidationError(
                {"detail": "Esse aluno já tem notas ou chamadas. Em vez de apagar, mude a situação para Cancelada."}
            )
        super().perform_destroy(matricula)

    @action(detail=False, methods=["post"])
    @transaction.atomic
    def nova(self, request):
        """POST /api/matriculas/nova/: cadastra aluno + responsável + matrícula de uma vez."""
        dados = NovaMatriculaSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        d = dados.validated_data
        escola = Escola.objects.filter(pk=d["escola"]).first()
        serie = Serie.objects.filter(pk=d["serie"]).first()
        if escola is None or serie is None:
            raise serializers.ValidationError({"detail": "Escola ou série não encontrada."})
        conferir_escola(request.user, escola.pk)

        aluno = Aluno(
            nome=d["aluno_nome"].strip(), data_nascimento=d["aluno_nascimento"],
            programa_social=d.get("programa_social", ""), nis=d.get("nis", ""),
            necessidade_especial=d.get("necessidade_especial", ""),
        )
        try:
            aluno.full_clean(exclude=["codigo"])
        except DjangoValidationError as erro:
            drf = erros_do_django_para_drf(erro).detail
            nomes = {"nome": "aluno_nome", "data_nascimento": "aluno_nascimento"}
            raise serializers.ValidationError({nomes.get(campo, campo): msg for campo, msg in drf.items()})
        aluno.save()

        if d.get("responsavel_nome"):
            responsavel = Responsavel.objects.filter(
                cpf="".join(c for c in d.get("responsavel_cpf", "") if c.isdigit())
            ).first()
            if responsavel is None:
                responsavel = Responsavel(
                    nome=d["responsavel_nome"].strip(), cpf=d.get("responsavel_cpf", ""),
                    telefone=d.get("responsavel_telefone", ""),
                )
                validar(responsavel, prefixo="responsavel_")
                responsavel.save()
            Vinculo.objects.create(responsavel=responsavel, aluno=aluno, parentesco=d.get("parentesco") or "outro")

        turma = Turma.objects.filter(pk=d.get("turma")).first() if d.get("turma") else None
        matricula = Matricula(
            aluno=aluno, escola=escola, serie=serie, ano_letivo=d["ano_letivo"], turma=turma,
            situacao=d["situacao"],
        )
        validar(matricula)
        matricula.save()
        registrar(request.user, "criou", matricula, descricao=f"Matrícula de {aluno.nome} ({serie.nome}, {escola})")
        return Response(MatriculaSerializer(matricula).data, status=201)


# ---------------------------------------------------------------- diário e chamada


class DoProfessorMixin:
    """Professor só mexe no que é dele; todo mundo lê o que pode ver."""

    def get_serializer_context(self):
        contexto = super().get_serializer_context()
        contexto["professor"] = professor_de(self.request.user)
        return contexto

    def so_os_meus(self, queryset):
        usuario = self.request.user
        if self.request.method not in ("GET", "HEAD", "OPTIONS") and not usuario.is_superuser:
            return queryset.filter(professor__usuario=usuario)
        return queryset

    def perform_create(self, serializer):
        if self.request.user.perfil == Perfil.PROFESSOR and professor_de(self.request.user) is None:
            raise PermissionDenied("Seu login não está ligado a um cadastro de professor no RH.")
        super().perform_create(serializer)


class AulaViewSet(DoProfessorMixin, Base):
    """Diário de classe e chamada. Ver AulaSerializer para o formato da chamada."""

    serializer_class = AulaSerializer
    permission_classes = SO_PROFESSOR
    filtros = {"turma": "turma_id", "materia": "materia_id", "professor": "professor_id", "data": "data",
               "desde": "data__gte", "ate": "data__lte"}

    def get_queryset(self):
        aulas = Aula.objects.filter(turma__in=turmas_visiveis(self.request.user)).select_related(
            "turma__serie", "turma__escola", "materia", "professor"
        ).prefetch_related("presencas")
        return self.so_os_meus(self.aplicar_filtros(aulas))


class NotaViewSet(FiltrosMixin, viewsets.ReadOnlyModelViewSet):
    """GET: notas que você pode ver. POST /api/notas/lancar/: lança as notas da turma."""

    serializer_class = NotaSerializer
    filtros = {"turma": "matricula__turma_id", "materia": "materia_id", "unidade": "unidade",
               "matricula": "matricula_id"}

    def get_queryset(self):
        notas = Nota.objects.filter(matricula__in=matriculas_visiveis(self.request.user))
        return self.aplicar_filtros(notas.select_related("matricula__aluno", "materia"))

    @action(detail=False, methods=["post"])
    @transaction.atomic
    def lancar(self, request):
        """{"turma": 1, "materia": 5, "unidade": 2, "notas": [{"matricula": 9, "valor": "7,5"}, ...]}

        Valor vazio apaga a nota. Se alguma nota der erro, nada é salvo e a resposta diz
        o erro de cada aluno em "alunos": {id da matrícula: mensagem}.
        """
        entrada = LancarNotasSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        d = entrada.validated_data
        turma = Turma.objects.filter(pk=d["turma"]).select_related("serie").first()
        materia = Materia.objects.filter(pk=d["materia"]).first()
        if turma is None or materia is None:
            raise serializers.ValidationError({"detail": "Turma ou matéria não encontrada."})
        lotacao = Lotacao.objects.filter(turma=turma, materia=materia, professor__usuario=request.user).first()
        if lotacao is None and not request.user.is_superuser:
            raise PermissionDenied(f"Você não está lotado em {materia} nessa turma.")
        if lotacao is not None:
            conferir_professor_da_lotacao(request.user, lotacao.professor_id)

        alunos = {m.pk: m for m in turma.matriculas.filter(situacao=Matricula.Situacao.CONFIRMADA).select_related("aluno")}
        erros, mudancas = {}, []
        for item in d["notas"]:
            matricula = alunos.get(item.get("matricula"))
            if matricula is None:
                erros[str(item.get("matricula"))] = "Esse aluno não é dessa turma."
                continue
            bruto = str(item.get("valor") if item.get("valor") is not None else "").strip().replace(",", ".")
            atual = Nota.objects.filter(matricula=matricula, materia=materia, unidade=d["unidade"]).first()
            if bruto == "":
                if atual is not None:
                    validar_unidade_aberta(turma, d["unidade"])
                    mudancas.append({"campo": matricula.aluno.nome, "antes": texto(atual.valor), "depois": "—"})
                    atual.delete()
                continue
            try:
                valor = Decimal(bruto)
            except InvalidOperation:
                erros[str(matricula.pk)] = "Digite um número de 0 a 10."
                continue
            nota = atual or Nota(matricula=matricula, materia=materia, unidade=d["unidade"])
            antes = texto(nota.valor) if atual else "—"
            nota.valor = valor
            nota.lancada_por = lotacao.professor if lotacao else None
            try:
                nota.full_clean()
            except DjangoValidationError as erro:
                erros[str(matricula.pk)] = " ".join(erro.messages)
                continue
            if antes != texto(nota.valor):
                nota.save()
                mudancas.append({"campo": matricula.aluno.nome, "antes": antes, "depois": texto(nota.valor)})

        if erros:
            transaction.set_rollback(True)  # nada é salvo
            return Response({"detail": "Confira as notas marcadas em vermelho.", "alunos": erros}, status=400)
        if mudancas:
            registrar(
                request.user, "editou", tipo="notas",
                descricao=f"Notas da {d['unidade']}ª unidade · {materia} · {turma.serie.nome} {turma.letra}",
                mudancas=mudancas,
            )
        notas = Nota.objects.filter(matricula__turma=turma, materia=materia, unidade=d["unidade"])
        return Response({"salvas": len(mudancas), "notas": NotaSerializer(notas, many=True).data})


def validar_unidade_aberta(turma, unidade):
    if Fechamento.objects.filter(turma=turma, unidade=unidade).exists():
        raise serializers.ValidationError({"detail": f"A {unidade}ª unidade dessa turma já foi fechada."})


class FechamentoViewSet(RegistrarAlteracoesMixin, FiltrosMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin,
                        viewsets.ReadOnlyModelViewSet):
    """Fechar (POST) e reabrir (DELETE) a unidade de uma turma."""

    serializer_class = FechamentoSerializer
    permission_classes = ESCOLA_OU_SECRETARIA
    filtros = {"turma": "turma_id", "unidade": "unidade", "escola": "turma__escola_id"}

    def get_queryset(self):
        fechamentos = Fechamento.objects.filter(turma__in=turmas_visiveis(self.request.user))
        return self.aplicar_filtros(fechamentos.select_related("turma__serie", "fechado_por"))

    def perform_create(self, serializer):
        conferir_escola(self.request.user, serializer.validated_data["turma"].escola_id)
        serializer.validated_data["fechado_por"] = self.request.user
        super().perform_create(serializer)

    def perform_destroy(self, fechamento):
        conferir_escola(self.request.user, fechamento.turma.escola_id)
        if Fechamento.objects.filter(turma=fechamento.turma, unidade__gt=fechamento.unidade).exists():
            raise serializers.ValidationError({"detail": "Reabra primeiro as unidades seguintes."})
        super().perform_destroy(fechamento)


class TarefaViewSet(DoProfessorMixin, Base):
    serializer_class = TarefaSerializer
    permission_classes = SO_PROFESSOR
    filtros = {"turma": "turma_id", "materia": "materia_id"}

    def get_queryset(self):
        tarefas = Tarefa.objects.filter(turma__in=turmas_visiveis(self.request.user)).select_related(
            "turma__serie", "materia", "professor"
        ).prefetch_related("entregas")
        if self.request.user.perfil == Perfil.PROFESSOR:
            tarefas = tarefas.filter(professor__usuario=self.request.user)  # cada professor vê as suas
        return self.so_os_meus(self.aplicar_filtros(tarefas))

    @action(detail=True, methods=["post"])
    def entregas(self, request, pk=None):
        """POST /api/tarefas/1/entregas/ {"matriculas": [ids de quem entregou]} (substitui a lista)."""
        tarefa = self.get_object()
        conferir_professor_da_lotacao(request.user, tarefa.professor_id)
        alunos = set(tarefa.turma.matriculas.values_list("id", flat=True))
        escolhidos = {int(i) for i in request.data.get("matriculas", [])}
        if escolhidos - alunos:
            raise serializers.ValidationError({"matriculas": "Tem aluno que não é dessa turma."})
        tarefa.entregas.exclude(matricula_id__in=escolhidos).delete()
        ja = set(tarefa.entregas.values_list("matricula_id", flat=True))
        Entrega.objects.bulk_create(Entrega(tarefa=tarefa, matricula_id=i) for i in escolhidos - ja)
        registrar(request.user, "editou", tarefa, tipo="entregas",
                  descricao=f"Entregas de \"{tarefa.titulo}\": {len(escolhidos)} aluno(s)")
        return Response(self.get_serializer(tarefa).data)


class PlanoAulaViewSet(DoProfessorMixin, Base):
    serializer_class = PlanoAulaSerializer
    permission_classes = SO_PROFESSOR
    filtros = {"turma": "turma_id", "unidade": "unidade", "status": "status"}

    def get_queryset(self):
        usuario = self.request.user
        planos = PlanoAula.objects.select_related("turma__serie", "materia")
        if usuario.perfil in (Perfil.ALUNO, Perfil.RESPONSAVEL):
            return planos.none()
        planos = planos.filter(turma__in=turmas_visiveis(usuario))
        if usuario.perfil == Perfil.PROFESSOR:
            planos = planos.filter(professor__usuario=usuario)
        return self.so_os_meus(self.aplicar_filtros(planos))


# ----------------------------------------------------------------------- comunicação


def escolas_do_usuario(usuario):
    """Ids das escolas ligadas ao usuário (onde trabalha ou estuda)."""
    if usuario.perfil == Perfil.ESCOLA:
        return {usuario.escola_id}
    return set(turmas_visiveis(usuario).values_list("escola_id", flat=True))


def comunicados_visiveis(usuario):
    """Rede toda + escola e turmas do usuário + os mandados para ele (ou por ele)."""
    comunicados = Comunicado.objects.select_related("autor", "escola", "turma__serie", "turma__escola",
                                                    "destinatario")
    if eh_secretaria(usuario):
        return comunicados
    return comunicados.filter(
        Q(alcance=Comunicado.Alcance.REDE)
        | Q(alcance=Comunicado.Alcance.ESCOLA, escola_id__in=escolas_do_usuario(usuario))
        | Q(alcance=Comunicado.Alcance.TURMA, turma__in=turmas_visiveis(usuario))
        | Q(destinatario=usuario)
        | Q(autor=usuario)
    ).distinct()


class ComunicadoViewSet(Base):
    serializer_class = ComunicadoSerializer
    filtros = {"alcance": "alcance"}

    def get_queryset(self):
        return self.aplicar_filtros(comunicados_visiveis(self.request.user))

    def perform_create(self, serializer):
        self.conferir_alcance(serializer.validated_data)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self.conferir_autor(serializer.instance)
        self.conferir_alcance({**ComunicadoSerializer(serializer.instance).data, **serializer.validated_data})
        super().perform_update(serializer)

    def perform_destroy(self, comunicado):
        self.conferir_autor(comunicado)
        super().perform_destroy(comunicado)

    def conferir_autor(self, comunicado):
        if comunicado.autor_id != self.request.user.pk and not eh_secretaria(self.request.user):
            raise PermissionDenied("Só quem escreveu pode mudar ou apagar o comunicado.")

    def conferir_alcance(self, dados):
        usuario = self.request.user
        alcance = dados.get("alcance")
        if eh_secretaria(usuario):
            return
        if usuario.perfil == Perfil.ESCOLA:
            escola = dados.get("escola")
            turma = dados.get("turma")
            escola_id = getattr(escola, "pk", escola)
            if alcance == Comunicado.Alcance.ESCOLA and escola_id == usuario.escola_id:
                return
            if alcance == Comunicado.Alcance.TURMA and turma is not None and getattr(turma, "escola_id", None) == usuario.escola_id:
                return
            if alcance == Comunicado.Alcance.PESSOA:
                return
            raise PermissionDenied("A escola só manda comunicado para a própria escola ou turmas dela.")
        if usuario.perfil == Perfil.PROFESSOR:
            turma = dados.get("turma")
            if alcance == Comunicado.Alcance.TURMA and turma is not None and turmas_visiveis(usuario).filter(
                pk=getattr(turma, "pk", turma)
            ).exists():
                return
            raise PermissionDenied("O professor só manda comunicado para as turmas onde dá aula.")
        raise PermissionDenied("Seu perfil não envia comunicados.")


# ------------------------------------------------------------------- horário e merenda


class HorarioViewSet(Base):
    """Grade de horários. Todo mundo logado lê; a escola monta a grade dela."""

    serializer_class = HorarioSerializer
    permission_classes = ESCOLA_OU_SECRETARIA
    filtros = {"turma": "lotacao__turma_id", "escola": "lotacao__turma__escola_id",
               "professor": "lotacao__professor_id", "dia": "dia_semana"}

    def get_queryset(self):
        return self.aplicar_filtros(Horario.objects.select_related(
            "lotacao__turma__serie", "lotacao__turma__escola", "lotacao__materia", "lotacao__professor"
        ))

    def perform_create(self, serializer):
        conferir_escola(self.request.user, serializer.validated_data["lotacao"].turma.escola_id)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        conferir_escola(self.request.user, serializer.instance.lotacao.turma.escola_id)
        lotacao = serializer.validated_data.get("lotacao")
        if lotacao is not None:
            conferir_escola(self.request.user, lotacao.turma.escola_id)
        super().perform_update(serializer)

    def perform_destroy(self, horario):
        conferir_escola(self.request.user, horario.lotacao.turma.escola_id)
        super().perform_destroy(horario)


class CardapioViewSet(Base):
    serializer_class = CardapioSerializer
    permission_classes = ESCOLA_OU_SECRETARIA
    queryset = Cardapio.objects.all()
    filtros = {"escola": "escola_id"}

    def perform_create(self, serializer):
        conferir_escola(self.request.user, serializer.validated_data["escola"].pk)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        conferir_escola(self.request.user, serializer.instance.escola_id)
        super().perform_update(serializer)

    def perform_destroy(self, cardapio):
        conferir_escola(self.request.user, cardapio.escola_id)
        super().perform_destroy(cardapio)

