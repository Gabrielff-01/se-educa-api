from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "perfil", "setor", "is_active")
    list_filter = ("perfil", "setor", "is_active", "is_staff")
    fieldsets = UserAdmin.fieldsets + (("SE Educa", {"fields": ("perfil", "setor")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("SE Educa", {"fields": ("perfil", "setor")}),)