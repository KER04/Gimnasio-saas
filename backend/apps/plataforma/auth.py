"""Autenticación del panel del proveedor.

El personal del proveedor (``UsuarioPlataforma``) NO es un usuario de gimnasio
(``organizacion.Usuario``). Son dos tablas distintas, con dos ciclos de vida
distintos, y sus identidades no deben poder confundirse jamás.

## El riesgo concreto

Los tokens de gimnasio llevan el claim ``user_id`` (lo pone ``for_user`` de
SimpleJWT) y ``tenant_id``. Los ids de ``usuarios`` y de
``usuarios_plataforma`` son secuencias INDEPENDIENTES: el usuario 3 de un
gimnasio y el empleado 3 del proveedor existen a la vez y no tienen nada que
ver. Si el panel autenticara mirando ``user_id``, el token de un recepcionista
cualquiera abriría el panel que gobierna TODOS los gimnasios.

Por eso los tokens de plataforma:

* llevan el claim ``ambito='plataforma'``, que ningún token de gimnasio tiene;
* guardan el id en ``usuario_plataforma_id``, NO en ``user_id``;
* no llevan ``tenant_id``, así que ``TenantMiddleware`` no resuelve ningún
  tenant con ellos y las tablas de negocio siguen sin devolver nada.

El aislamiento es simétrico y ambos sentidos están cubiertos por pruebas:

* un token de gimnasio en el panel -> 401, le falta ``ambito``;
* un token de plataforma en la API del gimnasio -> 401, le falta ``user_id``
  (``JWTAuthentication`` de SimpleJWT no encuentra el claim y rechaza).
"""
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.translation import gettext_lazy as _
from rest_framework import authentication, exceptions, permissions
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from .models import UsuarioPlataforma

#: Valor del claim que marca un token como "del panel del proveedor".
AMBITO_PLATAFORMA = 'plataforma'

#: Nombre del claim que guarda el id. Deliberadamente distinto de ``user_id``,
#: el que usa SimpleJWT para los usuarios de gimnasio.
CLAIM_USUARIO = 'usuario_plataforma_id'


#: Claim con una huella de la contraseña. Ver ``huella_password``.
CLAIM_HUELLA = 'hp'


def huella_password(usuario):
    """Huella corta y NO reversible del hash de la contraseña.

    Sirve para que cambiar la contraseña invalide los tokens ya emitidos.
    Los usuarios de gimnasio consiguen lo mismo poniendo sus refresh tokens
    en la lista negra, pero esa vía aquí no existe: los tokens del panel se
    construyen a mano (para no escribir el claim ``user_id``, ver arriba) y
    ``token_blacklist`` solo registra los que emite ``for_user``.

    Es el mismo mecanismo que usa Django para las sesiones
    (``get_session_auth_hash``): se deriva del hash almacenado, así que al
    cambiar la contraseña cambia la huella y todo token anterior deja de
    validar. Nunca viaja el hash en sí, solo un HMAC truncado suyo.
    """
    return salted_hmac(
        'apps.plataforma.auth.huella_password',
        usuario.password_hash,
    ).hexdigest()[:16]


def _poner_claims(token, usuario):
    token['ambito'] = AMBITO_PLATAFORMA
    token[CLAIM_USUARIO] = usuario.id
    token[CLAIM_HUELLA] = huella_password(usuario)
    # El rol viaja en el token solo para que el frontend pinte la interfaz.
    # NUNCA se usa para autorizar: los permisos se comprueban contra la fila
    # de la base de datos, que es la que puede cambiar sin que el token
    # emitido se entere.
    token['rol'] = usuario.rol
    return token


def crear_tokens(usuario):
    """Pareja de tokens para un ``UsuarioPlataforma`` ya autenticado.

    Se construye ``RefreshToken()`` a mano en vez de ``RefreshToken.for_user``
    a propósito: ``for_user`` escribiría el claim ``user_id``, que es
    justamente el que no debe existir aquí (ver el docstring del módulo).
    """
    refresh = _poner_claims(RefreshToken(), usuario)
    acceso = _poner_claims(refresh.access_token, usuario)
    return {'refresh': str(refresh), 'access': str(acceso)}


