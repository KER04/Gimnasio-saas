"""Panel del proveedor: identidad propia y listado de gimnasios.

Lo que más importa aquí no es que el panel funcione, sino que las DOS
identidades del sistema no se toquen. Un token de gimnasio que abriera el
panel daría a un recepcionista cualquiera la vista de toda la cartera de
clientes; un token de panel que valiera en la API de un gimnasio se saltaría
el aislamiento por tenant. Ambos sentidos están cubiertos abajo.
"""
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.core.tenant import tenant_context
from apps.organizacion.models import Rol, Usuario
from apps.plataforma.models import Tenant, UsuarioPlataforma

_ALLOWED_HOSTS_PRUEBA = ['testserver', '.testserver']
PASSWORD_PANEL = 'contrasena-del-panel-1'


def _crear_gimnasio(subdominio, sufijo):
    """Un tenant con un usuario de gimnasio, para los tests de aislamiento."""
    tenant = Tenant.objects.using('default').create(
        nombre_comercial=f'Gimnasio {sufijo}',
        subdominio=subdominio,
        responsable=f'Responsable {sufijo}',
        correo=f'contacto.{subdominio}@example.com',
    )
    with tenant_context(tenant.id):
        rol = Rol.objects.using('default').create(
            tenant=tenant, nombre=f'Administrador {sufijo}', es_sistema=True,
        )
        usuario = Usuario.objects.create_user(
            correo=f'admin.{subdominio}@example.com', nombre=f'Admin {sufijo}',
            tenant=tenant, rol=rol, password='clave-de-gimnasio-123',
        )
    return tenant, usuario


