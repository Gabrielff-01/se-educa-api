from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from rede.models import Curso, Escola, Materia, Serie, Turma


def horas_por_ano(aulas_semanais, duracao_aula_minutos, semanas_letivas):
    """Converte aulas por semana em horas de relógio no ano.

    Ex.: 30 aulas × 50 min × 40 semanas ÷ 60 = 1000 horas.
    """
    return aulas_semanais * duracao_aula_minutos * semanas_letivas / 60


def formatar_horas(horas):
    """833.333 -> "833,3" (com vírgula, do jeito brasileiro)."""
    return f"{horas:.1f}".replace(".", ",")


def validar_carga_minima(serie, duracao_aula_minutos, semanas_letivas, total_aulas):
    """Regra do DED: as aulas da matriz têm que somar a carga mínima do curso.

    Fica aqui (e não no admin) para a API da Aula 6 usar a MESMA regra.
    """
    horas = horas_por_ano(total_aulas, duracao_aula_minutos, semanas_letivas)
    minimo = serie.curso.carga_horaria_minima_anual
    if horas < minimo:
        raise ValidationError(
            f"A matriz soma {formatar_horas(horas)} horas por ano, mas {serie.curso} exige "
            f"no mínimo {minimo} horas. Faltam {formatar_horas(minimo - horas)} horas."
        )


def conferir_lotacoes(matriz, aulas_por_materia):
    """Diminuir (ou tirar) uma matéria da matriz não pode deixar professor lotado sobrando.

    aulas_por_materia: {id da matéria: aulas por semana} como a matriz vai ficar.
    As lotações são do app rh (Aula 5); aqui a gente só lê elas pela turma.
    """
    if not matriz.pk:
        return  # matriz nova: ainda não tem professor lotado
    turmas = Turma.objects.filter(serie_id=matriz.serie_id, ano_letivo=matriz.ano_letivo)
    if matriz.jornada == Matriz.Jornada.INTEGRAL:
        turmas = turmas.filter(turno=Turma.Turno.INTEGRAL)
    else:
        turmas = turmas.exclude(turno=Turma.Turno.INTEGRAL)
    lotadas = (
        turmas.filter(lotacoes__isnull=False)
        .values("letra", "lotacoes__materia", "lotacoes__materia__nome")
        .annotate(total=Sum("lotacoes__aulas_semanais"))
    )
    for linha in lotadas:
        permitido = aulas_por_materia.get(linha["lotacoes__materia"], 0)
        if linha["total"] > permitido:
            raise ValidationError(
                f"A turma {matriz.serie.nome} {linha['letra']} já tem {linha['total']} aulas de "
                f"{linha['lotacoes__materia__nome']} lotadas com professores, mas a matriz "
                f"ficaria com {permitido}. Ajuste as lotações no RH antes."
            )


class AtoAutorizativo(models.Model):
    """Documento oficial que autoriza a escola (ou um curso dela) a funcionar."""

    class Tipo(models.TextChoices):
        CRIACAO = "criacao", "Ato de criação"
        CREDENCIAMENTO = "credenciamento", "Credenciamento"
        AUTORIZACAO = "autorizacao", "Autorização de funcionamento"
        RECONHECIMENTO = "reconhecimento", "Reconhecimento"
        RENOVACAO = "renovacao", "Renovação de reconhecimento"

    # Tipos de ato que valem para um curso (nível de ensino) e não para a escola toda.
    TIPOS_POR_CURSO = [Tipo.AUTORIZACAO, Tipo.RECONHECIMENTO, Tipo.RENOVACAO]

    escola = models.ForeignKey(Escola, verbose_name="escola", on_delete=models.PROTECT, related_name="atos")
    curso = models.ForeignKey(
        Curso,
        verbose_name="curso",
        on_delete=models.PROTECT,
        related_name="atos",
        null=True,
        blank=True,
        help_text="Obrigatório para autorização, reconhecimento e renovação.",
    )
    tipo = models.CharField(verbose_name="tipo", max_length=20, choices=Tipo.choices)
    numero = models.CharField(verbose_name="número", max_length=60, help_text="Ex.: Resolução nº 123/2024")
    orgao_emissor = models.CharField(verbose_name="órgão emissor", max_length=60, default="CEE/SE")
    data_publicacao = models.DateField(verbose_name="data de publicação")
    validade = models.DateField(
        verbose_name="válido até",
        null=True,
        blank=True,
        help_text="Deixe em branco se o ato não tem prazo de validade.",
    )
    observacao = models.TextField(verbose_name="observação", blank=True)

    class Meta:
        ordering = ["escola__nome", "-data_publicacao"]
        verbose_name = "ato autorizativo"
        verbose_name_plural = "atos autorizativos"

    def clean(self):
        super().clean()
        if self.data_publicacao and self.validade and self.validade <= self.data_publicacao:
            raise ValidationError({"validade": "A validade tem que ser depois da data de publicação."})
        # Resolução Normativa CEE/SE nº 2/2014: autorização, reconhecimento e renovação
        # são dados para um nível de ensino (um curso), não para a escola toda.
        if self.tipo in self.TIPOS_POR_CURSO and not self.curso_id:
            raise ValidationError({"curso": "Esse tipo de ato vale para um curso. Escolha qual."})

    @property
    def vigente(self):
        """True se o ato ainda vale hoje."""
        return self.validade is None or self.validade >= timezone.localdate()

    def __str__(self):
        return f"{self.get_tipo_display()} {self.numero} - {self.escola}"


