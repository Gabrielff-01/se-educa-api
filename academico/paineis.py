"""Telas de resumo: boletim, frequência, painéis da escola, da rede e do RH.

Aqui nada é cadastrado: só junta e calcula o que já está no banco. Por isso são
funções simples com @api_view (só GET), e não ViewSets.
"""

from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from calendario.models import UNIDADES_POR_ANO, calendario_da_escola
from contas.models import Usuario
from contas.permissoes import eh_do_setor
from documentos.models import Documento
from rede.models import Escola, Regional, Turma
from rh.models import Afastamento, Alocacao, Lotacao, Professor, matriz_da_turma
from solicitacoes.models import Mensagem

from .acesso import aluno_pedido, alunos_visiveis, eh_secretaria, pode_cuidar_da_escola, professor_de
from .models import (
    Aluno,
    Aula,
    Fechamento,
    Matricula,
    Nota,
    Presenca,
    Tarefa,
    notas_faltando,
    situacao_pela_media,
)
from .views import comunicados_visiveis

Perfil = Usuario.Perfil
CONFIRMADA = Matricula.Situacao.CONFIRMADA


def hoje():
    return timezone.localdate()


def uma_casa(valor):
    """Decimal com 1 casa (7.25 -> 7.3), ou None."""
    if valor is None:
        return None
    return Decimal(valor).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def porcentagem(parte, total):
    return round(parte * 100 / total, 1) if total else None


def nome_turma(turma):
    return f"{turma.serie.nome} {turma.letra}" if turma else None


def unidade_atual(turma):
    calendario = calendario_da_escola(turma.escola, turma.ano_letivo)
    return calendario.unidade_em(hoje()) if calendario else 1


def escola_pedida(request):
    """A escola da tela: a do usuário da escola, ou ?escola=ID (Secretaria)."""
    usuario = request.user
    escola_id = request.query_params.get("escola") or usuario.escola_id
    if not escola_id:
        raise NotFound("Escolha uma escola (?escola=ID).")
    if not pode_cuidar_da_escola(usuario, int(escola_id)):
        raise PermissionDenied("Você só pode ver os dados da sua escola.")
    escola = Escola.objects.filter(pk=escola_id).first()
    if escola is None:
        raise NotFound("Escola não encontrada.")
    return escola


def ano_pedido(request):
    return int(request.query_params.get("ano") or hoje().year)


# ----------------------------------------------------------------- aluno e família


def frequencia_da_matricula(matricula, desde=None, ate=None):
    """{id da matéria: (aulas, faltas)} contando só as chamadas em que o aluno estava na turma."""
    presencas = Presenca.objects.filter(matricula=matricula)
    if desde:
        presencas = presencas.filter(aula__data__gte=desde)
    if ate:
        presencas = presencas.filter(aula__data__lte=ate)
    linhas = presencas.values("aula__materia").annotate(
        aulas=Sum("aula__quantidade"), faltas=Sum("aula__quantidade", filter=Q(presente=False))
    )
    return {linha["aula__materia"]: (linha["aulas"] or 0, linha["faltas"] or 0) for linha in linhas}


def boletim_da_matricula(matricula):
    turma = matricula.turma
    matriz = matriz_da_turma(turma) if turma else None
    itens = list(matriz.itens.select_related("materia").order_by("materia__nome")) if matriz else []
    notas = defaultdict(dict)
    for nota in matricula.notas.all():
        notas[nota.materia_id][nota.unidade] = nota.valor
    frequencia = frequencia_da_matricula(matricula)
    professores = defaultdict(list)
    if turma:
        for lotacao in turma.lotacoes.select_related("professor"):
            professores[lotacao.materia_id].append(lotacao.professor.nome)

    materias, medias = [], []
    aulas_total = faltas_total = 0
    for item in itens:
        das_unidades = notas.get(item.materia_id, {})
        media = uma_casa(sum(das_unidades.values()) / len(das_unidades)) if das_unidades else None
        aulas, faltas = frequencia.get(item.materia_id, (0, 0))
        aulas_total += aulas
        faltas_total += faltas
        freq = porcentagem(aulas - faltas, aulas)
        if media is not None:
            medias.append(media)
        materias.append({
            "materia": item.materia_id,
            "materia_nome": item.materia.nome,
            "professores": professores.get(item.materia_id, []),
            "aulas_semanais": item.aulas_semanais,
            "notas": {str(u): das_unidades.get(u) for u in range(1, UNIDADES_POR_ANO + 1)},
            "media": media,
            "aulas": aulas,
            "faltas": faltas,
            "frequencia": freq,
            "situacao": situacao_pela_media(media, len(das_unidades), freq),
        })

    media_geral = uma_casa(sum(medias) / len(medias)) if medias else None
    frequencia_geral = porcentagem(aulas_total - faltas_total, aulas_total)
    fechadas = list(Fechamento.objects.filter(turma=turma).values_list("unidade", flat=True)) if turma else []
    return {
        "matricula": {
            "id": matricula.id, "ano_letivo": matricula.ano_letivo, "escola": matricula.escola_id,
            "escola_nome": matricula.escola.nome,
            "municipio": matricula.escola.municipio, "serie_nome": matricula.serie.nome,
            "curso_nome": matricula.serie.curso.nome, "turma": matricula.turma_id, "turma_nome": nome_turma(turma),
            "turno_nome": turma.get_turno_display() if turma else None, "sala": turma.sala if turma else "",
            "situacao_nome": matricula.get_situacao_display(),
        },
        "unidade_atual": unidade_atual(turma) if turma else 1,
        "unidades_fechadas": sorted(fechadas),
        "materias": materias,
        "media_geral": media_geral,
        "frequencia_geral": frequencia_geral,
        "aulas_total": aulas_total,
        "faltas_total": faltas_total,
        "media_aprovacao": "6.0",
        "frequencia_minima": 75,
    }