def _crear_cuenta_panel(correo, rol=UsuarioPlataforma.RolPlataforma.ADMINISTRADOR):
    cuenta = UsuarioPlataforma(nombre='Empleado del proveedor', correo=correo, rol=rol)
    cuenta.set_password(PASSWORD_PANEL)
    cuenta.save()
    return cuenta


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class LoginPanelTestCase(TestCase):
    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.cuenta = _crear_cuenta_panel('admin.panel@proveedor.example.com')

    def _login(self, correo, password):
        return self.client.post(
            '/api/plataforma/login/',
            data={'correo': correo, 'password': password},
            content_type='application/json',
        )

    def test_login_correcto_devuelve_tokens_y_la_cuenta(self):
        respuesta = self._login('admin.panel@proveedor.example.com', PASSWORD_PANEL)

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        cuerpo = respuesta.json()
        self.assertIn('access', cuerpo)
        self.assertIn('refresh', cuerpo)
        self.assertEqual(cuerpo['usuario']['correo'], 'admin.panel@proveedor.example.com')

    def test_el_correo_no_distingue_mayusculas(self):
        """``correo`` es CITEXT y único sin distinguir mayúsculas: si el login
        sí distinguiera, la misma cuenta entraría o no según cómo se teclee."""
        respuesta = self._login('ADMIN.PANEL@Proveedor.Example.Com', PASSWORD_PANEL)
        self.assertEqual(respuesta.status_code, 200, respuesta.content)

    def test_nunca_devuelve_el_hash_de_la_contrasena(self):
        cuerpo = self._login('admin.panel@proveedor.example.com', PASSWORD_PANEL).json()
        self.assertNotIn('password_hash', cuerpo['usuario'])
        self.assertNotIn('password', cuerpo['usuario'])

    def test_contrasena_incorrecta_da_401(self):
        self.assertEqual(self._login('admin.panel@proveedor.example.com', 'otra').status_code, 401)

    def test_cuenta_inexistente_da_el_mismo_error_que_la_contrasena_mala(self):
        """Mensajes idénticos a propósito: distinguirlos permitiría averiguar
        qué correos son cuentas del proveedor probando uno a uno."""
        inexistente = self._login('nadie@proveedor.example.com', PASSWORD_PANEL)
        mala = self._login('admin.panel@proveedor.example.com', 'otra')

        self.assertEqual(inexistente.status_code, 401)
        self.assertEqual(inexistente.json()['detail'], mala.json()['detail'])

    def test_cuenta_desactivada_no_entra(self):
        cuenta = _crear_cuenta_panel('baja@proveedor.example.com')
        cuenta.activo = False
        cuenta.save(update_fields=['activo'])

        self.assertEqual(self._login('baja@proveedor.example.com', PASSWORD_PANEL).status_code, 401)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class AislamientoDeIdentidadesTestCase(TestCase):
    """Las dos identidades del sistema no deben poder cruzarse NUNCA."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.cuenta = _crear_cuenta_panel('aislamiento@proveedor.example.com')
        cls.tenant, cls.usuario_gimnasio = _crear_gimnasio('aislapanel', 'AP')

    def _token_panel(self):
        respuesta = self.client.post(
            '/api/plataforma/login/',
            data={'correo': 'aislamiento@proveedor.example.com', 'password': PASSWORD_PANEL},
            content_type='application/json',
        )
        return respuesta.json()['access']

    def test_sin_token_el_panel_responde_401(self):
        self.assertEqual(self.client.get('/api/plataforma/tenants/').status_code, 401)

    def test_un_token_de_gimnasio_no_abre_el_panel(self):
        """EL CASO QUE MÁS IMPORTA.

        Los ids de `usuarios` y de `usuarios_plataforma` son secuencias
        independientes: el usuario 3 de un gimnasio y el empleado 3 del
        proveedor existen a la vez. Si el panel autenticara por `user_id`,
        el token de cualquier recepcionista abriría la cartera entera.
        """
        token = AccessToken.for_user(self.usuario_gimnasio)
        token['tenant_id'] = self.tenant.id

        respuesta = self.client.get(
            '/api/plataforma/tenants/', HTTP_AUTHORIZATION=f'Bearer {token}',
        )

        self.assertEqual(respuesta.status_code, 401, respuesta.content)

    def test_un_token_del_panel_no_vale_en_la_api_del_gimnasio(self):
        """El sentido contrario: el token del panel no lleva `user_id`, así
        que `JWTAuthentication` de SimpleJWT no resuelve ningún usuario."""
        respuesta = self.client.get(
            '/api/clientes/',
            HTTP_AUTHORIZATION=f'Bearer {self._token_panel()}',
            HTTP_HOST='aislapanel.testserver',
        )

        self.assertEqual(respuesta.status_code, 401, respuesta.content)

    def test_desactivar_la_cuenta_invalida_el_token_ya_emitido(self):
        """El permiso se comprueba contra la FILA, no contra el token: dar de
        baja a alguien tiene que surtir efecto sin esperar a que caduque."""
        token = self._token_panel()
        cabecera = {'HTTP_AUTHORIZATION': f'Bearer {token}'}
        self.assertEqual(self.client.get('/api/plataforma/me/', **cabecera).status_code, 200)

        self.cuenta.activo = False
        self.cuenta.save(update_fields=['activo'])

        self.assertEqual(self.client.get('/api/plataforma/me/', **cabecera).status_code, 401)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ListadoDeTenantsTestCase(TestCase):
    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.cuenta = _crear_cuenta_panel('listado@proveedor.example.com')
        cls.tenant_uno, cls.usuario_uno = _crear_gimnasio('panelnorte', 'Norte')
        cls.tenant_dos, cls.usuario_dos = _crear_gimnasio('panelsur', 'Sur')

    def _cabecera(self):
        respuesta = self.client.post(
            '/api/plataforma/login/',
            data={'correo': 'listado@proveedor.example.com', 'password': PASSWORD_PANEL},
            content_type='application/json',
        )
        return {'HTTP_AUTHORIZATION': f'Bearer {respuesta.json()["access"]}'}

    def test_ve_todos_los_gimnasios(self):
        """Lo contrario que el resto de la API: aquí NO hay aislamiento por
        tenant, y ese es justamente el propósito del panel."""
        respuesta = self.client.get('/api/plataforma/tenants/', **self._cabecera())

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        subdominios = {t['subdominio'] for t in respuesta.json()['results']}
        self.assertIn('panelnorte', subdominios)
        self.assertIn('panelsur', subdominios)

    def test_no_expone_el_id_interno_del_tenant(self):
        """Se identifica por ``uuid_publico``: la columna existe para que las
        URLs no dejen enumerar la cartera contando 1, 2, 3."""
        filas = self.client.get('/api/plataforma/tenants/', **self._cabecera()).json()['results']

        for fila in filas:
            self.assertNotIn('id', fila)
            self.assertIn('uuid_publico', fila)

    def test_los_recuentos_atraviesan_rls(self):
        """La petición no tiene tenant fijado, así que una consulta normal a
        `usuarios` devolvería cero. Los recuentos salen de la vista, que se
        salta RLS a propósito."""
        filas = self.client.get('/api/plataforma/tenants/', **self._cabecera()).json()['results']
        por_subdominio = {t['subdominio']: t for t in filas}

        self.assertEqual(por_subdominio['panelnorte']['usuarios'], 1)
        self.assertEqual(por_subdominio['panelnorte']['clientes'], 0)
        self.assertEqual(por_subdominio['panelnorte']['membresias_activas'], 0)

    def test_filtra_por_estado(self):
        self.tenant_dos.estado = Tenant.EstadoTenant.SUSPENDIDO
        self.tenant_dos.save(update_fields=['estado'])

        respuesta = self.client.get(
            '/api/plataforma/tenants/', {'estado': 'suspendido'}, **self._cabecera(),
        )

        subdominios = {t['subdominio'] for t in respuesta.json()['results']}
        self.assertEqual(subdominios, {'panelsur'})

    def test_busca_palabra_a_palabra(self):
        respuesta = self.client.get(
            '/api/plataforma/tenants/', {'buscar': 'gimnasio norte'}, **self._cabecera(),
        )

        subdominios = {t['subdominio'] for t in respuesta.json()['results']}
        self.assertEqual(subdominios, {'panelnorte'})

    def test_la_ficha_trae_la_configuracion_del_gimnasio(self):
        respuesta = self.client.get(
            f'/api/plataforma/tenants/{self.tenant_uno.uuid_publico}/', **self._cabecera(),
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['subdominio'], 'panelnorte')
        self.assertEqual(cuerpo['zona_horaria'], 'America/Bogota')
        self.assertEqual(cuerpo['moneda'], 'COP')
        # Sin contrato todavía: el panel tiene que poder decirlo, no reventar.
        self.assertIsNone(cuerpo['suscripcion'])

    def test_soporte_tambien_puede_consultar(self):
        """Fase 1 es de solo lectura: soporte ve lo mismo que administración.
        La distinción de roles empezará a importar cuando haya acciones que
        cambien cosas."""
        _crear_cuenta_panel('soporte@proveedor.example.com', UsuarioPlataforma.RolPlataforma.SOPORTE)
        respuesta = self.client.post(
            '/api/plataforma/login/',
            data={'correo': 'soporte@proveedor.example.com', 'password': PASSWORD_PANEL},
            content_type='application/json',
        )
        cabecera = {'HTTP_AUTHORIZATION': f'Bearer {respuesta.json()["access"]}'}

        self.assertEqual(self.client.get('/api/plataforma/tenants/', **cabecera).status_code, 200)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class RefrescoDelPanelTestCase(TestCase):
    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.cuenta = _crear_cuenta_panel('refresco@proveedor.example.com')

    def _tokens(self):
        return self.client.post(
            '/api/plataforma/login/',
            data={'correo': 'refresco@proveedor.example.com', 'password': PASSWORD_PANEL},
            content_type='application/json',
        ).json()

    def test_refresca_el_access(self):
        respuesta = self.client.post(
            '/api/plataforma/refresh/',
            data={'refresh': self._tokens()['refresh']},
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        nuevo = respuesta.json()['access']
        self.assertEqual(
            self.client.get('/api/plataforma/me/', HTTP_AUTHORIZATION=f'Bearer {nuevo}').status_code,
            200,
        )

    def test_un_refresh_de_gimnasio_no_sirve_en_el_panel(self):
        _tenant, usuario = _crear_gimnasio('refrescoajeno', 'RA')
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(usuario)

        respuesta = self.client.post(
            '/api/plataforma/refresh/',
            data={'refresh': str(refresh)},
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 401, respuesta.content)

    def test_desactivar_la_cuenta_corta_tambien_el_refresco(self):
        refresh = self._tokens()['refresh']
        self.cuenta.activo = False
        self.cuenta.save(update_fields=['activo'])

        respuesta = self.client.post(
            '/api/plataforma/refresh/',
            data={'refresh': refresh},
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 401, respuesta.content)
