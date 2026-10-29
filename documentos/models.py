"""Documentos que o aluno ou o responsável mandam para a escola (atestado, papéis da matrícula...).

Como funciona:
1. O aluno ou o responsável escolhe o tipo, anexa o arquivo (PDF, JPG ou PNG, até 5 MB) e envia.
   O documento vai para a escola onde o aluno está matriculado neste ano.
2. A escola abre o arquivo e aceita ou recusa (explicando o motivo, ex.: "foto ilegível").
3. Quem enviou é avisado nas notificações. Se foi recusado, é só mandar de novo.

O arquivo fica guardado no próprio banco (Neon), e não numa pasta do servidor: o Render
grátis apaga as pastas a cada deploy, e o banco não.
"""

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from academico.models import Aluno
from rede.models import Escola

TAMANHO_MAXIMO = 5 * 1024 * 1024  # 5 MB


class Documento(models.Model):
    class Tipo(models.TextChoices):
        # Saúde e faltas
        ATESTADO = "atestado", "Atestado médico"
        JUSTIFICATIVA = "justificativa", "Justificativa de falta"
        LAUDO = "laudo", "Laudo ou relatório médico (AEE)"
        VACINA = "vacina", "Cartão de vacinação"
        SUS = "sus", "Cartão do SUS"
        # Matrícula e cadastro
        CERTIDAO = "certidao", "Certidão de nascimento"
        RG_CPF = "rg_cpf", "RG ou CPF do aluno"
        DOC_RESPONSAVEL = "doc_responsavel", "Documento do responsável"
        RESIDENCIA = "residencia", "Comprovante de residência"
        FOTO = "foto", "Foto 3x4"
        HISTORICO = "historico", "Histórico ou declaração da escola anterior"
        NIS = "nis", "Comprovante do NIS / Bolsa Família"
        # Outros
        AUTORIZACAO = "autorizacao", "Autorização assinada (passeio, saída)"
        OUTRO = "outro", "Outro documento"

    # Tipos que cobrem dias de aula: pedem o período (de quando até quando).
    COM_PERIODO = {Tipo.ATESTADO, Tipo.JUSTIFICATIVA}

    class Status(models.TextChoices):
        AGUARDANDO = "aguardando", "Aguardando análise"
        ACEITO = "aceito", "Aceito"
        RECUSADO = "recusado", "Recusado"

    aluno = models.ForeignKey(Aluno, verbose_name="aluno", on_delete=models.CASCADE, related_name="documentos")
    # A escola onde o aluno estava matriculado quando enviou (é ela quem analisa).
    escola = models.ForeignKey(Escola, verbose_name="escola", on_delete=models.CASCADE, related_name="documentos")
    tipo = models.CharField(verbose_name="tipo", max_length=20, choices=Tipo.choices)
    descricao = models.CharField(verbose_name="observação", max_length=300, blank=True)
    data_inicio = models.DateField(verbose_name="de", null=True, blank=True)
    data_fim = models.DateField(verbose_name="até", null=True, blank=True)

    # O arquivo em si (bytes) e os dados dele.
    arquivo = models.BinaryField(verbose_name="arquivo", editable=False)
    nome_arquivo = models.CharField(verbose_name="nome do arquivo", max_length=150)
    tipo_arquivo = models.CharField(verbose_name="formato", max_length=40)  # ex.: application/pdf
    tamanho = models.PositiveIntegerField(verbose_name="tamanho (bytes)")

    status = models.CharField(verbose_name="situação", max_length=12, choices=Status.choices,
                              default=Status.AGUARDANDO)
    resposta = models.CharField(verbose_name="resposta da escola", max_length=500, blank=True)
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="enviado por",
                                    on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    enviado_em = models.DateTimeField(verbose_name="enviado em", auto_now_add=True)
    analisado_por = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="analisado por",
                                      on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    analisado_em = models.DateTimeField(verbose_name="analisado em", null=True, blank=True)

    class Meta:
        ordering = ["-enviado_em", "-pk"]
        verbose_name = "documento"
        verbose_name_plural = "documentos"

    def __str__(self):
        return f"{self.get_tipo_display()} de {self.aluno}"

    def clean(self):
        super().clean()
        erros = {}
        if self.tipo in self.COM_PERIODO:
            if not self.data_inicio:
                erros["data_inicio"] = "Informe o primeiro dia."
            if not self.data_fim:
                erros["data_fim"] = "Informe o último dia."
            if self.data_inicio and self.data_fim:
                if self.data_fim < self.data_inicio:
                    erros["data_fim"] = "O último dia vem antes do primeiro."
                elif (self.data_fim - self.data_inicio).days > 180:
                    erros["data_fim"] = "O período passa de 180 dias. Para afastamento longo, fale com a escola."
                elif self.data_inicio > timezone.localdate() + timedelta(days=30):
                    erros["data_inicio"] = "O período começa daqui a mais de 30 dias."
        else:
            # Só atestado e justificativa têm período: nos outros tipos, ignora.
            self.data_inicio = self.data_fim = None
        if self.tipo == self.Tipo.OUTRO and not self.descricao.strip():
            erros["descricao"] = "Diga que documento é esse."
        if self.tamanho and self.tamanho > TAMANHO_MAXIMO:
            erros["arquivo"] = "O arquivo passa de 5 MB."
        if erros:
            raise ValidationError(erros)