class Oferta(models.Model):
    """Quais séries uma escola oferece em um ano letivo.

    Ex.: "em 2026, o Atheneu oferece 1ª, 2ª e 3ª série do Ensino Médio".
    """

    escola = models.ForeignKey(Escola, verbose_name="escola", on_delete=models.PROTECT, related_name="ofertas")
    ano_letivo = models.PositiveSmallIntegerField(
        verbose_name="ano letivo",
        validators=[MinValueValidator(2000), MaxValueValidator(2100)],
    )
    series = models.ManyToManyField(Serie, verbose_name="séries oferecidas", related_name="ofertas")

    class Meta:
        ordering = ["-ano_letivo", "escola__nome"]
        verbose_name = "oferta de séries"
        verbose_name_plural = "ofertas de séries"
        constraints = [
            models.UniqueConstraint(
                fields=["escola", "ano_letivo"],
                name="oferta_unica_por_escola_ano",
                violation_error_message="Essa escola já tem uma oferta cadastrada nesse ano letivo.",
            ),
        ]

    def turmas(self):
        """Turmas que dependem desta oferta (mesma escola e mesmo ano letivo)."""
        return self.escola.turmas.filter(ano_letivo=self.ano_letivo)

    def __str__(self):
        return f"{self.escola} ({self.ano_letivo})"


class Matriz(models.Model):
    """Matriz curricular: quantas aulas por semana cada matéria tem numa série."""

    class Jornada(models.TextChoices):
        PARCIAL = "parcial", "Tempo parcial"
        INTEGRAL = "integral", "Tempo integral"

    serie = models.ForeignKey(Serie, verbose_name="série", on_delete=models.PROTECT, related_name="matrizes")
    ano_letivo = models.PositiveSmallIntegerField(
        verbose_name="ano letivo",
        validators=[MinValueValidator(2000), MaxValueValidator(2100)],
    )
    jornada = models.CharField(
        verbose_name="jornada",
        max_length=10,
        choices=Jornada.choices,
        default=Jornada.PARCIAL,
        help_text="A rede pode ter uma matriz para o tempo parcial e outra para o tempo integral.",
    )
    duracao_aula_minutos = models.PositiveSmallIntegerField(
        verbose_name="duração da aula (minutos)",
        default=50,
        validators=[MinValueValidator(30), MaxValueValidator(60)],
    )
    semanas_letivas = models.PositiveSmallIntegerField(
        verbose_name="semanas letivas no ano",
        default=40,
        validators=[
            MinValueValidator(40, "A LDB exige no mínimo 200 dias letivos, ou seja, 40 semanas."),
            MaxValueValidator(52),
        ],
        help_text="200 dias letivos ÷ 5 dias por semana = 40 semanas.",
    )

    class Meta:
        ordering = ["-ano_letivo", "serie__curso__ordem", "serie__ordem", "jornada"]
        verbose_name = "matriz curricular"
        verbose_name_plural = "matrizes curriculares"
        constraints = [
            models.UniqueConstraint(
                fields=["serie", "ano_letivo", "jornada"],
                name="matriz_unica_por_serie_ano_jornada",
                violation_error_message="Essa série já tem uma matriz dessa jornada nesse ano letivo.",
            ),
        ]

    @property
    def total_aulas_semanais(self):
        return sum(item.aulas_semanais for item in self.itens.all())

    @property
    def carga_horaria_anual(self):
        return horas_por_ano(self.total_aulas_semanais, self.duracao_aula_minutos, self.semanas_letivas)

    @property
    def cumpre_minimo(self):
        """Se a matriz ainda bate a carga mínima do curso (o mínimo pode ter mudado depois)."""
        return self.carga_horaria_anual >= self.serie.curso.carga_horaria_minima_anual

    def __str__(self):
        return f"Matriz {self.serie} - {self.get_jornada_display()} ({self.ano_letivo})"


class ItemMatriz(models.Model):
    """Uma linha da matriz: a matéria e quantas aulas por semana ela tem."""

    matriz = models.ForeignKey(Matriz, verbose_name="matriz", on_delete=models.CASCADE, related_name="itens")
    materia = models.ForeignKey(Materia, verbose_name="matéria", on_delete=models.PROTECT, related_name="itens_matriz")
    aulas_semanais = models.PositiveSmallIntegerField(
        verbose_name="aulas por semana",
        validators=[MinValueValidator(1), MaxValueValidator(20)],
    )

    class Meta:
        ordering = ["materia__nome"]
        verbose_name = "matéria da matriz"
        verbose_name_plural = "matérias da matriz"
        constraints = [
            models.UniqueConstraint(
                fields=["matriz", "materia"],
                name="materia_unica_na_matriz",
                violation_error_message="Essa matéria já está na matriz.",
            ),
        ]

    def __str__(self):
        return f"{self.materia}: {self.aulas_semanais} aulas/semana"
