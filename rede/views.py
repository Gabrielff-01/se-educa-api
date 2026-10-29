from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from auditoria.historico import RegistrarAlteracoesMixin
from config.api import FiltrosMixin
from contas.permissoes import edicao_do_setor

from .models import Curso, Escola, Materia, Regional, Serie, Turma
from .serializers import (
    CursoSerializer,
    EscolaSerializer,
    MateriaSerializer,
    RegionalSerializer,
    SerieSerializer,
    TurmaSerializer,
)

# Todo mundo logado lê; só o DIES cadastra, edita e apaga.
SO_DIES_EDITA = [edicao_do_setor("dies")]


class RegionalViewSet(RegistrarAlteracoesMixin, viewsets.ModelViewSet):
    queryset = Regional.objects.all()
    serializer_class = RegionalSerializer
    permission_classes = SO_DIES_EDITA


class EscolaViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    queryset = Escola.objects.select_related("regional")
    serializer_class = EscolaSerializer
    permission_classes = SO_DIES_EDITA
    filtros = {"regional": "regional_id", "municipio": "municipio__iexact"}

    @action(detail=False, methods=["get"])
    def rede(self, request):
        """GET /api/escolas/rede/ (?ano=2026): as escolas para a tela "Escolas da rede" (lista e mapa).

        Para todo mundo logado: endereço, contato, cursos oferecidos (DED), turnos e vagas
        por série e turno (vaga = capacidade da turma - alunos confirmados).
        Só a gestão (Secretaria e escolas) recebe também alunos, turmas e servidores.
        """
        from academico.acesso import Perfil, eh_secretaria  # import aqui dentro: academico depende de rede

        ano = int(request.query_params.get("ano") or timezone.localdate().year)
        gestao = eh_secretaria(request.user) or request.user.perfil == Perfil.ESCOLA

        turmas = (
            Turma.objects.filter(ano_letivo=ano, escola__ativa=True)
            .select_related("serie__curso")
            .annotate(alunos=Count("matriculas", filter=Q(matriculas__situacao="confirmada")))
            .order_by("serie__curso__ordem", "serie__ordem", "turno")
        )
        por_escola = {}
        for turma in turmas:
            por_escola.setdefault(turma.escola_id, []).append(turma)
        servidores = dict(
            Escola.objects.annotate(total=Count("alocacoes")).values_list("id", "total")
        ) if gestao else {}

        resultado = []
        escolas = Escola.objects.filter(ativa=True).select_related("regional").prefetch_related(
            "ofertas__series__curso")
        for escola in escolas.order_by("nome"):
            lista = por_escola.get(escola.id, [])
            # Vagas somadas por série + turno (duas turmas de 1ª série de manhã viram uma linha só).
            vagas = {}
            for turma in lista:
                chave = (turma.serie.curso.nome, turma.serie.nome, turma.get_turno_display())
                vagas[chave] = vagas.get(chave, 0) + max(turma.capacidade - turma.alunos, 0)
            cursos = sorted({serie.curso.nome for oferta in escola.ofertas.all() if oferta.ano_letivo == ano
                             for serie in oferta.series.all()})
            item = {
                "id": escola.id, "nome": escola.nome, "dependencia_nome": escola.get_dependencia_display(),
                "regional_nome": escola.regional.nome, "zona": escola.zona, "zona_nome": escola.get_zona_display(),
                "endereco": escola.endereco, "numero": escola.numero, "bairro": escola.bairro,
                "municipio": escola.municipio, "cep_formatado": escola.cep_formatado,
                "telefone": escola.telefone, "email": escola.email,
                "latitude": escola.latitude, "longitude": escola.longitude,
                "cursos": cursos,
                "turnos": sorted({turma.get_turno_display() for turma in lista}),
                "vagas": sum(vagas.values()),
                "vagas_por_serie": [
                    {"curso_nome": curso, "serie_nome": serie, "turno_nome": turno, "vagas": total}
                    for (curso, serie, turno), total in vagas.items()
                ],
            }
            if gestao:
                item.update({
                    "turmas": len(lista),
                    "alunos": sum(turma.alunos for turma in lista),
                    "servidores": servidores.get(escola.id, 0),
                })
            resultado.append(item)
        return Response(resultado)

    @action(detail=True, methods=["get"])
    def ficha(self, request, pk=None):
        """GET /api/escolas/ID/ficha/ (?ano=2026): a ficha da escola, no modelo do site da SEDUC.

        Dados da escola, turmas, equipe diretiva, professores e resoluções (atos do DED).
        Quem vê: a Secretaria (todas) e a gestão da escola (só a dela).
        """
        # Importados aqui dentro porque rh e regulacao dependem de rede (evita import circular).
        from academico.acesso import pode_cuidar_da_escola
        from rh.models import Alocacao

        escola = self.get_object()
        if not pode_cuidar_da_escola(request.user, escola.id):
            raise PermissionDenied("Você só pode ver a ficha da sua escola.")
        hoje = timezone.localdate()
        ano = int(request.query_params.get("ano") or hoje.year)

        turmas = (
            Turma.objects.filter(escola=escola, ano_letivo=ano)
            .select_related("serie__curso")
            .annotate(alunos=Count("matriculas", filter=Q(matriculas__situacao="confirmada")))
            .order_by("serie__curso__ordem", "serie__ordem", "letra")
        )
        lista_turmas = [
            {
                "id": turma.id, "curso_nome": turma.serie.curso.nome, "serie_nome": turma.serie.nome,
                "letra": turma.letra, "turno_nome": turma.get_turno_display(), "sala": turma.sala,
                "alunos": turma.alunos, "capacidade": turma.capacidade,
            }
            for turma in turmas
        ]

        alocacoes = list(escola.alocacoes.select_related("professor"))
        ordem = {funcao: i for i, funcao in enumerate(Alocacao.FUNCOES_DIRETIVAS)}
        equipe = sorted(
            (a for a in alocacoes if a.funcao in ordem), key=lambda a: (ordem[a.funcao], a.professor.nome)
        )
        professores = [a for a in alocacoes if a.funcao == Alocacao.Funcao.PROFESSOR]
        por_vinculo = {}
        for alocacao in alocacoes:
            vinculo = alocacao.professor.get_vinculo_display()
            por_vinculo[vinculo] = por_vinculo.get(vinculo, 0) + 1

        return Response({
            "escola": EscolaSerializer(escola).data,
            "ano": ano,
            "resumo": {
                "turmas": len(lista_turmas),
                "alunos": sum(t["alunos"] for t in lista_turmas),
                "vagas": sum(max(t["capacidade"] - t["alunos"], 0) for t in lista_turmas),
                "servidores": len(alocacoes),
            },
            "turmas": lista_turmas,
            "equipe_diretiva": [
                {"funcao_nome": a.get_funcao_display(), "nome": a.professor.nome, "portaria": a.portaria_funcao}
                for a in equipe
            ],
            "professores": [
                {
                    "nome": a.professor.nome, "vinculo_nome": a.professor.get_vinculo_display(),
                    "horas": a.horas_semanais, "aulas": a.aulas_no_ano(ano),
                    "afastado": a.professor.afastamentos.filter(inicio__lte=hoje, fim__gte=hoje).exists(),
                }
                for a in professores
            ],
            "por_vinculo": [{"vinculo_nome": nome, "total": total} for nome, total in sorted(por_vinculo.items())],
            "resolucoes": [
                {
                    "tipo_nome": ato.get_tipo_display(), "curso_nome": ato.curso.nome if ato.curso else None,
                    "numero": ato.numero, "orgao_emissor": ato.orgao_emissor,
                    "data_publicacao": ato.data_publicacao, "validade": ato.validade, "vigente": ato.vigente,
                }
                for ato in escola.atos.select_related("curso").order_by("-data_publicacao")
            ],
        })


class CursoViewSet(RegistrarAlteracoesMixin, viewsets.ModelViewSet):
    queryset = Curso.objects.prefetch_related("series__curso")
    serializer_class = CursoSerializer
    permission_classes = SO_DIES_EDITA


class SerieViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    queryset = Serie.objects.select_related("curso")
    serializer_class = SerieSerializer
    permission_classes = SO_DIES_EDITA
    filtros = {"curso": "curso_id"}


class MateriaViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    queryset = Materia.objects.all()
    serializer_class = MateriaSerializer
    permission_classes = SO_DIES_EDITA
    filtros = {"area": "area"}


class TurmaViewSet(RegistrarAlteracoesMixin, FiltrosMixin, viewsets.ModelViewSet):
    # "alunos" = quantos alunos com matrícula confirmada estão na turma.
    queryset = Turma.objects.select_related("escola", "serie__curso").annotate(
        alunos=Count("matriculas", filter=Q(matriculas__situacao="confirmada"))
    )
    serializer_class = TurmaSerializer
    permission_classes = SO_DIES_EDITA
    filtros = {
        "escola": "escola_id",
        "serie": "serie_id",
        "ano_letivo": "ano_letivo",
        "turno": "turno",
    }
