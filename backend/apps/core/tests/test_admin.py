"""Pruebas del admin de Django sirviendo peticiones multi-tenant (Parte C).

## Por qué `self.client.login(..., tenant_id=...)`

``django.test.Client.login(**credentials)`` llama a
``django.contrib.auth.authenticate(**credentials)`` SIN pasar ningún
``request`` (``request=None`` internamente). ``TenantAuthBackend.authenticate``
cae entonces a ``request.tenant_id`` -- que no existe porque no hay
request -- así que hay que pasar ``tenant_id`` explícito como credencial
extra; el propio backend ya lo acepta como parámetro opcional (ver
``apps/autenticacion/backends.py``). Las peticiones POSTERIORES (las que sí
golpean rutas del admin) no necesitan ese ``tenant_id`` explícito:
``TenantMiddleware`` lo resuelve solo, por sesión (Parte C1) -- que es
precisamente lo que esta suite verifica.

``databases = {'default', 'ddl'}`` en ambas clases: la resolución de tenant
por sesión (``TenantAuthBackend.get_user``) hace un vistazo por 'ddl' antes
de reconsultar por 'default' (ver el docstring de ese método), y las dos
conexiones tienen ``ATOMIC_REQUESTS = True``.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.core.tenant import tenant_context

from .factories import crear_tenant_completo

Usuario = get_user_model()

_ALLOWED_HOSTS_PRUEBA = ['testserver', '.testserver']
PASSWORD = 'clave-admin-super-segura-123'


def _crear_usuario_staff(tenant, rol, sufijo, es_superusuario=True):
    """Usuario NUEVO (no el `usuario` sembrado por `crear_tenant_completo`,
    que guarda un password sin hashear -- inútil para un login real) con
    contraseña real y `es_staff=True`."""
    with tenant_context(tenant.id, using='default'):
        usuario = Usuario.objects.create_user(
            correo=f'staff.{sufijo}@example.com', nombre=f'Staff {sufijo}',
            tenant=tenant, rol=rol, password=PASSWORD,
        )
        usuario.es_staff = True
        usuario.es_superusuario = es_superusuario
        usuario.save(using='default')
    return usuario


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class AdminAislamientoTestCase(TestCase):
    """LA PRUEBA CENTRAL de la Parte C1: un usuario `es_staff` del tenant A,
    logueado por SESIÓN (no JWT) en el admin, ve en el listado de clientes
    SOLO los de A -- nunca los de B. Es la prueba que justifica haber
    quitado '/admin/' de TENANT_EXEMPT_PATHS."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos_a = crear_tenant_completo('admina', 'A', using='default')
        cls.datos_b = crear_tenant_completo('adminb', 'B', using='default')
        cls.staff_a = _crear_usuario_staff(cls.datos_a['tenant'], cls.datos_a['rol'], 'A')

    def _login_staff_a(self):
        logueado = self.client.login(
            correo=self.staff_a.correo, password=PASSWORD, tenant_id=self.datos_a['tenant'].id,
        )
        self.assertTrue(logueado, 'El login de prueba (admin de A) debió funcionar.')

    def test_admin_de_a_ve_solo_clientes_de_a_en_el_listado(self):
        self._login_staff_a()

        respuesta = self.client.get('/admin/clientes/cliente/', HTTP_HOST='admina.testserver')
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        contenido = respuesta.content.decode()
        self.assertIn(self.datos_a['cliente'].cedula, contenido)
        self.assertNotIn(self.datos_b['cliente'].cedula, contenido)

    def test_admin_de_a_no_accede_a_la_ficha_de_un_cliente_de_b(self):
        """Control más estricto que el listado: RLS + FORCE bloquea el
        SELECT incluso pidiendo el id de B directamente. `ModelAdmin` (no
        Http404) trata esto como "objeto no encontrado" y redirige al
        índice del admin con un aviso -- el comportamiento estándar de
        Django ante un id inexistente, aquí disparado por RLS en vez de por
        una fila borrada de verdad. Lo que importa es que NUNCA llegan los
        datos de B ni un 500."""
        self._login_staff_a()

        respuesta = self.client.get(
            f"/admin/clientes/cliente/{self.datos_b['cliente'].id}/change/",
            HTTP_HOST='admina.testserver',
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertNotIn('/admin/login/', respuesta.url)
        self.assertEqual(respuesta.url, '/admin/')

    def test_admin_de_a_no_ve_clientes_de_b_aunque_entre_por_el_host_de_b(self):
        """La sesión, no el subdominio de la petición, es la que manda para
        un usuario ya autenticado (orden de resolución C1: sesión antes que
        subdominio). Si el navegador de A visitara por error el host de B
        con la MISMA sesión (algo que en la práctica no ocurre: las cookies
        de sesión son por host, ver el reporte), seguiría viendo A, nunca
        B."""
        self._login_staff_a()

        respuesta = self.client.get('/admin/clientes/cliente/', HTTP_HOST='adminb.testserver')
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        contenido = respuesta.content.decode()
        self.assertIn(self.datos_a['cliente'].cedula, contenido)
        self.assertNotIn(self.datos_b['cliente'].cedula, contenido)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class AdminEsStaffFalseTestCase(TestCase):
    """Un usuario `es_staff=False` (el caso normal de cualquier usuario de
    tenant que no sea el administrador sembrado por `crear_tenant`) no puede
    entrar al admin, aunque sus credenciales sean correctas."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos = crear_tenant_completo('noadmin', 'N', using='default')
        with tenant_context(cls.datos['tenant'].id, using='default'):
            cls.usuario_normal = Usuario.objects.create_user(
                correo='normal@example.com', nombre='Usuario normal',
                tenant=cls.datos['tenant'], rol=cls.datos['rol'], password=PASSWORD,
            )

    def test_login_correcto_pero_admin_redirige_a_login(self):
        # authenticate() SÍ resuelve al usuario (existe, password correcta):
        # el rechazo lo impone el admin (AdminSite.has_permission exige
        # is_active AND is_staff), no el backend de autenticación.
        logueado = self.client.login(
            correo=self.usuario_normal.correo, password=PASSWORD, tenant_id=self.datos['tenant'].id,
        )
        self.assertTrue(logueado)
        self.assertFalse(self.usuario_normal.es_staff)

        respuesta = self.client.get('/admin/', HTTP_HOST='noadmin.testserver')
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/admin/login/', respuesta.url)

    def test_login_con_password_incorrecta_falla(self):
        logueado = self.client.login(
            correo=self.usuario_normal.correo, password='password-equivocada',
            tenant_id=self.datos['tenant'].id,
        )
        self.assertFalse(logueado)
