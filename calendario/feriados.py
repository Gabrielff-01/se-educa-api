"""Feriados e recessos que se repetem todo ano, para o DIES não digitar um por um."""

from datetime import date, timedelta

from .models import Evento

FERIADO = Evento.Tipo.FERIADO
RECESSO = Evento.Tipo.RECESSO


def pascoa(ano):
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher).

    Não precisa decorar: é uma fórmula conhecida. Carnaval, Semana Santa e
    Corpus Christi mudam de data todo ano, mas sempre a mesma distância da Páscoa.
    Confira: pascoa(2026) tem que dar date(2026, 4, 5).
    """
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    n = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * n) // 451
    mes, dia = divmod(h + n - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


def feriados_do_ano(ano):
    """Lista de (data, descrição, tipo) com os dias sem aula que se repetem todo ano.

    FERIADO: feriados nacionais e a data magna de Sergipe (8 de julho).
    RECESSO: pontos facultativos que o decreto estadual costuma dar todo ano e que
    suspendem as aulas na rede estadual. Confira o decreto de cada ano.
    """
    domingo_de_pascoa = pascoa(ano)
    return [
        (date(ano, 1, 1), "Confraternização Universal", FERIADO),
        (domingo_de_pascoa - timedelta(days=48), "Carnaval", RECESSO),
        (domingo_de_pascoa - timedelta(days=47), "Carnaval", RECESSO),
        (domingo_de_pascoa - timedelta(days=3), "Quinta-feira Santa", RECESSO),
        (domingo_de_pascoa - timedelta(days=2), "Sexta-feira Santa", FERIADO),
        (date(ano, 4, 21), "Tiradentes", FERIADO),
        (date(ano, 5, 1), "Dia do Trabalhador", FERIADO),
        (domingo_de_pascoa + timedelta(days=60), "Corpus Christi", RECESSO),
        (date(ano, 6, 24), "São João", RECESSO),
        (date(ano, 7, 8), "Emancipação Política de Sergipe", FERIADO),
        (date(ano, 9, 7), "Independência do Brasil", FERIADO),
        (date(ano, 10, 12), "Nossa Senhora Aparecida", FERIADO),
        (date(ano, 10, 28), "Dia do Servidor Público", RECESSO),
        (date(ano, 11, 2), "Finados", FERIADO),
        (date(ano, 11, 15), "Proclamação da República", FERIADO),
        (date(ano, 11, 20), "Dia Nacional de Zumbi e da Consciência Negra", FERIADO),
        (date(ano, 12, 25), "Natal", FERIADO),
    ]
