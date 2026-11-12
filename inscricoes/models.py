"""Matrícula pela internet: a família se inscreve sozinha, antes de ter login.

Caminho:
1. Na tela de entrada do app, "Fazer matrícula": a família digita o CPF do aluno.
   Já tem cadastro? Vai pro login. Não tem? Preenche os dados, o endereço, a série,
   o turno e por último a escola (só aparecem as que têm turma daquela série e turno).
   Nasce uma Inscricao "aguardando análise".
2. A ESCOLA escolhida analisa (tela "Matrículas pela internet") e aprova ou recusa com o motivo.
3. Aprovada: o sistema cria o aluno, o responsável, o login do aluno (e-mail e senha
   que ele escolheu) e a matrícula. Se a escola já escolheu a turma, a matrícula sai
   confirmada; se não, fica "em análise" sem turma e aparece na Enturmação.
Enquanto não é aprovada, quem tenta entrar com o e-mail vê o andamento no próprio login.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from academico.models import Aluno, Matricula, Vinculo
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

    # Análise da escola escolhida
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
                violation_error_message="Já existe um pedido de matrícula desse CPF esperando a análise da escola.",
            ),
            models.UniqueConstraint(
                fields=["email"], condition=Q(status="aguardando"), name="uma_inscricao_aguardando_por_email",
                violation_error_message="Já existe um pedido de matrícula com esse e-mail esperando a análise da escola.",
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
            # Só escola que oferece a série E tem turma dela no ano (senão o aluno fica sem turma pra ir).
            turmas = Turma.objects.filter(escola_id=self.escola_id, serie_id=self.serie_id, ano_letivo=self.ano_letivo)
            if not self.escola.ofertas.filter(ano_letivo=self.ano_letivo, series=self.serie).exists() or not turmas.exists():
                erros["escola"] = f"{self.escola} não tem turma de {self.serie.nome} em {self.ano_letivo}."
            elif self.turno_preferido and not turmas.filter(turno=self.turno_preferido).exists():
                erros["turno_preferido"] = (f"{self.escola} não tem turma de {self.serie.nome} no turno "
                                            f"{self.get_turno_preferido_display().lower()}.")
        # Aluno que já está na rede não faz matrícula nova pela internet: entra com o login dele.
        if self.cpf and self.pk is None and Aluno.objects.filter(cpf=self.cpf).exists():
            erros["cpf"] = "Verificamos que este CPF já possui cadastro. Entre com seu usuário e senha."
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
