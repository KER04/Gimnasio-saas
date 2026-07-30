from django.contrib import admin

from apps.core.admin import TenantModelAdmin

from .models import AutorizacionDatos, Cliente, DispositivoBiometrico, HuellaCliente


@admin.register(Cliente)
class ClienteAdmin(TenantModelAdmin):
    list_display = ('nombre', 'cedula', 'telefono', 'sede_origen', 'activo', 'fecha_registro')
    search_fields = ('nombre', 'cedula', 'telefono')
    list_filter = ('activo', 'sede_origen', 'sexo')


@admin.register(HuellaCliente)
class HuellaClienteAdmin(TenantModelAdmin):
    # `plantilla_cifrada` de solo lectura: es la plantilla biométrica
    # cifrada, no un dato para editar a mano desde un formulario.
    list_display = ('cliente', 'dedo', 'calidad', 'formato', 'fecha_captura')
    readonly_fields = ('plantilla_cifrada',)


admin.site.register(AutorizacionDatos, TenantModelAdmin)
admin.site.register(DispositivoBiometrico, TenantModelAdmin)
