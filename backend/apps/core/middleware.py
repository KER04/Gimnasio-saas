"""Middleware de resolución de tenant (Parte A del diseño multi-tenant;
ampliado en la Parte C para resolver el tenant desde el JWT, y en la Parte
C1 para servir también al admin de Django).

Responsabilidades de ``TenantMiddleware``:

1. Resolver a qué tenant pertenece la petición y publicarlo en
   ``request.tenant`` / ``request.tenant_id``. Orden de resolución (C1):

   a. Claim ``tenant_id`` de un JWT válido en ``Authorization: Bearer``.
      FUENTE DE VERDAD: si, además, la petición trae un subdominio de Host
      que resuelve a un tenant DISTINTO del tenant del token, se rechaza con
      403 antes de tocar ninguna vista -- no tiene sentido de negocio (ni es
      seguro) que un usuario autenticado en el tenant A pida datos al
      subdominio del tenant B.
   b. Si no hay JWT (o es inválido/expiró): tenant sembrado en la SESIÓN al
      loguearse (clave ``TENANT_SESSION_KEY``, ver
      apps/autenticacion/backends.py). Es la vía que usa el admin de Django
      (usa sesión, no JWT). Se lee directo de ``request.session``, sin
      tocar ``request.user`` -- evaluar ``request.user`` dispararía
      ``TenantAuthBackend.get_user()``, que consulta `usuarios` bajo RLS y
      necesitaría el tenant YA fijado para no ver cero filas: un ciclo. Leer
      la sesión en crudo rompe ese ciclo (``django_session`` no tiene RLS).
   c. Si tampoco hay sesión: subdominio del Host.
   d. Solo en ``DEBUG=True``, si no hay subdominio: cabecera ``X-Tenant``
      (simula subdominios en desarrollo local).
   e. Nada de lo anterior resuelve -> no se fija ningún tenant (falla
      cerrado).

2. Abrir la transacción de PostgreSQL que fija ``app.tenant_id`` para que las
   políticas RLS filtren correctamente — ver el comentario largo más abajo
   sobre por qué esto NO puede delegarse en ``ATOMIC_REQUESTS``.

Si no se resuelve ningún tenant, el middleware NO fija nada: falla cerrado.
``fn_tenant_actual()`` devolverá NULL y cada política RLS
(``tenant_id = fn_tenant_actual()``) será NULL = falsa para toda fila, así
que cualquier tabla de negocio devuelve cero filas en vez de fugarse datos de
todos los tenants.
"""
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from .tenant import tenant_context

# TTL corto del caché de resolución subdominio -> Tenant. No hace falta una
# invalidación más fina: un tenant que cambia de estado (p. ej. se suspende)
# tarda como mucho este tiempo en dejar de resolver.
_TENANT_CACHE_TTL = 60
_TENANT_CACHE_PREFIX = 'core:tenant:subdominio:'

# Sentinela para poder cachear también los "no existe" (evita repetir la
# consulta a `tenants` en cada petición de un subdominio inválido/typo).
#
# Es una CADENA y no un `object()`, y se compara por VALOR y no con `is`.
#
# El caché de Django SERIALIZA todo lo que guarda -- no solo Redis, también
# `LocMemCache`, que hace `pickle.dumps` al escribir y `pickle.loads` al
# leer. Lo que se recupera es por tanto siempre una reconstrucción, nunca el
# mismo objeto que se guardó, así que `cacheado is _MISS` era False SIEMPRE.
#
# La consecuencia no era una consulta de más: el centinela se ESCAPABA de
# esta función haciéndose pasar por un Tenant. Recorría el middleware hasta
# que alguien le pedía `.id` y reventaba con
#
#     AttributeError: 'object' object has no attribute 'id'
#
# dejando caído a todo el que entrara por un subdominio inexistente (y, en
# un PaaS, el dominio asignado por defecto es exactamente eso). El fallo
# estuvo latente desde el principio en todos los entornos: solo hacía falta
# pedir dos veces el mismo subdominio inexistente dentro de la ventana del
# TTL para provocarlo.
_MISS = '__core.tenant.no_existe__'

# Estados de tenant que NUNCA deben resolver, aunque el subdominio exista.
_ESTADOS_TENANT_EXCLUIDOS = ('cancelado', 'suspendido')


