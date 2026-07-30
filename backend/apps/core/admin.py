"""Base común para el admin de Django sobre modelos de negocio (Parte C3).

Todas las tablas de negocio (35 con RLS, ver apps/core/tests/test_aislamiento.py)
llevan una columna `tenant`. RLS ya impide que un usuario vea u opere filas de
otro tenant SIEMPRE que ``TenantMiddleware`` haya fijado ``app.tenant_id``
para la petición (Parte C1) -- eso es lo que hace el aislamiento real.

``TenantModelAdmin`` se ocupa de una cosa distinta y más simple: el
FORMULARIO. Sin esto, el campo `tenant` aparecería como un <select> con
TODOS los tenants visibles para la conexión activa (o, peor, ninguno útil
si RLS ya lo filtra) y el operador podría, sin querer, asignar la fila a un
tenant equivocado. Aquí se oculta ese campo y se rellena solo con el tenant
de la petición (``request.tenant_id``, publicado por TenantMiddleware) al
crear una fila nueva.
"""
from django.contrib import admin


class TenantModelAdmin(admin.ModelAdmin):
    """``ModelAdmin`` base para modelos con una columna `tenant`.

    - Oculta `tenant` del formulario de alta/edición (lo impone RLS; el
      operador del admin nunca debe poder elegirlo a mano).
    - Al crear una fila (``change=False``), la asigna automáticamente al
      tenant resuelto por ``TenantMiddleware`` para la petición actual.
      Al editar una fila existente, el tenant ya viene de la base de datos
      y no se toca.
    """

    def get_exclude(self, request, obj=None):
        excluidos = super().get_exclude(request, obj) or ()
        nombres_campos = {campo.name for campo in self.model._meta.get_fields()}
        if 'tenant' in nombres_campos and 'tenant' not in excluidos:
            return (*excluidos, 'tenant')
        return excluidos

    def save_model(self, request, obj, form, change):
        if not change and hasattr(obj, 'tenant_id'):
            obj.tenant_id = request.tenant_id
        super().save_model(request, obj, form, change)
