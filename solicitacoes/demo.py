"""Pedidos de exemplo da escola1 (Atheneu) para a DIES. Chamado pelo popular_demo."""

from contas.models import Usuario
from rede.models import Escola, Turma

from .models import Mensagem, Solicitacao


def criar_pedidos_demo(ano):
    if Solicitacao.objects.exists():
        return  # já criados antes: não duplica
    atheneu = Escola.objects.filter(codigo_inep="28012345").first()
    escola = Usuario.objects.filter(username="escola1").first()
    dies = Usuario.objects.filter(username="dies1").first()
    primeira = Turma.objects.filter(escola=atheneu, ano_letivo=ano, serie__ordem=1,
                                    serie__curso__nome__icontains="médio").select_related("serie").first()
    if not (atheneu and escola and dies and primeira):
        return

    turma_nova = Solicitacao.objects.create(
        escola=atheneu, tipo=Solicitacao.Tipo.NOVA_TURMA, serie=primeira.serie, turno=Turma.Turno.VESPERTINO,
        capacidade=35, criada_por=escola)
    conversa(turma_nova, [
        (escola, "Temos alunos da 1ª série esperando turma e a A e a B estão no turno da manhã. "
                 "Pedimos abrir uma 1ª série à tarde."),
        (dies, "Recebido. Vocês têm sala livre no vespertino?"),
        (escola, "Sim, a sala 12 fica livre à tarde."),
    ])

    reposicao = Solicitacao.objects.create(
        escola=atheneu, tipo=Solicitacao.Tipo.OUTRO, assunto="Reposição da aula de 28/10 (ponto facultativo)",
        criada_por=escola)
    conversa(reposicao, [
        (escola, "Com o ponto facultativo de 28/10, podemos repor a aula no sábado 07/11?"),
    ])


def conversa(pedido, falas):
    for autor, texto in falas:
        Mensagem.objects.create(solicitacao=pedido, autor=autor, texto=texto)
