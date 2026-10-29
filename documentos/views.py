"""API dos documentos enviados à escola.

GET    /api/documentos/              lista (aluno/responsável: os seus; escola: os da escola; Secretaria: todos)
                                     Filtros: ?status= ?tipo= ?aluno=
POST   /api/documentos/              aluno ou responsável envia (formulário com arquivo: multipart/form-data)
GET    /api/documentos/ID/arquivo/   baixa o arquivo (PDF/JPG/PNG)
DELETE /api/documentos/ID/           quem enviou cancela, enquanto a escola não analisou
POST   /api/documentos/ID/aceitar/   escola: {"resposta": "..."} (opcional)
POST   /api/documentos/ID/recusar/   escola: {"resposta": "motivo"} (obrigatório)
GET    /api/documentos/na-chamada/?turma=ID&data=AAAA-MM-DD
                                     professor da turma (e escola): quem tem atestado ou justificativa
                                     ACEITOS cobrindo aquele dia (a tela da chamada pinta de amarelo)
"""

from datetime import date

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from academico.acesso import alunos_visiveis, eh_secretaria, turmas_visiveis
from auditoria.historico import registrar
from config.api import FiltrosMixin
from contas.models import Usuario

from .models import Documento
from .serializers import DocumentoSerializer

Perfil = Usuario.Perfil


def documentos_visiveis(usuario):
    documentos = Documento.objects.all()
    if eh_secretaria(usuario):
        return documentos
    if usuario.perfil == Perfil.ESCOLA:
        return documentos.filter(escola_id=usuario.escola_id)
    if usuario.perfil in (Perfil.ALUNO, Perfil.RESPONSAVEL):
        return documentos.filter(aluno__in=alunos_visiveis(usuario))
    return documentos.none()


class DocumentoViewSet(FiltrosMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                       mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = DocumentoSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filtros = {"status": "status", "tipo": "tipo", "aluno": "aluno"}

    def get_queryset(self):
        documentos = documentos_visiveis(self.request.user).select_related(
            "aluno", "escola", "enviado_por", "analisado_por")
        if self.action != "arquivo":
            documentos = documentos.defer("arquivo")  # a lista não carrega os arquivos (podem ser grandes)
        return self.aplicar_filtros(documentos)

    def create(self, request, *args, **kwargs):
        if request.user.perfil not in (Perfil.ALUNO, Perfil.RESPONSAVEL):
            raise PermissionDenied("Quem envia documentos é o aluno ou o responsável.")
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        aluno = serializer.validated_data["aluno"]
        if not alunos_visiveis(self.request.user).filter(pk=aluno.pk).exists():
            raise PermissionDenied("Você só pode enviar documentos seus ou dos seus filhos.")
        documento = serializer.save(enviado_por=self.request.user)
        registrar(self.request.user, "criou", documento,
                  descricao=f"Enviou {documento.get_tipo_display().lower()} de {documento.aluno} "
                            f"para {documento.escola}")

    def perform_destroy(self, documento):
        if documento.enviado_por_id != self.request.user.pk:
            raise PermissionDenied("Só quem enviou pode cancelar o envio.")
        if documento.status != Documento.Status.AGUARDANDO:
            raise serializers.ValidationError({"detail": "A escola já analisou esse documento."})
        registrar(self.request.user, "apagou", documento, descricao=f"Cancelou o envio: {documento}")
        documento.delete()

    @action(detail=False, methods=["get"], url_path="na-chamada")
    def na_chamada(self, request):
        """Só o resumo (tipo e período), sem o arquivo: o professor não precisa ver o atestado em si."""
        turma = turmas_visiveis(request.user).filter(pk=request.query_params.get("turma") or 0).first()
        if turma is None:
            raise PermissionDenied("Você só pode ver as turmas em que dá aula.")
        try:
            dia = date.fromisoformat(request.query_params.get("data") or "")
        except ValueError:
            raise serializers.ValidationError({"data": "Informe o dia no formato AAAA-MM-DD."})
        documentos = Documento.objects.filter(
            escola_id=turma.escola_id, status=Documento.Status.ACEITO, tipo__in=Documento.COM_PERIODO,
            data_inicio__lte=dia, data_fim__gte=dia,
            aluno__matriculas__turma=turma, aluno__matriculas__situacao="confirmada",
        ).defer("arquivo").distinct().order_by("data_fim")
        resposta = {}
        for documento in documentos:  # se tiver mais de um, fica o que vai até mais longe
            resposta[documento.aluno_id] = {
                "aluno": documento.aluno_id, "tipo": documento.tipo, "tipo_nome": documento.get_tipo_display(),
                "data_inicio": documento.data_inicio, "data_fim": documento.data_fim,
            }
        return Response(list(resposta.values()))

    @action(detail=True, methods=["get"])
    def arquivo(self, request, pk=None):
        documento = self.get_object()
        resposta = HttpResponse(bytes(documento.arquivo), content_type=documento.tipo_arquivo)
        # "inline": o navegador mostra (PDF/foto) em vez de baixar direto.
        nome = documento.nome_arquivo.replace('"', "")
        resposta["Content-Disposition"] = f'inline; filename="{nome}"'
        return resposta

    def analisar(self, request, status):
        documento = self.get_object()
        usuario = request.user
        if not (usuario.is_superuser or (usuario.perfil == Perfil.ESCOLA and usuario.escola_id == documento.escola_id)):
            raise PermissionDenied("Só a escola do aluno analisa os documentos.")
        if documento.status != Documento.Status.AGUARDANDO:
            raise serializers.ValidationError({"detail": f"Esse documento já foi {documento.get_status_display().lower()}."})
        resposta = (request.data.get("resposta") or "").strip()
        if status == Documento.Status.RECUSADO and not resposta:
            raise serializers.ValidationError({"resposta": "Explique o motivo, para a família poder mandar de novo."})
        if len(resposta) > 500:
            raise serializers.ValidationError({"resposta": "Use no máximo 500 caracteres."})
        documento.status = status
        documento.resposta = resposta
        documento.analisado_por = usuario
        documento.analisado_em = timezone.now()
        documento.save(update_fields=["status", "resposta", "analisado_por", "analisado_em"])
        registrar(usuario, "editou", documento,
                  descricao=f"{documento.get_status_display()}: {documento}",
                  mudancas=[{"campo": "situação", "antes": "Aguardando análise",
                             "depois": documento.get_status_display()}])
        return Response(self.get_serializer(documento).data)

    @action(detail=True, methods=["post"])
    def aceitar(self, request, pk=None):
        return self.analisar(request, Documento.Status.ACEITO)

    @action(detail=True, methods=["post"])
    def recusar(self, request, pk=None):
        return self.analisar(request, Documento.Status.RECUSADO)
