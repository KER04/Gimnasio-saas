from django.db import connections
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.core.tenant import tenant_context

from .serializers import LoginSerializer, RegisterSerializer, UsuarioSerializer

# Debe coincidir con `apps.core.middleware._ESTADOS_TENANT_EXCLUIDOS`: un
# tenant cancelado/suspendido no debe poder "entrar por subdominio" tampoco
# cuando ese subdominio llega explícito en el cuerpo de login/register.
_ESTADOS_TENANT_EXCLUIDOS = ('cancelado', 'suspendido')


def _resolver_tenant_login_register(request):
    """Resuelve el tenant para login/register combinando el campo
    ``subdominio`` del cuerpo con lo que ``TenantMiddleware`` ya haya
    publicado en ``request.tenant`` (Host/JWT/sesión/cabecera X-Tenant).

    Devuelve ``(tenant, None)`` en éxito o ``(None, Response)`` con un 400
    ya listo para devolver tal cual. Orden de resolución (ver encargo,
    Parte A2):

    1. ``subdominio`` del cuerpo, si viene -> se busca el ``Tenant`` (excluye
       cancelado/suspendido). Si no existe ningún tenant con ese subdominio,
       400 (el subdominio va en la URL en producción, no es secreto: se
       puede decir que no existe).
    2. Si no viene en el cuerpo -> ``request.tenant`` (lo que ya resolvió el
       middleware).
    3. Si ninguno de los dos -> 400 con mensaje explicando cómo indicarlo.

    Si vienen los DOS y no coinciden -> 400: probablemente un error del
    cliente, mejor rechazar que adivinar. Si el Host no resolvió ningún
    tenant (p. ej. ``api.tuapp.com``), ``request.tenant`` es ``None`` y
    sencillamente no hay nada con qué comparar -- eso NO es un conflicto.
    """
    # request.data puede no ser un dict en teoría (payloads exóticos); nos
    # comportamos como si no hubiera venido `subdominio` en ese caso, en vez
    # de reventar con un AttributeError.
    subdominio_body = ''
    if hasattr(request.data, 'get'):
        subdominio_body = (request.data.get('subdominio') or '').strip()

    tenant_body = None
    if subdominio_body:
        from apps.plataforma.models import Tenant

        tenant_body = Tenant.objects.using('default').exclude(
            estado__in=_ESTADOS_TENANT_EXCLUIDOS,
        ).filter(subdominio__iexact=subdominio_body).first()
        if tenant_body is None:
            return None, Response(
                {'detail': f'No existe ningún gimnasio con el subdominio "{subdominio_body}".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    tenant_host = getattr(request, 'tenant', None)

    if tenant_body is not None and tenant_host is not None and tenant_body.id != tenant_host.id:
        return None, Response(
            {
                'detail': (
                    'El subdominio indicado no coincide con el gimnasio de la '
                    'URL desde la que accedes.'
                ),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    tenant = tenant_body or tenant_host
    if tenant is None:
        return None, Response(
            {
                'detail': (
                    "No se pudo determinar el gimnasio. Envía el campo "
                    "'subdominio' o accede por la URL de tu gimnasio."
                ),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    return tenant, None


def _transaccion_tenant_ya_abierta(tenant_id, using='default'):
    """True si la conexión ``using`` ya está dentro de una transacción con
    ``app.tenant_id`` fijado a ``tenant_id`` -- típicamente porque
    ``TenantMiddleware`` ya abrió ``tenant_context`` para TODA esta petición
    (caso: el Host trae un subdominio válido, ver middleware.py). En ese
    caso, la vista no necesita abrir su propio ``tenant_context``.

    Si no hay transacción abierta, o la hay pero con otro tenant (o
    ninguno) fijado, se devuelve False y la vista debe abrir la suya.

    Nota: anidar ``tenant_context`` igualmente NO rompería nada (ver el
    docstring de ``apps.core.tenant.tenant_context`` -- un SAVEPOINT no
    deshace ``set_config``), así que esta función es una optimización para
    no abrir una transacción/SAVEPOINT de más, no una necesidad de
    corrección.
    """
    conn = connections[using]
    if not conn.in_atomic_block:
        return False
    with conn.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.tenant_id', true)")
        valor = cursor.fetchone()[0]
    return valor == str(tenant_id)


class LoginView(TokenObtainPairView):
    """Login: devuelve access, refresh y los datos del usuario.

    El tenant puede llegar de dos formas, combinadas por
    ``_resolver_tenant_login_register`` (ver encargo "el API debe poder
    recibir el gimnasio como campo explícito, sin dejar de aceptar el
    subdominio del Host"):

    1. Campo ``subdominio`` en el cuerpo (nuevo): necesario cuando el
       frontend y el API NO comparten Host (p. ej. Angular en
       ``gimx.tuapp.com`` pegando a ``api.tuapp.com``) -- en ese caso
       ``request.tenant`` es ``None`` (el Host del API no tiene subdominio
       de tenant) y sin este campo el login sería imposible.
    2. Subdominio del Host, resuelto por ``TenantMiddleware`` en
       ``request.tenant`` (comportamiento previo, se mantiene como
       respaldo).

    CRÍTICO (Parte A3 del encargo): ``/api/auth/login/`` NO está en
    ``TENANT_EXEMPT_PATHS`` (ver comentario en ``settings/base.py``), así
    que CUANDO el Host resuelve un tenant, ``TenantMiddleware`` ya abrió
    ``tenant_context`` alrededor de TODA la petición (incluida esta vista).
    Pero cuando el Host NO resuelve ningún tenant (``api.tuapp.com``) y el
    tenant sale del campo del cuerpo, el middleware NO abrió ninguna
    transacción de tenant -- y tanto la autenticación (SELECT sobre
    `usuarios`, RLS+FORCE) como ``update_last_login`` (UPDATE sobre la misma
    tabla, disparado dentro de ``TokenObtainPairSerializer.validate()``)
    necesitan ``app.tenant_id`` fijado. Por eso esta vista abre su propio
    ``tenant_context`` envolviendo TODA la llamada a ``super().post()``
    (autenticación + emisión del token + update_last_login) -- salvo que
    ``_transaccion_tenant_ya_abierta`` detecte que el middleware ya lo hizo
    para este mismo tenant, en cuyo caso no se abre una segunda vez.
    """
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        tenant, error = _resolver_tenant_login_register(request)
        if error is not None:
            return error

        # TenantAuthBackend.authenticate() (invocado dentro de
        # super().post() -> serializer.is_valid() -> validate() ->
        # authenticate()) lee `request.tenant_id` -- hay que fijarlo AQUÍ,
        # antes de delegar, para que el subdominio explícito del cuerpo
        # tenga efecto (si no, se quedaría con lo que resolvió el
        # middleware, que puede ser None).
        request.tenant = tenant
        request.tenant_id = tenant.id

        if _transaccion_tenant_ya_abierta(tenant.id):
            return super().post(request, *args, **kwargs)

        with tenant_context(tenant.id):
            return super().post(request, *args, **kwargs)


class RegisterView(generics.CreateAPIView):
    """Registro de nuevos usuarios DENTRO del tenant resuelto (subdominio
    del cuerpo, con el subdominio del Host como respaldo -- ver
    ``_resolver_tenant_login_register``).

    Sigue con AllowAny (pendiente de restringir, ver encargo), pero exige un
    tenant resuelto: sin él, 400 -- no existe un usuario "sin gimnasio".
    """
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        tenant, error = _resolver_tenant_login_register(request)
        if error is not None:
            return error

        request.tenant = tenant
        request.tenant_id = tenant.id

        serializer = self.get_serializer(data=request.data)

        def _validar_y_guardar():
            # Envuelve TANTO la validación (validate_correo consulta
            # `usuarios`, el PrimaryKeyRelatedField de `rol` consulta
            # `roles`) COMO el guardado dentro del mismo tenant_context:
            # ambas tablas tienen RLS con FORCE, y esta ruta es exenta
            # (TenantMiddleware no abre tenant_context para ella). Sin
            # esto, is_valid()/save() verían siempre 0 filas o violarían la
            # política WITH CHECK del INSERT.
            serializer.is_valid(raise_exception=True)
            return serializer.save()

        # '/api/auth/register/' SIEMPRE está en TENANT_EXEMPT_PATHS (a
        # diferencia de login), así que el middleware NUNCA abre
        # tenant_context para esta ruta -- pero se comprueba igual, por
        # coherencia con _resolver_tenant_login_register y por si el día de
        # mañana deja de estar exenta.
        if _transaccion_tenant_ya_abierta(tenant.id):
            usuario = _validar_y_guardar()
        else:
            with tenant_context(tenant.id):
                usuario = _validar_y_guardar()

        refresh = RefreshToken.for_user(usuario)
        refresh['tenant_id'] = usuario.tenant_id
        data = {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UsuarioSerializer(usuario).data,
        }
        headers = self.get_success_headers(serializer.data)
        return Response(data, status=status.HTTP_201_CREATED, headers=headers)


class MeView(APIView):
    """Devuelve los datos del usuario autenticado."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UsuarioSerializer(request.user).data)


class LogoutView(APIView):
    """Invalida (blacklist) el refresh token recibido para cerrar la sesión."""
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {'detail': 'Se requiere el token "refresh" para cerrar sesión.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            return Response(
                {'detail': 'El token "refresh" es inválido o ya expiró.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({'detail': 'Sesión cerrada.'}, status=status.HTTP_200_OK)
