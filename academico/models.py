"""Vida escolar do aluno: matrícula, diário (aulas e chamada), notas, tarefas e comunicados.

Regras de aprovação (mude aqui se a rede usar outros números):
- média anual = média das 4 unidades; passa com MEDIA_APROVACAO ou mais;
- entre NOTA_RECUPERACAO e a média, vai para a recuperação;
- frequência abaixo de FREQUENCIA_MINIMA reprova por falta (LDB, art. 24, VI).
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from calendario.models import UNIDADES_POR_ANO, calendario_da_escola
from rede.models import Escola, Materia, Serie, Turma
from rh.models import Lotacao, Professor, matriz_da_turma, validar_cpf

MEDIA_APROVACAO = Decimal("6.0")
NOTA_RECUPERACAO = Decimal("4.0")
FREQUENCIA_MINIMA = 75  # em %


def situacao_pela_media(media, unidades_lancadas, frequencia):
    """Situação do aluno numa matéria (ou no ano). frequencia em %, ou None se não teve aula."""
    if frequencia is not None and frequencia < FREQUENCIA_MINIMA and unidades_lancadas == UNIDADES_POR_ANO:
        return "Reprovado por falta"
    if media is None or unidades_lancadas < UNIDADES_POR_ANO:
        return "Cursando"
    if media >= MEDIA_APROVACAO:
        return "Aprovado"
    if media >= NOTA_RECUPERACAO:
        return "Recuperação"
    return "Reprovado"


# --------------------------------------------------------------------------- pessoas


class Aluno(models.Model):
    class Programa(models.TextChoices):
        NENHUM = "", "Nenhum"
        BOLSA_FAMILIA = "bolsa_familia", "Bolsa Família"
        PE_DE_MEIA = "pe_de_meia", "Pé-de-Meia"

    # Frequência mínima que cada programa exige (Bolsa Família: 85%; Pé-de-Meia: 80%).
    FREQUENCIA_DO_PROGRAMA = {Programa.BOLSA_FAMILIA: 85, Programa.PE_DE_MEIA: 80}

    nome = models.CharField(verbose_name="nome completo", max_length=150)
    data_nascimento = models.DateField(verbose_name="data de nascimento")
    codigo = models.CharField(
        verbose_name="código do aluno",
        max_length=12,
        unique=True,
        null=True,
        editable=False,
        help_text="Gerado sozinho na hora do cadastro. Ex.: 2026.00042",
    )
    programa_social = models.CharField(
        verbose_name="programa social",
        max_length=15,
        choices=Programa.choices,
        blank=True,
        help_text="Bolsa Família exige 85% de frequência; Pé-de-Meia, 80%.",
    )
    nis = models.CharField(
        verbose_name="NIS",
        max_length=11,
        blank=True,
        validators=[RegexValidator(r"^\d{11}$", "O NIS tem 11 números.")],
        help_text="Número do CadÚnico. Obrigatório para quem tem programa social.",
    )
    necessidade_especial = models.CharField(
        verbose_name="necessidade especial (AEE)",
        max_length=120,
        blank=True,
        help_text="Em branco = não tem. Ex.: TEA, deficiência auditiva.",
    )
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="usuário de acesso",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="aluno",
        limit_choices_to={"perfil": "aluno"},
    )

    class Meta:
        ordering = ["nome"]
        verbose_name = "aluno"
        verbose_name_plural = "alunos"

    def clean(self):
        super().clean()
        if self.programa_social and not self.nis:
            raise ValidationError({"nis": "Quem recebe programa social precisa ter o NIS."})
        if self.data_nascimento and self.data_nascimento > timezone.localdate():
            raise ValidationError({"data_nascimento": "A data de nascimento está no futuro."})

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.codigo:
            # O código usa o id, que só existe depois de salvar. Ex.: 2026.00042
            self.codigo = f"{timezone.localdate().year}.{self.pk:05d}"
            super().save(update_fields=["codigo"])

    @property
    def idade(self):
        hoje = timezone.localdate()
        nascimento = self.data_nascimento
        fez_aniversario = (hoje.month, hoje.day) >= (nascimento.month, nascimento.day)
        return hoje.year - nascimento.year - (0 if fez_aniversario else 1)

    def matricula_atual(self):
        """A matrícula do ano corrente que vale (confirmada ou em análise)."""
        return (
            self.matriculas.filter(ano_letivo=timezone.localdate().year)
            .exclude(situacao__in=Matricula.SITUACOES_ENCERRADAS)
            .select_related("turma__serie__curso", "escola", "serie")
            .first()
        )

    def __str__(self):
        return self.nome


class Responsavel(models.Model):
    nome = models.CharField(verbose_name="nome completo", max_length=150)
    cpf = models.CharField(
        verbose_name="CPF",
        max_length=14,
        unique=True,
        validators=[validar_cpf],
        error_messages={"unique": "Já existe um responsável com esse CPF."},
    )
    telefone = models.CharField(verbose_name="telefone", max_length=20, blank=True)
    email = models.EmailField(verbose_name="e-mail", blank=True)
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="usuário de acesso",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="responsavel",
        limit_choices_to={"perfil": "responsavel"},
    )
    alunos = models.ManyToManyField(
        Aluno, verbose_name="alunos", through="Vinculo", related_name="responsaveis"
    )

    class Meta:
        ordering = ["nome"]
        verbose_name = "responsável"
        verbose_name_plural = "responsáveis"

    def clean(self):
        super().clean()
        if self.cpf:
            self.cpf = "".join(c for c in self.cpf if c.isdigit())

    def save(self, *args, **kwargs):
        if self.cpf:
            self.cpf = "".join(c for c in self.cpf if c.isdigit())
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nome


class Vinculo(models.Model):
    """Ligação entre responsável e aluno, com o parentesco."""

    class Parentesco(models.TextChoices):
        MAE = "mae", "Mãe"
        PAI = "pai", "Pai"
        AVO = "avo", "Avó / avô"
        TIO = "tio", "Tia / tio"
        OUTRO = "outro", "Outro responsável legal"

    responsavel = models.ForeignKey(Responsavel, on_delete=models.CASCADE, related_name="vinculos")
    aluno = models.ForeignKey(Aluno, on_delete=models.CASCADE, related_name="vinculos")
    parentesco = models.CharField(verbose_name="parentesco", max_length=10, choices=Parentesco.choices)

    class Meta:
        verbose_name = "vínculo familiar"
        verbose_name_plural = "vínculos familiares"
        constraints = [
            models.UniqueConstraint(
                fields=["responsavel", "aluno"],
                name="vinculo_unico",
                violation_error_message="Esse responsável já está ligado a esse aluno.",
            ),
        ]

    def __str__(self):
        return f"{self.responsavel} ({self.get_parentesco_display()}) de {self.aluno}"


# ------------------------------------------------------------------------- matrícula


class Matricula(models.Model):
    class Situacao(models.TextChoices):
        EM_ANALISE = "em_analise", "Em análise"
        CONFIRMADA = "confirmada", "Confirmada"
        CANCELADA = "cancelada", "Cancelada"
        TRANSFERIDA = "transferida", "Transferida"

    class Resultado(models.TextChoices):
        APROVADO = "aprovado", "Aprovado"
        REPROVADO = "reprovado", "Reprovado"

    # Matrículas que não contam mais: o aluno pode ter outra no mesmo ano.
    SITUACOES_ENCERRADAS = [Situacao.CANCELADA, Situacao.TRANSFERIDA]

    aluno = models.ForeignKey(Aluno, verbose_name="aluno", on_delete=models.PROTECT, related_name="matriculas")
    escola = models.ForeignKey(Escola, verbose_name="escola", on_delete=models.PROTECT, related_name="matriculas")
    serie = models.ForeignKey(Serie, verbose_name="série", on_delete=models.PROTECT, related_name="matriculas")
    ano_letivo = models.PositiveSmallIntegerField(
        verbose_name="ano letivo", validators=[MinValueValidator(2000), MaxValueValidator(2100)]
    )
    turma = models.ForeignKey(
        Turma,
        verbose_name="turma",
        on_delete=models.PROTECT,
        related_name="matriculas",
        null=True,
        blank=True,
        help_text="Em branco = esperando enturmação.",
    )
    situacao = models.CharField(
        verbose_name="situação", max_length=12, choices=Situacao.choices, default=Situacao.EM_ANALISE
    )
    data = models.DateField(verbose_name="data da matrícula", default=timezone.localdate)
    # Histórico de anos já encerrados (o ano atual é calculado pelas notas).
    resultado_final = models.CharField(
        verbose_name="resultado final", max_length=10, choices=Resultado.choices, blank=True
    )
    media_final = models.DecimalField(
        verbose_name="média final", max_digits=4, decimal_places=2, null=True, blank=True
    )

    class Meta:
        ordering = ["-ano_letivo", "aluno__nome"]
        verbose_name = "matrícula"
        verbose_name_plural = "matrículas"
        constraints = [
            models.UniqueConstraint(
                fields=["aluno", "ano_letivo"],
                condition=~Q(situacao__in=["cancelada", "transferida"]),
                name="uma_matricula_ativa_por_ano",
                violation_error_message="Esse aluno já tem matrícula nesse ano letivo.",
            ),
        ]

    def clean(self):
        super().clean()
        if not (self.aluno_id and self.escola_id and self.serie_id and self.ano_letivo):
            return
        # Regra do DED: só matricula em série que a escola oferece no ano.
        if not self.escola.ofertas.filter(ano_letivo=self.ano_letivo, series=self.serie).exists():
            raise ValidationError(
                {"serie": f"{self.escola} não oferece {self.serie.nome} em {self.ano_letivo}."}
            )
        if self.turma_id:
            self.conferir_turma()

    def conferir_turma(self):
        turma = self.turma
        if turma.escola_id != self.escola_id or turma.serie_id != self.serie_id or turma.ano_letivo != self.ano_letivo:
            raise ValidationError(
                {"turma": f"A turma tem que ser de {self.serie.nome}, {self.escola} em {self.ano_letivo}."}
            )
        if self.situacao != self.Situacao.CONFIRMADA:
            raise ValidationError({"turma": "Confirme a matrícula antes de colocar o aluno numa turma."})
        ocupadas = turma.matriculas.filter(situacao=self.Situacao.CONFIRMADA).exclude(pk=self.pk).count()
        if ocupadas >= turma.capacidade:
            raise ValidationError(
                {"turma": f"A turma {turma.serie.nome} {turma.letra} está cheia ({turma.capacidade} alunos)."}
            )

    def __str__(self):
        return f"{self.aluno} - {self.serie.nome} {self.ano_letivo}"


# ------------------------------------------------------------- quem dá aula onde


def professor_lotado(professor, turma, materia):
    """True se o professor tem lotação nessa turma e matéria (regra do RH)."""
    return Lotacao.objects.filter(professor=professor, turma=turma, materia=materia).exists()


def conferir_lotacao(objeto):
    """Usado no clean() de quem tem professor, turma e matéria (aula, tarefa, plano)."""
    if objeto.professor_id and objeto.turma_id and objeto.materia_id:
        if not professor_lotado(objeto.professor, objeto.turma, objeto.materia):
            raise ValidationError(
                {"materia": f"{objeto.professor.nome} não está lotado em {objeto.materia} nessa turma."}
            )


# ---------------------------------------------------------------- diário e chamada


class Aula(models.Model):
    """Registro de uma aula no diário de classe. A chamada fica em Presenca."""

    turma = models.ForeignKey(Turma, verbose_name="turma", on_delete=models.PROTECT, related_name="aulas")
    materia = models.ForeignKey(Materia, verbose_name="matéria", on_delete=models.PROTECT, related_name="aulas")
    professor = models.ForeignKey(Professor, verbose_name="professor", on_delete=models.PROTECT, related_name="aulas")
    data = models.DateField(verbose_name="data")
    quantidade = models.PositiveSmallIntegerField(
        verbose_name="aulas seguidas",
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(4)],
        help_text="Aula dupla (geminada) = 2. Cada uma conta como uma presença ou falta.",
    )
    conteudo = models.TextField(verbose_name="conteúdo da aula", blank=True)

    class Meta:
        ordering = ["-data", "turma__serie__ordem"]
        verbose_name = "aula"
        verbose_name_plural = "aulas (diário)"
        constraints = [
            models.UniqueConstraint(
                fields=["turma", "materia", "data"],
                name="uma_aula_por_dia",
                violation_error_message="Essa aula já foi registrada nesse dia. Edite o registro que já existe.",
            ),
        ]

    def clean(self):
        super().clean()
        conferir_lotacao(self)
        if not (self.turma_id and self.data):
            return
        if self.data > timezone.localdate():
            raise ValidationError({"data": "Não dá pra registrar aula de um dia que ainda não chegou."})
        calendario = calendario_da_escola(self.turma.escola, self.turma.ano_letivo)
        if calendario is None:
            raise ValidationError({"data": f"Ainda não tem calendário letivo de {self.turma.ano_letivo}."})
        if not calendario.eh_dia_letivo(self.data):
            raise ValidationError(
                {"data": f"{self.data:%d/%m/%Y} não é dia letivo no calendário (fim de semana, feriado ou férias)."}
            )

    @property
    def unidade(self):
        calendario = calendario_da_escola(self.turma.escola, self.turma.ano_letivo)
        return calendario.unidade_em(self.data) if calendario else 1

    def __str__(self):
        return f"{self.materia} - {self.turma.serie.nome} {self.turma.letra} ({self.data:%d/%m/%Y})"


class Presenca(models.Model):
    aula = models.ForeignKey(Aula, on_delete=models.CASCADE, related_name="presencas")
    matricula = models.ForeignKey(Matricula, on_delete=models.CASCADE, related_name="presencas")
    presente = models.BooleanField(verbose_name="presente", default=True)

    class Meta:
        verbose_name = "presença"
        verbose_name_plural = "presenças"
        constraints = [
            models.UniqueConstraint(fields=["aula", "matricula"], name="uma_presenca_por_aluno_na_aula"),
        ]

    def clean(self):
        super().clean()
        if self.aula_id and self.matricula_id and self.matricula.turma_id != self.aula.turma_id:
            raise ValidationError({"matricula": f"{self.matricula.aluno} não é dessa turma."})

    def __str__(self):
        return f"{self.matricula.aluno}: {'P' if self.presente else 'F'}"


# ---------------------------------------------------------------------------- notas


class Fechamento(models.Model):
    """A escola fecha a unidade de uma turma: o boletim sai e as notas não mudam mais."""

    turma = models.ForeignKey(Turma, verbose_name="turma", on_delete=models.CASCADE, related_name="fechamentos")
    unidade = models.PositiveSmallIntegerField(
        verbose_name="unidade", validators=[MinValueValidator(1), MaxValueValidator(UNIDADES_POR_ANO)]
    )
    fechado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="fechado por", on_delete=models.SET_NULL, null=True, blank=True
    )
    fechado_em = models.DateTimeField(verbose_name="fechado em", auto_now_add=True)

    class Meta:
        ordering = ["turma", "unidade"]
        verbose_name = "fechamento de unidade"
        verbose_name_plural = "fechamentos de unidade"
        constraints = [
            models.UniqueConstraint(
                fields=["turma", "unidade"],
                name="fechamento_unico",
                violation_error_message="Essa unidade já foi fechada nessa turma.",
            ),
        ]

    def clean(self):
        super().clean()
        if not (self.turma_id and self.unidade):
            return
        anterior = self.unidade - 1
        if anterior >= 1 and not Fechamento.objects.filter(turma=self.turma, unidade=anterior).exists():
            raise ValidationError({"unidade": f"Feche a {anterior}ª unidade antes da {self.unidade}ª."})
        faltando = notas_faltando(self.turma, self.unidade)
        if faltando:
            exemplos = ", ".join(f"{materia} ({quantas})" for materia, quantas in faltando[:4])
            raise ValidationError(
                {"unidade": f"Ainda faltam notas da {self.unidade}ª unidade: {exemplos}."}
            )

    def __str__(self):
        return f"{self.unidade}ª unidade - {self.turma.serie.nome} {self.turma.letra}"


def notas_faltando(turma, unidade):
    """[(matéria, quantos alunos sem nota), ...] considerando as matérias com professor lotado."""
    alunos = turma.matriculas.filter(situacao=Matricula.Situacao.CONFIRMADA)
    total = alunos.count()
    faltando = []
    if total == 0:
        return faltando
    materias = Materia.objects.filter(lotacoes__turma=turma).distinct()
    for materia in materias:
        lancadas = Nota.objects.filter(matricula__in=alunos, materia=materia, unidade=unidade).count()
        if lancadas < total:
            faltando.append((materia.nome, total - lancadas))
    return faltando


class Nota(models.Model):
    matricula = models.ForeignKey(Matricula, verbose_name="matrícula", on_delete=models.CASCADE, related_name="notas")
    materia = models.ForeignKey(Materia, verbose_name="matéria", on_delete=models.PROTECT, related_name="notas")
    unidade = models.PositiveSmallIntegerField(
        verbose_name="unidade", validators=[MinValueValidator(1), MaxValueValidator(UNIDADES_POR_ANO)]
    )
    valor = models.DecimalField(
        verbose_name="nota",
        max_digits=4,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0"), "A nota vai de 0 a 10."),
            MaxValueValidator(Decimal("10"), "A nota vai de 0 a 10."),
        ],
        error_messages={"invalid": "Digite um número de 0 a 10."},
    )
    lancada_por = models.ForeignKey(
        Professor, verbose_name="lançada por", on_delete=models.SET_NULL, null=True, blank=True, related_name="notas"
    )
    atualizada_em = models.DateTimeField(verbose_name="atualizada em", auto_now=True)

    class Meta:
        ordering = ["matricula__aluno__nome", "materia__nome", "unidade"]
        verbose_name = "nota"
        verbose_name_plural = "notas"
        constraints = [
            models.UniqueConstraint(
                fields=["matricula", "materia", "unidade"],
                name="uma_nota_por_unidade",
                violation_error_message="Esse aluno já tem nota nessa matéria e unidade.",
            ),
        ]

    def clean(self):
        super().clean()
        if not (self.matricula_id and self.materia_id and self.unidade):
            return
        turma = self.matricula.turma
        if turma is None:
            raise ValidationError({"matricula": f"{self.matricula.aluno} ainda não está numa turma."})
        matriz = matriz_da_turma(turma)
        if matriz is None or not matriz.itens.filter(materia=self.materia).exists():
            raise ValidationError({"materia": f"{self.materia} não está na matriz da turma."})
        if Fechamento.objects.filter(turma=turma, unidade=self.unidade).exists():
            raise ValidationError(
                {"unidade": f"A {self.unidade}ª unidade dessa turma já foi fechada pela escola. "
                            "Peça para a escola reabrir se precisar corrigir."}
            )

    def __str__(self):
        return f"{self.matricula.aluno} - {self.materia} - {self.unidade}ª: {self.valor}"


# --------------------------------------------------------------------- planejamento


class Tarefa(models.Model):
    turma = models.ForeignKey(Turma, verbose_name="turma", on_delete=models.CASCADE, related_name="tarefas")
    materia = models.ForeignKey(Materia, verbose_name="matéria", on_delete=models.PROTECT, related_name="tarefas")
    professor = models.ForeignKey(Professor, verbose_name="professor", on_delete=models.PROTECT, related_name="tarefas")
    titulo = models.CharField(verbose_name="título", max_length=120)
    descricao = models.TextField(verbose_name="descrição", blank=True)
    prazo = models.DateField(verbose_name="prazo de entrega")
    criada_em = models.DateTimeField(verbose_name="criada em", auto_now_add=True)

    class Meta:
        ordering = ["-prazo"]
        verbose_name = "tarefa"
        verbose_name_plural = "tarefas"

    def clean(self):
        super().clean()
        conferir_lotacao(self)
        if self.pk is None and self.prazo and self.prazo < timezone.localdate():
            raise ValidationError({"prazo": "O prazo não pode ser num dia que já passou."})

    def __str__(self):
        return self.titulo


class Entrega(models.Model):
    tarefa = models.ForeignKey(Tarefa, on_delete=models.CASCADE, related_name="entregas")
    matricula = models.ForeignKey(Matricula, on_delete=models.CASCADE, related_name="entregas")
    entregue_em = models.DateTimeField(verbose_name="entregue em", default=timezone.now)

    class Meta:
        verbose_name = "entrega"
        verbose_name_plural = "entregas"
        constraints = [models.UniqueConstraint(fields=["tarefa", "matricula"], name="uma_entrega_por_aluno")]

    def __str__(self):
        return f"{self.matricula.aluno} entregou {self.tarefa}"


class PlanoAula(models.Model):
    class Status(models.TextChoices):
        PLANEJADO = "planejado", "Planejado"
        EM_ANDAMENTO = "em_andamento", "Em andamento"
        CONCLUIDO = "concluido", "Concluído"

    professor = models.ForeignKey(Professor, verbose_name="professor", on_delete=models.CASCADE, related_name="planos")
    turma = models.ForeignKey(Turma, verbose_name="turma", on_delete=models.CASCADE, related_name="planos")
    materia = models.ForeignKey(Materia, verbose_name="matéria", on_delete=models.PROTECT, related_name="planos")
    unidade = models.PositiveSmallIntegerField(
        verbose_name="unidade", validators=[MinValueValidator(1), MaxValueValidator(UNIDADES_POR_ANO)]
    )
    tema = models.CharField(verbose_name="tema", max_length=120)
    objetivos = models.TextField(verbose_name="objetivos e atividades", blank=True)
    status = models.CharField(verbose_name="status", max_length=12, choices=Status.choices, default=Status.PLANEJADO)

    class Meta:
        ordering = ["unidade", "turma__serie__ordem", "tema"]
        verbose_name = "plano de aula"
        verbose_name_plural = "planos de aula"

    def clean(self):
        super().clean()
        conferir_lotacao(self)

    def __str__(self):
        return self.tema


# ----------------------------------------------------------------------- comunicação


class Comunicado(models.Model):
    class Alcance(models.TextChoices):
        REDE = "rede", "Rede toda"
        ESCOLA = "escola", "Escola"
        TURMA = "turma", "Turma"
        PESSOA = "pessoa", "Uma pessoa"

    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="autor", on_delete=models.SET_NULL, null=True, related_name="comunicados"
    )
    titulo = models.CharField(verbose_name="título", max_length=120)
    texto = models.TextField(verbose_name="texto")
    alcance = models.CharField(verbose_name="para quem", max_length=10, choices=Alcance.choices)
    escola = models.ForeignKey(Escola, verbose_name="escola", on_delete=models.CASCADE, null=True, blank=True)
    turma = models.ForeignKey(Turma, verbose_name="turma", on_delete=models.CASCADE, null=True, blank=True)
    destinatario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="destinatário",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="comunicados_recebidos",
    )
    criado_em = models.DateTimeField(verbose_name="enviado em", auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "comunicado"
        verbose_name_plural = "comunicados"

    def clean(self):
        super().clean()
        precisa = {
            self.Alcance.ESCOLA: ("escola", self.escola_id),
            self.Alcance.TURMA: ("turma", self.turma_id),
            self.Alcance.PESSOA: ("destinatario", self.destinatario_id),
        }
        if self.alcance in precisa:
            campo, valor = precisa[self.alcance]
            if not valor:
                raise ValidationError({campo: "Escolha para quem vai o comunicado."})

    def __str__(self):
        return self.titulo


# ------------------------------------------------------------------- horário e merenda


class Horario(models.Model):
    """Um tempo da grade semanal: em tal dia e hora, tal lotação (professor + matéria) dá aula."""

    class Dia(models.IntegerChoices):
        SEGUNDA = 1, "Segunda"
        TERCA = 2, "Terça"
        QUARTA = 3, "Quarta"
        QUINTA = 4, "Quinta"
        SEXTA = 5, "Sexta"

    lotacao = models.ForeignKey(Lotacao, verbose_name="lotação", on_delete=models.CASCADE, related_name="horarios")
    dia_semana = models.PositiveSmallIntegerField(verbose_name="dia", choices=Dia.choices)
    inicio = models.TimeField(verbose_name="início")

    class Meta:
        ordering = ["dia_semana", "inicio"]
        verbose_name = "horário"
        verbose_name_plural = "horários (grade)"

    def clean(self):
        super().clean()
        if not (self.lotacao_id and self.dia_semana and self.inicio):
            return
        lotacao = self.lotacao
        mesmo_tempo = Horario.objects.filter(dia_semana=self.dia_semana, inicio=self.inicio).exclude(pk=self.pk)
        hora = f"{self.get_dia_semana_display().lower()} às {self.inicio:%H:%M}"

        # 1) A turma não pode ter duas aulas no mesmo tempo.
        ocupado = mesmo_tempo.filter(lotacao__turma=lotacao.turma).select_related("lotacao__materia").first()
        if ocupado:
            raise ValidationError({"inicio": f"A turma já tem {ocupado.lotacao.materia} {hora}."})

        # 2) O professor não pode estar em duas turmas ao mesmo tempo.
        conflito = mesmo_tempo.filter(lotacao__professor=lotacao.professor).select_related(
            "lotacao__turma__serie", "lotacao__turma__escola"
        ).first()
        if conflito:
            outra = conflito.lotacao.turma
            raise ValidationError(
                {"inicio": f"Conflito: {lotacao.professor.nome} já dá aula na turma "
                           f"{outra.serie.nome} {outra.letra} ({outra.escola}) {hora}."}
            )

        # 3) A matéria não pode ter mais tempos na grade do que aulas na lotação.
        usados = Horario.objects.filter(lotacao=lotacao).exclude(pk=self.pk).count()
        if usados >= lotacao.aulas_semanais:
            raise ValidationError(
                {"lotacao": f"{lotacao.materia} já tem as {lotacao.aulas_semanais} aulas da semana na grade."}
            )

    def __str__(self):
        return f"{self.get_dia_semana_display()} {self.inicio:%H:%M} - {self.lotacao.materia}"


class Cardapio(models.Model):
    """Cardápio da merenda de um dia da semana numa escola."""

    escola = models.ForeignKey(Escola, verbose_name="escola", on_delete=models.CASCADE, related_name="cardapios")
    dia_semana = models.PositiveSmallIntegerField(verbose_name="dia", choices=Horario.Dia.choices)
    almoco = models.TextField(verbose_name="almoço", help_text="Um item por linha.")
    lanche = models.TextField(verbose_name="lanche", blank=True, help_text="Um item por linha.")

    class Meta:
        ordering = ["escola", "dia_semana"]
        verbose_name = "cardápio"
        verbose_name_plural = "cardápios da merenda"
        constraints = [
            models.UniqueConstraint(
                fields=["escola", "dia_semana"],
                name="um_cardapio_por_dia",
                violation_error_message="Essa escola já tem cardápio nesse dia.",
            ),
        ]

    def __str__(self):
        return f"{self.escola} - {self.get_dia_semana_display()}"
