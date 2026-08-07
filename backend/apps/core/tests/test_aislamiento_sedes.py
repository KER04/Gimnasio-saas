"""Aislamiento ENTRE SEDES del mismo gimnasio.

Distinto del aislamiento entre gimnasios, que lo garantiza RLS en PostgreSQL.
RLS acota por TENANT, no por sede: todas las sedes de un gimnasio comparten
las mismas políticas, así que sin lo que se prueba aquí un recepcionista de
Sede Norte podía consultar la caja, las ventas y la cartera de Sede Principal
sencillamente pidiéndolas.

Lo que NO se aísla, a propósito: los clientes son del gimnasio y pueden
entrenar donde quieran; el catálogo de productos, los planes y los ejercicios
también son del gimnasio.
"""
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.autenticacion.tests.test_auth import _cabecera_token, _crear_tenant_con_usuario
from apps.clientes.models import Cliente
from apps.core.tenant import tenant_context
from apps.organizacion.models import Permiso, Rol, RolPermiso, Sede, UsuarioSede, Usuario
from apps.ventas.models import Venta

_ALLOWED_HOSTS_PRUEBA = ['testserver', '.testserver']
PASSWORD = 'clave-de-prueba-1234'


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class AislamientoEntreSedesTestCase(TestCase):
    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        # El dueño: tiene `config.sedes`, así que ve el gimnasio entero.
        cls.tenant, cls.rol_duenio, cls.duenio = _crear_tenant_con_usuario(
            'aislasedes', 'AS', 'duenio@aislasedes.example.com',
            permisos=('reportes.ver', 'ventas.registrar', 'config.sedes', 'inventario.ver'),
        )

        with tenant_context(cls.tenant.id):
            cls.norte = Sede.objects.create(
                tenant=cls.tenant, nombre='Norte', direccion='Calle 1',
            )
            cls.sur = Sede.objects.create(
                tenant=cls.tenant, nombre='Sur', direccion='Calle 2',
            )

            # Un recepcionista SIN `config.sedes`, asignado solo a Norte.
            cls.rol_recepcion = Rol.objects.create(
                tenant=cls.tenant, nombre='Recepcionista', es_sistema=True,
            )
            por_codigo = {p.codigo: p for p in Permiso.objects.all()}
            RolPermiso.objects.bulk_create([
                RolPermiso(rol=cls.rol_recepcion, permiso=por_codigo[c], tenant=cls.tenant)
                for c in ('reportes.ver', 'ventas.registrar', 'inventario.ver', 'clientes.ver')
            ])
            cls.recepcion = Usuario.objects.create_user(
                correo='norte@aislasedes.example.com', nombre='Recepción Norte',
                tenant=cls.tenant, rol=cls.rol_recepcion, password=PASSWORD,
            )
            UsuarioSede.objects.create(
                usuario=cls.recepcion, sede=cls.norte, tenant=cls.tenant,
            )

            # Y otro sin NINGUNA sede asignada.
            cls.sin_sede = Usuario.objects.create_user(
                correo='sinsede@aislasedes.example.com', nombre='Sin Sede',
                tenant=cls.tenant, rol=cls.rol_recepcion, password=PASSWORD,
            )

            cls.cliente = Cliente.objects.create(
                tenant=cls.tenant, sede_origen=cls.norte, nombre='Socio',
                cedula='7001', telefono='300', direccion='Calle 3',
            )
            # Una venta en cada sede, con importes distintos para poder
            # distinguirlas de un vistazo.
            cls.venta_norte = Venta.objects.create(
                tenant=cls.tenant, sede=cls.norte, cliente=cls.cliente,
                usuario=cls.recepcion, consecutivo=1, subtotal=Decimal('100'),
                total=Decimal('100'),
            )
            cls.venta_sur = Venta.objects.create(
                tenant=cls.tenant, sede=cls.sur, cliente=cls.cliente,
                usuario=cls.duenio, consecutivo=1, subtotal=Decimal('900'),
                total=Decimal('900'),
            )

    def setUp(self):
        cache.clear()

    def _get(self, url, usuario):
        return self.client.get(
            url, HTTP_HOST='aislasedes.testserver', **_cabecera_token(usuario),
        )

    # --- Lo que SÍ se aísla ---------------------------------------------

    def test_solo_ve_las_ventas_de_su_sede(self):
        respuesta = self._get('/api/ventas/', self.recepcion)

        ids = [v['id'] for v in respuesta.json()['results']]
        self.assertIn(self.venta_norte.id, ids)
        self.assertNotIn(self.venta_sur.id, ids)

    def test_el_informe_de_ventas_no_suma_la_otra_sede(self):
        """El caso que lo hizo evidente: la caja del gimnasio entero se veía
        desde cualquier sede."""
        respuesta = self._get('/api/reportes/ventas/', self.recepcion)

        self.assertEqual(Decimal(respuesta.json()['facturado']), Decimal('100'))

    def test_pedir_otra_sede_da_403_y_no_una_lista_vacia(self):
        """Un cero silencioso se lee como "ese día no hubo ventas", que es
        una respuesta falsa. El 403 dice la verdad: no es tuya."""
        respuesta = self._get(f'/api/reportes/ventas/?sede={self.sur.id}', self.recepcion)

        self.assertEqual(respuesta.status_code, 403, respuesta.content)

    def test_puede_pedir_explicitamente_la_suya(self):
        respuesta = self._get(f'/api/reportes/ventas/?sede={self.norte.id}', self.recepcion)

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertEqual(Decimal(respuesta.json()['facturado']), Decimal('100'))

    def test_la_cartera_tambien_se_acota(self):
        """La deuda de la otra sede es información de la otra sede."""
        respuesta = self._get(f'/api/reportes/cartera/?sede={self.sur.id}', self.recepcion)

        self.assertEqual(respuesta.status_code, 403, respuesta.content)

    def test_sin_sede_asignada_no_ve_nada(self):
        """Coherente con que tampoco pueda vender ni cobrar. La pantalla lo
        explica en vez de enseñar ceros sin motivo."""
        ventas = self._get('/api/ventas/', self.sin_sede)
        informe = self._get('/api/reportes/ventas/', self.sin_sede)

        self.assertEqual(len(ventas.json()['results']), 0)
        self.assertEqual(Decimal(informe.json()['facturado']), Decimal('0'))

    # --- Lo que NO se aísla ---------------------------------------------

    def test_el_duenio_ve_el_consolidado(self):
        """§2.1 del encargo: el dueño ve "todas las sedes... reportes
        consolidados". Se distingue por el PERMISO `config.sedes`, no por el
        nombre del rol, porque los roles son configurables."""
        respuesta = self._get('/api/reportes/ventas/', self.duenio)

        self.assertEqual(Decimal(respuesta.json()['facturado']), Decimal('1000'))

    def test_el_duenio_puede_pedir_cualquier_sede(self):
        respuesta = self._get(f'/api/reportes/ventas/?sede={self.sur.id}', self.duenio)

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertEqual(Decimal(respuesta.json()['facturado']), Decimal('900'))

    def test_los_clientes_son_del_gimnasio_y_no_de_una_sede(self):
        """Un socio puede entrenar en cualquier sede sin volver a darse de
        alta: `sede_origen` solo registra dónde se inscribió."""
        respuesta = self._get('/api/clientes/', self.recepcion)

        self.assertIn(self.cliente.id, [c['id'] for c in respuesta.json()['results']])
