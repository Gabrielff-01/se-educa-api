from django.conf import settings
from django.db import models


class Registro(models.Model):
    """Uma linha do histórico: quem criou, editou ou apagou o quê, e quando.

    Quem grava é o RegistrarAlteracoesMixin (config/api.py), em toda tela da API.
    """

    class Acao(models.TextChoices):
        CRIOU = "criou", "Criou"
        EDITOU = "editou", "Editou"
        APAGOU = "apagou", "Apagou"

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="usuário",
        on_delete=models.SET_NULL,
        null=True,
        related_name="registros",
    )
    acao = models.CharField(verbose_name="ação", max_length=10, choices=Acao.choices)
    tipo = models.CharField(verbose_name="tipo de cadastro", max_length=60, help_text="Ex.: nota, turma.")
    objeto_id = models.CharField(verbose_name="id", max_length=20)
    descricao = models.CharField(verbose_name="o quê", max_length=200)
    mudancas = models.JSONField(
        verbose_name="mudanças",
        default=list,
        blank=True,
        help_text='Na edição: [{"campo": "nota", "antes": "7,0", "depois": "8,5"}].',
    )
    criado_em = models.DateTimeField(verbose_name="quando", auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-criado_em", "-id"]
        verbose_name = "registro"
        verbose_name_plural = "histórico de alterações"

    def __str__(self):
        return f"{self.usuario} {self.acao} {self.tipo} {self.descricao}"
