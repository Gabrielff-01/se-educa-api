# SE Educa API

Back-end do SE Educa (Residência 1, UNIT), feito em Django + Django REST Framework.
O front em React fica no repositório [se-educa-front](https://github.com/Gabrielff-01/se-educa-front).

## Rodar no seu PC (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py popular_demo
.\.venv\Scripts\python.exe manage.py runserver
```

- API: http://127.0.0.1:8000/api/
- Admin: http://127.0.0.1:8000/admin/ (com o seu superusuário)
- Testes: `.\.venv\Scripts\python.exe manage.py test`

Não precisa de `.env` no PC: sem ele o projeto usa SQLite e `DEBUG=True`.
O `.env.example` mostra as variáveis que o servidor usa.

## Usuários de demonstração

O comando `popular_demo` cria (ou reseta a senha de):

| Usuário | Senha | Perfil |
|---|---|---|
| aluno1 | aluno | Aluno |
| responsavel1 | responsavel | Responsável |
| professor1 | professor | Professor |
| escola1 | escola | Gestão da escola (Atheneu) |
| escola2 | escola | Gestão da escola (Gonçalo Rollemberg Leite) |
| escola3 | escola | Gestão da escola (Murilo Braga, Itabaiana) |
| dies1 | dies | Secretaria · DIES |
| ded1 | ded | Secretaria · DED |
| rh1 | rh | Secretaria · RH |

Ele também cria escolas, cursos, turmas, matrizes, o calendário de 2026, professores e lotações
de exemplo e, na primeira vez, a parte acadêmica: 79 alunos com responsáveis, grade de horários,
o diário de aulas até hoje com chamada, notas das unidades que já passaram, tarefas, planos,
comunicados, merenda e uma professora afastada (pra aparecer nas carências do RH).
Pode rodar de novo sem duplicar nada. Nomes, escolas, códigos INEP, CPFs e NIS são fictícios.

A aluna `aluno1` é a Ana Beatriz (1ª série A do Atheneu) e a `responsavel1` é a mãe dela,
que também tem o Pedro (6º ano no Gonçalo Rollemberg). O `professor1` dá Matemática.

## Estrutura

```
config/      configurações, endereços (urls.py) e peças comuns da API (api.py)
contas/      usuário (perfil, setor, escola), login JWT e permissões
rede/        DIES: regionais, escolas, cursos, séries, matérias e turmas
regulacao/   DED: atos autorizativos, ofertas de séries e matrizes curriculares
calendario/  DIES: calendário letivo, eventos e feriados de Sergipe
rh/          RH: professores, lotações e afastamentos (licenças, férias...)
academico/   alunos, responsáveis, matrículas, diário (aulas e chamada), notas, fechamento
             das unidades, tarefas, planos de aula, comunicados, grade de horários e merenda
auditoria/   histórico de alterações: quem criou, editou ou apagou o quê, e o antes/depois
solicitacoes/ pedidos da escola para a DIES (turma nova, capacidade, outros) com conversa
```

## Endereços da API

Todos pedem login (cabeçalho `Authorization: Bearer <token>`), menos o login e as opções.

| Endereço | O que faz |
|---|---|
| `POST /api/auth/login/` | `{"username", "password"}` → tokens + dados do usuário |
| `POST /api/auth/refresh/` | `{"refresh"}` → novo token de acesso |
| `GET /api/auth/eu/` | quem está logado |
| `GET /api/opcoes/` | listas de escolha (turnos, tipos de ato, cargas...) |
| `/api/regionais/` `/api/escolas/` `/api/cursos/` `/api/series/` `/api/materias/` `/api/turmas/` | DIES |
| `/api/calendarios/` `/api/eventos/` | DIES (`POST /api/calendarios/<id>/adicionar_feriados/`) |
| `/api/atos/` `/api/ofertas/` `/api/matrizes/` | DED |
| `/api/professores/` `/api/lotacoes/` `/api/afastamentos/` | RH (só a Secretaria vê). `POST /api/professores/<id>/criar_acesso/` cria o login |
| `GET /api/rh/painel/` `GET /api/rh/carencias/` | resumo do RH e aulas sem professor / para substituir |
| `/api/alunos/` `/api/responsaveis/` | escola e Secretaria. `criar_acesso` cria o login do aluno ou do responsável; `vincular_responsavel` e `desvincular_responsavel` ligam e desligam mãe/pai do aluno |
| `/api/matriculas/` | `POST /api/matriculas/nova/` cadastra aluno + responsável + matrícula de uma vez |
| `/api/aulas/` | diário do professor: aula + chamada (`faltas`: ids das matrículas que faltaram) |
| `GET /api/notas/` `POST /api/notas/lancar/` | notas; o lançar grava a turma inteira de uma vez |
| `/api/fechamentos/` | a escola fecha (POST) ou reabre (DELETE) uma unidade |
| `/api/tarefas/` `/api/planos/` | tarefas (e `POST .../entregas/`) e planos de aula do professor |
| `/api/comunicados/` `/api/horarios/` `/api/cardapios/` | comunicados, grade de horários e merenda |
| `GET /api/boletim/` `/api/historico/` `/api/minhas-tarefas/` `/api/meus-alunos/` | aluno e responsável (`?aluno=<id>` escolhe o filho) |
| `GET /api/agenda/` `/api/notificacoes/` | calendário do usuário e notificações (`POST` marca como lidas) |
| `GET /api/painel/professor/` `/api/painel/escola/` | telas iniciais do professor e da escola |
| `GET /api/escola/professores/` `diario/` `boletins/` `programas/` | gestão da escola |
| `GET /api/rede/matriculas/` `frequencia/` `carga-horaria/` | números da rede (Secretaria) |
| `GET /api/registros/` | histórico de alterações (a Secretaria vê tudo; os outros, só o que eles fizeram) |
| `/api/solicitacoes/` | pedidos escola → DIES. A escola abre e conversa (`mensagens`); a DIES responde, `atender` (cria a turma ou muda a capacidade) ou `recusar` |

Filtros pela URL, por exemplo: `/api/turmas/?escola=1&ano_letivo=2026`.

**Quem pode o quê:** todo mundo logado lê os cadastros da rede; só o setor responsável cria,
edita e apaga (DIES, DED ou RH). Professores e lotações só a Secretaria vê.
A escola cuida só dos alunos, matrículas, horários e merenda dela. O professor só lança
aula, chamada, nota, tarefa e plano nas turmas e matérias da sua lotação. O aluno vê só
o que é dele, e o responsável só o dos filhos.

## Regras de negócio

As regras ficam nos models (`clean()`), então valem igual no admin e na API:

- **Oferta:** turma só de série que a escola oferece naquele ano.
- **Matriz:** as aulas por semana têm que fechar a carga mínima do curso (800 h no Fundamental,
  1.000 h no Médio). Hora-aula de 50 min não é hora de relógio.
- **Calendário:** conta os dias letivos e avisa se ficar abaixo de 200 (LDB, art. 24).
  Feriados nacionais e de Sergipe entram com um clique.
- **Lotação:** a matéria tem que estar na matriz, não pode passar das aulas da matriz e o
  professor não passa de 2/3 da carga em sala (Lei 11.738/2008): 40 h → 26 aulas, 20 h → 13.
- **Matrícula:** só em série que a escola oferece; uma matrícula ativa por aluno no ano;
  a turma tem que ser da mesma escola, série e ano, e não pode passar da capacidade.
  Bolsa Família e Pé-de-Meia exigem o NIS (11 dígitos).
- **Unidades:** o ano letivo é dividido em 4 unidades com o mesmo número de dias letivos.
- **Diário:** aula só em dia letivo do calendário, nunca no futuro, e só pelo professor lotado.
- **Notas:** de 0 a 10. Média para aprovação 6,0; abaixo de 4,0 reprova direto; entre 4 e 6
  vai para recuperação. Frequência mínima 75% (Bolsa Família pede 85%, Pé-de-Meia 80%).
- **Fechamento:** a escola fecha a unidade quando todas as notas foram lançadas, uma unidade
  de cada vez. Unidade fechada não aceita mais nota.
- **Horário:** nem a turma nem o professor ficam em dois lugares ao mesmo tempo, e a matéria
  não passa das aulas semanais da lotação.

As constantes (média, frequência, número de unidades) ficam no topo de `academico/models.py`
e `calendario/models.py`.

## Histórico de alterações

Toda tela que cria, edita ou apaga algo pela API grava uma linha em `auditoria.Registro`
(quem, quando, o quê e cada campo com o antes e o depois). Para incluir um ViewSet novo,
é só colocar o `RegistrarAlteracoesMixin` antes do `ModelViewSet`. Dá para ver no admin
(só leitura) ou na tela "Histórico de alterações" do site.

## Deploy (Render + Neon)

1. No [Neon](https://neon.tech), crie um projeto e copie a *connection string*.
2. No [Render](https://render.com): **New > Blueprint**, escolha este repositório.
   O `render.yaml` já configura tudo; o Render só pergunta o `DATABASE_URL` (cole a do Neon)
   e o usuário/senha do superusuário do admin.
3. A cada push na `main`, o Render roda o `build.sh` (instala, migra e roda o `popular_demo`).
4. Na Vercel, no projeto se-educa-front, crie a variável `VITE_API_URL` com o endereço do
   Render (ex.: `https://se-educa-api.onrender.com`) e faça um Redeploy.

No plano grátis o Render "dorme" depois de 15 minutos parado: o primeiro acesso demora
uns 50 segundos.
