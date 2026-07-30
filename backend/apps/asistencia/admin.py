from django.contrib import admin

from apps.core.admin import TenantModelAdmin

from .models import Asistencia, IntentoBiometricoFallido


@admin.register(Asistencia)
class AsistenciaAdmin(TenantModelAdmin):
    list_display = ('cliente', 'sede', 'metodo', 'fecha_hora', 'con_membresia_vigente')
    search_fields = ('cliente__nombre', 'cliente__cedula')
    list_filter = ('metodo', 'sede', 'con_membresia_vigente')


admin.site.register(IntentoBiometricoFallido, TenantModelAdmin)
