from django.contrib import admin

from apps.core.admin import TenantModelAdmin

from .models import CategoriaGasto, CategoriaIngreso, DetalleVenta, Gasto, IngresoOtro, Pago, Venta


@admin.register(Venta)
class VentaAdmin(TenantModelAdmin):
    list_display = ('consecutivo', 'sede', 'cliente', 'usuario', 'total', 'estado', 'fecha_hora')
    search_fields = ('cliente__nombre', 'cliente__cedula')
    list_filter = ('estado', 'sede')


admin.site.register(CategoriaIngreso, TenantModelAdmin)
admin.site.register(CategoriaGasto, TenantModelAdmin)
admin.site.register(DetalleVenta, TenantModelAdmin)
admin.site.register(Pago, TenantModelAdmin)
admin.site.register(IngresoOtro, TenantModelAdmin)
admin.site.register(Gasto, TenantModelAdmin)
