from django.contrib import admin

from .models import Inscricao


@admin.register(Inscricao)
class InscricaoAdmin(admin.ModelAdmin):
    list_display = ["protocolo", "aluno_nome", "escola", "serie", "status", "criada_em"]
    list_filter = ["status", "escola"]
    search_fields = ["protocolo", "aluno_nome", "cpf", "email"]
    exclude = ["senha"]
    readonly_fields = ["protocolo", "status", "analisada_por", "analisada_em", "matricula"]
