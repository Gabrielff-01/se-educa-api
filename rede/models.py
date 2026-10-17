from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models


class Regional(models.Model):
    """Diretoria Regional de Educação (DRE). Ex.: DEA, DRE 01."""

    nome = models.CharField(verbose_name="nome", max_length=60, unique=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "regional"
        verbose_name_plural = "regionais"

    def __str__(self):
        return self.nome


class Escola(models.Model):
    class Dependencia(models.TextChoices):
        ESTADUAL = "estadual", "Estadual"
        MUNICIPAL = "municipal", "Municipal"
        FEDERAL = "federal", "Federal"
        PRIVADA = "privada", "Privada"

    nome = models.CharField(verbose_name="nome", max_length=150)
    codigo_inep = models.CharField(
        verbose_name="código INEP",
        max_length=8,
        unique=True,
        validators=[RegexValidator(r"^28\d{6}$", "O código INEP de Sergipe tem 8 números e começa com 28.")],
    )
    dependencia = models.CharField(
        verbose_name="dependência administrativa",
        max_length=10,
        choices=Dependencia.choices,
        default=Dependencia.ESTADUAL,
    )
    regional = models.ForeignKey(
        Regional,
        verbose_name="regional",
        on_delete=models.PROTECT,
        related_name="escolas",
    )
    municipio = models.CharField(verbose_name="município", max_length=80)
    bairro = models.CharField(verbose_name="bairro", max_length=80, blank=True)
    endereco = models.CharField(verbose_name="endereço", max_length=200, blank=True)
    latitude = models.FloatField(verbose_name="latitude", null=True, blank=True)
    longitude = models.FloatField(verbose_name="longitude", null=True, blank=True)
    ativa = models.BooleanField(verbose_name="ativa", default=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "escola"
        verbose_name_plural = "escolas"

    def __str__(self):
        return self.nome


class Curso(models.Model):
    """Etapa de ensino. Ex.: Ensino Fundamental - Anos Finais, Ensino Médio."""

    nome = models.CharField(verbose_name="nome", max_length=100, unique=True)
    ordem = models.PositiveSmallIntegerField(
        verbose_name="ordem",
        default=1,
        help_text="Ordem de exibição: 1 = Anos Iniciais, 2 = Anos Finais, 3 = Ensino Médio...",
    )
    carga_horaria_minima_anual = models.PositiveIntegerField(
        verbose_name="carga horária mínima anual (horas)",
        default=800,
        validators=[MinValueValidator(1)],
        help_text="LDB, art. 24: 800 h no Ensino Fundamental e 1.000 h no Ensino Médio.",
    )

    class Meta:
        ordering = ["ordem", "nome"]
        verbose_name = "curso"
        verbose_name_plural = "cursos"

    def __str__(self):
        return self.nome


class Serie(models.Model):
    """Ano/série dentro de um curso. Ex.: 1ª série do Ensino Médio."""

    curso = models.ForeignKey(Curso, verbose_name="curso", on_delete=models.PROTECT, related_name="series")
    nome = models.CharField(verbose_name="nome", max_length=30, help_text='Ex.: "6º ano", "1ª série".')
    ordem = models.PositiveSmallIntegerField(
        verbose_name="ordem",
        validators=[MinValueValidator(1)],
        help_text="Posição dentro do curso: 1, 2, 3...",
    )

    class Meta:
        ordering = ["curso__ordem", "ordem"]
        verbose_name = "série"
        verbose_name_plural = "séries"
        constraints = [
            models.UniqueConstraint(
                fields=["curso", "ordem"],
                name="serie_ordem_unica_no_curso",
                violation_error_message="Esse curso já tem uma série nessa posição.",
            ),
            models.UniqueConstraint(
                fields=["curso", "nome"],
                name="serie_nome_unico_no_curso",
                violation_error_message="Esse curso já tem uma série com esse nome.",
            ),
        ]

    def __str__(self):
        return f"{self.nome} - {self.curso}"


class Materia(models.Model):
    """Componente curricular. Ex.: Língua Portuguesa, Química."""

    class Area(models.TextChoices):
        LINGUAGENS = "linguagens", "Linguagens"
        MATEMATICA = "matematica", "Matemática"
        NATUREZA = "natureza", "Ciências da Natureza"
        HUMANAS = "humanas", "Ciências Humanas"
        RELIGIOSO = "religioso", "Ensino Religioso"
        OUTRA = "outra", "Outra"

    nome = models.CharField(verbose_name="nome", max_length=80, unique=True)
    area = models.CharField(verbose_name="área do conhecimento", max_length=20, choices=Area.choices)

    class Meta:
        ordering = ["nome"]
        verbose_name = "matéria"
        verbose_name_plural = "matérias"

    def __str__(self):
        return self.nome


class Turma(models.Model):
    class Turno(models.TextChoices):
        MATUTINO = "matutino", "Matutino"
        VESPERTINO = "vespertino", "Vespertino"
        NOTURNO = "noturno", "Noturno"
        INTEGRAL = "integral", "Integral"

    escola = models.ForeignKey(Escola, verbose_name="escola", on_delete=models.PROTECT, related_name="turmas")
    serie = models.ForeignKey(Serie, verbose_name="série", on_delete=models.PROTECT, related_name="turmas")
    ano_letivo = models.PositiveSmallIntegerField(
        verbose_name="ano letivo",
        validators=[MinValueValidator(2000), MaxValueValidator(2100)],
    )
    turno = models.CharField(verbose_name="turno", max_length=10, choices=Turno.choices)
    letra = models.CharField(
        verbose_name="letra",
        max_length=2,
        validators=[RegexValidator(r"^[A-Za-z]{1,2}$", 'Use 1 ou 2 letras. Ex.: "A", "B".')],
        help_text='Identificação da turma. Ex.: "A", "B".',
    )
    sala = models.CharField(verbose_name="sala", max_length=20, blank=True)
    capacidade = models.PositiveSmallIntegerField(
        verbose_name="capacidade",
        default=35,
        validators=[MinValueValidator(1), MaxValueValidator(60)],
    )

    class Meta:
        ordering = ["-ano_letivo", "escola__nome", "serie__curso__ordem", "serie__ordem", "letra"]
        verbose_name = "turma"
        verbose_name_plural = "turmas"
        constraints = [
            models.UniqueConstraint(
                fields=["escola", "serie", "ano_letivo", "letra"],
                name="turma_unica_por_escola_serie_ano",
                violation_error_message="Essa escola já tem essa turma nesse ano letivo.",
            ),
        ]

    def clean(self):
        # Roda no admin ANTES de checar duplicidade: "a" vira "A" e já é comparado certo.
        super().clean()
        if self.letra:
            self.letra = self.letra.strip().upper()

        # Regra do DED: só dá pra abrir turma de uma série que a escola oferece naquele ano.
        # "escola.ofertas" vem do related_name do app regulacao (por isso ele precisa estar instalado).
        if self.escola_id and self.serie_id and self.ano_letivo:
            oferece = self.escola.ofertas.filter(ano_letivo=self.ano_letivo, series=self.serie).exists()
            if not oferece:
                raise ValidationError(
                    {"serie": f"{self.escola} não oferece {self.serie.nome} em {self.ano_letivo}. "
                              "Cadastre antes em Regulação (DED) > Ofertas de séries."}
                )

    def save(self, *args, **kwargs):
        # Garante a letra em maiúscula mesmo quando o clean() não roda (shell, scripts, API).
        if self.letra:
            self.letra = self.letra.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.serie.nome} {self.letra} - {self.escola} ({self.ano_letivo})"
