from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class Usuario(AbstractUser):
    """Usuário do SE Educa.

    Herda tudo do usuário padrão do Django (username, senha, nome, e-mail...)
    e acrescenta o perfil e, para quem é da Secretaria, o setor.
    """

    class Perfil(models.TextChoices):
        ALUNO = "aluno", "Aluno"
        RESPONSAVEL = "responsavel", "Responsável"
        PROFESSOR = "professor", "Professor"
        ESCOLA = "escola", "Gestão da escola"
        SECRETARIA = "secretaria", "Secretaria"

    class Setor(models.TextChoices):
        DIES = "dies", "DIES"
        DED = "ded", "DED"
        RH = "rh", "RH"

    perfil = models.CharField(max_length=20, choices=Perfil.choices, default=Perfil.ALUNO)
    setor = models.CharField(
        max_length=10,
        choices=Setor.choices,
        blank=True,
        help_text="Só para usuários da Secretaria.",
    )
    escola = models.ForeignKey(
        "rede.Escola",  # em texto: o app rede vem depois do contas
        verbose_name="escola",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usuarios",
        help_text="Escola onde a pessoa estuda ou trabalha. Obrigatória para Gestão da escola.",
    )
    notificacoes_vistas_em = models.DateTimeField(
        verbose_name="viu as notificações em",
        null=True,
        blank=True,
        help_text="O que chegou depois disso aparece como novo.",
    )

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def clean(self):
        super().clean()
        if self.perfil == self.Perfil.SECRETARIA and not self.setor:
            raise ValidationError({"setor": "Usuário da Secretaria precisa de um setor (DIES, DED ou RH)."})
        if self.perfil != self.Perfil.SECRETARIA and self.setor:
            raise ValidationError({"setor": "Só usuários da Secretaria têm setor."})
        if self.perfil == self.Perfil.ESCOLA and not self.escola_id:
            raise ValidationError({"escola": "Usuário da Gestão da escola precisa de uma escola."})

    def __str__(self):
        return self.get_full_name() or self.username
