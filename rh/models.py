from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from rede.models import Escola, Materia, Turma
from regulacao.models import Matriz


def so_numeros(texto):
    """Tira tudo que não é número. Ex.: 123.456.789-09 vira 12345678909."""
    return "".join(caractere for caractere in texto if caractere in "0123456789")


def validar_cpf(valor):
    """Confere os 2 dígitos verificadores do CPF. Aceita com ou sem pontos e traço."""
    cpf = so_numeros(valor)
    if len(cpf) != 11:
        raise ValidationError("CPF inválido: tem que ter 11 números.")
    if cpf == cpf[0] * 11:  # 111.111.111-11 passa na conta, mas não existe
        raise ValidationError("CPF inválido.")
    # 1º dígito: pesos 10, 9, ..., 2 nos 9 primeiros números.
    # 2º dígito: pesos 11, 10, ..., 2 nos 10 primeiros números.
    for tamanho in (9, 10):
        soma = sum(int(cpf[i]) * (tamanho + 1 - i) for i in range(tamanho))
        resto = soma % 11
        digito = 0 if resto < 2 else 11 - resto
        if digito != int(cpf[tamanho]):
            raise ValidationError("CPF inválido: os dígitos verificadores não batem.")


def jornada_da_turma(turma):
    """Turma do turno integral segue a matriz de tempo integral; as outras, a de parcial."""
    if turma.turno == Turma.Turno.INTEGRAL:
        return Matriz.Jornada.INTEGRAL
    return Matriz.Jornada.PARCIAL


def matriz_da_turma(turma):
    """A matriz que vale para a turma (mesma série, ano e jornada). None se não tiver."""
    return Matriz.objects.filter(
        serie_id=turma.serie_id,
        ano_letivo=turma.ano_letivo,
        jornada=jornada_da_turma(turma),
    ).first()


class Professor(models.Model):
    class Carga(models.IntegerChoices):
        # Em Sergipe a jornada aparece em horas por mês: 100 h/mês = 20 h por semana.
        H20 = 20, "20 horas (100 h/mês)"
        H40 = 40, "40 horas (200 h/mês)"

    class Vinculo(models.TextChoices):
        EFETIVO = "efetivo", "Efetivo (concursado)"
        TEMPORARIO = "temporario", "Contrato temporário"

    nome = models.CharField(verbose_name="nome completo", max_length=150)
    matricula = models.CharField(
        verbose_name="matrícula funcional",
        max_length=12,
        unique=True,
        error_messages={"unique": "Já existe um professor com essa matrícula."},
        validators=[
            RegexValidator(
                r"^[0-9]{4,10}(-[0-9])?$",
                "Só números. Se tiver dígito verificador, use traço: 123456-7.",
            ),
        ],
    )
    # Simplificação: um CPF, um cadastro. Na vida real a Constituição (art. 37, XVI)
    # deixa o professor ter dois cargos, e cada um teria a sua matrícula.
    cpf = models.CharField(
        verbose_name="CPF",
        max_length=14,  # cabe com pontos e traço; salvamos só os 11 números
        unique=True,
        error_messages={"unique": "Já existe um professor com esse CPF."},
        validators=[validar_cpf],
        help_text="Pode digitar com ou sem pontos e traço.",
    )
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="usuário de acesso",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="professor",
        limit_choices_to={"perfil": "professor"},
        help_text="Login do professor no sistema (perfil Professor). Pode ligar depois.",
    )
    carga_horaria_semanal = models.PositiveSmallIntegerField(
        verbose_name="carga horária semanal",
        choices=Carga.choices,
        default=Carga.H40,
    )
    vinculo = models.CharField(
        verbose_name="vínculo",
        max_length=12,
        choices=Vinculo.choices,
        default=Vinculo.EFETIVO,
    )
    data_admissao = models.DateField(verbose_name="data de admissão", null=True, blank=True)
    ativo = models.BooleanField(verbose_name="ativo", default=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "professor"
        verbose_name_plural = "professores"

    def clean(self):
        super().clean()
        if self.cpf:
            self.cpf = so_numeros(self.cpf)  # antes de checar se o CPF já existe
        if self.pk and self.carga_horaria_semanal:
            self.conferir_reducao_de_carga()

    def conferir_reducao_de_carga(self):
        """Diminuir a carga (ex.: 40h -> 20h) não pode deixar o professor acima do limite."""
        carga_antiga = Professor.objects.get(pk=self.pk).carga_horaria_semanal
        if self.carga_horaria_semanal >= carga_antiga:
            return  # a carga não diminuiu: não tem o que conferir
        alocadas = self.alocacoes.aggregate(total=Sum("horas_semanais"))["total"] or 0
        if alocadas > self.carga_horaria_semanal:
            mensagem = (
                f"{self.nome} está alocado em escolas somando {alocadas} horas. "
                "Diminua ou tire uma alocação antes de diminuir a carga."
            )
            raise ValidationError({"carga_horaria_semanal": mensagem})
        anos = set(self.lotacoes.values_list("turma__ano_letivo", flat=True))
        for ano in sorted(anos):
            aulas = self.aulas_no_ano(ano)
            if aulas > self.limite_aulas:
                mensagem = (
                    f"Com {self.carga_horaria_semanal} horas, o limite é {self.limite_aulas} "
                    f"aulas por semana, mas em {ano} {self.nome} já tem {aulas}. "
                    "Remova lotações antes de diminuir a carga."
                )
                raise ValidationError({"carga_horaria_semanal": mensagem})

    def save(self, *args, **kwargs):
        if self.cpf:
            self.cpf = so_numeros(self.cpf)
        super().save(*args, **kwargs)

    @property
    def cpf_formatado(self):
        c = self.cpf
        return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}" if len(c) == 11 else c

    @property
    def limite_aulas(self):
        """Máximo de aulas por semana: 2/3 da carga (Lei 11.738/2008, art. 2º, § 4º).

        O outro 1/3 é hora-atividade: planejar, corrigir prova, estudar. Cada aula conta
        como 1 hora da jornada, seja de 50 ou de 60 minutos (Parecer CNE/CEB 18/2012).
        O // arredonda pra baixo: 40 h -> 26 aulas, 20 h -> 13 aulas.
        """
        return self.carga_horaria_semanal * 2 // 3

    def aulas_no_ano(self, ano_letivo, exceto=None):
        """Aulas por semana somando as lotações do ano.

        "exceto" serve para a Lotacao que está sendo editada não ser contada duas vezes.
        """
        lotacoes = self.lotacoes.filter(turma__ano_letivo=ano_letivo)
        if exceto is not None and exceto.pk:
            lotacoes = lotacoes.exclude(pk=exceto.pk)
        return lotacoes.aggregate(total=Sum("aulas_semanais"))["total"] or 0

    def __str__(self):
        return f"{self.nome} ({self.matricula})"


