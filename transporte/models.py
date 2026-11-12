"""Transporte escolar: as rotas que a ESCOLA cadastra (pedido do mentor: "quem gerou a rota?").

Rota = um veículo fazendo um trajeto num turno (ex.: "Rota 1 · Povoado Pedra Branca", manhã),
com as paradas em ordem e o horário em cada uma. A escola liga cada aluno a uma rota e à parada
onde ele embarca; o aluno e o responsável veem isso na tela Transporte.
"""

import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from academico.models import Aluno, Matricula
from rede.models import Escola, Turma

PLACA = re.compile(r"^[A-Z]{3}-?\d[A-Z0-9]\d{2}$")  # ABC-1234 (antiga) ou ABC1D23 (Mercosul)


def validar_placa(valor):
    if valor and not PLACA.match(valor.strip().upper()):
        raise ValidationError("Placa inválida. Ex.: ABC1D23 (Mercosul) ou ABC-1234.")


class Rota(models.Model):
    class Veiculo(models.TextChoices):
        ONIBUS = "onibus", "Ônibus"
        MICRO = "micro", "Micro-ônibus"
        VAN = "van", "Van"
        OUTRO = "outro", "Outro"

    escola = models.ForeignKey(Escola, verbose_name="escola", on_delete=models.PROTECT, related_name="rotas")
    nome = models.CharField(verbose_name="nome da rota", max_length=100, help_text="Ex.: Rota 1 · Povoado Pedra Branca")
    turno = models.CharField(verbose_name="turno", max_length=10, choices=Turma.Turno.choices)
    veiculo = models.CharField(verbose_name="veículo", max_length=10, choices=Veiculo.choices, default=Veiculo.ONIBUS)
    placa = models.CharField(verbose_name="placa", max_length=8, blank=True, validators=[validar_placa])
    motorista = models.CharField(verbose_name="motorista", max_length=100, blank=True)
    telefone = models.CharField(verbose_name="telefone do motorista", max_length=20, blank=True)
    capacidade = models.PositiveSmallIntegerField(verbose_name="lugares", default=40,
                                                  validators=[MinValueValidator(1), MaxValueValidator(80)])
    ativa = models.BooleanField(verbose_name="rota ativa", default=True)
    observacao = models.TextField(verbose_name="observação", blank=True)
    cadastrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="cadastrada por", on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name="+")
    atualizada_em = models.DateTimeField(verbose_name="atualizada em", auto_now=True)

    class Meta:
        ordering = ["escola__nome", "turno", "nome"]
        verbose_name = "rota de transporte"
        verbose_name_plural = "rotas de transporte"
        constraints = [models.UniqueConstraint(fields=["escola", "nome"], name="rota_nome_unico_na_escola",
                                               violation_error_message="A escola já tem uma rota com esse nome.")]

    def clean(self):
        super().clean()
        if self.placa:
            self.placa = self.placa.strip().upper()

    def __str__(self):
        return f"{self.nome} ({self.escola})"


class Parada(models.Model):
    rota = models.ForeignKey(Rota, verbose_name="rota", on_delete=models.CASCADE, related_name="paradas")
    ordem = models.PositiveSmallIntegerField(verbose_name="ordem")
    local = models.CharField(verbose_name="local", max_length=120, help_text="Ex.: Praça da Igreja (Povoado Pedra Branca)")
    referencia = models.CharField(verbose_name="ponto de referência", max_length=120, blank=True)
    horario = models.TimeField(verbose_name="horário")

    class Meta:
        ordering = ["rota", "ordem"]
        verbose_name = "parada"
        verbose_name_plural = "paradas"

    def __str__(self):
        return f"{self.horario:%H:%M} {self.local}"


class AlunoNaRota(models.Model):
    """O aluno usa esta rota e embarca nesta parada. Cada aluno fica em uma rota só."""

    aluno = models.OneToOneField(Aluno, verbose_name="aluno", on_delete=models.CASCADE, related_name="transporte")
    rota = models.ForeignKey(Rota, verbose_name="rota", on_delete=models.CASCADE, related_name="alunos")
    parada = models.ForeignKey(Parada, verbose_name="parada de embarque", on_delete=models.PROTECT, related_name="alunos")
    desde = models.DateField(verbose_name="desde", auto_now_add=True)

    class Meta:
        ordering = ["rota", "parada__ordem", "aluno__nome"]
        verbose_name = "aluno na rota"
        verbose_name_plural = "alunos nas rotas"

    def clean(self):
        super().clean()
        if not (self.rota_id and self.aluno_id and self.parada_id):
            return
        if self.parada.rota_id != self.rota_id:
            raise ValidationError({"parada": "Essa parada é de outra rota."})
        matricula = self.aluno.matricula_atual()
        if matricula is None or matricula.escola_id != self.rota.escola_id:
            raise ValidationError({"aluno": f"{self.aluno} não tem matrícula ativa em {self.rota.escola}."})
        # Turnos de verdade: aluno da tarde não vai na rota da manhã.
        if matricula.turma_id and matricula.turma.turno != self.rota.turno:
            raise ValidationError({"aluno": f"{self.aluno} estuda no turno {matricula.turma.get_turno_display().lower()}, "
                                            f"e esta rota é do turno {self.rota.get_turno_display().lower()}."})
        ocupados = self.rota.alunos.exclude(pk=self.pk).count()
        if ocupados >= self.rota.capacidade:
            raise ValidationError({"rota": f"A rota está cheia ({self.rota.capacidade} lugares)."})

    def __str__(self):
        return f"{self.aluno} - {self.rota.nome}"
