from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from rede.models import Escola

# LDB, art. 24: o ano letivo tem no mínimo 200 dias de efetivo trabalho escolar.
DIAS_LETIVOS_MINIMOS = 200

# O ano letivo é dividido em 4 unidades (bimestres). Cada uma tem a sua nota.
UNIDADES_POR_ANO = 4


def dias_entre(inicio, fim):
    """Lista com todos os dias de inicio até fim, incluindo os dois."""
    dias = []
    dia = inicio
    while dia <= fim:
        dias.append(dia)
        dia += timedelta(days=1)  # o dia seguinte
    return dias


def listar_dias_letivos(inicio, fim, eventos):
    """Lista os dias letivos de um calendário, em ordem.

    Dia letivo = (segunda a sexta OU dia marcado como aula extra)
                 E sem feriado, férias, recesso ou planejamento.
    """
    nao_letivos = set()
    aulas_extras = set()
    for evento in eventos:
        dias = dias_entre(evento.data_inicio, evento.ultimo_dia)
        if evento.tipo in Evento.TIPOS_NAO_LETIVOS:
            nao_letivos.update(dias)
        elif evento.tipo == Evento.Tipo.AULA:
            aulas_extras.update(dias)

    letivos = []
    for dia in dias_entre(inicio, fim):
        # weekday(): 0 = segunda, 1 = terça ... 4 = sexta, 5 = sábado, 6 = domingo
        dia_de_semana = dia.weekday() < 5
        if (dia_de_semana or dia in aulas_extras) and dia not in nao_letivos:
            letivos.append(dia)
    return letivos


def calendario_da_escola(escola, ano_letivo):
    """O calendário que vale para a escola: o dela, se tiver; senão, o da rede. None se não houver."""
    proprio = CalendarioLetivo.objects.filter(escola=escola, ano_letivo=ano_letivo).first()
    if proprio is not None:
        return proprio
    return CalendarioLetivo.objects.filter(escola__isnull=True, ano_letivo=ano_letivo).first()


class CalendarioLetivo(models.Model):
    """Calendário de um ano letivo: da rede toda ou de uma escola específica."""

    ano_letivo = models.PositiveSmallIntegerField(
        verbose_name="ano letivo",
        validators=[MinValueValidator(2000), MaxValueValidator(2100)],
    )
    escola = models.ForeignKey(
        Escola,
        verbose_name="escola",
        on_delete=models.PROTECT,
        related_name="calendarios",
        null=True,
        blank=True,
        help_text="Em branco = calendário da rede estadual (vale para todas as escolas).",
    )
    data_inicio = models.DateField(verbose_name="início das aulas")
    data_fim = models.DateField(
        verbose_name="fim das aulas",
        help_text="Último dia de aula regular. Recuperação e exame final ficam de fora "
                  "(LDB, art. 24, I).",
    )

    class Meta:
        ordering = ["-ano_letivo", "escola__nome"]
        verbose_name = "calendário letivo"
        verbose_name_plural = "calendários letivos"
        constraints = [
            # Uma escola só tem um calendário por ano...
            models.UniqueConstraint(
                fields=["escola", "ano_letivo"],
                condition=Q(escola__isnull=False),
                name="calendario_unico_por_escola_ano",
                violation_error_message="Essa escola já tem um calendário nesse ano letivo.",
            ),
            # ...e a rede também só tem um. Precisa desta segunda regra porque o banco
            # não compara valores vazios (NULL): sem ela daria pra criar dois da rede.
            models.UniqueConstraint(
                fields=["ano_letivo"],
                condition=Q(escola__isnull=True),
                name="calendario_da_rede_unico_por_ano",
                violation_error_message="A rede já tem um calendário nesse ano letivo.",
            ),
        ]

    def clean(self):
        super().clean()
        if not self.data_inicio or not self.data_fim:
            return  # falta data: o Django já mostra "Este campo é obrigatório"
        if self.data_fim <= self.data_inicio:
            raise ValidationError({"data_fim": "O fim tem que ser depois do início."})
        if self.ano_letivo and self.data_inicio.year != self.ano_letivo:
            ano = self.ano_letivo
            mensagem = f"As aulas de {ano} têm que começar em {ano}."
            raise ValidationError({"data_inicio": mensagem})
        if (self.data_fim - self.data_inicio).days > 366:
            raise ValidationError({"data_fim": "O calendário não pode passar de um ano."})

    @property
    def abrangencia(self):
        return self.escola.nome if self.escola_id else "Rede estadual"

    @property
    def dias_letivos(self):
        return len(self.lista_dias_letivos())

    @property
    def cumpre_minimo(self):
        return self.dias_letivos >= DIAS_LETIVOS_MINIMOS

    def lista_dias_letivos(self):
        return listar_dias_letivos(self.data_inicio, self.data_fim, self.eventos.all())

    def eh_dia_letivo(self, data):
        return data in set(self.lista_dias_letivos())

    def unidades(self):
        """Divide o ano em 4 unidades (bimestres) com o mesmo número de dias letivos.

        Devolve [(1, primeiro_dia, ultimo_dia), (2, ...), (3, ...), (4, ...)].
        Ex.: 200 dias letivos = 4 unidades de 50 dias.
        """
        dias = self.lista_dias_letivos()
        if not dias:
            return []
        tamanho = len(dias) / UNIDADES_POR_ANO
        resultado = []
        for numero in range(1, UNIDADES_POR_ANO + 1):
            primeiro = dias[round((numero - 1) * tamanho)]
            ultimo = dias[min(round(numero * tamanho), len(dias)) - 1]
            resultado.append((numero, primeiro, ultimo))
        return resultado

    def unidade_em(self, data):
        """Em qual unidade (1 a 4) cai a data. Antes do início = 1; depois do fim = 4."""
        for numero, _primeiro, ultimo in self.unidades():
            if data <= ultimo:
                return numero
        return UNIDADES_POR_ANO

    def adicionar_feriados(self):
        """Cria os feriados e recessos que caem dentro do calendário. Devolve quantos criou.

        Fica no model (e não no admin) para o admin e a API usarem a mesma regra.
        """
        from .feriados import feriados_do_ano  # aqui dentro: feriados.py importa este arquivo

        # Dias que o DIES já decidiu: sem aula (feriado, férias...) ou com aula extra.
        tipos_que_decidem = Evento.TIPOS_NAO_LETIVOS + [Evento.Tipo.AULA]
        eventos = list(self.eventos.all())
        criados = 0
        for ano in sorted({self.data_inicio.year, self.data_fim.year}):
            for data, descricao, tipo in feriados_do_ano(ano):
                if not self.data_inicio <= data <= self.data_fim:
                    continue  # cai antes do início ou depois do fim das aulas
                ja_decidido = any(
                    evento.tipo in tipos_que_decidem
                    and evento.data_inicio <= data <= evento.ultimo_dia
                    for evento in eventos
                )
                if ja_decidido:
                    continue  # não duplica nem passa por cima do que o DIES já marcou
                novo = Evento.objects.create(
                    calendario=self, tipo=tipo, descricao=descricao, data_inicio=data
                )
                eventos.append(novo)  # 2 datas no mesmo dia: entra só a 1ª
                criados += 1
        return criados

    def __str__(self):
        return f"Calendário {self.ano_letivo} - {self.abrangencia}"