def invalidar_cache_tenant(subdominio):
    """Olvida la resolución cacheada de un subdominio.

    Hay que llamarla en cuanto cambia algo que afecte a si ese subdominio
    debe resolver o no -- en la práctica, el ``estado`` del tenant. Sin esto,
    suspender un gimnasio tardaría hasta ``_TENANT_CACHE_TTL`` segundos en
    dejarlo fuera, y reactivarlo otro tanto: el caché guarda también los
    "no existe" (``_MISS``), así que un gimnasio recién reactivado seguiría
    rebotando a sus usuarios durante un minuto sin motivo aparente.

    Un TTL corto hace el fallo pasajero, no inofensivo: el minuto en el que
    un gimnasio suspendido sigue operando es exactamente el minuto en el que
    alguien decidió suspenderlo.
    """
    cache.delete(f'{_TENANT_CACHE_PREFIX}{subdominio.lower()}')


def _subdominio_desde_host(host):
    """Extrae el subdominio de un ``Host`` de request, o ``None`` si no aplica.

    ``host`` puede traer puerto (``"gima.testserver:8000"``); se descarta.
    ``localhost`` y ``127.0.0.1`` nunca tienen subdominio de tenant.

    Nota sobre el umbral de segmentos: en producción un host real tiene la
    forma ``subdominio.dominio.tld`` (3 segmentos, p. ej. ``gima.tuapp.com``).
    Sin embargo, el ``ALLOWED_HOSTS``/``Host`` que usa el propio test runner
    de Django es de la forma ``subdominio.testserver`` (2 segmentos, sin TLD).
    Exigir 3+ segmentos a rajatabla rompería la resolución de tenant bajo
    pruebas. Por eso el umbral real es "2 o más segmentos, y no es un host
    reservado (localhost/127.0.0.1)": sigue siendo imposible que una petición
    a un dominio "desnudo" de un solo segmento (``tuapp.com`` en producción
    tiene 2 segmentos igualmente, pero ese caso ya no correspondería a un
    subdominio de tenant real y sencillamente no encontrará Tenant y quedará
    sin resolver, fallando cerrado de todas formas).
    """
    host_sin_puerto = host.split(':')[0].lower()
    if host_sin_puerto in ('localhost', '127.0.0.1'):
        return None
    partes = host_sin_puerto.split('.')
    if len(partes) < 2:
        return None
    return partes[0]


def _tenant_por_subdominio(subdominio):
    # Import perezoso: evita acoplar la carga de apps de `apps.core` (que se
    # registra muy temprano) con el registro de modelos de `apps.plataforma`.
    from apps.plataforma.models import Tenant

    clave_cache = f'{_TENANT_CACHE_PREFIX}{subdominio.lower()}'
    cacheado = cache.get(clave_cache)
    if cacheado is not None:
        # De aquí solo sale un Tenant de verdad o None. La comprobación de
        # tipo no es paranoia: además del centinela, cubre lo que quede en
        # una caché COMPARTIDA escrito por una versión anterior del código
        # tras un despliegue (Redis sobrevive al reinicio de la aplicación).
        # Lo peor que puede pasar si el valor no se reconoce es una consulta
        # de más; lo peor si se dejara pasar es tumbar el sitio.
        return cacheado if isinstance(cacheado, Tenant) else None

    try:
        tenant = Tenant.objects.using('default').exclude(
            estado__in=_ESTADOS_TENANT_EXCLUIDOS,
        ).get(subdominio__iexact=subdominio)
    except Tenant.DoesNotExist:
        cache.set(clave_cache, _MISS, _TENANT_CACHE_TTL)
        return None

    cache.set(clave_cache, tenant, _TENANT_CACHE_TTL)
    return tenant


def _tenant_id_desde_jwt(request):
    """Extrae el claim ``tenant_id`` de un ``Authorization: Bearer <token>``
    válido, o ``None`` si no hay cabecera, el esquema no es Bearer, el token
    no decodifica (inválido/expirado/manipulado) o no trae el claim.

    Nunca lanza: un token roto se trata exactamente igual que "no hay
    token" -- el middleware cae al subdominio y es la vista (DRF/SimpleJWT)
    la que, más adelante, devolverá 401 al intentar autenticar con ese mismo
    token.
    """
    encabezado = request.META.get('HTTP_AUTHORIZATION', '')
    if not encabezado.startswith('Bearer '):
        return None

    token_str = encabezado[len('Bearer '):].strip()
    if not token_str:
        return None

    try:
        token = AccessToken(token_str)
    except TokenError:
        return None
    except Exception:
        # Defensa extra: cualquier fallo inesperado al decodificar (payload
        # corrupto, base64 roto, etc.) debe degradarse a "no hay token",
        # nunca reventar el middleware entero.
        return None

    # Se lee de `payload` (dict plano) en vez de `token['tenant_id']` para no
    # depender de que Token implemente __getitem__/get de una forma concreta.
    return token.payload.get('tenant_id')


