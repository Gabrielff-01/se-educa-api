"""Avisos das olimpíadas no sino (GET /api/notificacoes/), para aluno e responsável."""

from academico.acesso import alunos_visiveis
from contas.models import Usuario

from .models import Olimpiada
from .views import olimpiadas_visiveis

Perfil = Usuario.Perfil
MEDALHAS = {"ouro": "medalha de ouro", "prata": "medalha de prata", "bronze": "medalha de bronze", "destaque": "medalha"}


def avisos_de_olimpiadas(usuario, desde):
    if usuario.perfil not in (Perfil.ALUNO, Perfil.RESPONSAVEL):
        return []
    itens = []
    olimpiadas = olimpiadas_visiveis(usuario).select_related("escola")
    for olimpiada in olimpiadas.filter(status=Olimpiada.Status.INSCRICOES, criada_em__gte=desde)[:10]:
        itens.append({"id": f"olimpiada-{olimpiada.id}", "tipo": "olimpiada", "quando": olimpiada.criada_em,
                      "titulo": f"Inscrições abertas: {olimpiada.nome}",
                      "texto": f"Prova em {olimpiada.data_prova:%d/%m} · {olimpiada.escola.nome}", "tela": "olimpiadas"})
    meus = set(alunos_visiveis(usuario).values_list("pk", flat=True))
    for olimpiada in olimpiadas.filter(status=Olimpiada.Status.RESULTADO, resultado_em__gte=desde)[:10]:
        minhas = [p for p in olimpiada.classificacao() if p.aluno_id in meus]
        partes = []
        for p in minhas:
            quem = f"{p.aluno.nome.split()[0]}: " if usuario.perfil == Perfil.RESPONSAVEL else "Você ficou em "
            lugar = f"{p.posicao}º lugar" if p.posicao else "sem nota"
            partes.append(quem + lugar + (f", {MEDALHAS[p.medalha]}" if p.medalha else ""))
        itens.append({"id": f"olimpiada-resultado-{olimpiada.id}", "tipo": "olimpiada", "quando": olimpiada.resultado_em,
                      "titulo": f"Resultado: {olimpiada.nome}",
                      "texto": "; ".join(partes) or "Veja quem ganhou as medalhas.", "tela": "olimpiadas"})
    return itens
