"""Antes, o RH lotava o professor direto na turma. Agora o RH aloca na escola e a escola dá as turmas.

Esta migração cria uma alocação para cada professor em cada escola onde ele já tinha turma,
pra nada sumir: quem dava aula no Atheneu passa a estar alocado no Atheneu.
- Uma escola só: fica com a carga toda do professor (20 ou 40 h).
- Mais de uma escola: 20 h em cada (o RH ajusta depois, se precisar).
"""

from django.db import migrations


def criar_alocacoes(apps, schema_editor):
    Lotacao = apps.get_model("rh", "Lotacao")
    Alocacao = apps.get_model("rh", "Alocacao")
    escolas_do_professor = {}
    for professor_id, escola_id, carga in Lotacao.objects.values_list(
        "professor_id", "turma__escola_id", "professor__carga_horaria_semanal"
    ).distinct():
        escolas_do_professor.setdefault((professor_id, carga), set()).add(escola_id)
    for (professor_id, carga), escolas in escolas_do_professor.items():
        horas = carga if len(escolas) == 1 else 20
        for escola_id in escolas:
            Alocacao.objects.get_or_create(
                professor_id=professor_id, escola_id=escola_id, defaults={"horas_semanais": horas}
            )


class Migration(migrations.Migration):

    dependencies = [
        ("rh", "0003_alocacao"),
    ]

    operations = [
        migrations.RunPython(criar_alocacoes, migrations.RunPython.noop),
    ]
