from django.contrib import admin

from .models import Registro


@admin.register(Registro)
class RegistroAdmin(admin.ModelAdmin):
    """Só leitura: o histórico não pode ser editado nem apagado por ninguém."""

    list_display = ("criado_em", "usuario", "acao", "tipo", "descricao")
    list_filter = ("acao", "tipo")
    search_fields = ("descricao", "usuario__username", "usuario__first_name")
    date_hierarchy = "criado_em"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