class Alocacao(models.Model):
    """Em qual escola o professor trabalha e qual a função dele lá.

    Quem faz o quê:
    - o RH aloca: escolhe a escola e quantas horas da carga ele cumpre nela
      (um professor de 40 h pode ficar 20 h numa escola e 20 h em outra);
    - a escola define a função (professor, diretor, coordenador, secretário) e,
      se for professor, as turmas e matérias dele (a Lotacao, logo abaixo).
    """

    class Funcao(models.TextChoices):
        PROFESSOR = "professor", "Professor(a)"
        DIRETOR = "diretor", "Diretor(a)"
        COORDENADOR = "coordenador", "Coordenador(a)"
        SECRETARIO = "secretario", "Secretário(a) escolar"

    # Quem aparece na "Equipe diretiva" da ficha da escola.
    FUNCOES_DIRETIVAS = [Funcao.DIRETOR, Funcao.COORDENADOR, Funcao.SECRETARIO]

    professor = models.ForeignKey(
        Professor, verbose_name="professor", on_delete=models.PROTECT, related_name="alocacoes"
    )
    escola = models.ForeignKey(Escola, verbose_name="escola", on_delete=models.PROTECT, related_name="alocacoes")
    horas_semanais = models.PositiveSmallIntegerField(
        verbose_name="horas na escola", choices=Professor.Carga.choices, default=Professor.Carga.H40,
        help_text="Quantas horas da carga do professor ele cumpre nesta escola.",
    )
    portaria = models.CharField(
        verbose_name="portaria de lotação", max_length=30, blank=True, help_text="Ex.: 0428/2025"
    )
    desde = models.DateField(verbose_name="na escola desde", default=timezone.localdate)
    funcao = models.CharField(
        verbose_name="função", max_length=12, choices=Funcao.choices, default=Funcao.PROFESSOR
    )
    portaria_funcao = models.CharField(
        verbose_name="portaria da função", max_length=30, blank=True,
        help_text="Diretor e coordenador são nomeados por portaria. Ex.: 3161/2025",
    )

    class Meta:
        ordering = ["escola__nome", "professor__nome"]
        verbose_name = "alocação na escola"
        verbose_name_plural = "alocações nas escolas"
        constraints = [
            models.UniqueConstraint(
                fields=["professor", "escola"],
                name="alocacao_unica",
                violation_error_message="Esse professor já está alocado nessa escola. Edite a alocação que já existe.",
            ),
        ]

    def clean(self):
        super().clean()
        if not (self.professor_id and self.escola_id and self.horas_semanais):
            return
        professor = self.professor
        if not professor.ativo:
            raise ValidationError({"professor": "Esse professor está inativo."})
        if self.horas_semanais > professor.carga_horaria_semanal:
            raise ValidationError({"horas_semanais": (
                f"{professor.nome} tem carga de {professor.carga_horaria_semanal} horas: "
                "não dá pra cumprir mais que isso numa escola só."
            )})
        # A soma das escolas não passa da carga do professor.
        outras = professor.alocacoes.exclude(pk=self.pk).select_related("escola")
        usadas = sum(alocacao.horas_semanais for alocacao in outras)
        if usadas + self.horas_semanais > professor.carga_horaria_semanal:
            onde = ", ".join(f"{a.horas_semanais} h na {a.escola}" for a in outras)
            sobram = max(professor.carga_horaria_semanal - usadas, 0)
            raise ValidationError({"horas_semanais": (
                f"{professor.nome} tem {professor.carga_horaria_semanal} horas e já está com {onde}. "
                f"Sobram {sobram} horas."
            )})
        # Diminuir as horas não pode deixar as aulas que a escola já deu acima do novo limite.
        if self.pk:
            ano = timezone.localdate().year
            aulas = self.aulas_no_ano(ano)
            if aulas > self.limite_aulas:
                raise ValidationError({"horas_semanais": (
                    f"Com {self.horas_semanais} horas o limite nesta escola é {self.limite_aulas} aulas, "
                    f"mas {professor.nome} já tem {aulas}. A escola precisa tirar aulas antes."
                )})

    @property
    def limite_aulas(self):
        """Máximo de aulas por semana nesta escola: 2/3 das horas dele aqui (mesma regra do Professor)."""
        return self.horas_semanais * 2 // 3

    def aulas_no_ano(self, ano_letivo, exceto=None):
        """Aulas por semana que o professor tem nesta escola, no ano."""
        lotacoes = Lotacao.objects.filter(
            professor_id=self.professor_id, turma__escola_id=self.escola_id, turma__ano_letivo=ano_letivo
        )
        if exceto is not None and exceto.pk:
            lotacoes = lotacoes.exclude(pk=exceto.pk)
        return lotacoes.aggregate(total=Sum("aulas_semanais"))["total"] or 0

    def __str__(self):
        return f"{self.professor.nome} - {self.escola} ({self.get_funcao_display()})"


