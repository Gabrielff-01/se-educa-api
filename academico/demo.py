"""Dados acadêmicos de demonstração: alunos, grade, diário com chamada, notas, tarefas...

Chamado pelo comando popular_demo (contas/management/commands/popular_demo.py).
Tudo FICTÍCIO. Os números "aleatórios" usam random.Random com semente fixa: rodando
de novo num banco vazio, sai sempre igual.
"""

import random
from datetime import date, time, timedelta
from decimal import Decimal

from django.utils import timezone

from auditoria.historico import registrar
from calendario.models import calendario_da_escola
from contas.models import Usuario
from rede.models import Escola, Turma
from rh.models import Afastamento, Lotacao, Professor

from .models import (
    Aluno,
    Aula,
    Cardapio,
    Comunicado,
    Entrega,
    Fechamento,
    Horario,
    Matricula,
    Nota,
    PlanoAula,
    Presenca,
    Responsavel,
    Tarefa,
    Vinculo,
)

NOMES = [
    "Ana Beatriz", "Bruno Henrique", "Carla Vitória", "Davi Lucas", "Eduarda Maria", "Felipe Augusto",
    "Gabriela Nunes", "Heitor Miguel", "Isabela Cristina", "João Victor", "Kauã Gabriel", "Larissa Mel",
    "Matheus Felipe", "Nicole Alves", "Otávio Rafael", "Pietra Sophia", "Rafael Tavares", "Sophia Rezende",
    "Thiago José", "Valentina Rosa", "Wesley Santos", "Yasmin Oliveira", "Arthur Mendonça", "Lívia Maria",
    "Enzo Gabriel", "Maria Clara", "Lucas Emanuel", "Alice Fernanda", "Samuel Vitor", "Manuela Lima",
    "Pedro Henrique", "Júlia Vitória", "Guilherme Lopes", "Beatriz Helena", "Caio César", "Lorena Dias",
    "Daniel Victor", "Helena Cristina", "Miguel Ângelo", "Laura Beatriz",
]
SOBRENOMES = ["Santos", "Oliveira", "Souza", "Lima", "Costa", "Almeida", "Ferreira", "Rocha", "Barbosa",
              "Carvalho", "Nascimento", "Menezes", "Prado", "Andrade", "Dantas", "Góis", "Batista", "Fontes"]

HORAS = {
    Turma.Turno.MATUTINO: ["07:00", "07:50", "08:40", "09:50", "10:40", "11:30"],
    Turma.Turno.VESPERTINO: ["13:00", "13:50", "14:40", "15:50", "16:40", "17:30"],
    Turma.Turno.NOTURNO: ["19:00", "19:45", "20:30", "21:15"],
    Turma.Turno.INTEGRAL: ["07:30", "08:20", "09:30", "10:20", "13:30", "14:20", "15:30", "16:20"],
}

CONTEUDOS = {
    "Matemática": ["Conjuntos numéricos", "Funções do 1º grau", "Gráfico da função afim", "Função quadrática",
                   "Vértice da parábola", "Progressão aritmética", "Progressão geométrica", "Exercícios de revisão"],
    "Português": ["Gêneros textuais", "Leitura de crônica", "Concordância verbal", "Produção de resenha",
                  "Figuras de linguagem", "Romantismo", "Redação: dissertação", "Correção da redação"],
    "Física": ["Grandezas e unidades", "Movimento uniforme", "Velocidade média", "Leis de Newton",
               "Atrito", "Trabalho e energia", "Experimento: plano inclinado"],
    "Química": ["Matéria e energia", "Modelos atômicos", "Tabela periódica", "Ligações químicas",
                "Funções inorgânicas", "Aula prática no laboratório"],
    "História": ["Antiguidade clássica", "Feudalismo", "Grandes navegações", "Brasil colônia",
                 "Ciclo do açúcar em Sergipe", "Independência do Brasil", "Seminário em grupo"],
    "Geografia": ["Cartografia", "Relevo do Nordeste", "Clima e vegetação", "Bacia do São Francisco",
                  "Urbanização de Aracaju", "População brasileira"],
}

