"""Pedidos da escola para a DIES, com conversa (chat) em cada pedido.

A escola não cria nem muda turma sozinha: quem faz isso é a DIES. Então a escola
abre um pedido (abrir turma nova, mudar a capacidade de uma turma ou outro assunto),
as duas conversam ali e a DIES atende (o sistema já cria/muda a turma) ou recusa.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from rede.models import Escola, Serie, Turma


class Solicitacao(models.Model):
    class Tipo(models.TextChoices):
        NOVA_TURMA = "nova_turma", "Abrir turma nova"
        CAPACIDADE = "capacidade", "Mudar capacidade de turma"
        OUTRO = "outro", "Outro assunto"

    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberto"
        ATENDIDA = "atendida", "Atendido"
        RECUSADA = "recusada", "Recusado"

    escola = models.ForeignKey(Escola, verbose_name="escola", on_delete=models.CASCADE, related_name="solicitacoes")
    tipo = models.CharField(verbose_name="tipo", max_length=12, choices=Tipo.choices)
    # Turma nova: série, turno e capacidade. Mudar capacidade: turma e a capacidade nova.
    serie = models.ForeignKey(Serie, verbose_name="série", on_delete=models.PROTECT, null=True, blank=True)
    turno = models.CharField(verbose_name="turno", max_length=10, choices=Turma.Turno.choices, blank=True)
    turma = models.ForeignKey(Turma, verbose_name="turma", on_delete=models.CASCADE, null=True, blank=True,
                              related_name="solicitacoes")
    capacidade = models.PositiveSmallIntegerField(
        verbose_name="capacidade", null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(60)],
    )
    assunto = models.CharField(verbose_name="assunto", max_length=120, blank=True)
    status = models.CharField(verbose_name="situação", max_length=10, choices=Status.choices, default=Status.ABERTA)
    criada_por = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="criado por", on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    criada_em = models.DateTimeField(verbose_name="criado em", auto_now_add=True)
    atualizada_em = models.DateTimeField(verbose_name="última movimentação", auto_now=True)

    class Meta:
        ordering = ["-atualizada_em"]
        verbose_name = "pedido à DIES"
        verbose_name_plural = "pedidos à DIES"

    def __str__(self):
        return f"{self.titulo} ({self.escola})"

    @property
    def titulo(self):
        if self.tipo == self.Tipo.NOVA_TURMA and self.serie_id:
            return f"Turma nova de {self.serie.nome} ({self.get_turno_display().lower()})"
        if self.tipo == self.Tipo.CAPACIDADE and self.turma_id:
            return f"Capacidade da {self.turma.serie.nome} {self.turma.letra} para {self.capacidade} vagas"
        return self.assunto or self.get_tipo_display()

    def clean(self):
        super().clean()
        erros = {}
        if self.tipo == self.Tipo.NOVA_TURMA:
            if not self.serie_id:
                erros["serie"] = "Escolha a série da turma nova."
            if not self.turno:
                erros["turno"] = "Escolha o turno."
            if not self.capacidade:
                erros["capacidade"] = "Informe quantos alunos a turma deve ter."
        elif self.tipo == self.Tipo.CAPACIDADE:
            if not self.turma_id:
                erros["turma"] = "Escolha a turma."
            elif self.escola_id and self.turma.escola_id != self.escola_id:
                erros["turma"] = "Essa turma não é da sua escola."
            if not self.capacidade:
                erros["capacidade"] = "Informe a capacidade nova."
            elif self.turma_id and self.capacidade == self.turma.capacidade:
                erros["capacidade"] = f"A turma já tem capacidade {self.capacidade}."
        elif self.tipo == self.Tipo.OUTRO and not self.assunto.strip():
            erros["assunto"] = "Escreva o assunto do pedido."
        if erros:
            raise ValidationError(erros)


class Mensagem(models.Model):
    """Uma fala na conversa do pedido (da escola ou da DIES)."""

    solicitacao = models.ForeignKey(Solicitacao, on_delete=models.CASCADE, related_name="mensagens")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="autor", on_delete=models.SET_NULL,
                              null=True, blank=True, related_name="+")
    texto = models.TextField(verbose_name="mensagem", max_length=1000)
    criada_em = models.DateTimeField(verbose_name="enviada em", auto_now_add=True)

    class Meta:
        ordering = ["criada_em", "pk"]
        verbose_name = "mensagem"
        verbose_name_plural = "mensagens"

    def __str__(self):
        return self.texto[:60]