def dados_do_aluno(aluno):
    return {
        "id": aluno.id, "nome": aluno.nome, "codigo": aluno.codigo, "idade": aluno.idade,
        "data_nascimento": aluno.data_nascimento, "programa_social": aluno.programa_social,
        "programa_nome": aluno.get_programa_social_display() if aluno.programa_social else "",
    }


@api_view(["GET"])
def meus_alunos(request):
    """GET /api/meus-alunos/: o próprio aluno, os filhos do responsável ou os alunos visíveis (até 50)."""
    alunos = alunos_visiveis(request.user).prefetch_related("vinculos")[:50]
    resposta = []
    for aluno in alunos:
        matricula = aluno.matricula_atual()
        vinculo = next((v for v in aluno.vinculos.all() if v.responsavel.usuario_id == request.user.pk), None)
        resposta.append({
            **dados_do_aluno(aluno),
            "parentesco": vinculo.get_parentesco_display() if vinculo else None,
            "turma_nome": nome_turma(matricula.turma) if matricula else None,
            "escola": matricula.escola_id if matricula else None,
            "escola_nome": matricula.escola.nome if matricula else None,
        })
    return Response(resposta)


@api_view(["GET"])
def boletim(request):
    """GET /api/boletim/?aluno=ID: notas, médias, faltas e frequência do ano atual."""
    aluno = aluno_pedido(request)
    matricula = aluno.matricula_atual()
    if matricula is None:
        return Response({"aluno": dados_do_aluno(aluno), "matricula": None, "materias": []})
    return Response({"aluno": dados_do_aluno(aluno), **boletim_da_matricula(matricula)})


@api_view(["GET"])
def historico(request):
    """GET /api/historico/?aluno=ID: todos os anos do aluno (o atual calculado pelas notas)."""
    aluno = aluno_pedido(request)
    anos = []
    for matricula in aluno.matriculas.select_related("escola", "serie", "turma__serie").order_by("-ano_letivo"):
        if matricula.situacao in Matricula.SITUACOES_ENCERRADAS:
            situacao, media = matricula.get_situacao_display(), None
        elif matricula.resultado_final:
            situacao, media = matricula.get_resultado_final_display(), matricula.media_final
        else:
            dados = boletim_da_matricula(matricula)
            situacao, media = "Cursando", dados["media_geral"]
        anos.append({
            "ano_letivo": matricula.ano_letivo, "serie_nome": matricula.serie.nome,
            "escola_nome": matricula.escola.nome, "media": uma_casa(media), "situacao": situacao,
        })
    return Response({"aluno": dados_do_aluno(aluno), "anos": anos})


def tarefas_do_aluno(matricula):
    entregues = set(matricula.entregas.values_list("tarefa_id", flat=True))
    lista = []
    for tarefa in Tarefa.objects.filter(turma=matricula.turma).select_related("materia", "professor"):
        if tarefa.id in entregues:
            status = "Entregue"
        elif tarefa.prazo < hoje():
            status = "Atrasada"
        else:
            status = "Pendente"
        lista.append({
            "id": tarefa.id, "titulo": tarefa.titulo, "descricao": tarefa.descricao, "prazo": tarefa.prazo,
            "materia_nome": tarefa.materia.nome, "professor_nome": tarefa.professor.nome, "status": status,
        })
    return lista


@api_view(["GET"])
def minhas_tarefas(request):
    """GET /api/minhas-tarefas/?aluno=ID: tarefas da turma com Pendente / Atrasada / Entregue."""
    aluno = aluno_pedido(request)
    matricula = aluno.matricula_atual()
    if matricula is None or matricula.turma is None:
        return Response([])
    return Response(tarefas_do_aluno(matricula))


