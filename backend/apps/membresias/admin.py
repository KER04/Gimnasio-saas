from django.contrib import admin

from apps.core.admin import TenantModelAdmin

from .models import Membresia, Plan


@admin.register(Plan)
class PlanAdmin(TenantModelAdmin):
    list_display = ('nombre', 'tipo', 'duracion_dias', 'precio', 'requiere_entrenador', 'activo')
    search_fields = ('nombre',)
    list_filter = ('tipo', 'activo', 'requiere_entrenador')


@admin.register(Membresia)
class MembresiaAdmin(TenantModelAdmin):
    list_display = ('cliente', 'plan', 'sede', 'fecha_inicio', 'fecha_fin', 'estado')
    search_fields = ('cliente__nombre', 'cliente__cedula')
    list_filter = ('estado', 'sede', 'plan')
