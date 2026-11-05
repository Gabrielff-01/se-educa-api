"""API da matrícula pela internet.

Sem login (tela de entrada do app):
GET  /api/inscricoes/escolas/        escolas que oferecem séries no ano, com as séries e os turnos
POST /api/inscricoes/                a família envia o pedido; volta o protocolo

DIES:
GET  /api/inscricoes/                lista (?status=aguardando|aprovada|recusada, ?escola=ID)
POST /api/inscricoes/ID/aprovar/     cria aluno, responsável, login e matrícula sem turma (vai pra Enturmação)
POST /api/inscricoes/ID/recusar/     {"motivo": "..."}
"""

from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import Throttled
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from academico.models import Aluno, Matricula, Responsavel, Vinculo
from academico.views import validar
from auditoria.historico import registrar
from config.api import FiltrosMixin
from contas.models import Usuario
from contas.permissoes import eh_do_setor
from rede.models import Escola, Turma

from .models import Inscricao
from .serializers import InscricaoPublicaSerializer, InscricaoSerializer


class SoDies(BasePermission):
    message = "Só o DIES analisa as matrículas feitas pela internet."

    def has_permission(self, request, view):
        return eh_do_setor(request.user, "dies")


class InscricaoViewSet(FiltrosMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                       viewsets.GenericViewSet):
    filtros = {"status": "status", "escola": "escola_id"}
    throttle_scope = "inscricao"  # limite de envios por hora (settings.py), contra robô enchendo a fila

    def get_queryset(self):
        inscricoes = Inscricao.objects.select_related("escola", "serie__curso", "analisada_por", "matricula__turma__serie")
        return self.aplicar_filtros(inscricoes)

    def get_permissions(self):
        if self.action in ("create", "escolas"):
            return [AllowAny()]  # quem se matricula ainda não tem login
        return [SoDies()]

    def get_throttles(self):
        return [ScopedRateThrottle()] if self.action == "create" else []

    def throttled(self, request, wait):
        raise Throttled(wait, detail="Muitos pedidos de matrícula enviados desta rede. Tente de novo mais tarde.")

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
        """Escolas ativas que oferecem alguma série no ano, para a família escolher."""
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
                {serie for oferta in escola.ofertas.all() if oferta.ano_letivo == ano for serie in oferta.series.all()},
                key=lambda s: (s.curso.ordem, s.ordem),
            )
            resultado.append({
                "id": escola.id, "nome": escola.nome, "municipio": escola.municipio, "bairro": escola.bairro,
                "regional_nome": escola.regional.nome,
                "series": [
                    {
                        "id": serie.id, "nome": serie.nome, "curso_nome": serie.curso.nome,
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

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def aprovar(self, request, pk=None):
        inscricao = self.get_object()
        self.so_aguardando(inscricao)

        aluno = Aluno(
            nome=inscricao.aluno_nome.strip(), data_nascimento=inscricao.data_nascimento,
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

        # Matrícula em análise e sem turma: aparece na Enturmação do DIES.
        matricula = Matricula(aluno=aluno, escola=inscricao.escola, serie=inscricao.serie,
                              ano_letivo=inscricao.ano_letivo, situacao=Matricula.Situacao.EM_ANALISE)
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
