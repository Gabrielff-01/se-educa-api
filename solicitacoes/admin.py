from django.contrib import admin

from .models import Mensagem, Solicitacao


class MensagemInline(admin.TabularInline):
    model = Mensagem
    extra = 0


@admin.register(Solicitacao)
class SolicitacaoAdmin(admin.ModelAdmin):
    list_display = ["__str__", "tipo", "status", "atualizada_em"]
    list_filter = ["status", "tipo", "escola"]
    inlines = [MensagemInline]
