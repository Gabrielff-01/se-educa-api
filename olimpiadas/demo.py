"""Olimpíadas de exemplo. Chamado pelo popular_demo.

- Atheneu (escola1): Olimpíada de Matemática com resultado publicado (a Ana Beatriz, aluno1, ganhou prata)
  e Olimpíada de Ciências com inscrições abertas (a Ana pode se inscrever pelo app).
- Murilo Braga (escola3): Olimpíada de Redação em andamento (a escola ainda vai lançar as notas).
"""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from academico.models import Matricula
from contas.models import Usuario
from rede.models import Materia

from .models import Olimpiada, Participacao


def criar_olimpiadas_demo(ano):
    if Olimpiada.objects.exists():
        return  # já criadas antes: não duplica
    hoje = timezone.localdate()
    escola1 = Usuario.objects.get(username="escola1")
    escola3 = Usuario.objects.get(username="escola3")
    ana = Usuario.objects.get(username="aluno1").aluno

    def alunos_da(escola_id, quantos):
        matriculas = (Matricula.objects.filter(escola_id=escola_id, ano_letivo=ano, situacao=Matricula.Situacao.CONFIRMADA)
                      .select_related("aluno").order_by("aluno__nome"))
        return list(matriculas[:quantos])

    # 1) Matemática no Atheneu: resultado publicado. A Ana fica em 2º (prata).
    matematica = Olimpiada.objects.create(
        escola=escola1.escola, nome="Olimpíada de Matemática do Atheneu", materia=Materia.objects.get(nome="Matemática"),
        descricao="Prova de 20 questões de raciocínio lógico e problemas. Os 3 primeiros ganham medalha e representam a escola na OBMEP.",
        ano_letivo=ano, data_prova=hoje - timedelta(days=12), nota_maxima=Decimal("100"), premiados=3,
        status=Olimpiada.Status.RESULTADO, resultado_em=timezone.now() - timedelta(days=3), criada_por=escola1,
    )
    notas = [Decimal(n) for n in ("95", "88", "88", "81", "74", "70", "62", "55")]
    participantes = [m for m in alunos_da(escola1.escola_id, 12) if m.aluno_id != ana.pk][:len(notas) - 1]
    matricula_ana = Matricula.objects.filter(aluno=ana, ano_letivo=ano, situacao=Matricula.Situacao.CONFIRMADA).first()
    if matricula_ana:
        participantes.insert(1, matricula_ana)  # a Ana fica com a 2ª maior nota
    for matricula, nota in zip(participantes, notas):
        Participacao.objects.create(olimpiada=matematica, aluno=matricula.aluno, matricula=matricula, nota=nota)

    # 2) Ciências no Atheneu: inscrições abertas (sem a Ana, pra ela testar o "Quero participar").
    ciencias = Olimpiada.objects.create(
        escola=escola1.escola, nome="Olimpíada de Ciências da Natureza", materia=Materia.objects.get(nome="Biologia"),
        descricao="Física, Química e Biologia do dia a dia. Prova objetiva no auditório, no turno da manhã.",
        ano_letivo=ano, data_prova=hoje + timedelta(days=20), nota_maxima=Decimal("10"), premiados=3,
        status=Olimpiada.Status.INSCRICOES, criada_por=escola1,
    )
    for matricula in [m for m in alunos_da(escola1.escola_id, 8) if m.aluno_id != ana.pk][:4]:
        Participacao.objects.create(olimpiada=ciencias, aluno=matricula.aluno, matricula=matricula)

    # 3) Redação no Murilo Braga: em andamento (inscrições fechadas, notas por lançar).
    redacao = Olimpiada.objects.create(
        escola=escola3.escola, nome="Olimpíada de Redação", materia=Materia.objects.get(nome="Português"),
        descricao="Tema: \"O Sergipe que eu quero\". Texto dissertativo de até 30 linhas.",
        ano_letivo=ano, data_prova=hoje - timedelta(days=2), nota_maxima=Decimal("10"), premiados=3,
        status=Olimpiada.Status.ANDAMENTO, criada_por=escola3,
    )
    for matricula in alunos_da(escola3.escola_id, 5):
        Participacao.objects.create(olimpiada=redacao, aluno=matricula.aluno, matricula=matricula)
