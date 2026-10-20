from django.contrib import admin

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


class VinculoInline(admin.TabularInline):
    model = Vinculo
    extra = 1
    autocomplete_fields = ("responsavel",)


@admin.register(Aluno)
class AlunoAdmin(admin.ModelAdmin):
    list_display = ("nome", "codigo", "data_nascimento", "programa_social", "usuario")
    list_filter = ("programa_social",)
    search_fields = ("nome", "codigo", "nis")
    readonly_fields = ("codigo",)
    inlines = [VinculoInline]


@admin.register(Responsavel)
class ResponsavelAdmin(admin.ModelAdmin):
    list_display = ("nome", "cpf", "telefone", "usuario")
    search_fields = ("nome", "cpf")


@admin.register(Matricula)
class MatriculaAdmin(admin.ModelAdmin):
    list_display = ("aluno", "escola", "serie", "turma", "ano_letivo", "situacao")
    list_filter = ("ano_letivo", "situacao", "escola")
    search_fields = ("aluno__nome", "aluno__codigo")
    autocomplete_fields = ("aluno",)


class PresencaInline(admin.TabularInline):
    model = Presenca
    extra = 0


@admin.register(Aula)
class AulaAdmin(admin.ModelAdmin):
    list_display = ("data", "turma", "materia", "professor", "quantidade")
    list_filter = ("turma__escola", "materia")
    date_hierarchy = "data"
    inlines = [PresencaInline]


@admin.register(Nota)
class NotaAdmin(admin.ModelAdmin):
    list_display = ("matricula", "materia", "unidade", "valor", "atualizada_em")
    list_filter = ("unidade", "materia", "matricula__turma__escola")
    search_fields = ("matricula__aluno__nome",)


@admin.register(Fechamento)
class FechamentoAdmin(admin.ModelAdmin):
    list_display = ("turma", "unidade", "fechado_por", "fechado_em")


class EntregaInline(admin.TabularInline):
    model = Entrega
    extra = 0


@admin.register(Tarefa)
class TarefaAdmin(admin.ModelAdmin):
    list_display = ("titulo", "turma", "materia", "professor", "prazo")
    inlines = [EntregaInline]


@admin.register(PlanoAula)
class PlanoAulaAdmin(admin.ModelAdmin):
    list_display = ("tema", "turma", "materia", "unidade", "status")


@admin.register(Comunicado)
class ComunicadoAdmin(admin.ModelAdmin):
    list_display = ("titulo", "alcance", "autor", "criado_em")
    list_filter = ("alcance",)


@admin.register(Horario)
class HorarioAdmin(admin.ModelAdmin):
    list_display = ("lotacao", "dia_semana", "inicio")
    list_filter = ("dia_semana", "lotacao__turma__escola")


@admin.register(Cardapio)
class CardapioAdmin(admin.ModelAdmin):
    list_display = ("escola", "dia_semana")
