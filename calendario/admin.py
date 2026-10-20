from django.contrib import admin, messages

from .models import DIAS_LETIVOS_MINIMOS, CalendarioLetivo, Evento


class EventoInline(admin.TabularInline):
    model = Evento
    fields = ("tipo", "descricao", "data_inicio", "data_fim")
    extra = 1


@admin.register(CalendarioLetivo)
class CalendarioLetivoAdmin(admin.ModelAdmin):
    list_display = (
        "ano_letivo", "abrangencia", "data_inicio", "data_fim",
        "dias_letivos", "cumpre_minimo",
    )
    list_filter = ("ano_letivo",)
    search_fields = ("escola__nome",)
    autocomplete_fields = ("escola",)
    inlines = [EventoInline]
    actions = ["adicionar_feriados"]

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("escola").prefetch_related("eventos")

    def save_related(self, request, form, formsets, change):
        # Roda depois de salvar os eventos. Buscamos o calendário de novo no banco
        # porque o form.instance ainda guarda a lista de eventos de ANTES de salvar.
        super().save_related(request, form, formsets, change)
        calendario = CalendarioLetivo.objects.get(pk=form.instance.pk)
        dias = calendario.dias_letivos
        if dias < DIAS_LETIVOS_MINIMOS:
            self.message_user(
                request,
                f"Atenção: {calendario} tem {dias} dias letivos. "
                f"A LDB exige pelo menos {DIAS_LETIVOS_MINIMOS}.",
                messages.WARNING,
            )

    @admin.display(description="abrangência", ordering="escola__nome")
    def abrangencia(self, obj):
        return obj.abrangencia

    @admin.display(description="dias letivos")
    def dias_letivos(self, obj):
        return obj.dias_letivos

    @admin.display(description=f"cumpre os {DIAS_LETIVOS_MINIMOS} dias", boolean=True)
    def cumpre_minimo(self, obj):
        return obj.cumpre_minimo

    @admin.action(description="Adicionar feriados e recessos (nacionais e de Sergipe)")
    def adicionar_feriados(self, request, queryset):
        criados = sum(calendario.adicionar_feriados() for calendario in queryset)
        mensagem = f"{criados} dia(s) sem aula adicionado(s)."
        self.message_user(request, mensagem, messages.SUCCESS)