@api_view(["GET"])
def agenda(request):
    """GET /api/agenda/?ano=2026 (&aluno=ID): eventos do calendário + prazos de tarefas e provas.

    Cada item: {data, fim, titulo, tipo}. tipo: feriado, ferias, recesso, planejamento,
    prova, aula (sábado letivo) ou tarefa.
    """
    usuario = request.user
    ano = ano_pedido(request)
    escola, turmas = None, Turma.objects.none()
    if usuario.perfil in (Perfil.ALUNO, Perfil.RESPONSAVEL):
        matricula = aluno_pedido(request).matricula_atual()
        if matricula:
            escola = matricula.escola
            turmas = Turma.objects.filter(pk=matricula.turma_id)
    elif usuario.perfil == Perfil.PROFESSOR:
        turmas = Turma.objects.filter(lotacoes__professor__usuario=usuario, ano_letivo=ano).distinct()
        escola = turmas.first().escola if turmas.exists() else None
    elif usuario.perfil == Perfil.ESCOLA:
        escola = usuario.escola

    calendario = calendario_da_escola(escola, ano) if escola else calendario_da_escola(None, ano)
    itens = []
    if calendario:
        for evento in calendario.eventos.all():
            itens.append({"data": evento.data_inicio, "fim": evento.data_fim, "titulo": evento.descricao,
                          "tipo": evento.tipo})
        itens.append({"data": calendario.data_inicio, "fim": None, "titulo": "Início das aulas", "tipo": "aula"})
        itens.append({"data": calendario.data_fim, "fim": None, "titulo": "Último dia de aula", "tipo": "aula"})
    for tarefa in Tarefa.objects.filter(turma__in=turmas).select_related("materia", "turma__serie"):
        itens.append({"data": tarefa.prazo, "fim": None, "tipo": "tarefa",
                      "titulo": f"{tarefa.materia}: {tarefa.titulo}" + (
                          f" ({nome_turma(tarefa.turma)})" if usuario.perfil == Perfil.PROFESSOR else "")})
    itens.sort(key=lambda item: item["data"])
    return Response(itens)


# ------------------------------------------------------------------------ professor


def aulas_sem_registro(lotacao, ate):
    """Dias (até "ate") em que a grade tem aula dessa lotação e o diário não tem registro."""
    turma = lotacao.turma
    dias_da_grade = set(lotacao.horarios.values_list("dia_semana", flat=True))
    calendario = calendario_da_escola(turma.escola, turma.ano_letivo)
    if not dias_da_grade or calendario is None:
        return []
    registradas = set(Aula.objects.filter(turma=turma, materia=lotacao.materia).values_list("data", flat=True))
    return [
        dia for dia in calendario.lista_dias_letivos()
        if dia <= ate and dia.isoweekday() in dias_da_grade and dia not in registradas
    ]


def resumo_da_lotacao(lotacao, unidade):
    """Situação do diário e das notas de uma lotação (usado pelo professor e pela escola)."""
    turma = lotacao.turma
    ontem = hoje() - timedelta(days=1)
    faltando = aulas_sem_registro(lotacao, ontem)
    alunos = turma.matriculas.filter(situacao=CONFIRMADA).count()
    # Notas: a unidade anterior que ainda não foi fechada é a que "vence" primeiro.
    unidade_notas = unidade
    if unidade > 1 and not Fechamento.objects.filter(turma=turma, unidade=unidade - 1).exists():
        unidade_notas = unidade - 1
    lancadas = Nota.objects.filter(
        matricula__turma=turma, matricula__situacao=CONFIRMADA, materia=lotacao.materia, unidade=unidade_notas
    ).count()
    ultima = Aula.objects.filter(turma=turma, materia=lotacao.materia).order_by("-data").first()
    atraso = len(faltando)
    return {
        "lotacao": lotacao.id,
        "professor": lotacao.professor_id,
        "professor_nome": lotacao.professor.nome,
        "professor_usuario": lotacao.professor.usuario_id,
        "turma": turma.id,
        "turma_nome": nome_turma(turma),
        "materia": lotacao.materia_id,
        "materia_nome": lotacao.materia.nome,
        "alunos": alunos,
        "aulas_semanais": lotacao.aulas_semanais,
        "tem_grade": lotacao.horarios.exists(),
        "ultima_aula": ultima.data if ultima else None,
        "aulas_sem_registro": atraso,
        "sem_registro_desde": faltando[0] if faltando else None,
        "status_diario": "Em dia" if atraso == 0 else ("Pendente" if atraso < 5 else "Atrasado"),
        "unidade_notas": unidade_notas,
        "notas_lancadas": lancadas,
        "notas_faltando": max(alunos - lancadas, 0),
        # A unidade que está acontecendo agora ainda não venceu: "Em andamento", não é pendência.
        "status_notas": "Em dia" if lancadas >= alunos else (
            "Em andamento" if unidade_notas == unidade else ("Pendente" if lancadas else "Atrasado")),
    }


