"""Batería de autenticación consciente del tenant (Parte G).

Cubre exactamente los escenarios pedidos en el encargo:

1. LA PRUEBA CENTRAL: un usuario del tenant A, con JWT válido, apuntando al
   subdominio del tenant B -> 403, sin ver ni una fila de B.
2. El mismo correo en dos tenants distintos: ambos pueden entrar, cada uno a
   lo suyo.
3. Login con contraseña incorrecta -> 401.
4. Login sin tenant resuelto -> falla (401, sin llegar a comparar password).
5. El claim tenant_id está en el token y coincide con el del usuario.
6. Token inválido/expirado no rompe el middleware (no debe dar 500).

Usa ``TestCase`` (no ``TransactionTestCase``): a diferencia de
``test_aislamiento.py``, aquí no se comprueba si ``app.tenant_id``
"sobrevive" fuera de una transacción -- solo se ejercitan vistas HTTP
completas, así que el patrón de ``test_middleware.py`` (``TestCase`` +
``databases = {'default', 'ddl'}``, porque ambas conexiones tienen
``ATOMIC_REQUESTS = True``) es suficiente y mucho más rápido.
"""
import datetime

from django.core.cache import cache
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.core.tenant import tenant_context
from apps.organizacion.models import Permiso, Rol, RolPermiso, Usuario
from apps.plataforma.models import Tenant

_ALLOWED_HOSTS_PRUEBA = ['testserver', '.testserver']
PASSWORD = 'clave-super-segura-123'


def _crear_tenant_con_usuario(subdominio, sufijo, correo, password=PASSWORD, permisos=()):
    """Crea un tenant + rol + usuario CON password real (hasheada vía
    ``create_user``), a diferencia de ``crear_tenant_completo`` (usada en
    ``test_aislamiento.py``), que siembra un ``password`` dummy sin hashear
    porque esos tests nunca hacen login de verdad.

    ``permisos`` son códigos (``'config.usuarios'``...) que se conceden al rol.
    Por defecto NINGUNO: la mayoría de estas pruebas solo hacen login, y un
    rol sin permisos es el punto de partida honesto para comprobar los 403.
    """
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
        if permisos:
            por_codigo = {p.codigo: p for p in Permiso.objects.using('default').all()}
            RolPermiso.objects.using('default').bulk_create([
                RolPermiso(rol=rol, permiso=por_codigo[codigo], tenant=tenant)
                for codigo in permisos
            ])
        usuario = Usuario.objects.create_user(
            correo=correo, nombre=f'Usuario {sufijo}', tenant=tenant, rol=rol, password=password,
        )
    return tenant, rol, usuario


