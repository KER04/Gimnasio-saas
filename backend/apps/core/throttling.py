"""Límite de intentos de autenticación (Parte A del encargo de seguridad).

Dos throttles independientes, pensados para complementarse:

- ``LoginPorIPThrottle``: limita intentos por dirección IP del cliente.
- ``LoginPorCorreoThrottle``: limita intentos por el correo que se intenta
  autenticar, sin importar desde qué IP llegue.

## Por qué hacen falta LAS DOS, no solo una

Solo por IP no basta: quien ataque rotando de dirección (una botnet, una
IP dinámica, un proxy distinto en cada intento) revienta igual la cuenta de
una víctima concreta -- el límite por IP nunca se entera porque cada intento
"parece" nuevo. Y limitar solo por IP además castiga a inocentes: un
gimnasio entero suele salir a internet por una única IP pública (NAT
compartido de la sede), así que una sola cuenta atacada bloquearía el login
de TODO el personal de esa sede, no solo el de la víctima.

Solo por correo tampoco basta: no frena el "credential stuffing"/rociado
horizontal (probar contraseñas comunes contra MUCHOS correos distintos)
lanzado desde una sola máquina -- cada correo individual se mantendría muy
por debajo de su propio límite aunque la IP esté disparando miles de
intentos por minuto.

Juntas, cada una tapa el hueco de la otra.

## Por qué normalizar el correo es imprescindible

``LoginPorCorreoThrottle`` usa el correo como parte de la clave de caché.
Si no se normalizara, "Admin@X.com" y "admin@x.com" generarían dos claves de
caché DISTINTAS -- es decir, dos cupos de intentos distintos para la MISMA
cuenta (el login real sí es case-insensitive, ver
``uq_usuarios_correo``/``TenantAuthBackend``). Un atacante podría entonces
"resetear" su cupo variando solo las mayúsculas del correo en cada tanda de
intentos, dejando el throttle de correo completamente inútil. Por eso se
aplica ``.strip().lower()`` antes de construir la clave: el cupo es el mismo
sin importar cómo se escriba el correo.
"""
import math

from rest_framework.exceptions import Throttled
from rest_framework.settings import api_settings
from rest_framework.throttling import SimpleRateThrottle


class _RitmoSiempreActualMixin:
    """Lee el ritmo directamente de ``api_settings.DEFAULT_THROTTLE_RATES``
    en cada instancia, en vez de fiarse de ``SimpleRateThrottle.THROTTLE_RATES``.

    Ese atributo de clase se congela en el valor de ``api_settings`` que
    exista en el momento en que Django IMPORTA ``rest_framework.throttling``
    (``THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES`` a nivel de
    clase) -- una sola vez, al arrancar el proceso. ``override_settings`` en
    las pruebas (Parte A5) SÍ actualiza ``api_settings`` correctamente (DRF
    escucha la señal ``setting_changed``), pero esa actualización nunca
    llega a ``THROTTLE_RATES`` porque ya quedó copiado por valor en la clase
    base. Sin este mixin, ningún test con ``override_settings(REST_FRAMEWORK=
    {...})`` podría bajar el ritmo para probar el límite -- se comprobó en
    vivo: los tests fallaban en silencio, dejando pasar de largo cualquier
    número de intentos.
    """

    def get_rate(self):
        return api_settings.DEFAULT_THROTTLE_RATES[self.scope]


class LoginPorIPThrottle(_RitmoSiempreActualMixin, SimpleRateThrottle):
    """Limita los intentos de login por dirección IP del cliente.

    Ritmo genérico (ver ``DEFAULT_THROTTLE_RATES['login_ip']`` en
    settings/base.py): suficiente para un humano equivocándose de
    contraseña un par de veces, inútil para fuerza bruta sostenida.
    """

    scope = 'login_ip'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }


class LoginPorCorreoThrottle(_RitmoSiempreActualMixin, SimpleRateThrottle):
    """Limita los intentos de login por el correo indicado en el cuerpo de
    la petición, normalizado (ver docstring del módulo).

    Si la petición no trae el campo ``correo`` (cuerpo no es JSON, campo
    ausente, vacío...), ``get_cache_key`` devuelve ``None`` -- DRF interpreta
    eso como "este throttle no aplica a esta petición" y no cuenta ni
    bloquea nada. No tiene sentido intentar limitar por un correo que ni
    siquiera se envió; para eso ya está ``LoginPorIPThrottle``.
    """

    scope = 'login_correo'

    def get_cache_key(self, request, view):
        correo = None
        if hasattr(request.data, 'get'):
            correo = request.data.get('correo')

        if not correo:
            return None

        # Normalización imprescindible: ver docstring del módulo.
        correo_normalizado = correo.strip().lower()
        if not correo_normalizado:
            return None

        return self.cache_format % {
            'scope': self.scope,
            'ident': correo_normalizado,
        }


class MensajeThrottleEnEspanolMixin:
    """Traduce el mensaje del 429 al español (Parte A4 del encargo).

    DRF, cuando un throttle rechaza la petición, responde 429 con un cuerpo
    en inglés fijo: "Request was throttled. Expected available in N
    seconds." (``rest_framework.exceptions.Throttled.default_detail``). Ese
    texto en inglés llegaría literal a la pantalla de login.

    Se elige sobrescribir ``APIView.throttled()`` (vía este mixin, reutilizado
    en las tres vistas de autenticación) en vez de un manejador de excepciones
    (``EXCEPTION_HANDLER``) global por dos razones:

    1. El mensaje en español solo tiene sentido para ESTAS vistas de
       autenticación -- un ``EXCEPTION_HANDLER`` global tendría que volver a
       mirar qué vista lanzó el 429 para no traducir, por ejemplo, un futuro
       throttle de otro módulo que sí deba responder distinto. Sobrescribir
       ``throttled()`` acota el cambio exactamente a donde se necesita.
    2. ``throttled()`` ya recibe ``wait`` (segundos hasta el próximo intento
       permitido, calculado por el throttle) sin tener que volver a
       inspeccionar la excepción original: es el punto más simple y menos
       propenso a errores para construir el mensaje.

    Nota sobre ``Throttled.__init__``: si se le pasan ``detail`` Y ``wait``
    a la vez, la propia clase de DRF CONCATENA al detalle un sufijo fijo en
    inglés ("Expected available in N seconds") -- no hay forma de evitarlo
    pasando ambos argumentos al constructor. Por eso aquí se construye la
    excepción SOLO con ``detail`` (sin ``wait``) y se fija ``.wait`` a mano
    después: ese atributo es el que ``APIView`` lee para la cabecera
    ``Retry-After``, y fijarlo así no dispara la concatenación.
    """

    def throttled(self, request, wait):
        if wait is not None:
            segundos = math.ceil(wait)
            detalle = (
                f'Demasiados intentos. Vuelve a intentarlo en {segundos} '
                f'segundo{"s" if segundos != 1 else ""}.'
            )
        else:
            detalle = 'Demasiados intentos. Vuelve a intentarlo más tarde.'
        excepcion = Throttled(detail=detalle)
        excepcion.wait = wait
        raise excepcion