@api_view(["GET"])
def painel_professor(request):
    """GET /api/painel/professor/: turmas do professor logado, aulas de hoje e pendências."""
    professor = professor_de(request.user)
    if professor is None:
        raise PermissionDenied("Seu login não está ligado a um cadastro de professor no RH.")
    ano = ano_pedido(request)
    dia = hoje().isoweekday()
    lotacoes = professor.lotacoes.filter(turma__ano_letivo=ano).select_related(
        "turma__serie", "turma__escola", "materia", "professor"
    ).order_by("turma__escola__nome", "turma__serie__ordem", "turma__letra")
    turmas, alunos_total, pendencias = [], set(), 0
    for lotacao in lotacoes:
        resumo = resumo_da_lotacao(lotacao, unidade_atual(lotacao.turma))
        horarios_hoje = [f"{h.inicio:%H:%M}" for h in lotacao.horarios.filter(dia_semana=dia)]
        chamada_hoje = Aula.objects.filter(turma=lotacao.turma, materia=lotacao.materia, data=hoje()).exists()
        alunos_total.update(lotacao.turma.matriculas.filter(situacao=CONFIRMADA).values_list("id", flat=True))
        pendencias += (1 if resumo["aulas_sem_registro"] else 0) + (1 if resumo["status_notas"] in ("Pendente", "Atrasado") else 0)
        turmas.append({
            **resumo, "escola_nome": lotacao.turma.escola.nome, "sala": lotacao.turma.sala,
            "horarios_hoje": horarios_hoje, "chamada_hoje": chamada_hoje,
            "unidade_atual": unidade_atual(lotacao.turma),
        })
    hoje_dt = hoje()
    afastamento = professor.afastamentos.filter(inicio__lte=hoje_dt, fim__gte=hoje_dt).first()
    return Response({
        "professor": {
            "id": professor.id, "nome": professor.nome, "carga": professor.carga_horaria_semanal,
            "materias": sorted({lot.materia.nome for lot in lotacoes}),
            "aulas_semanais": professor.aulas_no_ano(ano), "limite_aulas": professor.limite_aulas,
            "afastado_ate": afastamento.fim if afastamento else None,
        },
        "turmas": turmas,
        "totais": {"alunos": len(alunos_total), "turmas": len({t["turma"] for t in turmas}), "pendencias": pendencias},
    })


# --------------------------------------------------------------------------- escola


def frequencia_da_turma(turmas, desde, ate):
    presencas = Presenca.objects.filter(aula__turma__in=turmas, aula__data__gte=desde, aula__data__lte=ate)
    total = presencas.aggregate(aulas=Sum("aula__quantidade"),
                                faltas=Sum("aula__quantidade", filter=Q(presente=False)))
    return porcentagem((total["aulas"] or 0) - (total["faltas"] or 0), total["aulas"] or 0)


@api_view(["GET"])
def painel_escola(request):
    """GET /api/painel/escola/ (?escola=ID para a Secretaria): números da escola no ano."""
    escola = escola_pedida(request)
    ano = ano_pedido(request)
    matriculas = Matricula.objects.filter(escola=escola, ano_letivo=ano)
    turmas = Turma.objects.filter(escola=escola, ano_letivo=ano).select_related("serie").annotate(
        alunos=Count("matriculas", filter=Q(matriculas__situacao=CONFIRMADA))
    ).order_by("serie__curso__ordem", "serie__ordem", "letra")
    lista_turmas = []
    for turma in turmas:
        matriz = matriz_da_turma(turma)
        previstas = (matriz.itens.aggregate(t=Sum("aulas_semanais"))["t"] or 0) if matriz else 0
        lotadas = turma.lotacoes.aggregate(t=Sum("aulas_semanais"))["t"] or 0
        lista_turmas.append({
            "id": turma.id, "nome": nome_turma(turma), "turno_nome": turma.get_turno_display(), "sala": turma.sala,
            "capacidade": turma.capacidade, "alunos": turma.alunos, "aulas_previstas": previstas,
            "aulas_com_professor": lotadas, "professores": turma.lotacoes.values("professor").distinct().count(),
        })
    capacidade = sum(t["capacidade"] for t in lista_turmas)
    enturmados = sum(t["alunos"] for t in lista_turmas)
    return Response({
        "escola": {"id": escola.id, "nome": escola.nome, "municipio": escola.municipio, "inep": escola.codigo_inep},
        "ano_letivo": ano,
        "indicadores": {
            "alunos": matriculas.filter(situacao=CONFIRMADA).count(),
            "em_analise": matriculas.filter(situacao=Matricula.Situacao.EM_ANALISE).count(),
            "aguardando_turma": matriculas.filter(turma__isnull=True).exclude(
                situacao__in=Matricula.SITUACOES_ENCERRADAS).count(),
            "canceladas": matriculas.filter(situacao__in=Matricula.SITUACOES_ENCERRADAS).count(),
            "professores": Professor.objects.filter(lotacoes__turma__in=turmas).distinct().count(),
            "turmas": len(lista_turmas),
            "vagas": max(capacidade - enturmados, 0),
            "frequencia_30_dias": frequencia_da_turma(turmas, hoje() - timedelta(days=30), hoje()),
        },
        "turmas": lista_turmas,
    })


