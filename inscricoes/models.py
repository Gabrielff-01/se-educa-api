"""Matrícula pela internet: a família se inscreve sozinha, antes de ter login.

Caminho:
1. Na tela de entrada do app, "Fazer matrícula": a família preenche os dados do aluno,
   o endereço e a escola/série que quer. Nasce uma Inscricao "aguardando análise".
2. O DIES analisa (tela "Matrículas pela internet") e aprova ou recusa com o motivo.
3. Aprovada: o sistema cria o aluno, o responsável, o login do aluno (e-mail e senha
   que ele escolheu) e a matrícula "em análise" SEM turma. Ela cai na Enturmação do DIES.
Enquanto não é aprovada, quem tenta entrar com o e-mail vê o andamento no próprio login.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from academico.models import Matricula, Vinculo
from rede.models import Escola, Serie, Turma
from rh.models import so_numeros, validar_cpf


class Inscricao(models.Model):
    class Status(models.TextChoices):
        AGUARDANDO = "aguardando", "Aguardando análise"
        APROVADA = "aprovada", "Aprovada"
        RECUSADA = "recusada", "Recusada"

    class Sexo(models.TextChoices):
        MASCULINO = "M", "Masculino"
        FEMININO = "F", "Feminino"
        NAO_INFORMADO = "N", "Prefiro não informar"

    class Raca(models.TextChoices):  # as 5 categorias do IBGE / Censo Escolar
        AMARELA = "amarela", "Amarela"
        BRANCA = "branca", "Branca"
        INDIGENA = "indigena", "Indígena"
        PARDA = "parda", "Parda"
        PRETA = "preta", "Preta"

    protocolo = models.CharField(verbose_name="protocolo", max_length=12, unique=True, null=True, editable=False,
                                 help_text="Gerado sozinho. Ex.: 2026-00042")

    # Etapa 1: dados do aluno e do responsável
    aluno_nome = models.CharField(verbose_name="nome do aluno", max_length=150)
    data_nascimento = models.DateField(verbose_name="data de nascimento")
    sexo = models.CharField(verbose_name="sexo", max_length=1, choices=Sexo.choices)
    raca = models.CharField(verbose_name="cor/raça", max_length=10, choices=Raca.choices)
    cpf = models.CharField(verbose_name="CPF do aluno", max_length=14, validators=[validar_cpf])
    bolsa_familia = models.BooleanField(verbose_name="recebe Bolsa Família", default=False)
    nis = models.CharField(verbose_name="NIS", max_length=11, blank=True,
                           validators=[RegexValidator(r"^\d{11}$", "O NIS tem 11 números.")])
    responsavel_nome = models.CharField(verbose_name="nome do responsável legal", max_length=150)
    responsavel_cpf = models.CharField(verbose_name="CPF do responsável", max_length=14, validators=[validar_cpf])
    responsavel_parentesco = models.CharField(verbose_name="parentesco", max_length=10,
                                              choices=Vinculo.Parentesco.choices, default=Vinculo.Parentesco.MAE)
    telefone = models.CharField(verbose_name="telefone", max_length=20)
    email = models.EmailField(verbose_name="e-mail (vira o login do aluno)")
    senha = models.CharField(verbose_name="senha (guardada criptografada)", max_length=128)

    # Etapa 2: endereço
    cep = models.CharField(verbose_name="CEP", max_length=9, validators=[RegexValidator(r"^\d{5}-?\d{3}$", "CEP tem 8 números.")])
    endereco = models.CharField(verbose_name="endereço", max_length=150)
    numero = models.CharField(verbose_name="número", max_length=10)
    complemento = models.CharField(verbose_name="complemento", max_length=60, blank=True)
    bairro = models.CharField(verbose_name="bairro", max_length=80)
    cidade = models.CharField(verbose_name="cidade", max_length=80)
    uf = models.CharField(verbose_name="UF", max_length=2)

    # Etapa 3: escola e série que a família quer
    escola = models.ForeignKey(Escola, verbose_name="escola desejada", on_delete=models.PROTECT, related_name="inscricoes")
    serie = models.ForeignKey(Serie, verbose_name="série", on_delete=models.PROTECT, related_name="inscricoes")
    ano_letivo = models.PositiveSmallIntegerField(verbose_name="ano letivo",
                                                  validators=[MinValueValidator(2000), MaxValueValidator(2100)])
    turno_preferido = models.CharField(verbose_name="turno preferido", max_length=10,
                                       choices=Turma.Turno.choices, blank=True)

    # Análise do DIES
    status = models.CharField(verbose_name="situação", max_length=10, choices=Status.choices, default=Status.AGUARDANDO)
    motivo_recusa = models.TextField(verbose_name="motivo da recusa", blank=True)
    analisada_por = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="analisada por", on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name="+")
    analisada_em = models.DateTimeField(verbose_name="analisada em", null=True, blank=True)
    matricula = models.OneToOneField(Matricula, verbose_name="matrícula criada", on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name="inscricao")
    criada_em = models.DateTimeField(verbose_name="enviada em", auto_now_add=True)

    class Meta:
        ordering = ["-criada_em"]
        verbose_name = "matrícula pela internet"
        verbose_name_plural = "matrículas pela internet"
        constraints = [
            models.UniqueConstraint(
                fields=["cpf"], condition=Q(status="aguardando"), name="uma_inscricao_aguardando_por_cpf",
                violation_error_message="Já existe um pedido de matrícula desse CPF esperando a análise do DIES.",
            ),
            models.UniqueConstraint(
                fields=["email"], condition=Q(status="aguardando"), name="uma_inscricao_aguardando_por_email",
                violation_error_message="Já existe um pedido de matrícula com esse e-mail esperando a análise do DIES.",
            ),
        ]

    def __str__(self):
        return f"{self.protocolo or 'novo'} · {self.aluno_nome}"

    def clean(self):
        super().clean()
        # Guarda só os números (o formulário manda com pontos e traço).
        self.cpf = so_numeros(self.cpf or "")
        self.responsavel_cpf = so_numeros(self.responsavel_cpf or "")
        self.email = (self.email or "").strip().lower()
        self.uf = (self.uf or "").strip().upper()
        erros = {}
        if self.bolsa_familia and not self.nis:
            erros["nis"] = "Quem recebe Bolsa Família precisa informar o NIS."
        if self.data_nascimento and self.data_nascimento > timezone.localdate():
            erros["data_nascimento"] = "A data de nascimento está no futuro."
        if self.cpf and self.cpf == self.responsavel_cpf and self.idade is not None and self.idade < 18:
            erros["responsavel_cpf"] = "O CPF do responsável tem que ser diferente do CPF do aluno."
        if self.escola_id and self.serie_id and self.ano_letivo:
            if not self.escola.ofertas.filter(ano_letivo=self.ano_letivo, series=self.serie).exists():
                erros["serie"] = f"{self.escola} não oferece {self.serie.nome} em {self.ano_letivo}."
        # O aluno não tem CPF no cadastro da rede; quem garante que não entra duas vezes é o pedido aprovado.
        if self.cpf and self.pk is None and self.ano_letivo:
            aprovada = Inscricao.objects.filter(cpf=self.cpf, ano_letivo=self.ano_letivo, status=self.Status.APROVADA).first()
            if aprovada:
                erros["cpf"] = (f"Esse aluno já tem matrícula aprovada para {self.ano_letivo} (protocolo {aprovada.protocolo}). "
                                "Para mudar de escola, fale com a escola.")
        if self.email and self.pk is None:
            from contas.models import Usuario  # aqui dentro: contas não depende deste app

            if Usuario.objects.filter(Q(username__iexact=self.email) | Q(email__iexact=self.email)).exists():
                erros["email"] = "Esse e-mail já tem login no SE Educa. Use outro ou entre com ele."
        if erros:
            raise ValidationError(erros)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.protocolo:
            # O protocolo usa o id, que só existe depois de salvar. Ex.: 2026-00042
            self.protocolo = f"{self.criada_em.year}-{self.pk:05d}"
            super().save(update_fields=["protocolo"])

    @property
    def idade(self):
        if not self.data_nascimento:
            return None
        hoje = timezone.localdate()
        nascimento = self.data_nascimento
        return hoje.year - nascimento.year - ((hoje.month, hoje.day) < (nascimento.month, nascimento.day))
