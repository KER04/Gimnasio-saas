"""Pruebas HTTP de TenantMiddleware (Parte C3), con el cliente de pruebas de
Django.

Usan ``override_settings(ROOT_URLCONF='apps.core.tests.urls')`` para poder
inspeccionar ``request.tenant``/``request.tenant_id`` desde una vista mínima
(``ping``) creada solo para esto (ver ``apps/core/tests/urls.py``). La
prueba de ruta exenta, en cambio, golpea el URLconf REAL de la aplicación
(``/api/auth/login/``), para probar la exención tal como la usaría un
cliente de verdad.

``ALLOWED_HOSTS`` se sobreescribe con ``'.testserver'`` porque
``validate_host`` exige que el host de la petición matchee exactamente un
patrón de la lista, y un patrón con punto inicial matchea el dominio y
todos sus subdominios (p. ej. ``.testserver`` matchea tanto ``testserver``
como ``gima.testserver``). Sin esto, Django rechazaría con
``DisallowedHost`` cualquier ``HTTP_HOST`` que no sea exactamente
``testserver`` (el que el test runner añade automáticamente a
ALLOWED_HOSTS por su cuenta).

Todas las clases declaran ``databases = {'default', 'ddl'}``: las dos
conexiones tienen ``ATOMIC_REQUESTS = True`` (ver settings/base.py), así que
Django envuelve CADA vista en una transacción por cada alias con
``ATOMIC_REQUESTS`` activo, no solo 'default'. Sin declarar 'ddl' aquí, el
test runner bloquea cualquier intento de tocar esa conexión con
``DatabaseOperationForbidden``, aunque el código de la prueba nunca la use
explícitamente.

## Por qué cada clase limpia el caché de resolución de tenant

``TenantMiddleware`` cachea subdominio -> Tenant durante 60s (ver
apps/core/middleware.py) usando el caché por defecto de Django
(``LocMemCache``), que vive en el proceso y NO se resetea entre clases de
prueba. Dos clases de esta suite reutilizan el subdominio ``'gima'``; cada
una crea SU PROPIO tenant en ``setUpTestData`` (con un id de fila distinto,
porque la secuencia IDENTITY de PostgreSQL no se reinicia aunque el
ROLLBACK de fin de clase borre la fila). Sin limpiar el caché, la segunda
clase heredaría la entrada cacheada por la primera y resolvería el tenant
EQUIVOCADO (mismo subdominio, id viejo) — se detectó exactamente este fallo
al escribir la prueba, y es la prueba en vivo de por qué la caché necesita
un TTL corto: aquí lo forzamos a cero limpiándolo a mano en vez de esperar
los 60s.
"""
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from .factories import crear_tenant_completo

_ALLOWED_HOSTS_PRUEBA = ['testserver', '.testserver']
_URLCONF_PRUEBA = 'apps.core.tests.urls'


@override_settings(ROOT_URLCONF=_URLCONF_PRUEBA, ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class TenantMiddlewareHostTestCase(TestCase):
    """Resolución de tenant por subdominio del Host."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos_a = crear_tenant_completo('gima', 'A', using='default')
        cls.datos_b = crear_tenant_completo('gimb', 'B', using='default')

    def test_subdominio_a_resuelve_tenant_a(self):
        respuesta = self.client.get('/ping/', HTTP_HOST='gima.testserver')
        self.assertEqual(respuesta.status_code, 200)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['tenant_id'], self.datos_a['tenant'].id)
        self.assertEqual(cuerpo['subdominio'], 'gima')

    def test_subdominio_b_resuelve_tenant_b(self):
        respuesta = self.client.get('/ping/', HTTP_HOST='gimb.testserver')
        self.assertEqual(respuesta.status_code, 200)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['tenant_id'], self.datos_b['tenant'].id)
        self.assertEqual(cuerpo['subdominio'], 'gimb')

    def test_subdominio_inexistente_no_fija_tenant(self):
        """Falla cerrado: un subdominio que no corresponde a ningún Tenant no
        debe fijar nada (ni reventar)."""
        respuesta = self.client.get('/ping/', HTTP_HOST='noexiste.testserver')
        self.assertEqual(respuesta.status_code, 200)
        cuerpo = respuesta.json()
        self.assertIsNone(cuerpo['tenant_id'])
        self.assertIsNone(cuerpo['subdominio'])


@override_settings(ROOT_URLCONF=_URLCONF_PRUEBA, ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class TenantMiddlewareCabeceraDebugTestCase(TestCase):
    """La cabecera X-Tenant solo debe atenderse con DEBUG=True. Con un host
    sin subdominio (bare 'testserver') aislamos la cabecera como único
    mecanismo posible de resolución."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos_a = crear_tenant_completo('gima', 'A', using='default')

    @override_settings(DEBUG=False)
    def test_debug_false_ignora_cabecera_x_tenant(self):
        """Control de seguridad crítico: en producción (DEBUG=False) la
        cabecera X-Tenant se ignora por completo, aunque venga un subdominio
        válido. Si no fuera así, cualquiera podría suplantar el tenant de
        otro gimnasio con solo mandar esta cabecera."""
        respuesta = self.client.get(
            '/ping/', HTTP_HOST='testserver', HTTP_X_TENANT='gima',
        )
        self.assertEqual(respuesta.status_code, 200)
        cuerpo = respuesta.json()
        self.assertIsNone(cuerpo['tenant_id'])
        self.assertIsNone(cuerpo['subdominio'])

    @override_settings(DEBUG=True)
    def test_debug_true_resuelve_cabecera_x_tenant(self):
        """Mismo host y misma cabecera que la prueba anterior: la única
        diferencia es DEBUG=True, y ahora sí debe resolver."""
        respuesta = self.client.get(
            '/ping/', HTTP_HOST='testserver', HTTP_X_TENANT='gima',
        )
        self.assertEqual(respuesta.status_code, 200)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['tenant_id'], self.datos_a['tenant'].id)
        self.assertEqual(cuerpo['subdominio'], 'gima')


class TenantMiddlewareRutaExentaTestCase(TestCase):
    """Rutas exentas: deben funcionar sin ningún tenant resuelto, usando el
    URLconf REAL de la aplicación (config.urls), sin overrides."""

    databases = {'default', 'ddl'}

    def test_login_funciona_sin_tenant(self):
        cliente = Client()
        respuesta = cliente.post(
            '/api/auth/login/',
            data={'correo': 'no-existe@example.com', 'password': 'lo-que-sea'},
            content_type='application/json',
        )
        # No nos interesa si las credenciales son válidas (no lo son), sino
        # que la petición se procesó sin exigir tenant: ni 500, ni un 4xx
        # relacionado con falta de tenant.
        self.assertIn(respuesta.status_code, (400, 401))
