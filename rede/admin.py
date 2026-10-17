from django.contrib import admin

from .models import Curso, Escola, Materia, Regional, Serie, Turma


@admin.register(Regional)
class RegionalAdmin(admin.ModelAdmin):
    list_display = ("nome",)
    search_fields = ("nome",)


@admin.register(Escola)
class EscolaAdmin(admin.ModelAdmin):
    list_display = ("nome", "codigo_inep", "municipio", "regional", "dependencia", "ativa")
    list_filter = ("regional", "dependencia", "ativa")
    search_fields = ("nome", "codigo_inep", "municipio")
    autocomplete_fields = ("regional",)


class SerieInline(admin.TabularInline):
    model = Serie
    extra = 0


@admin.register(Curso)
class CursoAdmin(admin.ModelAdmin):
    list_display = ("nome", "ordem", "carga_horaria_minima_anual")
    search_fields = ("nome",)
    inlines = [SerieInline]


@admin.register(Serie)
class SerieAdmin(admin.ModelAdmin):
    list_display = ("nome", "curso", "ordem")
    list_filter = ("curso",)
    search_fields = ("nome", "curso__nome")


@admin.register(Materia)
class MateriaAdmin(admin.ModelAdmin):
    list_display = ("nome", "area")
    list_filter = ("area",)
    search_fields = ("nome",)


@admin.register(Turma)
class TurmaAdmin(admin.ModelAdmin):
    list_display = ("serie", "letra", "escola", "ano_letivo", "turno", "sala", "capacidade")
    list_filter = ("ano_letivo", "turno", "serie__curso")
    search_fields = ("escola__nome", "serie__nome", "letra")
    autocomplete_fields = ("escola", "serie")
    list_select_related = ("escola", "serie__curso")
