from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from .models import AtoAutorizativo, ItemMatriz, Matriz, Oferta, formatar_horas, validar_carga_minima


@admin.register(AtoAutorizativo)
class AtoAutorizativoAdmin(admin.ModelAdmin):
    list_display = ("escola", "tipo", "numero", "curso", "data_publicacao", "validade", "vigente")
    list_filter = ("tipo",)
    search_fields = ("escola__nome", "numero")
    autocomplete_fields = ("escola", "curso")
    list_select_related = ("escola", "curso")

    @admin.display(description="vigente", boolean=True)
    def vigente(self, obj):
        return obj.vigente


class OfertaForm(forms.ModelForm):
    class Meta:
        model = Oferta
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        series = cleaned_data.get("series")
        if self.instance.pk and series is not None:
            # Turmas que ficariam sem a série delas marcada nesta oferta.
            sem_serie = self.instance.turmas().exclude(serie__in=series).select_related("serie", "escola")
            if sem_serie.exists():
                nomes = ", ".join(str(turma) for turma in sem_serie)
                raise ValidationError(
                    {"series": f"Estas turmas ficariam sem a série delas na oferta: {nomes}. "
                               "Marque a série delas ou apague essas turmas antes."}
                )
        return cleaned_data


@admin.register(Oferta)
class OfertaAdmin(admin.ModelAdmin):
    form = OfertaForm
    list_display = ("escola", "ano_letivo", "lista_series")
    list_filter = ("ano_letivo",)
    search_fields = ("escola__nome",)
    autocomplete_fields = ("escola",)
    filter_horizontal = ("series",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("escola").prefetch_related("series")

    def get_readonly_fields(self, request, obj=None):
        if obj:  # editando: escola e ano ficam travados, porque as turmas dependem deles
            return ("escola", "ano_letivo")
        return ()

    def get_deleted_objects(self, objs, request):
        # Turma não tem FK para Oferta, então o PROTECT não ajuda: bloqueamos aqui.
        apagados, contagem, sem_permissao, protegidos = super().get_deleted_objects(objs, request)
        for oferta in objs:
            protegidos.extend(str(turma) for turma in oferta.turmas().select_related("serie", "escola"))
        return apagados, contagem, sem_permissao, protegidos

    @admin.display(description="séries")
    def lista_series(self, obj):
        return ", ".join(serie.nome for serie in obj.series.all())


class ItemMatrizFormSet(BaseInlineFormSet):
    """Confere a regra das horas mínimas olhando TODAS as linhas da matriz juntas."""

    def get_unique_error_message(self, unique_check):
        return "A mesma matéria aparece em duas linhas. Deixe só uma."

    def clean(self):
        super().clean()
        if any(self.errors):
            return  # alguma linha tem erro: o usuário corrige as linhas primeiro

        # self.instance é a Matriz do formulário de cima, com o que foi digitado.
        matriz = self.instance
        if not matriz.serie_id:
            return  # sem série não dá pra saber o curso (nem o mínimo)
        try:
            matriz.clean_fields(exclude=["serie", "ano_letivo", "jornada"])
        except ValidationError:
            return  # duração ou semanas inválidas: o erro já aparece lá em cima

        total_aulas = 0
        for form in self.forms:
            dados = form.cleaned_data
            if not dados or dados.get("DELETE"):
                continue  # linha extra em branco ou marcada em "Remover?"
            total_aulas += dados["aulas_semanais"]

        validar_carga_minima(matriz.serie, matriz.duracao_aula_minutos, matriz.semanas_letivas, total_aulas)


class ItemMatrizInline(admin.TabularInline):
    model = ItemMatriz
    formset = ItemMatrizFormSet
    extra = 1
    autocomplete_fields = ("materia",)


@admin.register(Matriz)
class MatrizAdmin(admin.ModelAdmin):
    list_display = ("serie", "jornada", "ano_letivo", "total_aulas", "carga_anual", "cumpre_minimo")
    list_filter = ("ano_letivo", "jornada", "serie__curso")
    autocomplete_fields = ("serie",)
    inlines = [ItemMatrizInline]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("serie__curso").prefetch_related("itens")

    @admin.display(description="aulas por semana")
    def total_aulas(self, obj):
        return obj.total_aulas_semanais

    @admin.display(description="carga anual (horas)")
    def carga_anual(self, obj):
        return formatar_horas(obj.carga_horaria_anual)

    @admin.display(description="cumpre o mínimo", boolean=True)
    def cumpre_minimo(self, obj):
        return obj.cumpre_minimo