@api_view(["GET"])
def professores_da_escola(request):
    """GET /api/escola/professores/: quem o RH alocou na escola, a função e as turmas de cada um.

    Sem CPF nem matrícula (isso é só com o RH). É a base da tela "Professores e funções" da escola.
    """
    escola = escola_pedida(request)
    ano = ano_pedido(request)
    alocacoes = Alocacao.objects.filter(escola=escola).select_related("professor").order_by("professor__nome")
    lotacoes = Lotacao.objects.filter(turma__escola=escola, turma__ano_letivo=ano).select_related(
        "materia", "turma__serie").annotate(no_quadro=Count("horarios")).order_by(
        "turma__serie__ordem", "turma__letra", "materia__nome")
    por_professor = defaultdict(list)
    for lotacao in lotacoes:
        por_professor[lotacao.professor_id].append(lotacao)
    resposta = []
    for alocacao in alocacoes:
        professor = alocacao.professor
        lista = por_professor.get(professor.id, [])
        afastamento = professor.afastamentos.filter(inicio__lte=hoje(), fim__gte=hoje()).first()
        resposta.append({
            "id": professor.id, "alocacao": alocacao.id, "nome": professor.nome,
            "carga": professor.carga_horaria_semanal, "horas_na_escola": alocacao.horas_semanais,
            "vinculo_nome": professor.get_vinculo_display(),
            "funcao": alocacao.funcao, "funcao_nome": alocacao.get_funcao_display(),
            "portaria_funcao": alocacao.portaria_funcao,
            "materias": sorted({lot.materia.nome for lot in lista}),
            "turmas": sorted({nome_turma(lot.turma) for lot in lista}),
            "aulas_na_escola": sum(lot.aulas_semanais for lot in lista),
            "limite_aulas": alocacao.limite_aulas,
            "lotacoes": [
                {"id": lot.id, "turma": lot.turma_id, "turma_nome": nome_turma(lot.turma), "materia": lot.materia_id,
                 "materia_nome": lot.materia.nome, "aulas_semanais": lot.aulas_semanais, "no_quadro": lot.no_quadro}
                for lot in lista
            ],
            "afastamento": {"tipo_nome": afastamento.get_tipo_display(), "fim": afastamento.fim} if afastamento else None,
        })
    return Response(resposta)


@api_view(["GET"])
def diario_da_escola(request):
    """GET /api/escola/diario/: diário e notas de cada professor x turma x matéria (supervisão e pendências)."""
    escola = escola_pedida(request)
    ano = ano_pedido(request)
    lotacoes = Lotacao.objects.filter(turma__escola=escola, turma__ano_letivo=ano).select_related(
        "professor", "materia", "turma__serie", "turma__escola"
    ).order_by("professor__nome", "turma__serie__ordem", "turma__letra")
    return Response([resumo_da_lotacao(lotacao, unidade_atual(lotacao.turma)) for lotacao in lotacoes])


@api_view(["GET"])
def boletins_da_escola(request):
    """GET /api/escola/boletins/?unidade=3: quanto das notas já foi lançado em cada turma."""
    escola = escola_pedida(request)
    ano = ano_pedido(request)
    turmas = Turma.objects.filter(escola=escola, ano_letivo=ano).select_related("serie", "escola").order_by(
        "serie__curso__ordem", "serie__ordem", "letra")
    resposta = []
    for turma in turmas:
        atual = unidade_atual(turma)
        fechadas = set(turma.fechamentos.values_list("unidade", flat=True))
        unidade = int(request.query_params.get("unidade") or next(
            (u for u in range(1, UNIDADES_POR_ANO + 1) if u not in fechadas), UNIDADES_POR_ANO))
        alunos = turma.matriculas.filter(situacao=CONFIRMADA).count()
        materias = turma.lotacoes.values("materia").distinct().count()
        esperadas = alunos * materias
        lancadas = Nota.objects.filter(matricula__turma=turma, matricula__situacao=CONFIRMADA, unidade=unidade,
                                       materia__lotacoes__turma=turma).distinct().count()
        faltando = notas_faltando(turma, unidade)
        resposta.append({
            "turma": turma.id, "turma_nome": nome_turma(turma), "unidade": unidade, "unidade_atual": atual,
            "alunos": alunos, "notas_esperadas": esperadas, "notas_lancadas": lancadas,
            "porcentagem": porcentagem(lancadas, esperadas) or 0, "faltando": [
                {"materia": materia, "alunos": quantos} for materia, quantos in faltando],
            "fechada": unidade in fechadas, "unidades_fechadas": sorted(fechadas),
            "pode_fechar": unidade not in fechadas and not faltando and alunos > 0 and (
                unidade == 1 or (unidade - 1) in fechadas),
        })
    return Response(resposta)


