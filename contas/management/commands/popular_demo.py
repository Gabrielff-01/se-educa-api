"""Cria os usuários de demonstração e dados de exemplo.

Uso:  python manage.py popular_demo

Pode rodar quantas vezes quiser: o que já existe não é duplicado (get_or_create),
e as senhas dos usuários de demonstração voltam para as do README.
Escolas, códigos INEP, CPFs e pessoas são FICTÍCIOS.
"""

from datetime import date

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import transaction

from academico.demo import DemoAcademica, cpf_ficticio
from calendario.models import CalendarioLetivo, Evento
from contas.models import Usuario
from rede.models import Curso, Escola, Materia, Regional, Serie, Turma
from regulacao.models import AtoAutorizativo, ItemMatriz, Matriz, Oferta
from rh.models import Lotacao, Professor
from solicitacoes.demo import criar_pedidos_demo

ANO = 2026

MATERIAS = [
    ("Português", Materia.Area.LINGUAGENS),
    ("Inglês", Materia.Area.LINGUAGENS),
    ("Arte", Materia.Area.LINGUAGENS),
    ("Educação Física", Materia.Area.LINGUAGENS),
    ("Matemática", Materia.Area.MATEMATICA),
    ("Ciências", Materia.Area.NATUREZA),
    ("Física", Materia.Area.NATUREZA),
    ("Química", Materia.Area.NATUREZA),
    ("Biologia", Materia.Area.NATUREZA),
    ("História", Materia.Area.HUMANAS),
    ("Geografia", Materia.Area.HUMANAS),
    ("Sociologia", Materia.Area.HUMANAS),
    ("Filosofia", Materia.Area.HUMANAS),
]

# 30 aulas de 50 min em 40 semanas = 1.000 h (Ensino Médio)
MATRIZ_MEDIO = {
    "Português": 5, "Matemática": 5, "Física": 2, "Química": 2, "Biologia": 2,
    "História": 2, "Geografia": 2, "Inglês": 2, "Educação Física": 2, "Arte": 2,
    "Sociologia": 2, "Filosofia": 2,
}
# 25 aulas de 50 min em 40 semanas = 833 h (Fundamental: mínimo 800 h)
MATRIZ_FUNDAMENTAL = {
    "Português": 5, "Matemática": 5, "Ciências": 3, "História": 3, "Geografia": 3,
    "Inglês": 2, "Educação Física": 2, "Arte": 2,
}

# usuário, senha, nome, sobrenome, perfil, setor, escola (chave de criar_escolas ou None)
USUARIOS = [
    ("aluno1", "aluno", "Ana Beatriz", "Souza", Usuario.Perfil.ALUNO, "", "atheneu"),
    ("responsavel1", "responsavel", "Maria José", "Souza", Usuario.Perfil.RESPONSAVEL, "", "atheneu"),
    ("professor1", "professor", "Carlos Eduardo", "Menezes", Usuario.Perfil.PROFESSOR, "", "atheneu"),
    ("escola1", "escola", "Cláudia", "Ramos", Usuario.Perfil.ESCOLA, "", "atheneu"),
    ("escola2", "escola", "Fernanda", "Lima", Usuario.Perfil.ESCOLA, "", "goncalo"),
    ("escola3", "escola", "Marcos", "Vieira", Usuario.Perfil.ESCOLA, "", "murilo"),
    ("dies1", "dies", "Ricardo", "Alves", Usuario.Perfil.SECRETARIA, Usuario.Setor.DIES, None),
    ("ded1", "ded", "Patrícia", "Moura", Usuario.Perfil.SECRETARIA, Usuario.Setor.DED, None),
    ("rh1", "rh", "Sandra", "Oliveira", Usuario.Perfil.SECRETARIA, Usuario.Setor.RH, None),
]


