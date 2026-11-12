"""Rotas de exemplo cadastradas pelas escolas. Chamado pelo popular_demo.

- Atheneu (escola1): Rota 1 · Santa Maria, no turno da Ana Beatriz (aluno1), que embarca no Terminal.
- Murilo Braga (escola3, Itabaiana): duas rotas dos povoados.
"""

from datetime import time

from academico.models import Matricula
from contas.models import Usuario

from .models import AlunoNaRota, Parada, Rota


def nova_rota(usuario, nome, turno, paradas, **extra):
    rota = Rota.objects.create(escola=usuario.escola, nome=nome, turno=turno, cadastrada_por=usuario, **extra)
    for ordem, (horario, local, referencia) in enumerate(paradas, start=1):
        Parada.objects.create(rota=rota, ordem=ordem, horario=horario, local=local, referencia=referencia)
    return rota


def colocar_alunos(rota, quantos, primeiro=None):
    """Põe alunos do mesmo turno da rota, espalhados pelas paradas (menos a última, que é a escola)."""
    paradas = list(rota.paradas.order_by("ordem"))[:-1] or list(rota.paradas.all())
    matriculas = (Matricula.objects.filter(escola=rota.escola, situacao=Matricula.Situacao.CONFIRMADA,
                                           turma__turno=rota.turno, aluno__transporte__isnull=True)
                  .select_related("aluno").order_by("aluno__nome"))
    alunos = [m.aluno for m in matriculas[:quantos]]
    if primeiro is not None and primeiro not in alunos and not AlunoNaRota.objects.filter(aluno=primeiro).exists():
        alunos = [primeiro] + alunos[:quantos - 1]
    for indice, aluno in enumerate(alunos):
        AlunoNaRota.objects.create(aluno=aluno, rota=rota, parada=paradas[indice % len(paradas)])


def criar_rotas_demo():
    if Rota.objects.exists():
        return  # já criadas antes: não duplica
    escola1 = Usuario.objects.get(username="escola1")
    escola3 = Usuario.objects.get(username="escola3")
    ana = Usuario.objects.get(username="aluno1").aluno
    matricula_ana = ana.matricula_atual()
    turno_ana = matricula_ana.turma.turno if matricula_ana and matricula_ana.turma_id else "matutino"

    santa_maria = nova_rota(
        escola1, "Rota 1 · Santa Maria", turno_ana, [
            (time(6, 5), "Terminal do Santa Maria", "Ao lado da farmácia"),
            (time(6, 15), "Av. Alexandre Alcino (Conjunto Padre Pedro)", "Ponto de ônibus da praça"),
            (time(6, 30), "Av. Hermes Fontes (Mercado)", "Em frente ao mercado"),
            (time(6, 45), "Colégio Estadual Atheneu Sergipense", "Chegada na escola"),
        ],
        veiculo=Rota.Veiculo.ONIBUS, placa="QPA4E21", motorista="José Carlos Ferreira", telefone="(79) 99901-2233",
        capacidade=40, observacao="A volta sai da escola 15 minutos depois do fim da última aula.",
    )
    colocar_alunos(santa_maria, 8, primeiro=ana)

    for nome, paradas, placa, motorista in [
        ("Rota Povoado Carrilho", [(time(5, 50), "Povoado Carrilho", "Praça da igreja"),
                                   (time(6, 10), "Povoado Mangueira", "Bar do Zé"),
                                   (time(6, 35), "Centro de Excelência Murilo Braga", "Chegada na escola")],
         "RQX2B47", "Antônio Marcos Lima"),
        ("Rota Povoado Terra Vermelha", [(time(6, 0), "Povoado Terra Vermelha", "Posto de saúde"),
                                         (time(6, 25), "Povoado Rio das Pedras", "Ponte"),
                                         (time(6, 40), "Centro de Excelência Murilo Braga", "Chegada na escola")],
         "PTB-8812", "Edvaldo Souza Santos"),
    ]:
        rota = nova_rota(escola3, nome, "matutino", paradas, veiculo=Rota.Veiculo.MICRO, placa=placa,
                         motorista=motorista, telefone="(79) 99877-1020", capacidade=24)
        colocar_alunos(rota, 4)