CARDAPIO = [
    ("Arroz branco\nFeijão carioca\nCarne de panela\nMacaxeira cozida\nSalada de tomate", "Suco de caju\nBanana"),
    ("Cuscuz de milho\nGalinha guisada\nFeijão de corda\nVinagrete", "Iogurte natural\nPão com manteiga"),
    ("Arroz com cenoura\nFeijão preto\nPeixe ao molho\nAbóbora refogada", "Suco de acerola\nBolo de macaxeira"),
    ("Baião de dois\nCarne de sol desfiada\nSalada verde", "Mamão\nBiscoito integral"),
    ("Arroz branco\nFeijão carioca\nFrango assado\nPurê de inhame", "Laranja\nPão de queijo"),
]


def cpf_ficticio(base):
    """Gera um CPF válido (dígitos certos) a partir de 9 números. Só para teste."""
    numeros = [int(c) for c in base]
    for tamanho in (9, 10):
        soma = sum(numeros[i] * (tamanho + 1 - i) for i in range(tamanho))
        resto = soma % 11
        numeros.append(0 if resto < 2 else 11 - resto)
    return "".join(str(n) for n in numeros)


class DemoAcademica:
    def __init__(self, ano, avisos, medio, fundamental):
        self.ano = ano
        self.medio = medio
        self.fundamental = fundamental
        self.avisos = avisos
        self.sorte = random.Random(2026)
        self.hoje = timezone.localdate()
        self.contador_nomes = 0

    def rodar(self):
        if Aluno.objects.filter(usuario__username="aluno1").exists():
            return  # já foi criado antes: não duplica
        atheneu = Escola.objects.filter(codigo_inep="28012345").first()
        goncalo = Escola.objects.filter(codigo_inep="28023456").first()
        murilo = Escola.objects.filter(codigo_inep="28034567").first()
        if not (atheneu and goncalo and murilo):
            self.avisos.append("Escolas de demonstração não encontradas; pulei os dados acadêmicos.")
            return
        self.dar_salas()
        self.criar_professor_sem_lotacao()
        self.criar_afastamentos()
        for escola in (atheneu, goncalo):
            self.criar_grade(escola)
        self.criar_alunos(atheneu, goncalo, murilo)
        self.criar_diario()
        self.criar_notas_e_fechamentos()
        self.criar_tarefas_e_planos()
        self.criar_comunicados(atheneu)
        for escola in (atheneu, goncalo):
            for dia, (almoco, lanche) in enumerate(CARDAPIO, start=1):
                Cardapio.objects.get_or_create(escola=escola, dia_semana=dia,
                                               defaults={"almoco": almoco, "lanche": lanche})
        # Primeira linha do histórico de alterações. Daqui pra frente, tudo que for
        # cadastrado, editado ou apagado pelo site entra lá com o nome de quem fez.
        registrar(None, "criou", tipo="demonstração",
                  descricao=f"Dados de demonstração carregados: {Aluno.objects.count()} alunos, "
                            f"{Aula.objects.count()} aulas no diário e {Nota.objects.count()} notas")

    def dar_salas(self):
        """Cada turma sem sala ganha uma (Sala 01, 02...), por escola."""
        for escola in Escola.objects.all():
            turmas = Turma.objects.filter(escola=escola, ano_letivo=self.ano).order_by("turno", "serie__ordem", "letra")
            for numero, turma in enumerate(turmas, start=1):
                if not turma.sala:
                    turma.sala = f"Sala {numero:02d}"
                    turma.save(update_fields=["sala"])

    # --------------------------------------------------------------------- RH

    def criar_professor_sem_lotacao(self):
        Professor.objects.get_or_create(
            matricula="100005-5",
            defaults={"nome": "Paulo Roberto Dias", "cpf": cpf_ficticio("567891235"),
                      "carga_horaria_semanal": 40, "vinculo": "temporario", "data_admissao": date(2026, 9, 1)},
        )

    def criar_afastamentos(self):
        fernanda = Professor.objects.filter(matricula="100002-2").first()
        jose = Professor.objects.filter(matricula="100003-3").first()
        if fernanda:
            # Afastada desde a semana passada: o diário de Português fica sem registro e
            # aparece em "Carências" do RH pedindo substituto.
            Afastamento.objects.create(
                professor=fernanda, tipo=Afastamento.Tipo.SAUDE, inicio=self.hoje - timedelta(days=7),
                fim=self.hoje + timedelta(days=14), observacao="Atestado de 21 dias",
            )
        if jose:
            Afastamento.objects.create(
                professor=jose, tipo=Afastamento.Tipo.CAPACITACAO, inicio=date(self.ano, 8, 10),
                fim=date(self.ano, 8, 14), observacao="Formação de professores de Física (SEDUC)",
            )

    # ------------------------------------------------------------------ grade

    def criar_grade(self, escola):
        """Monta a grade sem conflito: nem a turma nem o professor ficam em 2 lugares ao mesmo tempo."""
        lotacoes = Lotacao.objects.filter(turma__escola=escola, turma__ano_letivo=self.ano).select_related(
            "turma", "materia", "professor").order_by("turma_id", "-aulas_semanais", "materia__nome")
        ocupado_turma, ocupado_prof = set(), set()
        for horario in Horario.objects.select_related("lotacao"):
            ocupado_turma.add((horario.lotacao.turma_id, horario.dia_semana, horario.inicio))
            ocupado_prof.add((horario.lotacao.professor_id, horario.dia_semana, horario.inicio))
        for lotacao in lotacoes:
            if lotacao.horarios.exists():
                continue
            horas = [time.fromisoformat(h) for h in HORAS[lotacao.turma.turno]]
            for numero in range(lotacao.aulas_semanais):
                colocada = False
                for desvio in range(5):
                    dia = (numero + desvio) % 5 + 1
                    for inicio in horas:
                        if (lotacao.turma_id, dia, inicio) in ocupado_turma:
                            continue
                        if (lotacao.professor_id, dia, inicio) in ocupado_prof:
                            continue
                        Horario.objects.create(lotacao=lotacao, dia_semana=dia, inicio=inicio)
                        ocupado_turma.add((lotacao.turma_id, dia, inicio))
                        ocupado_prof.add((lotacao.professor_id, dia, inicio))
                        colocada = True
                        break
                    if colocada:
                        break

    # ----------------------------------------------------------------- alunos

    def proximo_nome(self):
        nome = NOMES[self.contador_nomes % len(NOMES)]
        sobrenome = SOBRENOMES[(self.contador_nomes * 7) % len(SOBRENOMES)]
        segundo = SOBRENOMES[(self.contador_nomes * 3 + 5) % len(SOBRENOMES)]
        self.contador_nomes += 1
        return f"{nome} {segundo} {sobrenome}" if segundo != sobrenome else f"{nome} {sobrenome}"

    def novo_aluno(self, nome, nascimento_ano, programa=None):
        if programa is None:
            sorteio = self.sorte.random()
            programa = "bolsa_familia" if sorteio < 0.25 else ""
        aluno = Aluno.objects.create(
            nome=nome,
            data_nascimento=date(nascimento_ano, self.sorte.randint(1, 12), self.sorte.randint(1, 28)),
            programa_social=programa,
            nis="".join(str(self.sorte.randint(0, 9)) for _ in range(11)) if programa else "",
        )
        # Faltas: a maioria falta pouco; alguns faltam bastante (aparecem nos alertas).
        sorteio = self.sorte.random()
        aluno.chance_falta = 0.03 if sorteio < 0.7 else (0.10 if sorteio < 0.88 else (0.17 if sorteio < 0.96 else 0.30))
        aluno.nivel = self.sorte.uniform(-1.8, 1.8)  # aluno "forte" ou "fraco" nas notas
        return aluno

    def matricular(self, aluno, turma, situacao=Matricula.Situacao.CONFIRMADA):
        return Matricula.objects.create(
            aluno=aluno, escola=turma.escola, serie=turma.serie, ano_letivo=self.ano,
            turma=turma if situacao == Matricula.Situacao.CONFIRMADA else None, situacao=situacao,
            data=date(self.ano, 1, self.sorte.randint(10, 30)),
        )

    def turma(self, escola, curso, ordem, letra):
        return Turma.objects.filter(escola=escola, serie__curso=curso, serie__ordem=ordem, ano_letivo=self.ano,
                                    letra=letra).select_related("serie", "escola").first()

    def criar_alunos(self, atheneu, goncalo, murilo):
        self.perfil_aluno = {}  # id da matrícula -> (chance de falta, nível nas notas)
        medio, fundamental = self.medio, self.fundamental

        # Ana Beatriz (aluno1) na 1ª série A do Atheneu, filha da Maria José (responsavel1).
        mae = Responsavel.objects.create(
            nome="Maria José Souza", cpf=cpf_ficticio("321654987"), telefone="(79) 99876-5432",
            email="maria.souza@exemplo.com", usuario=Usuario.objects.get(username="responsavel1"))
        primeira_a = self.turma(atheneu, medio, 1, "A")
        ana = self.novo_aluno("Ana Beatriz Souza", self.ano - 16, programa="pe_de_meia")
        ana.usuario = Usuario.objects.get(username="aluno1")
        ana.save()
        Vinculo.objects.create(responsavel=mae, aluno=ana, parentesco=Vinculo.Parentesco.MAE)
        if primeira_a:
            self.perfil_aluno[self.matricular(ana, primeira_a).id] = (0.05, 0.6)
        # Histórico da Ana: 8º e 9º ano no Gonçalo Rollemberg (anos já encerrados).
        for ano, ordem, media in ((self.ano - 2, 3, "8.1"), (self.ano - 1, 4, "7.9")):
            serie = fundamental.series.filter(ordem=ordem).first()
            if serie:
                Matricula.objects.create(
                    aluno=ana, escola=goncalo, serie=serie, ano_letivo=ano, situacao=Matricula.Situacao.CONFIRMADA,
                    resultado_final=Matricula.Resultado.APROVADO, media_final=Decimal(media), data=date(ano, 1, 15))
        # Irmão da Ana no 6º ano do Gonçalo: a mãe acompanha os dois filhos.
        sexto = self.turma(goncalo, fundamental, 1, "A")
        if sexto:
            pedro = self.novo_aluno("Pedro Henrique Souza", self.ano - 12, programa="bolsa_familia")
            Vinculo.objects.create(responsavel=mae, aluno=pedro, parentesco=Vinculo.Parentesco.MAE)
            self.perfil_aluno[self.matricular(pedro, sexto).id] = (0.12, -0.3)

        # Os outros alunos de cada turma: (escola, curso, série, letra, quantos)
        plano = [
            (atheneu, medio, 1, "A", 11), (atheneu, medio, 1, "B", 10), (atheneu, medio, 2, "A", 10),
            (atheneu, medio, 3, "A", 9), (goncalo, fundamental, 1, "A", 9), (goncalo, medio, 1, "A", 7),
            (murilo, medio, 1, "A", 8), (murilo, medio, 2, "A", 6),
        ]
        for escola, curso, ordem, letra, quantos in plano:
            turma = self.turma(escola, curso, ordem, letra)
            if turma is None:
                continue
            idade = 15 + ordem if curso == medio else 10 + ordem
            for _ in range(quantos):
                programa = "pe_de_meia" if curso == medio and self.sorte.random() < 0.2 else None
                aluno = self.novo_aluno(self.proximo_nome(), self.ano - idade, programa=programa)
                matricula = self.matricular(aluno, turma)
                self.perfil_aluno[matricula.id] = (aluno.chance_falta, aluno.nivel)
                if self.sorte.random() < 0.08:
                    aluno.necessidade_especial = self.sorte.choice(["TEA", "Deficiência auditiva", "TDAH"])
                    aluno.save(update_fields=["necessidade_especial"])
                if self.sorte.random() < 0.5:
                    primeiro = self.sorte.choice(["Joana", "Antônia", "Cícera", "José", "Francisco"])
                    responsavel = Responsavel.objects.create(
                        nome=f"{primeiro} {aluno.nome.split()[-1]}",
                        cpf=cpf_ficticio(str(self.sorte.randint(100000000, 999999999))),
                        telefone=f"(79) 9{self.sorte.randint(8000, 9999)}-{self.sorte.randint(1000, 9999)}")
                    Vinculo.objects.create(responsavel=responsavel, aluno=aluno,
                                           parentesco=self.sorte.choice(["mae", "pai", "avo"]))

        # Fila de enturmação: matrículas novas, ainda sem turma (a 1ª ainda em análise).
        for escola, quantos in ((atheneu, 3), (goncalo, 2), (murilo, 2)):
            serie = medio.series.filter(ordem=1).first()
            for numero in range(quantos):
                aluno = self.novo_aluno(self.proximo_nome(), self.ano - 15)
                situacao = Matricula.Situacao.EM_ANALISE if numero == 0 else Matricula.Situacao.CONFIRMADA
                Matricula.objects.create(aluno=aluno, escola=escola, serie=serie, ano_letivo=self.ano,
                                         situacao=situacao, data=self.hoje - timedelta(days=numero + 2))

    # ---------------------------------------------------------- diário e chamada

    def criar_diario(self):
        ontem = self.hoje - timedelta(days=1)
        fernanda = Professor.objects.filter(matricula="100002-2").first()
        afastada_desde = fernanda.afastamentos.order_by("-inicio").first().inicio if fernanda else None
        lotacoes = Lotacao.objects.filter(turma__ano_letivo=self.ano, horarios__isnull=False).distinct().select_related(
            "turma__escola", "materia", "professor")
        for lotacao in lotacoes:
            turma = lotacao.turma
            calendario = calendario_da_escola(turma.escola, self.ano)
            if calendario is None:
                continue
            por_dia = {}
            for horario in lotacao.horarios.all():
                por_dia[horario.dia_semana] = por_dia.get(horario.dia_semana, 0) + 1
            dias = [d for d in calendario.lista_dias_letivos() if d <= ontem and d.isoweekday() in por_dia]
            if lotacao.professor_id == getattr(fernanda, "id", None) and afastada_desde:
                dias = [d for d in dias if d < afastada_desde]  # afastada: ninguém registrou
            if lotacao.materia.nome == "Física" and turma.serie.ordem == 1:
                dias = dias[:-3]  # o professor esqueceu os 3 últimos registros (vira pendência)
            conteudos = CONTEUDOS.get(lotacao.materia.nome, ["Aula expositiva", "Exercícios", "Revisão"])
            aulas = Aula.objects.bulk_create(
                Aula(turma=turma, materia=lotacao.materia, professor=lotacao.professor, data=dia,
                     quantidade=por_dia[dia.isoweekday()],
                     conteudo=conteudos[(numero // 3) % len(conteudos)])
                for numero, dia in enumerate(dias)
            )
            matriculas = list(turma.matriculas.filter(situacao=Matricula.Situacao.CONFIRMADA))
            presencas = []
            for aula in aulas:
                for matricula in matriculas:
                    if matricula.data > aula.data:
                        continue
                    chance, _nivel = self.perfil_aluno.get(matricula.id, (0.04, 0))
                    presencas.append(Presenca(aula=aula, matricula=matricula, presente=self.sorte.random() >= chance))
            Presenca.objects.bulk_create(presencas, batch_size=2000)

    # ------------------------------------------------------------------ notas

    def criar_notas_e_fechamentos(self):
        escola_usuario = Usuario.objects.filter(username="escola1").first()
        turmas = Turma.objects.filter(ano_letivo=self.ano, lotacoes__isnull=False).distinct()
        for turma in turmas.select_related("escola", "serie"):
            calendario = calendario_da_escola(turma.escola, self.ano)
            if calendario is None:
                continue
            unidades_passadas = [numero for numero, _inicio, fim in calendario.unidades() if fim < self.hoje]
            matriculas = list(turma.matriculas.filter(situacao=Matricula.Situacao.CONFIRMADA))
            lotacoes = list(turma.lotacoes.select_related("materia", "professor"))
            notas = []
            for lotacao in lotacoes:
                dificuldade = self.sorte.uniform(-0.8, 0.6)
                for matricula in matriculas:
                    _chance, nivel = self.perfil_aluno.get(matricula.id, (0.04, 0))
                    for unidade in unidades_passadas:
                        valor = 7.0 + nivel + dificuldade + self.sorte.uniform(-1.5, 1.5)
                        notas.append(Nota(matricula=matricula, materia=lotacao.materia, unidade=unidade,
                                          valor=Decimal(str(round(min(max(valor, 0), 10) * 2) / 2)),
                                          lancada_por=lotacao.professor))
            Nota.objects.bulk_create(notas, batch_size=2000)
            # A escola fechou as unidades passadas, menos a última nas turmas de 1ª série
            # (fica para mostrar o botão "Fechar unidade" ao vivo).
            for unidade in unidades_passadas:
                if unidade == unidades_passadas[-1] and turma.serie.ordem == 1 and turma.serie.curso_id == self.medio.id:
                    continue
                Fechamento.objects.create(turma=turma, unidade=unidade, fechado_por=escola_usuario)
            # Unidade atual: Carlos já lançou metade das notas de Matemática da 1ª série A.
            atual = calendario.unidade_em(self.hoje)
            for lotacao in lotacoes:
                primeira_a = turma.serie.curso_id == self.medio.id and turma.serie.ordem == 1 and turma.letra == "A"
                if lotacao.professor.usuario_id and primeira_a and atual not in unidades_passadas:
                    for matricula in matriculas[: len(matriculas) // 2]:
                        Nota.objects.create(matricula=matricula, materia=lotacao.materia, unidade=atual,
                                            valor=Decimal(str(self.sorte.choice([6, 6.5, 7, 7.5, 8, 8.5, 9]))),
                                            lancada_por=lotacao.professor)

    # ------------------------------------------------------- tarefas e planos

    def criar_tarefas_e_planos(self):
        titulos = {
            "Matemática": ["Lista de funções", "Desafio da parábola", "Lista de progressões"],
            "Português": ["Resenha de Vidas Secas", "Redação: o lixo no mar de Sergipe", "Análise de crônica"],
            "Física": ["Relatório do plano inclinado", "Lista de Leis de Newton"],
            "Química": ["Tabela periódica ilustrada", "Relatório da aula prática"],
            "História": ["Linha do tempo do Brasil colônia", "Pesquisa: Sergipe no século XIX"],
            "Geografia": ["Mapa do relevo de Sergipe", "Entrevista sobre migração"],
        }
        for lotacao in Lotacao.objects.filter(turma__ano_letivo=self.ano).select_related("turma", "materia", "professor"):
            matriculas = list(lotacao.turma.matriculas.filter(situacao=Matricula.Situacao.CONFIRMADA))
            lista = titulos.get(lotacao.materia.nome, ["Exercícios do capítulo"])
            prazos = [self.hoje - timedelta(days=40), self.hoje - timedelta(days=6), self.hoje + timedelta(days=7)]
            for numero, titulo in enumerate(lista):
                prazo = prazos[min(numero, len(prazos) - 1)] if numero < len(lista) - 1 else prazos[-1]
                tarefa = Tarefa.objects.create(turma=lotacao.turma, materia=lotacao.materia, professor=lotacao.professor,
                                               titulo=titulo, prazo=prazo,
                                               descricao="Entregar no caderno ou pelo grupo da turma.")
                Tarefa.objects.filter(pk=tarefa.pk).update(criada_em=timezone.now() - timedelta(
                    days=(self.hoje - prazo).days + 10 if prazo < self.hoje else 2))
                taxa = 0.85 if prazo < self.hoje else 0.3
                Entrega.objects.bulk_create(
                    Entrega(tarefa=tarefa, matricula=m) for m in matriculas if self.sorte.random() < taxa)

        carlos = Professor.objects.filter(usuario__username="professor1").first()
        if carlos:
            lotacoes = list(carlos.lotacoes.filter(turma__ano_letivo=self.ano).select_related("turma", "materia"))
            planos = [
                ("Função quadrática e gráficos", 3, PlanoAula.Status.CONCLUIDO),
                ("Progressões aritméticas", 4, PlanoAula.Status.EM_ANDAMENTO),
                ("Progressões geométricas", 4, PlanoAula.Status.PLANEJADO),
                ("Revisão para a recuperação final", 4, PlanoAula.Status.PLANEJADO),
            ]
            for numero, (tema, unidade, status) in enumerate(planos):
                if lotacoes:
                    lotacao = lotacoes[numero % len(lotacoes)]
                    PlanoAula.objects.create(professor=carlos, turma=lotacao.turma, materia=lotacao.materia,
                                             unidade=unidade, tema=tema, status=status,
                                             objetivos="Aula expositiva, exercícios em dupla e correção coletiva.")

    def criar_comunicados(self, atheneu):
        dies = Usuario.objects.filter(username="dies1").first()
        escola = Usuario.objects.filter(username="escola1").first()
        professor = Usuario.objects.filter(username="professor1").first()
        turma = atheneu.turmas.filter(ano_letivo=self.ano, letra="A", serie__ordem=1).first()
        Comunicado.objects.create(
            autor=dies, alcance=Comunicado.Alcance.REDE, titulo=f"Matrículas {self.ano + 1}",
            texto=f"A renovação de matrícula para {self.ano + 1} vai de 03/11 a 28/11. Alunos novos se "
                  "inscrevem pelo app a partir de 01/12.")
        Comunicado.objects.create(
            autor=escola, alcance=Comunicado.Alcance.ESCOLA, escola=atheneu, titulo="Reunião de pais e mestres",
            texto="Dia 05/11, às 18h30, no auditório. A presença dos responsáveis é muito importante.")
        if turma:
            Comunicado.objects.create(
                autor=professor, alcance=Comunicado.Alcance.TURMA, turma=turma,
                titulo="Prova de Matemática da 4ª unidade",
                texto="A prova será no dia 10/11. Conteúdo: progressões aritmética e geométrica.")