class Command(BaseCommand):
    help = "Cria usuários de demonstração (aluno1/aluno, dies1/dies...) e dados de exemplo."

    @transaction.atomic
    def handle(self, *args, **options):
        self.avisos = []
        materias = self.criar_materias()
        escolas = self.criar_escolas()
        medio, fundamental = self.criar_cursos()
        self.criar_ofertas_e_matrizes(escolas, medio, fundamental, materias)
        turmas = self.criar_turmas(escolas, medio, fundamental)
        self.criar_atos(escolas, medio, fundamental)
        self.criar_calendario()
        self.criar_usuarios(escolas)
        self.criar_professores(turmas, materias)
        # Alunos, grade, diário, notas, tarefas... (academico/demo.py)
        DemoAcademica(ANO, self.avisos, medio, fundamental).rodar()
        # Pedidos da escola1 para a DIES (solicitacoes/demo.py)
        criar_pedidos_demo(ANO)

        for aviso in self.avisos:
            self.stdout.write(self.style.WARNING(f"Aviso: {aviso}"))
        self.stdout.write(self.style.SUCCESS("Dados de demonstração prontos. Usuários:"))
        for username, senha, *_ in USUARIOS:
            self.stdout.write(f"  {username} / {senha}")

    # ------------------------------------------------------------------ DIES

    def criar_materias(self):
        materias = {}
        for nome, area in MATERIAS:
            materias[nome], _ = Materia.objects.get_or_create(nome=nome, defaults={"area": area})
        return materias

    def criar_escolas(self):
        dea, _ = Regional.objects.get_or_create(nome="DEA")
        dre03, _ = Regional.objects.get_or_create(nome="DRE 03")
        dados = {
            "atheneu": ("28012345", "Colégio Estadual Atheneu Sergipense", dea, "Aracaju", "Centro"),
            "goncalo": ("28023456", "Colégio Estadual Gonçalo Rollemberg Leite", dea, "Aracaju",
                        "Suíssa"),
            "murilo": ("28034567", "Centro de Excelência Murilo Braga", dre03, "Itabaiana",
                       "Centro"),
        }
        escolas = {}
        for chave, (inep, nome, regional, municipio, bairro) in dados.items():
            escolas[chave], _ = Escola.objects.get_or_create(
                codigo_inep=inep,
                defaults={
                    "nome": nome, "regional": regional, "municipio": municipio, "bairro": bairro,
                },
            )
        return escolas

    def criar_cursos(self):
        medio, _ = Curso.objects.get_or_create(
            nome="Ensino Médio", defaults={"ordem": 3, "carga_horaria_minima_anual": 1000}
        )
        fundamental, _ = Curso.objects.get_or_create(
            nome="Ensino Fundamental - Anos Finais",
            defaults={"ordem": 2, "carga_horaria_minima_anual": 800},
        )
        for ordem in (1, 2, 3):
            Serie.objects.get_or_create(curso=medio, ordem=ordem, defaults={"nome": f"{ordem}ª série"})
        for ordem, ano in enumerate((6, 7, 8, 9), start=1):
            Serie.objects.get_or_create(
                curso=fundamental, ordem=ordem, defaults={"nome": f"{ano}º ano"}
            )
        return medio, fundamental

    def criar_turmas(self, escolas, medio, fundamental):
        serie = {
            "1em": medio.series.get(ordem=1), "2em": medio.series.get(ordem=2),
            "3em": medio.series.get(ordem=3), "6ano": fundamental.series.get(ordem=1),
        }
        lista = [
            ("atheneu", "1em", "A", Turma.Turno.MATUTINO),
            ("atheneu", "1em", "B", Turma.Turno.MATUTINO),
            ("atheneu", "2em", "A", Turma.Turno.MATUTINO),
            ("atheneu", "3em", "A", Turma.Turno.MATUTINO),
            ("goncalo", "6ano", "A", Turma.Turno.VESPERTINO),
            ("goncalo", "1em", "A", Turma.Turno.MATUTINO),
            ("murilo", "1em", "A", Turma.Turno.MATUTINO),
            ("murilo", "2em", "A", Turma.Turno.VESPERTINO),
        ]
        turmas = {}
        for escola, chave_serie, letra, turno in lista:
            turmas[(escola, chave_serie, letra)], _ = Turma.objects.get_or_create(
                escola=escolas[escola], serie=serie[chave_serie], ano_letivo=ANO, letra=letra,
                defaults={"turno": turno},
            )
        return turmas

    def criar_calendario(self):
        calendario, criado = CalendarioLetivo.objects.get_or_create(
            escola=None, ano_letivo=ANO,
            defaults={"data_inicio": date(ANO, 2, 9), "data_fim": date(ANO, 12, 18)},
        )
        if criado:
            Evento.objects.create(
                calendario=calendario, tipo=Evento.Tipo.PLANEJAMENTO,
                descricao="Jornada pedagógica", data_inicio=date(ANO, 2, 9),
                data_fim=date(ANO, 2, 10),
            )
            Evento.objects.create(
                calendario=calendario, tipo=Evento.Tipo.FERIAS, descricao="Férias de julho",
                data_inicio=date(ANO, 7, 13), data_fim=date(ANO, 7, 24),
            )
            Evento.objects.create(
                calendario=calendario, tipo=Evento.Tipo.PROVA,
                descricao="Avaliação do 1º bimestre", data_inicio=date(ANO, 4, 27),
                data_fim=date(ANO, 4, 30),
            )
            Evento.objects.create(
                calendario=calendario, tipo=Evento.Tipo.AULA,
                descricao="Sábado letivo", data_inicio=date(ANO, 5, 16),
            )
            calendario.adicionar_feriados()

    # ------------------------------------------------------------------- DED

    def criar_ofertas_e_matrizes(self, escolas, medio, fundamental, materias):
        series_medio = list(medio.series.all())
        series_fundamental = list(fundamental.series.all())
        ofertas = {
            "atheneu": series_medio,
            "goncalo": series_fundamental + series_medio,
            "murilo": series_medio,
        }
        for chave, series in ofertas.items():
            oferta, _ = Oferta.objects.get_or_create(escola=escolas[chave], ano_letivo=ANO)
            oferta.series.add(*series)

        for serie in series_medio:
            self.criar_matriz(serie, MATRIZ_MEDIO, materias)
        self.criar_matriz(series_fundamental[0], MATRIZ_FUNDAMENTAL, materias)

    def criar_matriz(self, serie, aulas, materias):
        matriz, criada = Matriz.objects.get_or_create(
            serie=serie, ano_letivo=ANO, jornada=Matriz.Jornada.PARCIAL
        )
        if criada:
            ItemMatriz.objects.bulk_create(
                ItemMatriz(matriz=matriz, materia=materias[nome], aulas_semanais=quantidade)
                for nome, quantidade in aulas.items()
            )

    def criar_atos(self, escolas, medio, fundamental):
        atos = [
            ("atheneu", None, AtoAutorizativo.Tipo.CREDENCIAMENTO, "Resolução nº 010/2019",
             date(2019, 3, 15), None),
            ("atheneu", medio, AtoAutorizativo.Tipo.RECONHECIMENTO, "Resolução nº 145/2023",
             date(2023, 8, 2), date(2028, 8, 1)),
            ("goncalo", fundamental, AtoAutorizativo.Tipo.AUTORIZACAO, "Resolução nº 087/2020",
             date(2020, 5, 20), date(2025, 12, 31)),  # vencido: aparece com alerta
            ("murilo", medio, AtoAutorizativo.Tipo.RECONHECIMENTO, "Resolução nº 201/2025",
             date(2025, 11, 10), date(2030, 11, 9)),
        ]
        for chave, curso, tipo, numero, publicacao, validade in atos:
            AtoAutorizativo.objects.get_or_create(
                escola=escolas[chave], tipo=tipo, numero=numero,
                defaults={"curso": curso, "data_publicacao": publicacao, "validade": validade},
            )

    # -------------------------------------------------------------- usuários

    def criar_usuarios(self, escolas):
        for username, senha, nome, sobrenome, perfil, setor, escola in USUARIOS:
            usuario, _ = Usuario.objects.get_or_create(username=username)
            usuario.first_name = nome
            usuario.last_name = sobrenome
            usuario.perfil = perfil
            usuario.setor = setor
            usuario.escola = escolas[escola] if escola else None
            usuario.set_password(senha)  # guarda o hash, nunca a senha em texto
            usuario.save()

    # -------------------------------------------------------------------- RH

    def criar_professores(self, turmas, materias):
        professores = [
            # matrícula, nome, base do CPF, carga, vínculo, usuário
            ("100001-1", "Carlos Eduardo Menezes", "123456781", 40, "efetivo", "professor1"),
            ("100002-2", "Fernanda Lima Barreto", "234567892", 40, "efetivo", None),
            ("100003-3", "José Ricardo Santos", "345678913", 20, "temporario", None),
            ("100004-4", "Mariana Costa Prado", "456789124", 40, "efetivo", None),
        ]
        criados = {}
        for matricula, nome, base_cpf, carga, vinculo, username in professores:
            usuario = Usuario.objects.filter(username=username).first() if username else None
            criados[matricula], _ = Professor.objects.get_or_create(
                matricula=matricula,
                defaults={
                    "nome": nome, "cpf": cpf_ficticio(base_cpf), "carga_horaria_semanal": carga,
                    "vinculo": vinculo, "usuario": usuario, "data_admissao": date(2018, 3, 1),
                },
            )

        atheneu = [("atheneu", "1em", "A"), ("atheneu", "1em", "B"), ("atheneu", "2em", "A"),
                   ("atheneu", "3em", "A")]
        lotacoes = [("100001-1", turma, "Matemática") for turma in atheneu]
        lotacoes += [("100002-2", turma, "Português") for turma in atheneu]
        lotacoes += [
            ("100003-3", ("atheneu", "1em", "A"), "Física"),
            ("100003-3", ("atheneu", "1em", "A"), "Química"),
            ("100003-3", ("atheneu", "2em", "A"), "Física"),
            ("100004-4", ("atheneu", "1em", "A"), "História"),
            ("100004-4", ("atheneu", "2em", "A"), "História"),
            ("100004-4", ("goncalo", "6ano", "A"), "História"),
            ("100004-4", ("goncalo", "6ano", "A"), "Geografia"),
        ]
        for matricula, chave_turma, nome_materia in lotacoes:
            self.lotar(criados[matricula], turmas[chave_turma], materias[nome_materia])

    def lotar(self, professor, turma, materia):
        """Lota o professor com TODAS as aulas que a matriz dá pra matéria, se as regras deixarem."""
        if Lotacao.objects.filter(professor=professor, turma=turma, materia=materia).exists():
            return
        item = ItemMatriz.objects.filter(
            matriz__serie=turma.serie, matriz__ano_letivo=turma.ano_letivo, materia=materia
        ).first()
        if item is None:
            self.avisos.append(f"{materia} não está na matriz de {turma.serie}; pulei {professor.nome}.")
            return
        lotacao = Lotacao(
            professor=professor, turma=turma, materia=materia, aulas_semanais=item.aulas_semanais
        )
        try:
            lotacao.full_clean()  # as mesmas regras do admin e da API
        except ValidationError as erro:
            self.avisos.append(f"{professor.nome} em {turma}: {'; '.join(erro.messages)}")
            return
        lotacao.save()