class Lotacao(models.Model):
    """Atribuição de aulas: qual professor dá qual matéria, em qual turma.

    Quem cadastra é a escola, e só com professores que o RH alocou nela (Alocacao).
    """

    professor = models.ForeignKey(
        Professor, verbose_name="professor", on_delete=models.PROTECT, related_name="lotacoes"
    )
    turma = models.ForeignKey(
        Turma, verbose_name="turma", on_delete=models.PROTECT, related_name="lotacoes"
    )
    materia = models.ForeignKey(
        Materia, verbose_name="matéria", on_delete=models.PROTECT, related_name="lotacoes"
    )
    aulas_semanais = models.PositiveSmallIntegerField(
        verbose_name="aulas por semana",
        validators=[MinValueValidator(1), MaxValueValidator(20)],
    )

    class Meta:
        ordering = ["-turma__ano_letivo", "professor__nome", "materia__nome"]
        verbose_name = "lotação"
        verbose_name_plural = "lotações"
        constraints = [
            models.UniqueConstraint(
                fields=["professor", "turma", "materia"],
                name="lotacao_unica",
                violation_error_message=(
                    "Esse professor já dá essa matéria nessa turma. "
                    "Edite a lotação que já existe."
                ),
            ),
        ]

    def clean(self):
        super().clean()
        campos = [self.professor_id, self.turma_id, self.materia_id, self.aulas_semanais]
        if not all(campos):
            return  # falta campo: o Django já mostra "Este campo é obrigatório"

        duplicada = Lotacao.objects.filter(
            professor_id=self.professor_id, turma_id=self.turma_id, materia_id=self.materia_id
        ).exclude(pk=self.pk)
        if duplicada.exists():
            return  # o aviso de "já existe" vem da UniqueConstraint lá do Meta

        professor = self.professor
        turma = self.turma
        if not professor.ativo:
            raise ValidationError({"professor": "Esse professor está inativo."})

        # Regra 0: o RH tem que ter alocado o professor nesta escola, na função de professor.
        alocacao = Alocacao.objects.filter(professor=professor, escola_id=turma.escola_id).first()
        if alocacao is None:
            raise ValidationError({"professor": (
                f"{professor.nome} não está alocado na {turma.escola}. Peça ao RH para alocar."
            )})
        if alocacao.funcao != Alocacao.Funcao.PROFESSOR:
            raise ValidationError({"professor": (
                f"{professor.nome} está como {alocacao.get_funcao_display()} nesta escola. "
                "Mude a função para Professor(a) antes de dar turmas a ele."
            )})

        # Regra 1: a matéria tem que estar na matriz curricular da turma (Aula 3, DED).
        matriz = matriz_da_turma(turma)
        if matriz is None:
            jornada = jornada_da_turma(turma).label.lower()
            mensagem = (
                f"{turma.serie} não tem matriz de {jornada} em {turma.ano_letivo}. "
                "Cadastre antes em Regulação (DED) > Matrizes curriculares."
            )
            raise ValidationError({"turma": mensagem})
        item = matriz.itens.filter(materia=self.materia).first()
        if item is None:
            mensagem = f"{self.materia} não está na matriz de {turma.serie}."
            raise ValidationError({"materia": mensagem})

        # Regra 2: somando todos os professores, a matéria não passa das aulas da matriz.
        outras = Lotacao.objects.filter(turma=turma, materia=self.materia).exclude(pk=self.pk)
        ja_lotadas = outras.aggregate(total=Sum("aulas_semanais"))["total"] or 0
        sobram = max(item.aulas_semanais - ja_lotadas, 0)
        if self.aulas_semanais > sobram:
            mensagem = (
                f"A matriz tem {item.aulas_semanais} aulas de {self.materia} por semana. "
                f"Já lotadas com outros professores: {ja_lotadas}. Disponíveis: {sobram}."
            )
            raise ValidationError({"aulas_semanais": mensagem})

        # Regra 3 (Lei 11.738/2008): o professor não passa de 2/3 das horas com alunos.
        # Conta só esta escola, com as horas que o RH deu a ele aqui.
        antes = alocacao.aulas_no_ano(turma.ano_letivo, exceto=self)
        depois = antes + self.aulas_semanais
        if depois > alocacao.limite_aulas:
            mensagem = (
                f"{professor.nome} ficaria com {depois} aulas por semana nesta escola. "
                f"Com {alocacao.horas_semanais} horas aqui, o limite é "
                f"{alocacao.limite_aulas} aulas (2/3 da carga, Lei 11.738/2008). "
                f"Hoje já tem {antes}."
            )
            raise ValidationError({"aulas_semanais": mensagem})

    def __str__(self):
        return f"{self.professor.nome} - {self.materia} - {self.turma}"


