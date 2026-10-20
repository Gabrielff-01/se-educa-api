from django.contrib import admin
from django.utils import timezone

from .models import Afastamento, Lotacao, Professor


class LotacaoInline(admin.TabularInline):
    """Só mostra as lotações do professor. Cadastrar é na tela de Lotações,
    porque lá cada lotação passa pelas regras uma de cada vez."""

    model = Lotacao
    fields = ("turma", "materia", "aulas_semanais")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        # Sem isto, salvar o professor faria o Django conferir de novo cada lotação dele.
        return False


@admin.register(Professor)
class ProfessorAdmin(admin.ModelAdmin):
    list_display = (
        "nome", "matricula", "cpf_formatado", "carga_horaria_semanal", "vinculo",
        "em_sala", "ativo",
    )
    list_filter = ("vinculo", "carga_horaria_semanal", "ativo")
    search_fields = ("nome", "matricula", "cpf")
    search_help_text = "Busque por nome, matrícula ou CPF (só os números)."
    inlines = [LotacaoInline]

    @admin.display(description="CPF", ordering="cpf")
    def cpf_formatado(self, obj):
        return obj.cpf_formatado

    @admin.display(description="aulas por semana (ano atual)")
    def em_sala(self, obj):
        ano = timezone.localdate().year
        return f"{obj.aulas_no_ano(ano)} de {obj.limite_aulas}"


@admin.register(Lotacao)
class LotacaoAdmin(admin.ModelAdmin):
    list_display = ("professor", "materia", "turma", "aulas_semanais")
    list_filter = ("turma__ano_letivo", "materia")
    search_fields = ("professor__nome", "professor__matricula", "turma__escola__nome")
    autocomplete_fields = ("professor", "turma", "materia")
    list_select_related = ("professor", "materia", "turma__escola", "turma__serie")


@admin.register(Afastamento)
class AfastamentoAdmin(admin.ModelAdmin):
    list_display = ("professor", "tipo", "inicio", "fim")
    list_filter = ("tipo",)
    search_fields = ("professor__nome",)
    date_hierarchy = "inicio"
