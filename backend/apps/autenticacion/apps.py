from django.apps import AppConfig


class AutenticacionConfig(AppConfig):
    """App de autenticación multi-tenant (Parte A).

    SIN modelos propios: importa ``Usuario`` de ``apps.organizacion``
    (``AUTH_USER_MODEL = 'organizacion.Usuario'`` no cambia). Esta app agrupa
    solo la LÓGICA de autenticación -- backend, serializers, vistas y rutas
    de /api/auth/... -- separada de las entidades de organización (Sede,
    Rol, Usuario...) que viven en apps.organizacion.
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.autenticacion'
    label = 'autenticacion'

    def ready(self):
        # Registra el receptor de `user_logged_in` (Parte C1: espeja
        # tenant_id a la sesión en cada login por sesión) desde el arranque,
        # sin depender de que algo más importe `apps.autenticacion.backends`
        # primero.
        from . import backends  # noqa: F401