def _tenant_por_id(tenant_id):
    from apps.plataforma.models import Tenant

    try:
        return Tenant.objects.using('default').get(pk=tenant_id)
    except Tenant.DoesNotExist:
        return None


def _tenant_por_usuario_sesion(request):
    """Segunda vía de resolución (C1, tras el JWT): sesión autenticada (el
    admin de Django usa sesión, no JWT).

    Lee el tenant DIRECTAMENTE de ``request.session`` (clave
    ``TENANT_SESSION_KEY``, sembrada por ``apps.autenticacion.backends`` en
    cada login por sesión) en vez de tocar ``request.user``. Es deliberado:
    ``request.user`` es un ``SimpleLazyObject`` cuya evaluación dispara
    ``TenantAuthBackend.get_user()``, que consulta la tabla `usuarios` bajo
    RLS -- y esa consulta necesita ``app.tenant_id`` YA fijado para no
    devolver cero filas. Si este método intentara resolver el tenant
    TOCANDO ``request.user`` primero, sería un ciclo imposible (necesitar el
    tenant para poder averiguar el tenant). Leyendo la sesión en crudo se
    rompe el ciclo: ``django_session`` no tiene RLS ni columna `tenant_id`
    propia, así que no hay nada que resolver antes de leerla.

    Nada de esto revienta si la sesión no trae la clave (usuario anónimo,
    sesión vieja de antes de esta funcionalidad, JWT-only): se trata igual
    que "no hay sesión" y se cae a la siguiente vía (subdominio).
    """
    # Import perezoso: mismo motivo que los imports de `apps.plataforma.models`
    # más arriba -- evita acoplar la carga de `apps.core` con `apps.autenticacion`.
    from apps.autenticacion.backends import TENANT_SESSION_KEY

    try:
        tenant_id = request.session.get(TENANT_SESSION_KEY)
    except Exception:
        return None

    if tenant_id is None:
        return None

    return _tenant_por_id(tenant_id)


def _resolver_tenant_por_subdominio_o_header(request):
    """Orden de resolución cuando NO hay un JWT válido con claim tenant_id
    NI una sesión autenticada (parte A1, sin cambios):

    1. Subdominio del Host.
    2. Cabecera ``X-Tenant``, SOLO si ``DEBUG`` es True.
    3. Ninguno de los anteriores -> no se resuelve tenant (falla cerrado).
    """
    subdominio = _subdominio_desde_host(request.get_host())
    if subdominio:
        tenant = _tenant_por_subdominio(subdominio)
        if tenant is not None:
            return tenant

    # CRÍTICO DE SEGURIDAD: esta cabecera solo se atiende con DEBUG=True.
    # Existe únicamente para poder simular subdominios en desarrollo local sin
    # tener que configurar DNS/hosts. Si se atendiera también con DEBUG=False,
    # cualquier usuario autenticado del gimnasio A podría mandar
    # "X-Tenant: B" en su petición y leer/escribir datos del gimnasio B: la
    # cabecera la controla el cliente HTTP, no el servidor, así que en
    # producción es una superficie de suplantación de tenant directa. Por
    # eso, fuera de DEBUG, se ignora POR COMPLETO (ni siquiera se lee). El
    # JWT, cuando existe, siempre gana sobre esta cabecera (se resuelve
    # antes, en TenantMiddleware.__call__, y esta función ni se llama).
    if settings.DEBUG:
        subdominio_header = request.META.get('HTTP_X_TENANT')
        if subdominio_header:
            tenant = _tenant_por_subdominio(subdominio_header)
            if tenant is not None:
                return tenant

    return None


def _es_ruta_exenta(path):
    return any(path.startswith(prefijo) for prefijo in settings.TENANT_EXEMPT_PATHS)


