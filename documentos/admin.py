from django.contrib import admin

from .models import Documento


@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ["__str__", "escola", "status", "enviado_em"]
    list_filter = ["status", "tipo", "escola"]
    search_fields = ["aluno__nome"]
    exclude = ["arquivo"]  # o arquivo é visto pela tela da escola
    readonly_fields = ["nome_arquivo", "tipo_arquivo", "tamanho", "enviado_por", "analisado_por", "analisado_em"]
