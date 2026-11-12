from django.contrib import admin

from .models import Olimpiada, Participacao


class ParticipacaoInline(admin.TabularInline):
    model = Participacao
    extra = 0
    raw_id_fields = ["aluno", "matricula"]


@admin.register(Olimpiada)
class OlimpiadaAdmin(admin.ModelAdmin):
    list_display = ["nome", "escola", "data_prova", "status"]
    list_filter = ["status", "escola", "ano_letivo"]
    search_fields = ["nome"]
    filter_horizontal = ["series"]
    inlines = [ParticipacaoInline]