@api_view(["GET"])
def programas_sociais(request):
    """GET /api/escola/programas/?mes=2026-09: frequência do mês de quem tem Bolsa Família ou Pé-de-Meia."""
    escola = escola_pedida(request)
    mes = request.query_params.get("mes") or f"{hoje():%Y-%m}"
    ano, numero = (int(parte) for parte in mes.split("-"))
    inicio = hoje().replace(year=ano, month=numero, day=1)
    fim = (inicio.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    matriculas = Matricula.objects.filter(
        escola=escola, ano_letivo=ano, situacao=CONFIRMADA, aluno__programa_social__gt=""
    ).select_related("aluno", "turma__serie")
    resposta = []
    for matricula in matriculas:
        frequencia = frequencia_da_matricula(matricula, desde=inicio, ate=fim)
        aulas = sum(a for a, _ in frequencia.values())
        faltas = sum(f for _, f in frequencia.values())
        minimo = Aluno.FREQUENCIA_DO_PROGRAMA[matricula.aluno.programa_social]
        freq = porcentagem(aulas - faltas, aulas)
        if freq is None:
            status = "Sem aulas"
        elif freq < minimo:
            status = "Risco"
        elif freq < minimo + 3:
            status = "Atenção"
        else:
            status = "Regular"
        resposta.append({
            "aluno": matricula.aluno_id, "nome": matricula.aluno.nome, "nis": matricula.aluno.nis,
            "turma_nome": nome_turma(matricula.turma), "programa": matricula.aluno.programa_social,
            "programa_nome": matricula.aluno.get_programa_social_display(), "minimo": minimo,
            "aulas": aulas, "faltas": faltas, "frequencia": freq, "status": status,
        })
    resposta.sort(key=lambda linha: (linha["frequencia"] is None, linha["frequencia"] or 0))
    return Response({"mes": mes, "inicio": inicio, "fim": fim, "alunos": resposta})


# ---------------------------------------------------------------------------- rede


def so_secretaria(request):
    if not eh_secretaria(request.user):
        raise PermissionDenied("Só a Secretaria vê os números da rede.")


@api_view(["GET"])
def rede_matriculas(request):
    """GET /api/rede/matriculas/: matrículas, vagas e fila de enturmação por regional."""
    so_secretaria(request)
    ano = ano_pedido(request)
    resposta = []
    for regional in Regional.objects.all():
        matriculas = Matricula.objects.filter(escola__regional=regional, ano_letivo=ano)
        turmas = Turma.objects.filter(escola__regional=regional, ano_letivo=ano).annotate(
            alunos=Count("matriculas", filter=Q(matriculas__situacao=CONFIRMADA)))
        vagas = sum(max(t.capacidade - t.alunos, 0) for t in turmas)
        resposta.append({
            "regional": regional.id, "regional_nome": regional.nome,
            "escolas": regional.escolas.count(),
            "confirmadas": matriculas.filter(situacao=CONFIRMADA).count(),
            "em_analise": matriculas.filter(situacao=Matricula.Situacao.EM_ANALISE).count(),
            "sem_turma": matriculas.filter(turma__isnull=True).exclude(
                situacao__in=Matricula.SITUACOES_ENCERRADAS).count(),
            "vagas": vagas,
        })
    return Response(resposta)


@api_view(["GET"])
def rede_frequencia(request):
    """GET /api/rede/frequencia/: frequência dos últimos 30 dias x 30 dias antes, por regional."""
    so_secretaria(request)
    agora = hoje()
    resposta = []
    for regional in Regional.objects.all():
        turmas = Turma.objects.filter(escola__regional=regional, ano_letivo=agora.year)
        resposta.append({
            "regional": regional.id, "regional_nome": regional.nome,
            "atual": frequencia_da_turma(turmas, agora - timedelta(days=30), agora),
            "anterior": frequencia_da_turma(turmas, agora - timedelta(days=60), agora - timedelta(days=31)),
        })
    return Response(resposta)


def carencias(escolas, ano):
    """Aulas da matriz sem professor + aulas de professor afastado hoje (precisam de substituto)."""
    lista = []
    for turma in Turma.objects.filter(escola__in=escolas, ano_letivo=ano).select_related("serie", "escola"):
        matriz = matriz_da_turma(turma)
        if matriz is None:
            continue
        lotadas = defaultdict(int)
        for lotacao in turma.lotacoes.select_related("professor"):
            lotadas[lotacao.materia_id] += lotacao.aulas_semanais
            afastamento = lotacao.professor.afastamentos.filter(inicio__lte=hoje(), fim__gte=hoje()).first()
            if afastamento:
                lista.append({
                    "tipo": "substituicao", "escola_nome": turma.escola.nome, "turma": turma.id,
                    "turma_nome": nome_turma(turma), "materia_nome": lotacao.materia.nome,
                    "aulas": lotacao.aulas_semanais, "professor_nome": lotacao.professor.nome,
                    "motivo": f"{afastamento.get_tipo_display()} até {afastamento.fim:%d/%m/%Y}",
                })
        for item in matriz.itens.select_related("materia"):
            faltam = item.aulas_semanais - lotadas.get(item.materia_id, 0)
            if faltam > 0:
                lista.append({
                    "tipo": "sem_professor", "escola_nome": turma.escola.nome, "turma": turma.id,
                    "turma_nome": nome_turma(turma), "materia_nome": item.materia.nome, "aulas": faltam,
                    "professor_nome": None, "motivo": "Sem professor na turma",
                })
    return lista


@api_view(["GET"])
def rede_carga_horaria(request):
    """GET /api/rede/carga-horaria/: dias letivos e cobertura das aulas da matriz em cada escola."""
    so_secretaria(request)
    ano = ano_pedido(request)
    resposta = []
    for escola in Escola.objects.filter(ativa=True).select_related("regional"):
        turmas = Turma.objects.filter(escola=escola, ano_letivo=ano)
        previstas = lotadas = 0
        for turma in turmas:
            matriz = matriz_da_turma(turma)
            previstas += (matriz.itens.aggregate(t=Sum("aulas_semanais"))["t"] or 0) if matriz else 0
            lotadas += turma.lotacoes.aggregate(t=Sum("aulas_semanais"))["t"] or 0
        calendario = calendario_da_escola(escola, ano)
        resposta.append({
            "escola": escola.id, "escola_nome": escola.nome, "regional_nome": escola.regional.nome,
            "turmas": turmas.count(),
            "dias_letivos": calendario.dias_letivos if calendario else None,
            "aulas_previstas": previstas, "aulas_com_professor": min(lotadas, previstas),
            "cobertura": porcentagem(min(lotadas, previstas), previstas),
        })
    return Response(resposta)


# ------------------------------------------------------------------------------ RH


@api_view(["GET"])
def rh_carencias(request):
    """GET /api/rh/carencias/ (?escola=ID): onde falta professor."""
    so_secretaria(request)
    escolas = Escola.objects.all()
    if request.query_params.get("escola"):
        escolas = escolas.filter(pk=request.query_params["escola"])
    return Response(carencias(escolas, ano_pedido(request)))


@api_view(["GET"])
def rh_painel(request):
    """GET /api/rh/painel/: números do quadro de professores."""
    so_secretaria(request)
    ano = ano_pedido(request)
    professores = list(Professor.objects.filter(ativo=True).annotate(escolas=Count("alocacoes")))
    perto, sem_escola = [], []
    for professor in professores:
        aulas = professor.aulas_no_ano(ano)
        if professor.escolas == 0:
            sem_escola.append(professor.nome)  # o RH ainda não alocou em nenhuma escola
        elif aulas >= professor.limite_aulas * 0.8:
            perto.append({"nome": professor.nome, "aulas": aulas, "limite": professor.limite_aulas})
    lista = carencias(Escola.objects.all(), ano)
    return Response({
        "professores": len(professores),
        "carga_20h": sum(1 for p in professores if p.carga_horaria_semanal == 20),
        "carga_40h": sum(1 for p in professores if p.carga_horaria_semanal == 40),
        "efetivos": sum(1 for p in professores if p.vinculo == Professor.Vinculo.EFETIVO),
        "temporarios": sum(1 for p in professores if p.vinculo == Professor.Vinculo.TEMPORARIO),
        "afastados_hoje": Afastamento.objects.filter(inicio__lte=hoje(), fim__gte=hoje()).count(),
        "perto_do_limite": perto,
        "sem_escola": sem_escola,
        "aulas_sem_professor": sum(c["aulas"] for c in lista if c["tipo"] == "sem_professor"),
        "aulas_para_substituir": sum(c["aulas"] for c in lista if c["tipo"] == "substituicao"),
    })


# -------------------------------------------------------------------- notificações


@api_view(["GET", "POST"])
def notificacoes(request):
    """GET /api/notificacoes/: o que aconteceu nos últimos 30 dias. POST: marca tudo como lido."""
    usuario = request.user
    if request.method == "POST":
        usuario.notificacoes_vistas_em = timezone.now()
        usuario.save(update_fields=["notificacoes_vistas_em"])
        return Response({"ok": True})

    desde = timezone.now() - timedelta(days=30)
    itens = []
    if usuario.perfil in (Perfil.ALUNO, Perfil.RESPONSAVEL):
        for aluno in alunos_visiveis(usuario):
            prefixo = f"{aluno.nome.split()[0]} · " if usuario.perfil == Perfil.RESPONSAVEL else ""
            for nota in Nota.objects.filter(matricula__aluno=aluno, atualizada_em__gte=desde).select_related("materia"):
                itens.append({"id": f"nota-{nota.id}", "tipo": "nota", "quando": nota.atualizada_em,
                              "titulo": f"{prefixo}Nota lançada",
                              "texto": f"{nota.materia} · {nota.unidade}ª unidade: {str(uma_casa(nota.valor)).replace('.', ',')}",
                              "tela": "notas"})
            faltas = Presenca.objects.filter(matricula__aluno=aluno, presente=False,
                                             aula__data__gte=desde.date()).select_related("aula__materia")
            for presenca in faltas:
                aula = presenca.aula
                quando = timezone.make_aware(datetime.combine(aula.data, time(7, 0)))
                itens.append({"id": f"falta-{presenca.id}", "tipo": "falta", "quando": quando,
                              "titulo": f"{prefixo}Falta registrada", "texto": f"{aula.materia} · {aula.data:%d/%m}",
                              "tela": "frequencia"})
            matricula = aluno.matricula_atual()
            if matricula and matricula.turma_id:
                for tarefa in Tarefa.objects.filter(turma_id=matricula.turma_id, criada_em__gte=desde).select_related("materia"):
                    itens.append({"id": f"tarefa-{tarefa.id}", "tipo": "tarefa", "quando": tarefa.criada_em,
                                  "titulo": f"{prefixo}Nova tarefa",
                                  "texto": f"{tarefa.materia}: {tarefa.titulo} (até {tarefa.prazo:%d/%m})",
                                  "tela": "tarefas"})
    itens += avisos_de_pedidos(usuario, desde)
    itens += avisos_de_documentos(usuario, desde)
    for comunicado in comunicados_visiveis(usuario).filter(criado_em__gte=desde).exclude(autor=usuario)[:30]:
        itens.append({"id": f"comunicado-{comunicado.id}", "tipo": "comunicado", "quando": comunicado.criado_em,
                      "titulo": comunicado.titulo, "texto": comunicado.texto[:140], "tela": "comunicados"})

    vistas = usuario.notificacoes_vistas_em
    for item in itens:
        item["nova"] = vistas is None or item["quando"] > vistas
    itens.sort(key=lambda item: item["quando"], reverse=True)
    return Response(itens[:60])


def avisos_de_pedidos(usuario, desde):
    """Pedidos escola ↔ DIES: avisa quando o outro lado escreveu (ou quando o pedido foi atendido/recusado)."""
    if eh_do_setor(usuario, "dies"):
        # Para a DIES: o que as escolas escreveram.
        mensagens = Mensagem.objects.filter(autor__perfil=Perfil.ESCOLA)
        tela = "diesPedidos"
    elif usuario.perfil == Perfil.ESCOLA and usuario.escola_id:
        # Para a escola: respostas da DIES e avisos do sistema nos pedidos dela.
        mensagens = Mensagem.objects.filter(solicitacao__escola_id=usuario.escola_id).exclude(autor__perfil=Perfil.ESCOLA)
        tela = "escPedidos"
    else:
        return []
    mensagens = mensagens.filter(criada_em__gte=desde).select_related(
        "solicitacao__escola", "solicitacao__serie", "solicitacao__turma__serie").order_by("-criada_em")[:30]
    itens = []
    for m in mensagens:
        pedido = m.solicitacao
        titulo = f"{pedido.escola.nome}: pedido à DIES" if tela == "diesPedidos" else "Resposta da DIES"
        itens.append({"id": f"pedido-{m.id}", "tipo": "pedido", "quando": m.criada_em, "titulo": titulo,
                      "texto": f"{pedido.titulo} · {m.texto[:120]}", "tela": tela})
    return itens


def avisos_de_documentos(usuario, desde):
    """Documentos enviados à escola: a escola é avisada do que chegou; a família, da resposta."""
    if usuario.perfil == Perfil.ESCOLA and usuario.escola_id:
        chegaram = Documento.objects.filter(escola_id=usuario.escola_id, enviado_em__gte=desde).defer("arquivo")
        return [
            {"id": f"documento-{d.id}", "tipo": "documento", "quando": d.enviado_em,
             "titulo": "Documento recebido", "texto": f"{d.aluno.nome} · {d.get_tipo_display()}",
             "tela": "escDocumentos"}
            for d in chegaram.select_related("aluno")[:30]
        ]
    if usuario.perfil in (Perfil.ALUNO, Perfil.RESPONSAVEL):
        analisados = Documento.objects.filter(aluno__in=alunos_visiveis(usuario), analisado_em__gte=desde)
        itens = []
        for d in analisados.defer("arquivo").select_related("aluno")[:30]:
            prefixo = f"{d.aluno.nome.split()[0]} · " if usuario.perfil == Perfil.RESPONSAVEL else ""
            situacao = "aceito" if d.status == Documento.Status.ACEITO else "recusado"
            texto = d.get_tipo_display() + (f": {d.resposta}" if d.resposta else "")
            itens.append({"id": f"documento-{d.id}", "tipo": "documento", "quando": d.analisado_em,
                          "titulo": f"{prefixo}Documento {situacao} pela escola", "texto": texto[:160],
                          "tela": "documentos"})
        return itens
    return []