class Afastamento(models.Model):
    """Licença, férias ou outro período em que o professor não está na escola."""

    class Tipo(models.TextChoices):
        SAUDE = "saude", "Licença para tratamento de saúde"
        MATERNIDADE = "maternidade", "Licença-maternidade"
        PATERNIDADE = "paternidade", "Licença-paternidade"
        FERIAS = "ferias", "Férias"
        CAPACITACAO = "capacitacao", "Capacitação / formação"
        OUTRO = "outro", "Outro"

    professor = models.ForeignKey(
        Professor, verbose_name="professor", on_delete=models.CASCADE, related_name="afastamentos"
    )
    tipo = models.CharField(verbose_name="tipo", max_length=12, choices=Tipo.choices)
    inicio = models.DateField(verbose_name="início")
    fim = models.DateField(verbose_name="volta em", help_text="Último dia do afastamento.")
    observacao = models.CharField(verbose_name="observação", max_length=200, blank=True)

    class Meta:
        ordering = ["-inicio"]
        verbose_name = "afastamento"
        verbose_name_plural = "afastamentos"

    def clean(self):
        super().clean()
        if not (self.professor_id and self.inicio and self.fim):
            return
        if self.fim < self.inicio:
            raise ValidationError({"fim": "A volta não pode ser antes do início."})
        # Dois afastamentos do mesmo professor não podem se sobrepor.
        sobreposto = Afastamento.objects.filter(
            professor_id=self.professor_id, inicio__lte=self.fim, fim__gte=self.inicio
        ).exclude(pk=self.pk).first()
        if sobreposto:
            mensagem = (
                f"Já existe {sobreposto.get_tipo_display().lower()} de "
                f"{sobreposto.inicio:%d/%m/%Y} a {sobreposto.fim:%d/%m/%Y} nesse período."
            )
            raise ValidationError({"inicio": mensagem})

    @property
    def vigente(self):
        return self.inicio <= timezone.localdate() <= self.fim

    def __str__(self):
        return f"{self.professor.nome}: {self.get_tipo_display()} ({self.inicio:%d/%m} a {self.fim:%d/%m})"
