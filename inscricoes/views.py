"""API da matrícula pela internet.

Sem login (tela de entrada do app):
POST /api/auth/identificar/          {"usuario"}: CPF, usuário ou e-mail já tem cadastro? (sim = pede a senha;
                                     CPF novo = vai pra matrícula). Fica aqui porque olha alunos e pedidos.
GET  /api/inscricoes/escolas/        escolas com turma no ano, com as séries e os turnos de cada uma
POST /api/inscricoes/                a família envia o pedido; volta o protocolo

Escola (só os pedidos feitos para ela):
GET  /api/inscricoes/                lista (?status=aguardando|aprovada|recusada)
POST /api/inscricoes/ID/aprovar/     {"turma": ID ou nada}: cria aluno, responsável, login e matrícula
                                     (com turma = confirmada; sem turma = em análise, vai pra Enturmação)
POST /api/inscricoes/ID/recusar/     {"motivo": "..."}
O DIES só acompanha (lista e vê todos, sem aprovar).
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from django.db.models import Q
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.exceptions import PermissionDenied, Throttled
from rest_framework.permissions import SAFE_METHODS, AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle

from academico.models import Aluno, Matricula, Responsavel, Vinculo
from academico.views import validar
from auditoria.historico import registrar
from config.api import FiltrosMixin
from contas.models import Usuario
from contas.permissoes import eh_do_setor
from rede.models import Escola, Turma
from rh.models import so_numeros, validar_cpf

from .models import Inscricao
from .serializers import InscricaoPublicaSerializer, InscricaoSerializer


class IdentificarThrottle(SimpleRateThrottle):
    """No máximo X tentativas por hora por IP (settings.py), pra ninguém ficar testando CPFs."""

    scope = "identificar"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([IdentificarThrottle])
def identificar(request):
    """1º passo do login e da matrícula: o que a pessoa digitou (CPF, usuário ou e-mail) já tem cadastro?

    Responde só a situação, nunca o nome ou outro dado pessoal:
    - tem_login: pede a senha;
    - pedido: tem matrícula pela internet esperando ou recusada (entra com o e-mail e a senha do pedido);
    - sem_acesso: o aluno está na rede, mas ainda não tem senha (pede na escola);
    - novo: CPF válido sem cadastro (vai pra matrícula com o CPF preenchido);
    - nao_encontrado: usuário ou e-mail que não existe.
    """
    digitado = str(request.data.get("usuario") or "").strip()
    if not digitado:
        raise serializers.ValidationError({"usuario": "Digite o CPF, o usuário ou o e-mail."})
    numeros = so_numeros(digitado)
    parece_cpf = len(numeros) == 11 and all(c in "0123456789.- " for c in digitado)

    if parece_cpf:
        try:
            validar_cpf(numeros)
        except DjangoValidationError as erro:
            raise serializers.ValidationError({"usuario": erro.messages})
        aluno = Aluno.objects.filter(cpf=numeros).first()
        if aluno and aluno.usuario_id:
            return Response({"situacao": "tem_login", "mensagem": "Verificamos que este CPF já possui cadastro. Digite sua senha."})
        if aluno:
            return Response({"situacao": "sem_acesso", "mensagem": (
                "Verificamos que este CPF já possui cadastro, mas ainda não tem senha. "
                "Peça o acesso na secretaria da escola.")})
        if Inscricao.objects.filter(cpf=numeros).exclude(status=Inscricao.Status.APROVADA).exists():
            return Response({"situacao": "pedido", "mensagem": (
                "Este CPF tem um pedido de matrícula pela internet. Digite a senha que você criou no pedido.")})
        return Response({"situacao": "novo", "cpf": numeros, "mensagem": (
            "Este CPF ainda não tem cadastro no SE Educa. Vamos fazer a matrícula.")})

    if Usuario.objects.filter(Q(username__iexact=digitado) | Q(email__iexact=digitado), is_active=True).exists():
        return Response({"situacao": "tem_login", "mensagem": ""})
    if Inscricao.objects.filter(email__iexact=digitado).exclude(status=Inscricao.Status.APROVADA).exists():
        return Response({"situacao": "pedido", "mensagem": "Digite a senha que você criou no pedido de matrícula."})
    return Response({"situacao": "nao_encontrado", "mensagem": (
        "Não encontramos esse usuário. Confira o que digitou ou, se o aluno ainda não estuda na rede, faça a matrícula.")})


class EscolaAnalisa(BasePermission):
    """A escola escolhida pela família aprova ou recusa. O DIES só acompanha (lê)."""

    message = "Quem analisa a matrícula pela internet é a escola escolhida pela família."

    def has_permission(self, request, view):
        usuario = request.user
        if not usuario.is_authenticated:
            return False
        if usuario.is_superuser or (usuario.perfil == usuario.Perfil.ESCOLA and usuario.escola_id):
            return True
        return request.method in SAFE_METHODS and eh_do_setor(usuario, "dies")


class InscricaoViewSet(FiltrosMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                       viewsets.GenericViewSet):
    filtros = {"status": "status", "escola": "escola_id"}
    throttle_scope = "inscricao"  # limite de envios por hora (settings.py), contra robô enchendo a fila

    def get_queryset(self):
        inscricoes = Inscricao.objects.select_related("escola", "serie__curso", "analisada_por", "matricula__turma__serie")
        usuario = self.request.user
        if usuario.is_authenticated and not usuario.is_superuser and usuario.perfil == usuario.Perfil.ESCOLA:
            inscricoes = inscricoes.filter(escola_id=usuario.escola_id)  # a escola só vê os pedidos dela
        return self.aplicar_filtros(inscricoes)

    def get_permissions(self):
        if self.action in ("create", "escolas"):
            return [AllowAny()]  # quem se matricula ainda não tem login
        return [EscolaAnalisa()]

    def get_throttles(self):
        # Limite de envios por hora (settings.py), contra robô enchendo a fila.
        return [ScopedRateThrottle()] if self.action == "create" else []

    def throttled(self, request, wait):
        raise Throttled(wait, detail="Muitas tentativas desta rede. Tente de novo mais tarde.")

    def get_serializer_class(self):
        return InscricaoPublicaSerializer if self.action == "create" else InscricaoSerializer

    def create(self, request, *args, **kwargs):
        dados = InscricaoPublicaSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        inscricao = dados.save()
        # Só o necessário para a tela de sucesso: nada de devolver os dados pessoais.
        return Response({
            "protocolo": inscricao.protocolo, "aluno_nome": inscricao.aluno_nome,
            "escola_nome": inscricao.escola.nome, "serie_nome": inscricao.serie.nome,
            "curso_nome": inscricao.serie.curso.nome, "email": inscricao.email,
        }, status=201)

    @action(detail=False, methods=["get"])
    def escolas(self, request):
        """Escolas ativas com turma no ano, cada uma com as séries que têm turma e os turnos dessas turmas.

        A tela usa isso de trás pra frente: a família escolhe a série, depois o turno,
        e só então aparecem as escolas que têm turma daquela série naquele turno.
        """
        ano = timezone.localdate().year
        escolas = (Escola.objects.filter(ativa=True, ofertas__ano_letivo=ano).distinct()
                   .select_related("regional").prefetch_related("ofertas__series__curso"))
        turnos = {}
        for turma in Turma.objects.filter(ano_letivo=ano).only("escola_id", "serie_id", "turno"):
            turnos.setdefault((turma.escola_id, turma.serie_id), set()).add(turma.turno)
        nomes_turno = dict(Turma.Turno.choices)
        resultado = []
        for escola in escolas.order_by("municipio", "nome"):
            series = sorted(
                {serie for oferta in escola.ofertas.all() if oferta.ano_letivo == ano for serie in oferta.series.all()
                 if (escola.id, serie.id) in turnos},  # oferece E tem turma (sem turma, o aluno não teria pra onde ir)
                key=lambda s: (s.curso.ordem, s.ordem),
            )
            if not series:
                continue
            resultado.append({
                "id": escola.id, "nome": escola.nome, "municipio": escola.municipio, "bairro": escola.bairro,
                "regional_nome": escola.regional.nome,
                "series": [
                    {
                        "id": serie.id, "nome": serie.nome, "curso_nome": serie.curso.nome,
                        "ordem": serie.curso.ordem * 100 + serie.ordem,  # pra tela listar 1º ano antes do 6º
                        "turnos": [{"valor": t, "nome": nomes_turno[t]}
                                   for t in sorted(turnos.get((escola.id, serie.id), set()))],
                    }
                    for serie in series
                ],
            })
        return Response({"ano_letivo": ano, "escolas": resultado})

    def so_aguardando(self, inscricao):
        if inscricao.status != Inscricao.Status.AGUARDANDO:
            raise serializers.ValidationError({"detail": f"Esse pedido já foi {inscricao.get_status_display().lower()}."})

    def so_a_escola(self, inscricao):
        usuario = self.request.user
        if not usuario.is_superuser and usuario.escola_id != inscricao.escola_id:
            raise PermissionDenied("Quem analisa este pedido é a escola escolhida pela família.")

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def aprovar(self, request, pk=None):
        inscricao = self.get_object()
        self.so_a_escola(inscricao)
        self.so_aguardando(inscricao)

        # A escola pode já escolher a turma (da mesma série e ano). Sem turma, vai pra Enturmação.
        turma = None
        if request.data.get("turma"):
            turma = Turma.objects.filter(pk=request.data["turma"], escola_id=inscricao.escola_id,
                                         serie_id=inscricao.serie_id, ano_letivo=inscricao.ano_letivo).first()
            if turma is None:
                raise serializers.ValidationError({"turma": f"Escolha uma turma de {inscricao.serie.nome} desta escola."})

        aluno = Aluno(
            nome=inscricao.aluno_nome.strip(), data_nascimento=inscricao.data_nascimento, cpf=inscricao.cpf,
            programa_social=Aluno.Programa.BOLSA_FAMILIA if inscricao.bolsa_familia else "", nis=inscricao.nis,
        )
        validar(aluno)
        aluno.save()

        # Irmão já matriculado: o responsável já existe (mesmo CPF) e só ganha mais um vínculo.
        responsavel = Responsavel.objects.filter(cpf=inscricao.responsavel_cpf).first()
        if responsavel is None:
            responsavel = Responsavel(nome=inscricao.responsavel_nome.strip(), cpf=inscricao.responsavel_cpf,
                                      telefone=inscricao.telefone)
            validar(responsavel, prefixo="responsavel_")
            responsavel.save()
        Vinculo.objects.create(responsavel=responsavel, aluno=aluno, parentesco=inscricao.responsavel_parentesco)

        # Login do aluno: o e-mail e a senha que ele escolheu (a senha já está criptografada).
        if Usuario.objects.filter(username__iexact=inscricao.email).exists():
            raise serializers.ValidationError({"detail": f"O e-mail {inscricao.email} já virou login de outra pessoa. "
                                                         "Recuse o pedido explicando que é preciso outro e-mail."})
        primeiro, _, resto = aluno.nome.partition(" ")
        usuario = Usuario(username=inscricao.email, email=inscricao.email, first_name=primeiro, last_name=resto,
                          perfil=Usuario.Perfil.ALUNO, escola=inscricao.escola, password=inscricao.senha)
        usuario.save()
        aluno.usuario = usuario
        aluno.save(update_fields=["usuario"])

        # Com turma: matrícula confirmada. Sem turma: em análise, aparece na Enturmação.
        situacao = Matricula.Situacao.CONFIRMADA if turma else Matricula.Situacao.EM_ANALISE
        matricula = Matricula(aluno=aluno, escola=inscricao.escola, serie=inscricao.serie, turma=turma,
                              ano_letivo=inscricao.ano_letivo, situacao=situacao)
        validar(matricula)
        matricula.save()

        inscricao.status = Inscricao.Status.APROVADA
        inscricao.matricula = matricula
        inscricao.analisada_por = request.user
        inscricao.analisada_em = timezone.now()
        inscricao.senha = ""  # já virou a senha do login; não precisa ficar guardada aqui
        inscricao.save()
        registrar(request.user, "criou", matricula,
                  descricao=f"Aprovou a matrícula pela internet {inscricao.protocolo}: {aluno.nome} "
                            f"({inscricao.serie.nome}, {inscricao.escola})")
        return Response(InscricaoSerializer(inscricao).data)

    @action(detail=True, methods=["post"])
    def recusar(self, request, pk=None):
        inscricao = self.get_object()
        self.so_a_escola(inscricao)
        self.so_aguardando(inscricao)
        motivo = (request.data.get("motivo") or "").strip()
        if not motivo:
            raise serializers.ValidationError({"motivo": "Explique o motivo. A família vê esse texto ao tentar entrar."})
        if len(motivo) > 500:
            raise serializers.ValidationError({"motivo": "Use no máximo 500 caracteres."})
        inscricao.status = Inscricao.Status.RECUSADA
        inscricao.motivo_recusa = motivo
        inscricao.analisada_por = request.user
        inscricao.analisada_em = timezone.now()
        inscricao.save()
        registrar(request.user, "editou", inscricao,
                  descricao=f"Recusou a matrícula pela internet {inscricao.protocolo}: {inscricao.aluno_nome}")
        return Response(InscricaoSerializer(inscricao).data)