def _cabecera_token(usuario):
    """Cabecera con un access token como el que emite ``LoginSerializer``.

    El claim ``tenant_id`` es imprescindible, no decorativo: ``TenantMiddleware``
    lo usa para fijar ``app.tenant_id``, y sin él la propia autenticación
    (que resuelve al usuario leyendo `usuarios`, tabla con RLS FORCE) no
    encuentra a nadie y responde "User not found" aunque el token sea válido.
    """
    token = AccessToken.for_user(usuario)
    token['tenant_id'] = usuario.tenant_id
    return {'HTTP_AUTHORIZATION': f'Bearer {token}'}


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class LoginTenantTestCase(TestCase):
    """Escenarios 2, 3, 4, 5 del encargo: login básico consciente del tenant."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.tenant_a, cls.rol_a, cls.usuario_a = _crear_tenant_con_usuario(
            'autha', 'A', 'compartido@example.com',
        )
        cls.tenant_b, cls.rol_b, cls.usuario_b = _crear_tenant_con_usuario(
            'authb', 'B', 'compartido@example.com',
        )

    def setUp(self):
        # Parte A (throttling): esta clase llama a /api/auth/login/ varias
        # veces con el MISMO correo a través de distintos métodos de
        # prueba. cache.clear() en setUpTestData solo corre una vez para
        # toda la clase; sin limpiar también aquí (antes de CADA prueba), el
        # contador de LoginPorCorreoThrottle (5/min) se acumularía entre
        # métodos y una prueba tardía podría recibir 429 en vez del código
        # que realmente está probando.
        cache.clear()

    def test_mismo_correo_en_dos_tenants_cada_uno_entra_a_lo_suyo(self):
        """Escenario 2: el mismo correo existe en A y en B (regla de negocio
        que motivó todo el diseño). Login en cada subdominio debe entrar al
        tenant correcto, no al primero que encuentre."""
        respuesta_a = self.client.post(
            '/api/auth/login/',
            data={'correo': 'compartido@example.com', 'password': PASSWORD},
            content_type='application/json',
            HTTP_HOST='autha.testserver',
        )
        self.assertEqual(respuesta_a.status_code, 200, respuesta_a.content)
        cuerpo_a = respuesta_a.json()
        self.assertEqual(cuerpo_a['user']['tenant_id'], self.tenant_a.id)
        self.assertEqual(cuerpo_a['user']['id'], self.usuario_a.id)

        respuesta_b = self.client.post(
            '/api/auth/login/',
            data={'correo': 'compartido@example.com', 'password': PASSWORD},
            content_type='application/json',
            HTTP_HOST='authb.testserver',
        )
        self.assertEqual(respuesta_b.status_code, 200, respuesta_b.content)
        cuerpo_b = respuesta_b.json()
        self.assertEqual(cuerpo_b['user']['tenant_id'], self.tenant_b.id)
        self.assertEqual(cuerpo_b['user']['id'], self.usuario_b.id)

        # Y, por supuesto, son usuarios DISTINTOS (mismo correo, distinta fila).
        self.assertNotEqual(cuerpo_a['user']['id'], cuerpo_b['user']['id'])

    def test_password_incorrecta_devuelve_401(self):
        """Escenario 3."""
        respuesta = self.client.post(
            '/api/auth/login/',
            data={'correo': 'compartido@example.com', 'password': 'password-equivocada'},
            content_type='application/json',
            HTTP_HOST='autha.testserver',
        )
        self.assertEqual(respuesta.status_code, 401)

    @override_settings(DEBUG=False)
    def test_login_sin_tenant_resuelto_falla(self):
        """Escenario 4 (actualizado por el campo `subdominio` explícito en
        el cuerpo): host sin subdominio (bare 'testserver'), sin cabecera
        X-Tenant (además deshabilitada por DEBUG=False) y sin `subdominio`
        en el cuerpo -> no hay NINGUNA forma de resolver el tenant ->
        `LoginView.post` rechaza con 400 ANTES de intentar autenticar (ya
        no con 401 de `TenantAuthBackend`, que ni llega a ejecutarse)."""
        respuesta = self.client.post(
            '/api/auth/login/',
            data={'correo': 'compartido@example.com', 'password': PASSWORD},
            content_type='application/json',
            HTTP_HOST='testserver',
        )
        self.assertEqual(respuesta.status_code, 400)

    def test_claim_tenant_id_presente_y_coincide_con_el_usuario(self):
        """Escenario 5."""
        respuesta = self.client.post(
            '/api/auth/login/',
            data={'correo': 'compartido@example.com', 'password': PASSWORD},
            content_type='application/json',
            HTTP_HOST='autha.testserver',
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        cuerpo = respuesta.json()

        access = AccessToken(cuerpo['access'])
        self.assertEqual(access['tenant_id'], self.tenant_a.id)
        self.assertEqual(access['tenant_id'], self.usuario_a.tenant_id)

        refresh_claims = _decodificar_sin_verificar(cuerpo['refresh'])
        self.assertEqual(refresh_claims.get('tenant_id'), self.tenant_a.id)


def _decodificar_sin_verificar(token_str):
    """Decodifica el payload de un JWT sin validar firma/expiración: solo
    para inspeccionar claims en pruebas (nunca usar así en código de
    producción)."""
    import base64
    import json

    payload_b64 = token_str.split('.')[1]
    payload_b64 += '=' * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64))


@override_settings(ROOT_URLCONF='config.urls', ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class TenantCruzadoTestCase(TestCase):
    """Escenario 1 (LA PRUEBA CENTRAL) y escenario 6 del encargo."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.tenant_a, cls.rol_a, cls.usuario_a = _crear_tenant_con_usuario(
            'cruza', 'A', 'usuario.a@example.com',
        )
        cls.tenant_b, cls.rol_b, cls.usuario_b = _crear_tenant_con_usuario(
            'cruzb', 'B', 'usuario.b@example.com',
        )

    def setUp(self):
        # Ver el comentario equivalente en LoginTenantTestCase.setUp: varios
        # métodos de esta clase loguean al mismo usuario ('usuario.a@...'),
        # y el throttle por correo (5/min) acumularía intentos entre
        # métodos sin esto.
        cache.clear()

    def _login(self, subdominio, correo):
        respuesta = self.client.post(
            '/api/auth/login/',
            data={'correo': correo, 'password': PASSWORD},
            content_type='application/json',
            HTTP_HOST=f'{subdominio}.testserver',
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        return respuesta.json()['access']

    def test_jwt_de_a_contra_subdominio_de_b_devuelve_403(self):
        """LA PRUEBA CENTRAL: token válido del tenant A usado contra el
        subdominio del tenant B debe rechazarse con 403 -- y no debe
        devolver ni una fila de B (la petición ni siquiera llega a la
        vista)."""
        access_a = self._login('cruza', 'usuario.a@example.com')

        respuesta = self.client.get(
            '/api/auth/me/',
            HTTP_HOST='cruzb.testserver',
            HTTP_AUTHORIZATION=f'Bearer {access_a}',
        )
        self.assertEqual(respuesta.status_code, 403)
        # No debe filtrar ningún dato de negocio en el cuerpo de la respuesta.
        cuerpo = respuesta.json()
        self.assertNotIn('correo', cuerpo)
        self.assertNotIn('id', cuerpo)

    def test_jwt_de_a_contra_subdominio_de_a_funciona(self):
        """Control positivo: el mismo token, contra SU PROPIO subdominio,
        debe funcionar con normalidad (para descartar que el 403 de arriba
        sea un bug que rechaza todo)."""
        access_a = self._login('cruza', 'usuario.a@example.com')

        respuesta = self.client.get(
            '/api/auth/me/',
            HTTP_HOST='cruza.testserver',
            HTTP_AUTHORIZATION=f'Bearer {access_a}',
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['id'], self.usuario_a.id)
        self.assertEqual(cuerpo['tenant_id'], self.tenant_a.id)

    def test_jwt_de_a_sin_subdominio_tambien_funciona(self):
        """El token es la fuente de verdad incluso sin ningún subdominio en
        el Host (p. ej. un cliente que pega directo a la IP/host base)."""
        access_a = self._login('cruza', 'usuario.a@example.com')

        respuesta = self.client.get(
            '/api/auth/me/',
            HTTP_HOST='testserver',
            HTTP_AUTHORIZATION=f'Bearer {access_a}',
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertEqual(respuesta.json()['tenant_id'], self.tenant_a.id)

    def test_token_invalido_no_revienta_el_middleware(self):
        """Escenario 6: un token corrupto/manipulado no debe dar 500 -- el
        middleware lo ignora, cae al subdominio, y es la vista (JWTAuthentication)
        la que responde 401 al no poder validar credenciales."""
        respuesta = self.client.get(
            '/api/auth/me/',
            HTTP_HOST='cruza.testserver',
            HTTP_AUTHORIZATION='Bearer esto-no-es-un-jwt-valido',
        )
        self.assertEqual(respuesta.status_code, 401)

    def test_token_expirado_no_revienta_el_middleware(self):
        """Variante de escenario 6 con un token real pero ya expirado."""
        access = AccessToken.for_user(self.usuario_a)
        access['tenant_id'] = self.usuario_a.tenant_id
        access.set_exp(lifetime=datetime.timedelta(seconds=-1))

        respuesta = self.client.get(
            '/api/auth/me/',
            HTTP_HOST='cruza.testserver',
            HTTP_AUTHORIZATION=f'Bearer {access}',
        )
        self.assertEqual(respuesta.status_code, 401)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class RegisterTenantTestCase(TestCase):
    """``/api/auth/register/`` ya NO es anónimo.

    Dar de alta a un compañero es una operación del administrador del
    gimnasio (``config.usuarios``). Cuando el endpoint era ``AllowAny``,
    cualquiera que conociera un subdominio podía crearse una cuenta dentro de
    ese gimnasio.
    """

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.tenant, cls.rol, cls.admin = _crear_tenant_con_usuario(
            'registro', 'R', 'ya-existe@example.com', permisos=('config.usuarios',),
        )
        # Segundo gimnasio, para comprobar que no se puede sembrar dentro de
        # él desde el primero.
        cls.tenant_ajeno, cls.rol_ajeno, _ = _crear_tenant_con_usuario(
            'registroajeno', 'RA', 'ajeno@example.com',
        )
        # Usuario del MISMO gimnasio pero sin el permiso.
        with tenant_context(cls.tenant.id):
            rol_pelado = Rol.objects.using('default').create(
                tenant=cls.tenant, nombre='Sin permisos R', es_sistema=False,
            )
            cls.sin_permiso = Usuario.objects.create_user(
                correo='pelado@example.com', nombre='Sin Permiso',
                tenant=cls.tenant, rol=rol_pelado, password=PASSWORD,
            )

    def setUp(self):
        cache.clear()

    def _registrar(self, correo, cabeceras=None, **extra_body):
        return self.client.post(
            '/api/auth/register/',
            data={
                'correo': correo,
                'nombre': 'Nuevo Usuario',
                'password': PASSWORD,
                'rol': self.rol.id,
                **extra_body,
            },
            content_type='application/json',
            HTTP_HOST='registro.testserver',
            **(cabeceras or {}),
        )

    def test_registro_anonimo_da_401(self):
        respuesta = self._registrar('nuevo@example.com')
        self.assertEqual(respuesta.status_code, 401, respuesta.content)

    def test_registro_sin_el_permiso_da_403(self):
        respuesta = self._registrar('nuevo@example.com', _cabecera_token(self.sin_permiso))
        self.assertEqual(respuesta.status_code, 403, respuesta.content)

    def test_registro_con_permiso_crea_usuario_en_el_tenant_de_quien_lo_pide(self):
        respuesta = self._registrar('nuevo@example.com', _cabecera_token(self.admin))
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['user']['tenant_id'], self.tenant.id)
        self.assertIn('access', cuerpo)
        self.assertIn('refresh', cuerpo)

    def test_el_subdominio_del_cuerpo_no_puede_sembrar_en_otro_gimnasio(self):
        """El tenant sale del TOKEN, no del cuerpo.

        Mientras el endpoint fue anónimo, el tenant se resolvía del cuerpo
        (o del Host) porque no había otra fuente. Ahora la hay, y seguir
        haciendo caso al cuerpo dejaría que el administrador del gimnasio A
        creara usuarios dentro del gimnasio B con solo cambiar un campo.
        """
        respuesta = self._registrar(
            'infiltrado@example.com',
            _cabecera_token(self.admin),
            subdominio='registroajeno',
        )

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        self.assertEqual(respuesta.json()['user']['tenant_id'], self.tenant.id)

        with tenant_context(self.tenant_ajeno.id):
            self.assertFalse(
                Usuario.objects.filter(correo='infiltrado@example.com').exists(),
                'El usuario acabó en el gimnasio ajeno: el cuerpo mandó sobre el token.',
            )


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class SubdominioExplicitoTestCase(TestCase):
    """Batería del campo `subdominio` explícito en el cuerpo de login/register
    (Parte C del encargo: "el API debe poder recibir el gimnasio como un
    campo explícito en el cuerpo, sin dejar de aceptar el subdominio del Host
    como respaldo").

    Cubre exactamente los escenarios pedidos:

    1. Login desde un Host SIN subdominio, enviando `subdominio` en el
       cuerpo -> 200 y el token trae el `tenant_id` correcto (LA CAPACIDAD
       NUEVA: esto es lo que permite loguearse cuando Angular y el API no
       comparten host, p. ej. gimx.tuapp.com vs api.tuapp.com).
    2. Retrocompatibilidad: Host con subdominio y SIN `subdominio` en el
       cuerpo -> sigue en 200 (ya cubierto también por
       LoginTenantTestCase/TenantCruzadoTestCase, que no tocan este campo).
    3. Sin ninguna de las dos cosas -> 400 (ver
       LoginTenantTestCase.test_login_sin_tenant_resuelto_falla, actualizado
       en este mismo cambio de 401 a 400).
    4. `subdominio` del cuerpo distinto del subdominio del Host -> 400.
    5. `subdominio` inexistente -> 400.
    6. El mismo correo en dos tenants: enviando `subdominio` en el cuerpo,
       cada uno entra al suyo.
    7. `register` con `subdominio` en el cuerpo, desde un Host sin
       subdominio.
    """

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.tenant_a, cls.rol_a, cls.usuario_a = _crear_tenant_con_usuario(
            'expla', 'ExplA', 'compartido.expl@example.com', permisos=('config.usuarios',),
        )
        cls.tenant_b, cls.rol_b, cls.usuario_b = _crear_tenant_con_usuario(
            'explb', 'ExplB', 'compartido.expl@example.com',
        )

    def setUp(self):
        # Ver el comentario equivalente en LoginTenantTestCase.setUp: esta
        # clase es la que más veces reutiliza el mismo correo
        # ('compartido.expl@...') entre métodos de prueba distintos -- sin
        # limpiar el caché antes de cada uno, el throttle por correo
        # (5/min) terminaría bloqueando una prueba tardía con 429 en vez del
        # código que en realidad se quiere comprobar.
        cache.clear()

    def test_login_host_sin_subdominio_con_subdominio_en_cuerpo_da_200(self):
        """Escenario 1 (LA CAPACIDAD NUEVA)."""
        respuesta = self.client.post(
            '/api/auth/login/',
            data={
                'correo': 'compartido.expl@example.com',
                'password': PASSWORD,
                'subdominio': 'expla',
            },
            content_type='application/json',
            HTTP_HOST='testserver',
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['user']['tenant_id'], self.tenant_a.id)
        self.assertEqual(cuerpo['user']['id'], self.usuario_a.id)

        access = AccessToken(cuerpo['access'])
        self.assertEqual(access['tenant_id'], self.tenant_a.id)

    def test_login_host_con_subdominio_sin_campo_en_cuerpo_sigue_funcionando(self):
        """Escenario 2: retrocompatibilidad -- el campo `subdominio` es
        opcional, el respaldo del Host sigue funcionando solo."""
        respuesta = self.client.post(
            '/api/auth/login/',
            data={'correo': 'compartido.expl@example.com', 'password': PASSWORD},
            content_type='application/json',
            HTTP_HOST='expla.testserver',
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertEqual(respuesta.json()['user']['tenant_id'], self.tenant_a.id)

    def test_login_subdominio_de_cuerpo_distinto_del_host_da_400(self):
        """Escenario 4: si vienen los dos y no coinciden, se rechaza -- no
        se adivina cuál de los dos "gana"."""
        respuesta = self.client.post(
            '/api/auth/login/',
            data={
                'correo': 'compartido.expl@example.com',
                'password': PASSWORD,
                'subdominio': 'explb',
            },
            content_type='application/json',
            HTTP_HOST='expla.testserver',
        )
        self.assertEqual(respuesta.status_code, 400, respuesta.content)

    def test_login_subdominio_inexistente_da_400(self):
        """Escenario 5: el subdominio no es un secreto (va en la URL), así
        que se puede decir sin problema que no existe."""
        respuesta = self.client.post(
            '/api/auth/login/',
            data={
                'correo': 'compartido.expl@example.com',
                'password': PASSWORD,
                'subdominio': 'este-subdominio-no-existe',
            },
            content_type='application/json',
            HTTP_HOST='testserver',
        )
        self.assertEqual(respuesta.status_code, 400, respuesta.content)

    def test_mismo_correo_en_dos_tenants_via_subdominio_de_cuerpo(self):
        """Escenario 6, pero resolviendo el tenant por el campo del cuerpo
        (no por el Host) -- ambos entran, cada uno a lo suyo."""
        respuesta_a = self.client.post(
            '/api/auth/login/',
            data={
                'correo': 'compartido.expl@example.com',
                'password': PASSWORD,
                'subdominio': 'expla',
            },
            content_type='application/json',
            HTTP_HOST='testserver',
        )
        self.assertEqual(respuesta_a.status_code, 200, respuesta_a.content)
        self.assertEqual(respuesta_a.json()['user']['id'], self.usuario_a.id)

        respuesta_b = self.client.post(
            '/api/auth/login/',
            data={
                'correo': 'compartido.expl@example.com',
                'password': PASSWORD,
                'subdominio': 'explb',
            },
            content_type='application/json',
            HTTP_HOST='testserver',
        )
        self.assertEqual(respuesta_b.status_code, 200, respuesta_b.content)
        self.assertEqual(respuesta_b.json()['user']['id'], self.usuario_b.id)

        self.assertNotEqual(respuesta_a.json()['user']['id'], respuesta_b.json()['user']['id'])

    def test_register_desde_host_sin_subdominio_usa_el_tenant_del_token(self):
        """El ``subdominio`` explícito del cuerpo es cosa de LOGIN, no de register.

        Tenía sentido mientras register era anónimo: sin token no había otra
        forma de saber a qué gimnasio iba el usuario nuevo. Ahora el endpoint
        exige ``config.usuarios``, y el tenant sale del token de quien lo
        pide -- que es la única fuente que el cliente no puede falsear.

        Se sigue entrando por un Host SIN subdominio a propósito: demuestra
        que el alta funciona sin depender de la URL.
        """
        respuesta = self.client.post(
            '/api/auth/register/',
            data={
                'correo': 'nuevo.expl@example.com',
                'nombre': 'Nuevo Usuario Explícito',
                'password': PASSWORD,
                'rol': self.rol_a.id,
            },
            content_type='application/json',
            HTTP_HOST='testserver',
            **_cabecera_token(self.usuario_a),
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['user']['tenant_id'], self.tenant_a.id)
        self.assertIn('access', cuerpo)
        self.assertIn('refresh', cuerpo)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class RefrescoDeSesionTestCase(TransactionTestCase):
    """Renovación del access token contra la base con RLS activo.

    Usa TransactionTestCase y NO TestCase, deliberadamente. TestCase envuelve
    toda la clase en una única transacción que nunca se confirma; como los
    datos se siembran dentro de tenant_context, el app.tenant_id fijado allí
    con set_config(..., true) sigue vigente durante todos los tests de la
    clase. RLS entonces nunca bloquea nada y estas pruebas pasarían igual con
    el fallo presente: comprobado por mutación.

    Con TransactionTestCase cada test confirma de verdad, el contexto de
    tenant se evapora entre transacciones, y la petición HTTP llega al
    servidor en las mismas condiciones que en producción.

    Regresión de un fallo real detectado en uso: la ruta /api/auth/refresh/
    está exenta del middleware de tenant, pero el serializer de simplejwt
    consulta la tabla `usuarios` para comprobar que el usuario siga activo.
    Como esa tabla tiene RLS con FORCE, sin app.tenant_id fijado la consulta
    devolvía cero filas y la petición reventaba con Usuario.DoesNotExist,
    respondiendo HTTP 500.

    El efecto práctico era que, al caducar el access token (60 minutos), la
    sesión no se podía renovar y el usuario quedaba fuera de la aplicación.

    Ningún test lo detectó porque el único que ejercitaba esa ruta por HTTP
    corría sobre SQLite, antes de que existiera RLS.
    """

    databases = {"default", "ddl"}

    def setUp(self):
        # TransactionTestCase no tiene setUpTestData: los datos se siembran
        # por test, porque entre tests se truncan las tablas.
        cache.clear()
        self.tenant, self.rol, self.usuario = _crear_tenant_con_usuario(
            "refresca", "REF", "refresco@example.com",
        )

    def _tokens(self):
        respuesta = self.client.post(
            "/api/auth/login/",
            data={"correo": "refresco@example.com", "password": PASSWORD},
            content_type="application/json",
            HTTP_HOST="refresca.testserver",
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        return respuesta.json()

    def test_refresh_devuelve_un_access_nuevo_y_utilizable(self):
        refresh = self._tokens()["refresh"]

        respuesta = self.client.post(
            "/api/auth/refresh/",
            data={"refresh": refresh},
            content_type="application/json",
            HTTP_HOST="refresca.testserver",
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        access_nuevo = respuesta.json()["access"]

        # El token renovado tiene que servir de verdad, no solo existir.
        me = self.client.get(
            "/api/auth/me/",
            HTTP_AUTHORIZATION=f"Bearer {access_nuevo}",
            HTTP_HOST="refresca.testserver",
        )
        self.assertEqual(me.status_code, 200, me.content)
        self.assertEqual(me.json()["correo"], "refresco@example.com")

    def test_refresh_conserva_el_tenant_en_el_token_renovado(self):
        """Si el claim se perdiera al refrescar, el middleware volvería a
        fiarse del subdominio y se reabriría la fuga entre gimnasios."""
        refresh = self._tokens()["refresh"]
        respuesta = self.client.post(
            "/api/auth/refresh/",
            data={"refresh": refresh},
            content_type="application/json",
            HTTP_HOST="refresca.testserver",
        )
        access = AccessToken(respuesta.json()["access"])
        self.assertEqual(access["tenant_id"], self.tenant.id)

    def test_refresh_reutilizado_responde_401_y_no_500(self):
        """El backend rota y revoca el refresh anterior: reusarlo es un
        rechazo de autenticación, no un error del servidor."""
        refresh = self._tokens()["refresh"]
        self.client.post(
            "/api/auth/refresh/", data={"refresh": refresh},
            content_type="application/json", HTTP_HOST="refresca.testserver",
        )
        segunda = self.client.post(
            "/api/auth/refresh/", data={"refresh": refresh},
            content_type="application/json", HTTP_HOST="refresca.testserver",
        )
        self.assertEqual(segunda.status_code, 401, segunda.content)

    def test_refresh_con_token_malformado_responde_401_y_no_500(self):
        respuesta = self.client.post(
            "/api/auth/refresh/",
            data={"refresh": "esto.no.es.un.token"},
            content_type="application/json",
            HTTP_HOST="refresca.testserver",
        )
        self.assertEqual(respuesta.status_code, 401, respuesta.content)
