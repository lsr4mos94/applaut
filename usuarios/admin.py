from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import Perfil

class PerfilInline(admin.StackedInline):
    model = Perfil
    can_delete = False
    verbose_name_plural = 'Informações de Vendedor'

class UserAdmin(BaseUserAdmin):
    inlines = (PerfilInline,)

    list_display = ('username', 'first_name', 'last_name', 'get_codigo', 'is_staff')

    def get_codigo(self, instance):

        if hasattr(instance, 'perfil'):
            return instance.perfil.codigo_vendedor
        return "Sem Código"
    get_codigo.short_description = 'Cód. Vendedor'

admin.site.unregister(User)
admin.site.register(User, UserAdmin)