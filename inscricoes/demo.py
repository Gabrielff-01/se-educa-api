"""Matrículas pela internet de exemplo, esperando a análise da escola. Chamado pelo popular_demo.

Para testar o aviso no login: entre com lucas.andrade@exemplo.com e a senha matricula123.
"""

from datetime import date

from django.contrib.auth.hashers import make_password
from django.db import models

from academico.demo import cpf_ficticio
from contas.models import Usuario
from rede.models import Escola, Turma

from .models import Inscricao

SENHA_DEMO = "matricula123"


def criar_inscricoes_demo(ano):
    if Inscricao.objects.exists():
        return  # já criadas antes: não duplica
    escolas = list(Escola.objects.filter(ofertas__ano_letivo=ano).distinct().order_by("nome"))
    if not escolas:
        return
    pedidos = [
        dict(aluno_nome="Lucas Andrade Menezes", data_nascimento=date(ano - 15, 3, 14), sexo="M", raca="parda",
             cpf=cpf_ficticio("714250368"), bolsa_familia=True, nis="16273849501",
             responsavel_nome="Cristiane Andrade Menezes", responsavel_cpf=cpf_ficticio("508913274"),
             responsavel_parentesco="mae", telefone="(79) 99812-4410", email="lucas.andrade@exemplo.com",
             cep="49025-090", endereco="Rua Exemplo das Flores", numero="120", bairro="Grageru",
             cidade="Aracaju", uf="SE", turno_preferido=Turma.Turno.MATUTINO),
        dict(aluno_nome="Júlia Santos Oliveira", data_nascimento=date(ano - 16, 8, 2), sexo="F", raca="branca",
             cpf=cpf_ficticio("632018457"), bolsa_familia=False, nis="",
             responsavel_nome="Marcos Oliveira Santos", responsavel_cpf=cpf_ficticio("295746813"),
             responsavel_parentesco="pai", telefone="(79) 99633-0187", email="julia.oliveira@exemplo.com",
             cep="49500-000", endereco="Avenida Exemplo Central", numero="45", complemento="Casa B",
             bairro="Centro", cidade="Itabaiana", uf="SE", turno_preferido=""),
    ]
    # Lucas pede vaga no Atheneu (escola1) e Júlia no Murilo Braga (escola3, Itabaiana, onde ela mora),
    # sempre numa série e turno que a escola tem turma. Assim a escola1 e a escola3 já têm pedido pra analisar.
    destinos = [Usuario.objects.filter(username=u).values_list("escola_id", flat=True).first()
                for u in ("escola1", "escola3")]
    for dados, escola_id in zip(pedidos, destinos):
        turno = dados["turno_preferido"]
        turmas = Turma.objects.filter(ano_letivo=ano, escola_id=escola_id, escola__ofertas__ano_letivo=ano,
                                      escola__ofertas__series=models.F("serie"))
        if turno:
            turmas = turmas.filter(turno=turno)
        turma = turmas.select_related("escola", "serie").order_by("serie__curso__ordem", "serie__ordem").first()
        if turma is None:
            continue
        inscricao = Inscricao(**dados, escola=turma.escola, serie=turma.serie, ano_letivo=ano,
                              senha=make_password(SENHA_DEMO))
        inscricao.full_clean()
        inscricao.save()
