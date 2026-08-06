"""Gestión de sedes (``/api/sedes-admin/``, permiso ``config.sedes``).

Dos cosas justifican los tests de aquí: que crear una sede deje también su
secuencia de comprobantes (sin ella, la primera venta en esa sede falla al
numerar el recibo) y que no se pueda dejar el gimnasio sin ninguna sede.
"""
from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.autenticacion.tests.test_auth import _cabecera_token, _crear_tenant_con_usuario
from apps.core.tenant import tenant_context
from apps.organizacion.models import SecuenciaComprobante, Sede

_ALLOWED_HOSTS_PRUEBA = ['testserver', '.testserver']


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class SedesTestCase(TestCase):
    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.tenant, cls.rol, cls.usuario = _crear_tenant_con_usuario(
            'gestsedes', 'GS', 'admin@gestsedes.example.com',
            permisos=('config.sedes',),
        )
        with tenant_context(cls.tenant.id):
            cls.sede = Sede.objects.create(
                tenant=cls.tenant, nombre='Sede Principal', direccion='Calle 1',
            )
            SecuenciaComprobante.objects.create(sede=cls.sede, tenant=cls.tenant)

    def setUp(self):
        cache.clear()

    def _peticion(self, metodo, url, datos=None):
        fn = getattr(self.client, metodo)
        kwargs = {'HTTP_HOST': 'gestsedes.testserver', **_cabecera_token(self.usuario)}
        if datos is not None:
            kwargs['data'] = datos
            kwargs['content_type'] = 'application/json'
        return fn(url, **kwargs)

    def _crear(self, **extra):
        return self._peticion('post', '/api/sedes-admin/', {
            'nombre': 'Sede Norte', 'direccion': 'Calle 100', **extra,
        })

    def test_crear_una_sede_crea_su_secuencia_de_comprobantes(self):
        """Sin la fila en `secuencias_comprobantes`, la primera venta en la
        sede nueva reventaría al buscar su consecutivo."""
        respuesta = self._crear()

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        with tenant_context(self.tenant.id):
            self.assertTrue(
                SecuenciaComprobante.objects.filter(sede_id=respuesta.json()['id']).exists(),
            )

    def test_el_nombre_es_unico_dentro_del_gimnasio(self):
        self._crear()

        respuesta = self._crear(nombre='sede norte')

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('nombre', respuesta.json())

    def test_normaliza_el_prefijo_de_comprobante(self):
        respuesta = self._crear(prefijo_comprobante='n2')

        self.assertEqual(respuesta.json()['prefijo_comprobante'], 'N2')

    def test_rechaza_un_prefijo_con_signos(self):
        respuesta = self._crear(prefijo_comprobante='N-2')

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('prefijo_comprobante', respuesta.json())

    def test_edita_los_datos_de_la_sede(self):
        respuesta = self._peticion(
            'patch', f'/api/sedes-admin/{self.sede.id}/',
            {'telefono': '3001234567', 'direccion': 'Calle 2'},
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertEqual(respuesta.json()['direccion'], 'Calle 2')

    def test_no_se_puede_cerrar_la_unica_sede_activa(self):
        """Vender, cobrar y registrar asistencia ocurren SIEMPRE en una sede:
        sin ninguna activa, el gimnasio no puede operar en absoluto."""
        respuesta = self._peticion('post', f'/api/sedes-admin/{self.sede.id}/desactivar/', {})

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.sede.refresh_from_db()
        self.assertTrue(self.sede.activa)

    def test_se_puede_cerrar_una_sede_si_queda_otra(self):
        nueva = self._crear().json()

        respuesta = self._peticion('post', f'/api/sedes-admin/{nueva["id"]}/desactivar/', {})

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertFalse(respuesta.json()['activa'])

    def test_avisa_de_quien_se_queda_sin_sede_al_cerrar(self):
        """Cerrar una sede es legítimo; dejar a alguien sin poder trabajar sin
        decirlo, no. Se avisa, no se bloquea."""
        from django.contrib.auth import get_user_model

        from apps.organizacion.models import UsuarioSede

        Usuario = get_user_model()
        nueva = self._crear().json()
        with tenant_context(self.tenant.id):
            empleado = Usuario.objects.create_user(
                correo='solo.norte@gestsedes.example.com', nombre='Solo Norte',
                tenant=self.tenant, rol=self.rol, password='clave-larga-de-prueba',
            )
            UsuarioSede.objects.create(
                usuario=empleado, sede_id=nueva['id'], tenant=self.tenant,
            )

        respuesta = self._peticion('post', f'/api/sedes-admin/{nueva["id"]}/desactivar/', {})

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertIn('Solo Norte', respuesta.json()['usuarios_sin_sede'])

    def test_se_puede_reabrir_una_sede_cerrada(self):
        nueva = self._crear().json()
        self._peticion('post', f'/api/sedes-admin/{nueva["id"]}/desactivar/', {})

        respuesta = self._peticion('post', f'/api/sedes-admin/{nueva["id"]}/activar/', {})

        self.assertTrue(respuesta.json()['activa'])

    def test_el_listado_de_gestion_incluye_las_cerradas(self):
        """Si solo saliesen las activas, reactivar una sería imposible."""
        nueva = self._crear().json()
        self._peticion('post', f'/api/sedes-admin/{nueva["id"]}/desactivar/', {})

        respuesta = self._peticion('get', '/api/sedes-admin/')

        self.assertIn(nueva['id'], [s['id'] for s in respuesta.json()])

    def test_no_hay_borrado_de_sedes(self):
        """Ventas, gastos y stock la protegen con PROTECT."""
        respuesta = self._peticion('delete', f'/api/sedes-admin/{self.sede.id}/')

        self.assertEqual(respuesta.status_code, 405, respuesta.content)

    def test_el_selector_de_sedes_no_exige_el_permiso_de_gestion(self):
        """`GET /api/sedes/` lo usa cualquier sesión para saber dónde trabaja:
        exigir `config.sedes` dejaría a un recepcionista sin poder elegir."""
        _t, _r, sin_permiso = _crear_tenant_con_usuario(
            'sedessinperm', 'SSP', 'nadie@sedessinperm.example.com',
        )

        selector = self.client.get(
            '/api/sedes/', HTTP_HOST='sedessinperm.testserver', **_cabecera_token(sin_permiso),
        )
        gestion = self.client.get(
            '/api/sedes-admin/', HTTP_HOST='sedessinperm.testserver',
            **_cabecera_token(sin_permiso),
        )

        self.assertEqual(selector.status_code, 200, selector.content)
        self.assertEqual(gestion.status_code, 403, gestion.content)
