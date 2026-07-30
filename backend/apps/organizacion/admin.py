"""Admin de las entidades de organización (Parte C3).

``Permiso`` es un catálogo GLOBAL sin `tenant` (lo define el proveedor, no el
gimnasio): se registra con ``admin.ModelAdmin`` normal, no con
``TenantModelAdmin``. El resto de modelos de esta app sí llevan `tenant`.
"""
from django.contrib import admin

from apps.core.admin import TenantModelAdmin

from .models import Permiso, Rol, SecuenciaComprobante, Sede, Usuario


@admin.register(Sede)
class SedeAdmin(TenantModelAdmin):
    list_display = ('nombre', 'direccion', 'telefono', 'activa', 'creado_en')
    search_fields = ('nombre', 'direccion', 'nit')
    list_filter = ('activa',)


@admin.register(Rol)
class RolAdmin(TenantModelAdmin):
    list_display = ('nombre', 'es_sistema', 'activo', 'creado_en')
    search_fields = ('nombre',)
    list_filter = ('es_sistema', 'activo')


@admin.register(Usuario)
class UsuarioAdmin(TenantModelAdmin):
    """Admin deliberadamente simple (sin ``UserAdmin``/``ReadOnlyPasswordHashField``):
    ``password`` queda de solo lectura para que no se pueda dejar un hash a
    medio escribir desde el formulario; cambiar contraseñas sigue siendo
    cosa de la API (``/api/auth/...``) o de un shell, no del admin.
    """

    list_display = ('correo', 'nombre', 'rol', 'activo', 'es_staff', 'es_superusuario', 'creado_en')
    search_fields = ('correo', 'nombre')
    list_filter = ('activo', 'es_staff', 'es_superusuario', 'rol')
    readonly_fields = ('password', 'last_login', 'creado_en', 'actualizado_en')


@admin.register(Permiso)
class PermisoAdmin(admin.ModelAdmin):
    """Catálogo global del proveedor: sin `tenant`, visible igual en
    cualquier admin (es de solo consulta en la práctica: lo siembra
    ``apps.core.migrations.0001_esquema_postgres``, no el operador)."""

    list_display = ('codigo', 'modulo', 'descripcion')
    search_fields = ('codigo', 'modulo', 'descripcion')
    list_filter = ('modulo',)


admin.site.register(SecuenciaComprobante, TenantModelAdmin)

# RolPermiso y UsuarioSede usan CompositePrimaryKey (pk = (rol, permiso) /
# (usuario, sede)): el admin de Django 6 rechaza explícitamente registrar un
# modelo con PK compuesta (`ImproperlyConfigured: ... has a composite
# primary key, so it cannot be registered with admin`). Quedan fuera del
# admin por esa restricción del framework, no por decisión de diseño.