class Evento(models.Model):
    """Um dia (ou período) especial dentro do calendário."""

    class Tipo(models.TextChoices):
        FERIADO = "feriado", "Feriado"
        FERIAS = "ferias", "Férias"
        RECESSO = "recesso", "Recesso / ponto facultativo"
        PLANEJAMENTO = "planejamento", "Planejamento (sem alunos)"
        PROVA = "prova", "Prova / avaliação"  # prova bimestral é dia letivo normal
        AULA = "aula", "Aula extra (sábado letivo ou reposição)"

    # Tipos que tiram o dia da contagem de dias letivos.
    TIPOS_NAO_LETIVOS = [Tipo.FERIADO, Tipo.FERIAS, Tipo.RECESSO, Tipo.PLANEJAMENTO]

    calendario = models.ForeignKey(
        CalendarioLetivo,
        verbose_name="calendário",
        on_delete=models.CASCADE,
        related_name="eventos",
    )
    tipo = models.CharField(verbose_name="tipo", max_length=15, choices=Tipo.choices)
    descricao = models.CharField(
        verbose_name="descrição",
        max_length=100,
        help_text="Ex.: Tiradentes, 1ª avaliação.",
    )
    data_inicio = models.DateField(verbose_name="data")
    data_fim = models.DateField(
        verbose_name="até",
        null=True,
        blank=True,
        help_text="Só para períodos (ex.: férias). Em branco = um dia só.",
    )

    class Meta:
        ordering = ["data_inicio"]
        verbose_name = "evento"
        verbose_name_plural = "eventos"

    @property
    def ultimo_dia(self):
        """Último dia do evento. Se o "até" está em branco, é um dia só."""
        return self.data_fim or self.data_inicio

    def clean(self):
        super().clean()
        if not self.data_inicio:
            return
        if self.data_fim == self.data_inicio:
            self.data_fim = None  # "até" igual à data é um dia só: guardamos em branco
        if self.data_fim and self.data_fim < self.data_inicio:
            raise ValidationError({"data_fim": "A data final não pode ser antes da inicial."})

        # No admin, self.calendario é o calendário da parte de cima da tela,
        # já com as datas digitadas (mesmo antes de salvar).
        calendario = getattr(self, "calendario", None)  # None se ainda não tem calendário
        if not calendario or not calendario.data_inicio or not calendario.data_fim:
            return
        if calendario.data_fim <= calendario.data_inicio:
            return  # as datas do calendário estão erradas: o erro já aparece lá em cima
        if self.data_inicio < calendario.data_inicio or self.ultimo_dia > calendario.data_fim:
            mensagem = (
                f"Essa data fica fora do calendário ({calendario.data_inicio:%d/%m/%Y} "
                f"a {calendario.data_fim:%d/%m/%Y})."
            )
            raise ValidationError({"data_inicio": mensagem})

    def __str__(self):
        if self.data_fim:
            return f"{self.descricao} ({self.data_inicio:%d/%m} a {self.data_fim:%d/%m})"
        return f"{self.descricao} ({self.data_inicio:%d/%m})"