class TenantMiddleware:
    """Resuelve el tenant de la petición y fija ``app.tenant_id`` en la
    conexión ``default`` mientras se procesa la vista.

    ## Por qué el middleware abre su propia transacción (A2)

    ``ATOMIC_REQUESTS = True`` envuelve en una transacción la VISTA (lo hace
    ``BaseHandler`` internamente, vía ``non_atomic_requests``/
    ``transaction.atomic(using=alias)`` colocado alrededor de la función de
    vista), no la cadena de middlewares completa. Si este middleware hiciera
    ``SET LOCAL`` / ``set_config(..., true)`` ANTES de llamar a
    ``self.get_response(request)`` sin abrir su propia transacción, ese
    ``SET`` quedaría fuera de cualquier transacción (en autocommit) y, para
    cuando ``ATOMIC_REQUESTS`` abra la transacción real alrededor de la
    vista, el valor ya se habría perdido (un ``SET LOCAL`` fuera de una
    transacción explícita se comporta como un ``SET`` de sesión que se
    resetea en el siguiente ciclo de autocommit).

    Por eso este middleware envuelve TODA la llamada a ``get_response`` en su
    propia ``transaction.atomic(using='default')`` (a través de
    ``tenant_context``, que además fija ``app.tenant_id`` dentro). La
    transacción que ``ATOMIC_REQUESTS`` abre después, alrededor de la vista,
    queda ANIDADA dentro de esta (como SAVEPOINT) y ve perfectamente el valor
    ya fijado, porque un SAVEPOINT no reinicia las variables de sesión
    locales a la transacción: solo un COMMIT/ROLLBACK de la transacción
    exterior (la de este middleware) las hace desaparecer.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant_id_jwt = _tenant_id_desde_jwt(request)

        if tenant_id_jwt is not None:
            # El JWT es la fuente de verdad. Si además la petición trae un
            # subdominio que resuelve a un tenant DISTINTO, es una
            # inconsistencia que no debe pasar en silencio ni resolverse "a
            # favor" de uno u otro: se rechaza de plano, sin servir nada.
            # Esta comprobación corre para TODA petición con un token válido
            # (exenta o no) porque un token nunca debería viajar hacia un
            # subdominio ajeno, ni siquiera hacia rutas como /api/auth/logout/.
            subdominio = _subdominio_desde_host(request.get_host())
            if subdominio:
                tenant_subdominio = _tenant_por_subdominio(subdominio)
                if tenant_subdominio is not None and tenant_subdominio.id != tenant_id_jwt:
                    return JsonResponse(
                        {
                            'detail': (
                                'El tenant del token no coincide con el '
                                'tenant del subdominio solicitado.'
                            ),
                        },
                        status=403,
                    )
            tenant = _tenant_por_id(tenant_id_jwt)
        else:
            tenant = _tenant_por_usuario_sesion(request)
            if tenant is None:
                tenant = _resolver_tenant_por_subdominio_o_header(request)

        request.tenant = tenant
        request.tenant_id = tenant.id if tenant is not None else None

        if _es_ruta_exenta(request.path):
            # Rutas exentas (register/refresh/logout de la API, estáticos):
            # no abren transacción de tenant porque no la necesitan. El
            # tenant ya quedó publicado en request.tenant/request.tenant_id
            # arriba, por si la vista lo necesita igual.
            #
            # NOTA: ni '/api/auth/login/' ni '/admin/login/' están en esta
            # lista (ver el comentario largo en TENANT_EXEMPT_PATHS,
            # settings/base.py): ambas SÍ necesitan la transacción de tenant
            # abierta cuando el subdominio resuelve, porque un login real
            # escribe (`update_last_login`). Cuando el tenant no resuelve,
            # el `if tenant is None` de abajo ya despacha la petición sin
            # transacción de todas formas, así que no hace falta una
            # exención explícita para que la página de login funcione.
            return self.get_response(request)

        if tenant is None:
            # Falla cerrado: no se fija app.tenant_id. Las políticas RLS
            # comparan tenant_id = fn_tenant_actual() y, con la variable sin
            # fijar, fn_tenant_actual() devuelve NULL: NULL = cualquier cosa
            # es NULL (ni verdadero ni falso), así que ninguna fila de
            # negocio pasa el filtro. La petición sigue su curso normal (la
            # vista puede, por ejemplo, devolver 404/400), simplemente no ve
            # ningún dato de negocio.
            return self.get_response(request)

        with tenant_context(tenant.id, using='default'):
            response = self.get_response(request)
        return response
