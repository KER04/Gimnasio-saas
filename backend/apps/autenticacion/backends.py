"""Backend de autenticación consciente del tenant (Parte B).

Reemplaza al ``ModelBackend`` de Django, que resuelve un usuario por un único
campo global (``username``/``email``). Aquí el correo NO es único
globalmente -- es único POR TENANT (``UniqueConstraint(Lower('correo'),
'tenant')`` en ``apps.organizacion.Usuario``), así que "quién eres" depende
tanto del correo como del tenant al que apuntas. Autenticar sin tenant
resuelto sería ambiguo (¿cuál de los N usuarios con ese correo, uno por
tenant?) y, peor, sin tenant no hay forma de acotar la búsqueda: por eso este
backend falla cerrado si no hay tenant.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from apps.core.tenant import tenant_context

Usuario = get_user_model()

# Parte C1: clave de sesión donde se guarda el `tenant_id` del usuario en el
# momento del login. Es la pieza que rompe el problema del huevo y la
# gallina de la autenticación por sesión: `TenantMiddleware` necesita saber
# el tenant ANTES de decidir si abre `tenant_context` para la petición, pero
# la única forma "normal" de saberlo sería a través de `request.user` --que
# a su vez necesita `tenant_context` ya abierto para poder consultarse a sí
# mismo, porque `usuarios` tiene RLS con FORCE. Guardar el tenant_id
# DIRECTAMENTE en la sesión (datos de `django_session`, sin RLS ni tenant_id
# propios) evita el ciclo por completo: `TenantMiddleware` lo lee sin tocar
# la tabla `usuarios` en absoluto (ver ``apps/core/middleware.py``).
TENANT_SESSION_KEY = '_auth_user_tenant_id'


@receiver(user_logged_in)
def _guardar_tenant_id_en_sesion(sender, request, user, **kwargs):
    """Espeja `tenant_id` a la sesión en cada login por sesión (el admin de
    Django; la API JWT no dispara `user_logged_in`, es sin estado)."""
    request.session[TENANT_SESSION_KEY] = user.tenant_id

# Hash dummy fijo, calculado una sola vez al importar el módulo. Se usa para
# ejecutar SIEMPRE un check_password (aunque el usuario no exista), de modo
# que el tiempo de respuesta de un login con correo inexistente sea
# indistinguible del de un login con correo existente y password incorrecta.
# Sin esto, la ausencia del costoso hash de password (PBKDF2/Argon2) cuando
# el usuario no existe sería una fuga de tiempo que permite enumerar qué
# correos están registrados en un tenant.
_HASH_DUMMY = make_password(None)


class TenantAuthBackend(BaseBackend):
    """Autentica por ``correo`` + ``password`` DENTRO de un tenant concreto.

    Sin tenant no hay login: si no se puede resolver un ``tenant_id`` (ni
    por parámetro explícito ni por ``request.tenant_id``), ``authenticate``
    devuelve ``None`` sin tocar la base de datos.
    """

    def authenticate(self, request, correo=None, password=None, tenant_id=None, username=None, **kwargs):
        # Parte C2: el formulario de login del admin de Django llama a
        # ``authenticate(request, username=<valor>, password=...)`` --
        # ``username`` es el nombre de parámetro fijo que usa
        # ``AuthenticationForm``, no configurable sin reescribir el formulario
        # entero. Aquí se acepta como sinónimo de ``correo`` (ambos
        # identifican al usuario por el mismo campo, el correo) para que el
        # mismo backend sirva tanto a /api/auth/login/ (que sí manda
        # ``correo``) como al admin (que manda ``username``).
        correo = correo or username
        if not correo or password is None:
            return None

        if tenant_id is None:
            tenant_id = getattr(request, 'tenant_id', None)
        if tenant_id is None:
            return None

        # ## Por qué esta consulta va envuelta en tenant_context
        #
        # La tabla `usuarios` tiene RLS con FORCE: cualquier SELECT por la
        # conexión 'default' (rol keradmin, sin privilegios especiales) solo
        # ve filas donde tenant_id = fn_tenant_actual(). El login ocurre en
        # una ruta EXENTA (TENANT_EXEMPT_PATHS incluye /api/auth/login/), así
        # que TenantMiddleware NO abre ninguna transacción/tenant_context
        # alrededor de esta petición (ver apps/core/middleware.py: las rutas
        # exentas se saltan el `with tenant_context(...)` que envuelve el
        # resto de la cadena). Sin fijar app.tenant_id aquí mismo,
        # fn_tenant_actual() devolvería NULL y la política RLS
        # (tenant_id = fn_tenant_actual()) sería NULL para toda fila: el
        # SELECT de abajo devolvería SIEMPRE 0 filas, sin importar que el
        # usuario exista y la password sea correcta.
        #
        # Se verificó manualmente (runserver + petición real) que, sin este
        # `with tenant_context(tenant_id)`, el login falla con
        # "credenciales inválidas" incluso con correo/tenant/password
        # correctos -- exactamente el síntoma de RLS bloqueando el SELECT.
        # Envolviendo la búsqueda aquí, dentro de una transacción acotada a
        # esta única consulta, el login funciona sin necesidad de que el
        # middleware trate /api/auth/login/ como una ruta "con tenant".
        with tenant_context(tenant_id, using='default'):
            try:
                usuario = Usuario.objects.using('default').get(
                    correo__iexact=correo, tenant_id=tenant_id, activo=True,
                )
            except Usuario.DoesNotExist:
                # Hash dummy: ver comentario de _HASH_DUMMY arriba.
                check_password(password, _HASH_DUMMY)
                return None

            if usuario.check_password(password):
                return usuario
            return None

    def get_user(self, user_id):
        """Resuelve un usuario a partir del id guardado en la sesión.

        En el flujo de API (JWT sin estado) este método casi nunca se
        ejercita -- ``JWTAuthentication.get_user`` consulta el modelo de
        usuario directamente, dentro de la transacción de tenant que ya
        abrió ``TenantMiddleware`` a partir del claim del token.

        Desde la Parte C1 sí hay un flujo real que pasa por aquí: el admin
        de Django autentica por sesión. Podría parecer que hay un problema
        del huevo y la gallina -- ``TenantMiddleware`` necesita el tenant del
        usuario para decidir si abre ``tenant_context``, pero este método
        (para poder leer la fila bajo RLS) necesitaría que ``tenant_context``
        ya estuviera abierto -- pero NO lo hay: ``TenantMiddleware`` resuelve
        el tenant de la sesión leyendo ``request.session`` DIRECTAMENTE
        (``TENANT_SESSION_KEY``, sembrado por ``_guardar_tenant_id_en_sesion``
        más arriba en cada login), sin pasar por ``request.user`` ni por este
        método. Así que, para cuando algo dispara la evaluación perezosa de
        ``request.user`` (típicamente el propio admin, al comprobar
        permisos), ``TenantMiddleware`` YA fijó ``app.tenant_id`` en la
        conexión 'default' -- esta consulta simplemente lo aprovecha.

        Si el id no existe (usuario borrado) o el tenant no coincide con el
        que ya está fijado en la conexión, RLS hace que el SELECT no
        encuentre la fila y se devuelva ``None``: falla cerrado, nunca un
        usuario de otro tenant.
        """
        try:
            return Usuario.objects.using('default').get(pk=user_id)
        except Usuario.DoesNotExist:
            return None
