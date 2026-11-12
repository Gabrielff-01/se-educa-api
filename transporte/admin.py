from django.contrib import admin

from .models import AlunoNaRota, Parada, Rota


class ParadaInline(admin.TabularInline):
    model = Parada
    extra = 0


@admin.register(Rota)
class RotaAdmin(admin.ModelAdmin):
    list_display = ["nome", "escola", "turno", "veiculo", "placa", "ativa"]
    list_filter = ["escola", "turno", "ativa"]
    search_fields = ["nome", "motorista", "placa"]
    inlines = [ParadaInline]


@admin.register(AlunoNaRota)
class AlunoNaRotaAdmin(admin.ModelAdmin):
    list_display = ["aluno", "rota", "parada"]
    list_filter = ["rota__escola", "rota"]
    raw_id_fields = ["aluno"]
