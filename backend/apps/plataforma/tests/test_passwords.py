"""Contraseñas en el panel del proveedor.

Dos operaciones distintas y con riesgos distintos:

* cambiar la PROPIA, que exige la actual;
* restablecer la de un usuario de un gimnasio, que es un rescate de soporte
  y por tanto queda registrado en auditoría.
"""
import json

from django.core.cache import cache
from django.db import connections
from django.test import TestCase, override_settings

from apps.core.tenant import tenant_context
from apps.organizacion.models import Usuario
from apps.plataforma.models import Tenant, UsuarioPlataforma

from .test_panel import PASSWORD_PANEL, _crear_cuenta_panel

_ALLOWED_HOSTS_PRUEBA = ['testserver', '.testserver']
PASSWORD_NUEVA = 'clave-nueva-del-panel-77'


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class CambiarPasswordPropiaTestCase(TestCase):
    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.cuenta = _crear_cuenta_panel('pwd.propia@proveedor.example.com')

    def setUp(self):
        cache.clear()

    def _login(self, password=PASSWORD_PANEL):
        return self.client.post(
            '/api/plataforma/login/',
            data={'correo': 'pwd.propia@proveedor.example.com', 'password': password},
            content_type='application/json',
        )

    def _cambiar(self, actual, nueva, acceso):
        return self.client.post(
            '/api/plataforma/cambiar-password/',
            data={'password_actual': actual, 'password_nueva': nueva},
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {acceso}',
        )

    def test_cambia_la_contrasena(self):
        tokens = self._login().json()

        respuesta = self._cambiar(PASSWORD_PANEL, PASSWORD_NUEVA, tokens['access'])

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertEqual(self._login(PASSWORD_NUEVA).status_code, 200)
        self.assertEqual(self._login(PASSWORD_PANEL).status_code, 401)

    def test_exige_la_contrasena_actual(self):
        tokens = self._login().json()

        respuesta = self._cambiar('la-que-no-es', PASSWORD_NUEVA, tokens['access'])

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('password_actual', respuesta.json())

    def test_los_tokens_anteriores_dejan_de_valer(self):
        """Los tokens del panel no pasan por ``token_blacklist`` (se
        construyen a mano para no llevar el claim ``user_id``), así que la
        invalidación va por otra vía: llevan una huella del hash de la
        contraseña que deja de coincidir en cuanto esta cambia."""
        tokens = self._login().json()

        self._cambiar(PASSWORD_PANEL, PASSWORD_NUEVA, tokens['access'])

        viejo = self.client.get(
            '/api/plataforma/me/', HTTP_AUTHORIZATION=f'Bearer {tokens["access"]}',
        )
        self.assertEqual(viejo.status_code, 401, viejo.content)

        refresco = self.client.post(
            '/api/plataforma/refresh/',
            data={'refresh': tokens['refresh']},
            content_type='application/json',
        )
        self.assertEqual(refresco.status_code, 401, refresco.content)

    def test_devuelve_tokens_nuevos_para_no_echar_a_quien_lo_hizo(self):
        tokens = self._login().json()

        cuerpo = self._cambiar(PASSWORD_PANEL, PASSWORD_NUEVA, tokens['access']).json()

        respuesta = self.client.get(
            '/api/plataforma/me/', HTTP_AUTHORIZATION=f'Bearer {cuerpo["access"]}',
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)

    def test_aplica_los_validadores_de_django(self):
        tokens = self._login().json()

        respuesta = self._cambiar(PASSWORD_PANEL, '123', tokens['access'])

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('password_nueva', respuesta.json())


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class RestablecerPasswordDeGimnasioTestCase(TestCase):
    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.admin = _crear_cuenta_panel('pwd.reset@proveedor.example.com')
        cls.soporte = _crear_cuenta_panel(
            'pwd.soporte@proveedor.example.com', UsuarioPlataforma.RolPlataforma.SOPORTE,
        )

    def setUp(self):
        cache.clear()
        respuesta = self.client.post(
            '/api/plataforma/tenants/',
            data={
                'nombre_comercial': 'Gimnasio Reset',
                'subdominio': 'resetuno',
                'correo_admin': 'duenio@reset.example.com',
            },
            content_type='application/json', **self._como('pwd.reset@proveedor.example.com'),
        )
        self.uuid = respuesta.json()['uuid_publico']
        self.acceso_original = respuesta.json()['acceso_inicial']
        self.tenant = Tenant.objects.get(uuid_publico=self.uuid)
        with tenant_context(self.tenant.id):
            self.usuario = Usuario.objects.get(tenant=self.tenant)

    def _como(self, correo):
        respuesta = self.client.post(
            '/api/plataforma/login/',
            data={'correo': correo, 'password': PASSWORD_PANEL},
            content_type='application/json',
        )
        return {'HTTP_AUTHORIZATION': f'Bearer {respuesta.json()["access"]}'}

    def _restablecer(self, usuario_id, correo='pwd.reset@proveedor.example.com'):
        return self.client.post(
            f'/api/plataforma/tenants/{self.uuid}/restablecer-password/',
            data={'usuario_id': usuario_id},
            content_type='application/json', **self._como(correo),
        )

    def test_lista_los_usuarios_del_gimnasio(self):
        """Hace falta para saber a QUIÉN se le restablece: elegir "el primer
        administrador" convertiría una operación delicada en una lotería."""
        respuesta = self.client.get(
            f'/api/plataforma/tenants/{self.uuid}/usuarios/',
            **self._como('pwd.reset@proveedor.example.com'),
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        correos = [u['correo'] for u in respuesta.json()]
        self.assertIn('duenio@reset.example.com', correos)

    def test_la_contrasena_nueva_funciona_y_la_vieja_no(self):
        respuesta = self._restablecer(self.usuario.id)

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        nueva = respuesta.json()['password']

        entra = self.client.post(
            '/api/auth/login/',
            data={'correo': 'duenio@reset.example.com', 'password': nueva},
            content_type='application/json', HTTP_HOST='resetuno.testserver',
        )
        self.assertEqual(entra.status_code, 200, entra.content)

        vieja = self.client.post(
            '/api/auth/login/',
            data={'correo': 'duenio@reset.example.com', 'password': self.acceso_original['password']},
            content_type='application/json', HTTP_HOST='resetuno.testserver',
        )
        self.assertNotEqual(vieja.status_code, 200)

    def test_queda_registrado_en_auditoria_como_accion_del_proveedor(self):
        """Entregar el acceso a la cuenta de un cliente no puede ser
        invisible. La columna `usuario_plataforma_id` distingue esto de un
        cambio hecho por el propio gimnasio."""
        self._restablecer(self.usuario.id)

        with tenant_context(self.tenant.id):
            with connections['default'].cursor() as cursor:
                cursor.execute(
                    """
                    SELECT usuario_plataforma_id, usuario_id, valor_nuevo
                    FROM auditoria
                    WHERE tenant_id = %s AND entidad = 'usuarios'
                    ORDER BY fecha_hora DESC LIMIT 1
                    """,
                    [self.tenant.id],
                )
                fila = cursor.fetchone()

        self.assertIsNotNone(fila, 'El restablecimiento no dejó traza en auditoría.')
        self.assertEqual(fila[0], self.admin.id)
        self.assertEqual(fila[1], self.usuario.id)
        # El cursor en crudo devuelve el jsonb como texto, no como dict.
        valor_nuevo = json.loads(fila[2]) if isinstance(fila[2], str) else fila[2]
        self.assertTrue(valor_nuevo['password_restablecida_por_soporte'])

    def test_la_traza_nunca_guarda_la_contrasena(self):
        respuesta = self._restablecer(self.usuario.id)
        nueva = respuesta.json()['password']

        with tenant_context(self.tenant.id):
            with connections['default'].cursor() as cursor:
                cursor.execute(
                    "SELECT valor_nuevo::text FROM auditoria WHERE tenant_id = %s AND entidad = 'usuarios'",
                    [self.tenant.id],
                )
                trazas = [fila[0] for fila in cursor.fetchall()]

        for traza in trazas:
            self.assertNotIn(nueva, traza)

    def test_no_se_puede_restablecer_a_un_usuario_de_otro_gimnasio(self):
        """RLS ya lo esconde; la vista solo lo traduce a un 404 legible."""
        otro = self.client.post(
            '/api/plataforma/tenants/',
            data={
                'nombre_comercial': 'Gimnasio Ajeno Reset',
                'subdominio': 'resetajeno',
                'correo_admin': 'duenio@resetajeno.example.com',
            },
            content_type='application/json', **self._como('pwd.reset@proveedor.example.com'),
        )

        tenant_ajeno = Tenant.objects.get(uuid_publico=otro.json()['uuid_publico'])
        with tenant_context(tenant_ajeno.id):
            usuario_ajeno = Usuario.objects.get(tenant=tenant_ajeno)

        respuesta = self._restablecer(usuario_ajeno.id)

        self.assertEqual(respuesta.status_code, 404, respuesta.content)
        entra = self.client.post(
            '/api/auth/login/',
            data={
                'correo': 'duenio@resetajeno.example.com',
                'password': otro.json()['acceso_inicial']['password'],
            },
            content_type='application/json', HTTP_HOST='resetajeno.testserver',
        )
        self.assertEqual(entra.status_code, 200, 'Se cambió la contraseña de un gimnasio ajeno.')

    def test_soporte_no_puede_restablecer(self):
        respuesta = self._restablecer(self.usuario.id, 'pwd.soporte@proveedor.example.com')

        self.assertEqual(respuesta.status_code, 403, respuesta.content)

    def test_soporte_si_puede_ver_los_usuarios(self):
        respuesta = self.client.get(
            f'/api/plataforma/tenants/{self.uuid}/usuarios/',
            **self._como('pwd.soporte@proveedor.example.com'),
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