def refrescar_acceso(refresh_str):
    """Nuevo access token a partir de un refresh de plataforma.

    Revalida contra la base de datos: un empleado desactivado deja de entrar
    en cuanto caduca su access token, sin esperar a que caduque el refresh.
    """
    try:
        refresh = RefreshToken(refresh_str)
    except TokenError:
        raise exceptions.AuthenticationFailed(_('El token de refresco no es válido o expiró.'))

    if refresh.payload.get('ambito') != AMBITO_PLATAFORMA:
        raise exceptions.AuthenticationFailed(_('El token de refresco no es de este panel.'))

    usuario = _usuario_activo(refresh.payload.get(CLAIM_USUARIO))
    if usuario is None:
        raise exceptions.AuthenticationFailed(_('La cuenta ya no está activa.'))

    if not _huella_coincide(refresh.payload, usuario):
        raise exceptions.AuthenticationFailed(
            _('La contraseña cambió. Vuelve a iniciar sesión.'),
        )

    return {'access': str(_poner_claims(refresh.access_token, usuario))}


def _usuario_activo(usuario_id):
    if usuario_id is None:
        return None
    return UsuarioPlataforma.objects.filter(pk=usuario_id, activo=True).first()


def _huella_coincide(payload, usuario):
    """``constant_time_compare`` y no ``==``: comparar secretos con el
    operador normal filtra información por el tiempo que tarda en fallar."""
    return constant_time_compare(payload.get(CLAIM_HUELLA, ''), huella_password(usuario))


class AutenticacionPlataforma(authentication.BaseAuthentication):
    """Resuelve un ``UsuarioPlataforma`` desde el ``Authorization: Bearer``.

    Solo acepta tokens con ``ambito='plataforma'``. Un token de gimnasio, por
    válido que sea, se rechaza aquí.
    """

    palabra_clave = 'Bearer'

    def authenticate(self, request):
        encabezado = request.META.get('HTTP_AUTHORIZATION', '')
        if not encabezado.startswith(f'{self.palabra_clave} '):
            # Sin cabecera no se autentica, pero tampoco se falla: deja que
            # sea la clase de permiso la que responda 401.
            return None

        bruto = encabezado[len(self.palabra_clave) + 1:].strip()
        if not bruto:
            return None

        try:
            token = AccessToken(bruto)
        except TokenError:
            raise exceptions.AuthenticationFailed(_('El token no es válido o expiró.'))

        if token.payload.get('ambito') != AMBITO_PLATAFORMA:
            # Aquí es donde muere el token de un usuario de gimnasio.
            raise exceptions.AuthenticationFailed(_('Este token no da acceso al panel del proveedor.'))

        usuario = _usuario_activo(token.payload.get(CLAIM_USUARIO))
        if usuario is None:
            raise exceptions.AuthenticationFailed(_('La cuenta no existe o está inactiva.'))

        if not _huella_coincide(token.payload, usuario):
            # La contraseña cambió después de emitir este token: se cae aquí
            # tanto si la cambió su dueño como si se la restablecieron. En
            # ambos casos la sesión anterior debe morir.
            raise exceptions.AuthenticationFailed(
                _('La contraseña cambió. Vuelve a iniciar sesión.'),
            )

        return (usuario, token)

    def authenticate_header(self, request):
        return self.palabra_clave


class EsPersonalDePlataforma(permissions.BasePermission):
    """Cualquier empleado del proveedor, activo. Incluye a soporte."""

    message = 'Necesitas una cuenta del panel del proveedor.'

    def has_permission(self, request, view):
        usuario = getattr(request, 'user', None)
        return isinstance(usuario, UsuarioPlataforma) and usuario.activo


class EsAdministradorDePlataforma(EsPersonalDePlataforma):
    """Solo el rol ``administrador``.

    Se comprueba contra la FILA, no contra el claim ``rol`` del token: si a
    alguien se le baja de administrador a soporte, el cambio surte efecto en
    la siguiente petición y no cuando caduque su token.
    """

    message = 'Esta acción es solo para administradores del proveedor.'

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.es_administrador
