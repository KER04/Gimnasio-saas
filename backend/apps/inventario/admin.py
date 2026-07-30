from django.contrib import admin

from apps.core.admin import TenantModelAdmin

from .models import CategoriaProducto, MovimientoInventario, Producto


@admin.register(Producto)
class ProductoAdmin(TenantModelAdmin):
    list_display = ('nombre', 'marca', 'categoria_producto', 'precio_venta', 'costo', 'activo')
    search_fields = ('nombre', 'marca', 'codigo_barras')
    list_filter = ('categoria_producto', 'activo')


admin.site.register(CategoriaProducto, TenantModelAdmin)
admin.site.register(MovimientoInventario, TenantModelAdmin)

# StockSede usa CompositePrimaryKey (pk = (producto, sede)): el admin de
# Django 6 rechaza explícitamente registrar un modelo con PK compuesta, así
# que queda fuera del admin por esa restricción del framework.
