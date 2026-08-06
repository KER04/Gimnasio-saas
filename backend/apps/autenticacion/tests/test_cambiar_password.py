"""Cambio de la contraseña propia (``/api/auth/cambiar-password/``).

Lo importante aquí no es que la contraseña cambie, sino las dos garantías
que la rodean: que no baste con tener la sesión abierta para cambiarla, y
que cambiarla eche de verdad a quien estuviera dentro con la anterior.
"""
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.core.tenant import tenant_context

from .test_auth import PASSWORD, _cabecera_token, _crear_tenant_con_usuario

_ALLOWED_HOSTS_PRUEBA = ['testserver', '.testserver']
PASSWORD_NUEVA = 'clave-nueva-muy-segura-456'


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class CambiarPasswordTestCase(TestCase):
    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.tenant, cls.rol, cls.usuario = _crear_tenant_con_usuario(
            'cambiopwd', 'CP', 'usuario@cambiopwd.example.com',
        )

    def setUp(self):
        cache.clear()

    def _cambiar(self, actual, nueva, cabecera=None):
        return self.client.post(
            '/api/auth/cambiar-password/',
            data={'password_actual': actual, 'password_nueva': nueva},
            content_type='application/json',
            HTTP_HOST='cambiopwd.testserver',
            **(cabecera if cabecera is not None else _cabecera_token(self.usuario)),
        )

    def _login(self, password):
        return self.client.post(
            '/api/auth/login/',
            data={'correo': 'usuario@cambiopwd.example.com', 'password': password},
            content_type='application/json',
            HTTP_HOST='cambiopwd.testserver',
        )

    def test_cambia_la_contrasena(self):
        respuesta = self._cambiar(PASSWORD, PASSWORD_NUEVA)

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertEqual(self._login(PASSWORD_NUEVA).status_code, 200)
        self.assertNotEqual(self._login(PASSWORD).status_code, 200)

    def test_devuelve_tokens_nuevos_para_no_echar_a_quien_lo_hizo(self):
        """Se invalidan todas las sesiones, incluida la actual: sin una pareja
        nueva, quien cambia su contraseña se quedaría fuera al instante."""
        cuerpo = self._cambiar(PASSWORD, PASSWORD_NUEVA).json()

        self.assertIn('access', cuerpo)
        self.assertIn('refresh', cuerpo)
        respuesta = self.client.get(
            '/api/auth/me/',
            HTTP_HOST='cambiopwd.testserver',
            HTTP_AUTHORIZATION=f'Bearer {cuerpo["access"]}',
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)

    def test_exige_la_contrasena_actual(self):
        """Tener la sesión abierta NO prueba ser la persona: un navegador
        olvidado en el mostrador no puede bastar para quedarse con la cuenta."""
        respuesta = self._cambiar('la-que-no-es', PASSWORD_NUEVA)

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('password_actual', respuesta.json())
        self.assertEqual(self._login(PASSWORD).status_code, 200)

    def test_aplica_los_validadores_de_django(self):
        respuesta = self._cambiar(PASSWORD, '123')

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('password_nueva', respuesta.json())

    def test_rechaza_repetir_la_misma(self):
        respuesta = self._cambiar(PASSWORD, PASSWORD)

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('password_nueva', respuesta.json())

    def test_cierra_las_demas_sesiones(self):
        """Quien cambia su contraseña suele hacerlo porque cree que alguien
        más la tiene. Si las sesiones abiertas en otros dispositivos
        siguieran vivas, el cambio sería decorativo."""
        otra_sesion = self._login(PASSWORD).json()['refresh']

        self._cambiar(PASSWORD, PASSWORD_NUEVA)

        respuesta = self.client.post(
            '/api/auth/refresh/',
            data={'refresh': otra_sesion},
            content_type='application/json',
            HTTP_HOST='cambiopwd.testserver',
        )
        self.assertNotEqual(respuesta.status_code, 200, respuesta.content)
        self.assertTrue(
            BlacklistedToken.objects.filter(
                token__in=OutstandingToken.objects.filter(user_id=self.usuario.id),
            ).exists(),
        )

    def test_anonimo_no_puede(self):
        respuesta = self.client.post(
            '/api/auth/cambiar-password/',
            data={'password_actual': PASSWORD, 'password_nueva': PASSWORD_NUEVA},
            content_type='application/json',
            HTTP_HOST='cambiopwd.testserver',
        )

        self.assertIn(respuesta.status_code, (401, 403), respuesta.content)

    def test_no_puede_cambiar_la_de_otro_gimnasio(self):
        """El usuario sale del TOKEN, nunca del cuerpo: no hay ningún campo
        que permita apuntar a otra cuenta."""
        otro_tenant, _rol, otro_usuario = _crear_tenant_con_usuario(
            'cambiopwdajeno', 'CPA', 'ajeno@cambiopwd.example.com',
        )

        self._cambiar(PASSWORD, PASSWORD_NUEVA)

        with tenant_context(otro_tenant.id):
            otro_usuario.refresh_from_db()
            self.assertTrue(otro_usuario.check_password(PASSWORD))
