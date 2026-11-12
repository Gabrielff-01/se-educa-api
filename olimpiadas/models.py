"""Olimpíadas escolares (diferencial pedido pelo mentor em 10/11).

A escola cadastra a olimpíada (ex.: "Olimpíada de Matemática do Atheneu"), os alunos se inscrevem
(ou a escola inscreve), a escola lança a nota de cada um e publica o resultado: a classificação
sai sozinha, ordenada pela nota, e os primeiros colocados ganham medalha (ouro, prata e bronze).

Andamento: inscrições abertas -> em andamento (inscrições fechadas, lançando notas) -> resultado publicado.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from academico.models import Aluno, Matricula
from rede.models import Escola, Materia, Serie


class Olimpiada(models.Model):
    class Status(models.TextChoices):
        INSCRICOES = "inscricoes", "Inscrições abertas"
        ANDAMENTO = "andamento", "Em andamento"
        RESULTADO = "resultado", "Resultado publicado"

    escola = models.ForeignKey(Escola, verbose_name="escola", on_delete=models.PROTECT, related_name="olimpiadas")
    nome = models.CharField(verbose_name="nome", max_length=120, help_text="Ex.: Olimpíada de Matemática do Atheneu")
    materia = models.ForeignKey(Materia, verbose_name="matéria", on_delete=models.PROTECT, null=True, blank=True,
                                related_name="olimpiadas", help_text="Em branco = conhecimentos gerais.")
    descricao = models.TextField(verbose_name="como funciona", blank=True)
    ano_letivo = models.PositiveSmallIntegerField(verbose_name="ano letivo",
                                                  validators=[MinValueValidator(2000), MaxValueValidator(2100)])
    data_prova = models.DateField(verbose_name="data da prova")
    series = models.ManyToManyField(Serie, verbose_name="séries que podem participar", blank=True,
                                    related_name="olimpiadas", help_text="Nenhuma marcada = todas as séries.")
    nota_maxima = models.DecimalField(verbose_name="nota máxima", max_digits=5, decimal_places=1, default=Decimal("10"),
                                      validators=[MinValueValidator(Decimal("1"))])
    premiados = models.PositiveSmallIntegerField(verbose_name="quantos ganham medalha", default=3,
                                                 validators=[MinValueValidator(1), MaxValueValidator(20)])
    status = models.CharField(verbose_name="andamento", max_length=12, choices=Status.choices, default=Status.INSCRICOES)
    criada_por = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="criada por", on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    criada_em = models.DateTimeField(verbose_name="criada em", auto_now_add=True)
    resultado_em = models.DateTimeField(verbose_name="resultado publicado em", null=True, blank=True)

    class Meta:
        ordering = ["-data_prova", "nome"]
        verbose_name = "olimpíada"
        verbose_name_plural = "olimpíadas"

    def __str__(self):
        return f"{self.nome} ({self.escola})"

    def aceita_serie(self, serie_id):
        series = [serie.pk for serie in self.series.all()]
        return not series or serie_id in series

    def matricula_valida(self, aluno):
        """A matrícula do aluno nesta escola e neste ano (confirmada), ou None."""
        return (Matricula.objects.filter(aluno=aluno, escola_id=self.escola_id, ano_letivo=self.ano_letivo,
                                         situacao=Matricula.Situacao.CONFIRMADA)
                .select_related("serie", "turma__serie").first())

    def classificacao(self):
        """Participações em ordem de nota, com posição (empate divide a posição: 1º, 2º, 2º, 4º)
        e medalha para quem ficou até a posição "premiados". Quem ficou sem nota vai pro fim."""
        participacoes = list(self.participacoes.select_related("aluno", "matricula__turma__serie", "matricula__serie"))
        com_nota = sorted([p for p in participacoes if p.nota is not None], key=lambda p: (-p.nota, p.aluno.nome))
        sem_nota = sorted([p for p in participacoes if p.nota is None], key=lambda p: p.aluno.nome)
        medalhas = {1: "ouro", 2: "prata", 3: "bronze"}
        anterior, posicao = None, 0
        for indice, participacao in enumerate(com_nota, start=1):
            if participacao.nota != anterior:
                posicao, anterior = indice, participacao.nota
            participacao.posicao = posicao
            participacao.medalha = (medalhas.get(posicao, "destaque") if posicao <= self.premiados else "")
        for participacao in sem_nota:
            participacao.posicao, participacao.medalha = None, ""
        return com_nota + sem_nota


class Participacao(models.Model):
    olimpiada = models.ForeignKey(Olimpiada, verbose_name="olimpíada", on_delete=models.CASCADE,
                                  related_name="participacoes")
    aluno = models.ForeignKey(Aluno, verbose_name="aluno", on_delete=models.CASCADE, related_name="olimpiadas")
    matricula = models.ForeignKey(Matricula, verbose_name="matrícula", on_delete=models.CASCADE, related_name="+")
    nota = models.DecimalField(verbose_name="nota", max_digits=5, decimal_places=1, null=True, blank=True,
                               validators=[MinValueValidator(Decimal("0"))])
    inscrita_em = models.DateTimeField(verbose_name="inscrito em", auto_now_add=True)

    class Meta:
        ordering = ["olimpiada", "aluno__nome"]
        verbose_name = "participação"
        verbose_name_plural = "participações"
        constraints = [models.UniqueConstraint(fields=["olimpiada", "aluno"], name="uma_participacao_por_aluno",
                                               violation_error_message="Esse aluno já está inscrito nessa olimpíada.")]

    def clean(self):
        super().clean()
        if self.nota is not None and self.olimpiada_id and self.nota > self.olimpiada.nota_maxima:
            raise ValidationError({"nota": f"A nota máxima desta olimpíada é {self.olimpiada.nota_maxima}."})

    def __str__(self):
        return f"{self.aluno} - {self.olimpiada.nome}"
