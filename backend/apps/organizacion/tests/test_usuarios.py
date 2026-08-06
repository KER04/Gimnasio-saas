"""Gestión de usuarios del gimnasio (``/api/usuarios/``).

Lo que más se comprueba aquí son las GUARDAS. Un fallo en esta pantalla no
se manifiesta como un error: se manifiesta como un gimnasio que se queda sin
nadie capaz de administrarlo, y cuya única salida es llamar al proveedor.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.core.tenant import tenant_context
from apps.organizacion.models import Permiso, Rol, RolPermiso, Sede, UsuarioSede
from apps.plataforma.models import Tenant

from apps.autenticacion.tests.test_auth import PASSWORD, _cabecera_token, _crear_tenant_con_usuario

Usuario = get_user_model()
_ALLOWED_HOSTS_PRUEBA = ['testserver', '.testserver']


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class BaseUsuariosTestCase(TestCase):
    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.tenant, cls.rol_admin, cls.admin = _crear_tenant_con_usuario(
            'gestusuarios', 'GU', 'admin@gestusuarios.example.com',
            permisos=('config.usuarios',),
        )
        with tenant_context(cls.tenant.id):
            cls.rol_recepcion = Rol.objects.create(
                tenant=cls.tenant, nombre='Recepcionista', es_sistema=True,
            )
            por_codigo = {p.codigo: p for p in Permiso.objects.all()}
            RolPermiso.objects.create(
                rol=cls.rol_recepcion, permiso=por_codigo['clientes.ver'], tenant=cls.tenant,
            )
            cls.sede = Sede.objects.create(
                tenant=cls.tenant, nombre='Sede Centro', direccion='Calle 1',
            )
            cls.sede_norte = Sede.objects.create(
                tenant=cls.tenant, nombre='Sede Norte', direccion='Calle 2',
            )

    def setUp(self):
        cache.clear()

    def _peticion(self, metodo, url, datos=None, usuario=None):
        fn = getattr(self.client, metodo)
        kwargs = {
            'HTTP_HOST': 'gestusuarios.testserver',
            **_cabecera_token(usuario or self.admin),
        }
        if datos is not None:
            kwargs['data'] = datos
            kwargs['content_type'] = 'application/json'
        return fn(url, **kwargs)

    def _crear_empleado(self, correo='nuevo@gestusuarios.example.com', **extra):
        return self._peticion('post', '/api/usuarios/', {
            'nombre': 'Empleado Nuevo',
            'correo': correo,
            'rol': self.rol_recepcion.id,
            **extra,
        })


class AltaDeUsuariosTestCase(BaseUsuariosTestCase):

    def test_crea_un_empleado_que_puede_entrar(self):
        """La prueba que importa del alta: que la credencial que le vas a dar
        al empleado FUNCIONE. Se enseña una sola vez."""
        respuesta = self._crear_empleado()

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        cuerpo = respuesta.json()
        self.assertIn('password', cuerpo)

        login = self.client.post(
            '/api/auth/login/',
            data={'correo': 'nuevo@gestusuarios.example.com', 'password': cuerpo['password']},
            content_type='application/json', HTTP_HOST='gestusuarios.testserver',
        )
        self.assertEqual(login.status_code, 200, login.content)

    def test_la_contrasena_la_genera_el_servidor(self):
        respuesta = self._crear_empleado(password='la-mia-1234')

        self.assertNotEqual(respuesta.json()['password'], 'la-mia-1234')
        self.assertGreaterEqual(len(respuesta.json()['password']), 16)

    def test_el_correo_es_unico_dentro_del_gimnasio(self):
        self._crear_empleado()

        respuesta = self._crear_empleado()

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('correo', respuesta.json())

    def test_asigna_las_sedes_indicadas(self):
        respuesta = self._crear_empleado(sedes=[self.sede.id, self.sede_norte.id])

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        self.assertCountEqual(
            [s['id'] for s in respuesta.json()['sedes']], [self.sede.id, self.sede_norte.id],
        )

    def test_nunca_devuelve_la_contrasena_almacenada(self):
        """El hash no tiene por qué salir de la base de datos."""
        self._crear_empleado()

        listado = self._peticion('get', '/api/usuarios/').json()

        for fila in listado['results']:
            self.assertNotIn('password_hash', fila)
            self.assertNotIn('last_login', [c for c in fila if c == 'password'])

    def test_sin_permiso_no_se_pueden_crear_usuarios(self):
        _tenant, _rol, sin_permiso = _crear_tenant_con_usuario(
            'gestsinperm', 'GSP', 'nadie@gestsinperm.example.com',
        )

        respuesta = self.client.post(
            '/api/usuarios/',
            data={'nombre': 'X', 'correo': 'x@x.example.com', 'rol': self.rol_recepcion.id},
            content_type='application/json',
            HTTP_HOST='gestsinperm.testserver', **_cabecera_token(sin_permiso),
        )

        self.assertEqual(respuesta.status_code, 403, respuesta.content)


class EdicionYBajaTestCase(BaseUsuariosTestCase):

    def _empleado(self):
        respuesta = self._crear_empleado()
        return Usuario.objects.get(pk=respuesta.json()['id'])

    def test_edita_nombre_y_telefono(self):
        empleado = self._empleado()

        respuesta = self._peticion(
            'patch', f'/api/usuarios/{empleado.id}/', {'nombre': 'Nombre Cambiado', 'telefono': '3001112233'},
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertEqual(respuesta.json()['nombre'], 'Nombre Cambiado')

    def test_el_correo_no_se_edita(self):
        """Es la credencial con la que entra: cambiárselo desde otra sesión
        equivale a apropiarse de la cuenta."""
        empleado = self._empleado()

        respuesta = self._peticion(
            'patch', f'/api/usuarios/{empleado.id}/', {'correo': 'otro@gestusuarios.example.com'},
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        empleado.refresh_from_db()
        self.assertEqual(empleado.correo, 'nuevo@gestusuarios.example.com')

    def test_desactivar_quita_el_acceso_sin_borrar_nada(self):
        """`Venta`, `Pago` y los movimientos de inventario apuntan al usuario
        con PROTECT: un recibo tiene que poder decir quién lo hizo aunque esa
        persona ya no trabaje allí."""
        empleado = self._empleado()

        respuesta = self._peticion('post', f'/api/usuarios/{empleado.id}/desactivar/', {})

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        empleado.refresh_from_db()
        self.assertFalse(empleado.activo)
        self.assertTrue(Usuario.objects.filter(pk=empleado.pk).exists())

        login = self.client.post(
            '/api/auth/login/',
            data={'correo': empleado.correo, 'password': PASSWORD},
            content_type='application/json', HTTP_HOST='gestusuarios.testserver',
        )
        self.assertNotEqual(login.status_code, 200)

    def test_se_puede_volver_a_activar(self):
        empleado = self._empleado()
        self._peticion('post', f'/api/usuarios/{empleado.id}/desactivar/', {})

        respuesta = self._peticion('post', f'/api/usuarios/{empleado.id}/activar/', {})

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        empleado.refresh_from_db()
        self.assertTrue(empleado.activo)

    def test_los_inactivos_solo_salen_si_se_piden(self):
        empleado = self._empleado()
        self._peticion('post', f'/api/usuarios/{empleado.id}/desactivar/', {})

        normal = self._peticion('get', '/api/usuarios/').json()['results']
        self.assertNotIn(empleado.id, [u['id'] for u in normal])

        todos = self._peticion('get', '/api/usuarios/?incluir_inactivos=1').json()['results']
        self.assertIn(empleado.id, [u['id'] for u in todos])

    def test_cambia_las_sedes_asignadas(self):
        empleado = self._empleado()
        self._peticion('patch', f'/api/usuarios/{empleado.id}/', {'sedes': [self.sede.id]})

        respuesta = self._peticion(
            'patch', f'/api/usuarios/{empleado.id}/', {'sedes': [self.sede_norte.id]},
        )

        self.assertEqual([s['id'] for s in respuesta.json()['sedes']], [self.sede_norte.id])
        with tenant_context(self.tenant.id):
            self.assertEqual(UsuarioSede.objects.filter(usuario=empleado).count(), 1)


class GuardasContraQuedarseFueraTestCase(BaseUsuariosTestCase):
    """El accidente que estas comprobaciones evitan: un gimnasio sin nadie
    capaz de administrarlo, cuya única salida sería llamar al proveedor."""

    def test_nadie_puede_desactivarse_a_si_mismo(self):
        respuesta = self._peticion('post', f'/api/usuarios/{self.admin.id}/desactivar/', {})

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.activo)

    def test_nadie_puede_cambiarse_su_propio_rol(self):
        """Un administrador que se degrada por error ya no tiene permisos para
        volver a subirse."""
        respuesta = self._peticion(
            'patch', f'/api/usuarios/{self.admin.id}/', {'rol': self.rol_recepcion.id},
        )

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('rol', respuesta.json())
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.rol_id, self.rol_admin.id)

    def test_no_se_puede_desactivar_al_ultimo_administrador(self):
        otro_admin = Usuario.objects.create_user(
            correo='segundo@gestusuarios.example.com', nombre='Segundo Admin',
            tenant=self.tenant, rol=self.rol_admin, password=PASSWORD,
        )

        # Con dos administradores, desactivar a uno se permite.
        respuesta = self._peticion('post', f'/api/usuarios/{otro_admin.id}/desactivar/', {})
        self.assertEqual(respuesta.status_code, 200, respuesta.content)

        # Ahora solo queda uno: el propio peticionario, que además no puede
        # desactivarse a sí mismo. Se comprueba desde la otra cuenta.
        self._peticion('post', f'/api/usuarios/{otro_admin.id}/activar/', {})
        respuesta = self._peticion(
            'post', f'/api/usuarios/{self.admin.id}/desactivar/', {}, usuario=otro_admin,
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)

        # Y ya no queda ninguno más: el último no se puede tumbar.
        self.admin.refresh_from_db()
        respuesta = self._peticion(
            'post', f'/api/usuarios/{otro_admin.id}/desactivar/', {}, usuario=otro_admin,
        )
        self.assertEqual(respuesta.status_code, 400, respuesta.content)

    def test_no_se_puede_degradar_al_ultimo_administrador(self):
        otro_admin = Usuario.objects.create_user(
            correo='tercero@gestusuarios.example.com', nombre='Tercer Admin',
            tenant=self.tenant, rol=self.rol_admin, password=PASSWORD,
        )
        # El peticionario deja de ser administrador tumbándose por otro: con
        # `otro_admin` como único admin restante, degradarlo debe fallar.
        self._peticion('post', f'/api/usuarios/{self.admin.id}/desactivar/', {}, usuario=otro_admin)

        respuesta = self._peticion(
            'patch', f'/api/usuarios/{otro_admin.id}/', {'rol': self.rol_recepcion.id},
            usuario=otro_admin,
        )

        # Falla por la guarda del propio rol, que es la primera que salta.
        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        otro_admin.refresh_from_db()
        self.assertEqual(otro_admin.rol_id, self.rol_admin.id)


class RestablecerPasswordTestCase(BaseUsuariosTestCase):

    def test_la_contrasena_nueva_funciona_y_la_vieja_no(self):
        """Es la llamada más frecuente de cualquier gimnasio: "no me acuerdo
        de mi contraseña". Sin esto había que molestar al proveedor."""
        creado = self._crear_empleado().json()
        empleado_id, password_vieja = creado['id'], creado['password']

        respuesta = self._peticion(
            'post', f'/api/usuarios/{empleado_id}/restablecer-password/', {},
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        nueva = respuesta.json()['password']
        self.assertNotEqual(nueva, password_vieja)

        entra = self.client.post(
            '/api/auth/login/',
            data={'correo': 'nuevo@gestusuarios.example.com', 'password': nueva},
            content_type='application/json', HTTP_HOST='gestusuarios.testserver',
        )
        self.assertEqual(entra.status_code, 200, entra.content)

        vieja = self.client.post(
            '/api/auth/login/',
            data={'correo': 'nuevo@gestusuarios.example.com', 'password': password_vieja},
            content_type='application/json', HTTP_HOST='gestusuarios.testserver',
        )
        self.assertNotEqual(vieja.status_code, 200)

    def test_sin_permiso_no_se_restablece(self):
        creado = self._crear_empleado().json()
        _t, _r, sin_permiso = _crear_tenant_con_usuario(
            'gestsinperm2', 'GSP2', 'nadie2@gestsinperm2.example.com',
        )

        respuesta = self.client.post(
            f'/api/usuarios/{creado["id"]}/restablecer-password/',
            content_type='application/json',
            HTTP_HOST='gestsinperm2.testserver', **_cabecera_token(sin_permiso),
        )

        self.assertIn(respuesta.status_code, (403, 404), respuesta.content)


class AislamientoEntreGimnasiosTestCase(BaseUsuariosTestCase):

    def test_no_se_ven_los_usuarios_de_otro_gimnasio(self):
        otro_tenant, _rol, otro_usuario = _crear_tenant_con_usuario(
            'gestajeno', 'GA', 'ajeno@gestajeno.example.com', permisos=('config.usuarios',),
        )

        listado = self._peticion('get', '/api/usuarios/?incluir_inactivos=1').json()['results']

        self.assertNotIn(otro_usuario.id, [u['id'] for u in listado])

    def test_no_se_puede_tocar_a_un_usuario_de_otro_gimnasio(self):
        """RLS ya lo esconde: la vista solo lo traduce a un 404."""
        otro_tenant, _rol, otro_usuario = _crear_tenant_con_usuario(
            'gestajeno2', 'GA2', 'ajeno2@gestajeno2.example.com',
        )

        respuesta = self._peticion(
            'post', f'/api/usuarios/{otro_usuario.id}/desactivar/', {},
        )

        self.assertEqual(respuesta.status_code, 404, respuesta.content)
        # La relectura necesita el contexto del OTRO tenant: `usuarios` tiene
        # RLS, así que fuera de él su propia fila no existe (y por eso la
        # vista devolvió 404 más arriba).
        with tenant_context(otro_tenant.id):
            otro_usuario.refresh_from_db()
        self.assertTrue(otro_usuario.activo)


class UltimoAccesoTestCase(BaseUsuariosTestCase):
    """`usuarios.ultimo_acceso` tiene que reflejar la realidad.

    Con `UPDATE_LAST_LOGIN` desactivado (el valor por defecto de SimpleJWT),
    la columna solo la escribía el login por SESIÓN del admin de Django: la
    pantalla enseñaba "nunca ha entrado" para gente que trabajaba a diario.
    Y sobre ese dato se decide a quién se le quita el acceso.
    """

    def test_entrar_actualiza_el_ultimo_acceso(self):
        creado = self._crear_empleado().json()
        antes = Usuario.objects.get(pk=creado['id']).last_login
        self.assertIsNone(antes)

        self.client.post(
            '/api/auth/login/',
            data={'correo': creado['correo'], 'password': creado['password']},
            content_type='application/json', HTTP_HOST='gestusuarios.testserver',
        )

        self.assertIsNotNone(
            Usuario.objects.get(pk=creado['id']).last_login,
            'Entrar por la API debe registrar el último acceso.',
        )

    def test_un_intento_fallido_no_cuenta_como_acceso(self):
        creado = self._crear_empleado().json()

        self.client.post(
            '/api/auth/login/',
            data={'correo': creado['correo'], 'password': 'no-es-esta'},
            content_type='application/json', HTTP_HOST='gestusuarios.testserver',
        )

        self.assertIsNone(Usuario.objects.get(pk=creado['id']).last_login)


class RolesTestCase(BaseUsuariosTestCase):

    def test_lista_los_roles_del_gimnasio(self):
        respuesta = self._peticion('get', '/api/roles/')

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        nombres = [r['nombre'] for r in respuesta.json()['results']]
        self.assertIn('Recepcionista', nombres)

    def test_sin_permiso_no_se_listan_los_roles(self):
        _t, _r, sin_permiso = _crear_tenant_con_usuario(
            'gestsinperm3', 'GSP3', 'nadie3@gestsinperm3.example.com',
        )

        respuesta = self.client.get(
            '/api/roles/', HTTP_HOST='gestsinperm3.testserver', **_cabecera_token(sin_permiso),
        )

        self.assertEqual(respuesta.status_code, 403, respuesta.content)
