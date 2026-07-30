from django.contrib import admin

from apps.core.admin import TenantModelAdmin

from .models import (
    ControlMedida,
    Ejercicio,
    FichaMedidas,
    GrupoMuscular,
    RecordPersonal,
    RegistroEjercicio,
    Rutina,
    RutinaDia,
    RutinaEjercicio,
)


@admin.register(Ejercicio)
class EjercicioAdmin(TenantModelAdmin):
    list_display = ('nombre', 'grupo_muscular', 'activo')
    search_fields = ('nombre',)
    list_filter = ('grupo_muscular', 'activo')


@admin.register(Rutina)
class RutinaAdmin(TenantModelAdmin):
    list_display = ('nombre', 'cliente', 'entrenador', 'fecha_inicio', 'fecha_fin', 'activa')
    search_fields = ('nombre', 'cliente__nombre')
    list_filter = ('activa',)


admin.site.register(GrupoMuscular, TenantModelAdmin)
admin.site.register(FichaMedidas, TenantModelAdmin)
admin.site.register(ControlMedida, TenantModelAdmin)
admin.site.register(RutinaDia, TenantModelAdmin)
admin.site.register(RutinaEjercicio, TenantModelAdmin)
admin.site.register(RegistroEjercicio, TenantModelAdmin)
admin.site.register(RecordPersonal, TenantModelAdmin)
