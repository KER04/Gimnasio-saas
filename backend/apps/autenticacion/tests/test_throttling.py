"""Batería del límite de intentos de autenticación (Parte A5 del encargo).

Reutiliza ``_crear_tenant_con_usuario`` y ``PASSWORD`` de ``test_auth.py``
para no duplicar el sembrado de tenant + usuario con contraseña real.

Cada prueba fija ritmos bajos con ``override_settings`` (sobre una copia del
diccionario ``REST_FRAMEWORK`` real, para no perder el resto de la
configuración de DRF -- paginación, autenticación...) y limpia el caché
ANTES de correr, para que el contador de una prueba no contamine la
siguiente (los throttles de DRF viven en el caché por defecto, que no se
resetea solo entre métodos de prueba).
"""
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings

from .test_auth import PASSWORD, _cabecera_token, _crear_tenant_con_usuario

_ALLOWED_HOSTS_PRUEBA = ['testserver', '.testserver']


def _rates(login_ip='20/min', login_correo='5/min'):
    """Copia de REST_FRAMEWORK con ritmos de throttle sobrescritos, para
    usar con @override_settings(REST_FRAMEWORK=_rates(...))."""
    return {
        **settings.REST_FRAMEWORK,
        'DEFAULT_THROTTLE_RATES': {
            'login_ip': login_ip,
            'login_correo': login_correo,
        },
    }


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ThrottlingLoginTestCase(TestCase):
    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.rol, cls.usuario = _crear_tenant_con_usuario(
            'throttle', 'THR', 'usuario.throttle@example.com',
        )

    def setUp(self):
        # Imprescindible: sin esto, el contador de intentos de una prueba
        # (guardado en el caché por defecto, LocMemCache en pruebas) seguiría
        # vigente para la siguiente y la contaminaría.
        cache.clear()

    def _login(self, correo='usuario.throttle@example.com', password='lo-que-sea', **extra):
        return self.client.post(
            '/api/auth/login/',
            data={'correo': correo, 'password': password},
            content_type='application/json',
            HTTP_HOST='throttle.testserver',
            **extra,
        )

    @override_settings(REST_FRAMEWORK=_rates(login_ip='2/min', login_correo='1000/min'))
    def test_superar_limite_por_ip_da_429(self):
        """Tres intentos con correos DISTINTOS (para no disparar el throttle
        de correo, prácticamente inutilizado aquí) pero desde la MISMA IP:
        los dos primeros consumen el cupo de IP (2/min), el tercero debe
        recibir 429."""
        r1 = self._login(correo='correo-uno@example.com')
        r2 = self._login(correo='correo-dos@example.com')
        r3 = self._login(correo='correo-tres@example.com')

        self.assertNotEqual(r1.status_code, 429, r1.content)
        self.assertNotEqual(r2.status_code, 429, r2.content)
        self.assertEqual(r3.status_code, 429, r3.content)

    @override_settings(REST_FRAMEWORK=_rates(login_ip='1000/min', login_correo='2/min'))
    def test_superar_limite_por_correo_da_429_aunque_cambie_la_ip(self):
        """Mismo correo, IP distinta en cada intento: el throttle de IP
        (1000/min) nunca se dispara, pero el de correo (2/min) sí debe
        bloquear el tercer intento."""
        correo = 'victima@example.com'
        r1 = self._login(correo=correo, REMOTE_ADDR='10.0.0.1')
        r2 = self._login(correo=correo, REMOTE_ADDR='10.0.0.2')
        r3 = self._login(correo=correo, REMOTE_ADDR='10.0.0.3')

        self.assertNotEqual(r1.status_code, 429, r1.content)
        self.assertNotEqual(r2.status_code, 429, r2.content)
        self.assertEqual(r3.status_code, 429, r3.content)

    @override_settings(REST_FRAMEWORK=_rates(login_ip='1000/min', login_correo='1/min'))
    def test_variar_mayusculas_del_correo_no_da_cupo_nuevo(self):
        """'Admin@X.com' y 'admin@x.com' deben contar como el MISMO correo
        para el throttle (normalización obligatoria): con un límite de
        1/min, el primer intento consume el único cupo y el segundo -- con
        mayúsculas distintas -- debe seguir bloqueado, no recibir un cupo
        nuevo."""
        r1 = self._login(correo='Admin@X.com')
        r2 = self._login(correo='ADMIN@x.COM')

        self.assertNotEqual(r1.status_code, 429, r1.content)
        self.assertEqual(r2.status_code, 429, r2.content)

    @override_settings(REST_FRAMEWORK=_rates(login_ip='20/min', login_correo='5/min'))
    def test_login_correcto_dentro_del_limite_sigue_funcionando(self):
        """Dentro de un límite razonable, un login válido sigue dando 200 (no
        429) y uno con contraseña incorrecta sigue dando 401 (no 429)."""
        correcto = self._login(correo='usuario.throttle@example.com', password=PASSWORD)
        self.assertEqual(correcto.status_code, 200, correcto.content)

        cache.clear()
        incorrecto = self._login(
            correo='usuario.throttle@example.com', password='password-mala',
        )
        self.assertEqual(incorrecto.status_code, 401, incorrecto.content)

    @override_settings(REST_FRAMEWORK=_rates(login_ip='1/min', login_correo='1000/min'))
    def test_mensaje_del_429_esta_en_espanol(self):
        r1 = self._login(correo='primero@example.com')
        self.assertNotEqual(r1.status_code, 429, r1.content)

        r2 = self._login(correo='segundo@example.com')
        self.assertEqual(r2.status_code, 429, r2.content)
        detalle = r2.json()['detail']
        self.assertIn('Demasiados intentos', detalle)
        self.assertIn('segundo', detalle)  # "segundos" o "1 segundo"
        # Ninguna huella del mensaje original de DRF en inglés.
        self.assertNotIn('throttled', detalle.lower())


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ThrottlingRegisterTestCase(TestCase):
    """RegisterView solo lleva throttle de IP (Parte A3)."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        # `config.usuarios`: desde que register dejó de ser AllowAny, DRF
        # comprueba los permisos ANTES que el throttle. Sin el permiso, las
        # tres llamadas se quedarían en 403 y el contador de peticiones ni
        # se incrementaría: la prueba no llegaría a ejercitar el throttle.
        cls.tenant, cls.rol, cls.admin = _crear_tenant_con_usuario(
            'throttlereg', 'THRREG', 'ya-existe.throttlereg@example.com',
            permisos=('config.usuarios',),
        )

    def setUp(self):
        cache.clear()

    def _register(self, correo, **extra):
        return self.client.post(
            '/api/auth/register/',
            data={
                'correo': correo,
                'nombre': 'Nuevo Usuario',
                'password': PASSWORD,
                'rol': self.rol.id,
            },
            content_type='application/json',
            HTTP_HOST='throttlereg.testserver',
            **_cabecera_token(self.admin),
            **extra,
        )

    @override_settings(REST_FRAMEWORK=_rates(login_ip='2/min', login_correo='1000/min'))
    def test_superar_limite_por_ip_en_registro_da_429(self):
        r1 = self._register('nuevo-uno@example.com')
        r2 = self._register('nuevo-dos@example.com')
        r3 = self._register('nuevo-tres@example.com')

        self.assertNotEqual(r1.status_code, 429, r1.content)
        self.assertNotEqual(r2.status_code, 429, r2.content)
        self.assertEqual(r3.status_code, 429, r3.content)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ThrottlingRefreshTestCase(TestCase):
    """RefreshView solo lleva throttle de IP (Parte A3)."""

    databases = {'default', 'ddl'}

    def setUp(self):
        cache.clear()

    def _refresh(self, **extra):
        return self.client.post(
            '/api/auth/refresh/',
            data={'refresh': 'token-invalido-de-prueba'},
            content_type='application/json',
            HTTP_HOST='testserver',
            **extra,
        )

    @override_settings(REST_FRAMEWORK=_rates(login_ip='2/min', login_correo='1000/min'))
    def test_superar_limite_por_ip_en_refresh_da_429(self):
        r1 = self._refresh()
        r2 = self._refresh()
        r3 = self._refresh()

        self.assertNotEqual(r1.status_code, 429, r1.content)
        self.assertNotEqual(r2.status_code, 429, r2.content)
        self.assertEqual(r3.status_code, 429, r3.content)
