"""Settings de producción.

Para usarlos hay que fijar ``DJANGO_SETTINGS_MODULE=config.settings.prod`` en
el entorno: tanto ``manage.py`` como ``config/wsgi.py`` traen
``config.settings.dev`` como valor por defecto, así que un despliegue que no
la defina arrancaría con la configuración de DESARROLLO sin avisar de nada.
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS', default=[])


# ---------------------------------------------------------------------------
# Detrás de un proxy (Railway, Render, Fly, cualquier PaaS)
# ---------------------------------------------------------------------------
#
# El proxy termina el TLS y reenvía la petición a la aplicación por HTTP
# plano. Sin esta cabecera, Django ve `request.is_secure() == False`, y como
# `SECURE_SSL_REDIRECT` está activo responde con una redirección a HTTPS...
# que el proxy vuelve a entregar por HTTP: bucle infinito de redirecciones y
# el sitio entero caído con ERR_TOO_MANY_REDIRECTS.
#
# Solo es seguro porque quien pone `X-Forwarded-Proto` es el proxy del
# proveedor, que sobrescribe lo que mande el cliente. Si algún día la
# aplicación queda expuesta SIN proxy delante, esta línea deja de ser válida:
# cualquiera podría mandar la cabecera y hacerse pasar por una conexión
# segura.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# El origen de las peticiones POST del admin llega con el dominio real, no
# con el interno del contenedor. Sin esto, entrar al admin da 403 CSRF.
CSRF_TRUSTED_ORIGINS = env.list('DJANGO_CSRF_TRUSTED_ORIGINS', default=[])


# ---------------------------------------------------------------------------
# Estáticos del admin de Django
# ---------------------------------------------------------------------------
#
# La API no sirve páginas, pero el admin sí, y sin esto se ve sin estilos.
# WhiteNoise los sirve desde el propio proceso: evita montar un nginx para
# cuatro archivos CSS. Va inmediatamente DESPUÉS de SecurityMiddleware, como
# exige su documentación.
MIDDLEWARE = list(MIDDLEWARE)  # noqa: F405
MIDDLEWARE.insert(
    MIDDLEWARE.index('django.middleware.security.SecurityMiddleware') + 1,
    'whitenoise.middleware.WhiteNoiseMiddleware',
)

STATIC_ROOT = BASE_DIR / 'staticfiles'  # noqa: F405

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
#
# `base.py` solo autoriza localhost, que es lo correcto en desarrollo. Aquí se
# SUSTITUYE por el dominio real del frontend, tomado del entorno.
#
# Nunca se pone un comodín: `CORS_ALLOW_ALL_ORIGINS` dejaría que cualquier
# página de internet hiciera peticiones a esta API con las credenciales del
# usuario que la tenga abierta.
CORS_ALLOWED_ORIGINS = env.list('DJANGO_CORS_ALLOWED_ORIGINS', default=[])

# Para cuando cada gimnasio entre por su propio subdominio
# (`^https://[a-z0-9-]+\.midominio\.com$`). Mientras se sirva todo desde un
# dominio único, se queda vacío y basta con la lista de arriba.
CORS_ALLOWED_ORIGIN_REGEXES = env.list('DJANGO_CORS_ALLOWED_ORIGIN_REGEXES', default=[])


# ---------------------------------------------------------------------------
# Comprobación de arranque: el rol de la aplicación NO puede ser superusuario
# ---------------------------------------------------------------------------
#
# Todo el aislamiento entre gimnasios son 35 políticas de Row Level Security
# dentro de PostgreSQL, y un superusuario SE LAS SALTA TODAS, incluso con
# FORCE ROW LEVEL SECURITY. Si `DB_APP_USER` apuntara al superusuario del
# proveedor de hosting (que es el único rol que suele darte), la aplicación
# arrancaría, los tests pasarían y todo parecería funcionar mientras cada
# gimnasio ve los clientes, las ventas y la caja de todos los demás.
#
# No hay error, no hay aviso y no se nota hasta que lo nota un cliente. Por
# eso se comprueba aquí, al arrancar, en vez de confiar en que nadie se
# equivoque configurando el entorno.
if env('DB_APP_USER') == env('DB_DDL_USER'):
    raise ImproperlyConfigured(
        'DB_APP_USER y DB_DDL_USER son el mismo rol. El rol de la aplicación '
        'debe ser uno SIN privilegios de superusuario: los superusuarios de '
        'PostgreSQL ignoran Row Level Security, y con esta configuración cada '
        'gimnasio vería los datos de todos los demás. Crea un rol aparte '
        '(ver DESPLIEGUE.md) y apunta DB_APP_USER a él.'
    )
