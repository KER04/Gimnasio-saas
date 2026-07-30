"""Batería OBLIGATORIA de aislamiento multi-tenant (Row Level Security).

## Por qué esta suite usa TransactionTestCase y NO TestCase

``django.test.TestCase`` envuelve cada método de prueba en una transacción
que nunca se confirma (hace ROLLBACK al final para aislar pruebas entre sí).
Cualquier ``transaction.atomic()`` que se abra DENTRO de un método de prueba
queda entonces ANIDADO dentro de esa transacción exterior, y Django lo
implementa con SAVEPOINTs, no con transacciones reales. La diferencia
importa muchísimo para esta suite en concreto: ``set_config(..., true)``
(el equivalente de ``SET LOCAL``) solo se deshace en un COMMIT o ROLLBACK de
transacción real; un simple ``RELEASE SAVEPOINT`` (que es lo que pasa al
salir con éxito de un ``with tenant_context(...)`` anidado) NO lo deshace.

Eso significa que, bajo ``TestCase``, la prueba "tras salir de
tenant_context, app.tenant_id ya no está fijado" DARÍA FALSO POSITIVO (el
valor seguiría fijado porque solo hubo un RELEASE SAVEPOINT) o, peor,
enmascararía una fuga real. Como el propio encargo insiste en que una prueba
de aislamiento mal escrita es peor que no tenerla, esta suite usa
``TransactionTestCase``: cada método de prueba corre SIN una transacción
exterior ya abierta (Django aísla las pruebas con TRUNCATE al final, no con
ROLLBACK), así que un ``tenant_context`` de nivel superior es una
transacción real y su salida sí dispara un COMMIT/ROLLBACK real que revierte
``app.tenant_id``.

El costo es que no se puede usar ``setUpTestData`` (es exclusivo de
``TestCase``); se siembra en ``setUp`` para cada método.
"""
from django.db import DatabaseError, connections
from django.test import TransactionTestCase

from apps.asistencia.models import Asistencia, IntentoBiometricoFallido
from apps.auditoria.models import (
    Auditoria,
    VistaCorteDiario,
    VistaMembresiaEstado,
    VistaVentaSaldo,
)
from apps.clientes.models import AutorizacionDatos, Cliente, DispositivoBiometrico, HuellaCliente
from apps.core.tenant import tenant_context
from apps.entrenamiento.models import (
    ControlMedida,
    Ejercicio,
    FichaMedidas,
    GrupoMuscular,
    RecordPersonal,
    RegistroEjercicio,
    Rutina,
    RutinaDia,
    RutinaEjercicio,
)
from apps.inventario.models import CategoriaProducto, MovimientoInventario, Producto, StockSede
from apps.membresias.models import Membresia, Plan
from apps.organizacion.models import Rol, RolPermiso, SecuenciaComprobante, Sede, Usuario, UsuarioSede
from apps.ventas.models import CategoriaGasto, CategoriaIngreso, DetalleVenta, Gasto, IngresoOtro, Pago, Venta

from .factories import crear_tenant_completo

# Las 12 tablas que `crear_tenant_completo` siembra con una fila por tenant.
# Permiten la comprobación FUERTE: no solo "cuántas filas", sino "cuáles
# filas exactamente" (por id) ve cada tenant.
MODELOS_SEMBRADOS = [
    (Sede, 'sede'),
    (Rol, 'rol'),
    (Usuario, 'usuario'),
    (Cliente, 'cliente'),
    (Plan, 'plan'),
    (CategoriaProducto, 'categoria_producto'),
    (Producto, 'producto'),
    (CategoriaIngreso, 'categoria_ingreso'),
    (Membresia, 'membresia'),
    (Venta, 'venta'),
    (DetalleVenta, 'detalle_venta'),
    (Pago, 'pago'),
]

# Las 35 tablas de negocio con RLS (sección 17 del .sql / SQL_RLS de
# apps/core/migrations/0001_esquema_postgres.py), para la prueba "sin
# contexto". Las que no están en MODELOS_SEMBRADOS quedan vacías porque la
# fábrica no las puebla (no lo pide el encargo de C1); su conteo en 0 es
# entonces una comprobación más débil (no distingue "vacía por RLS" de
# "vacía porque no hay filas"), pero sigue confirmando que RLS existe sobre
# ellas y que ninguna consulta revienta al no haber tenant fijado.
TODOS_LOS_MODELOS_RLS = [
    Sede, SecuenciaComprobante, Rol, RolPermiso, Usuario, UsuarioSede,
    Cliente, AutorizacionDatos, HuellaCliente, DispositivoBiometrico,
    Plan, Membresia,
    CategoriaProducto, CategoriaIngreso, Producto, StockSede, MovimientoInventario,
    Venta, DetalleVenta, Pago, IngresoOtro, CategoriaGasto, Gasto,
    Asistencia, IntentoBiometricoFallido,
    FichaMedidas, ControlMedida, GrupoMuscular, Ejercicio, Rutina,
    RutinaDia, RutinaEjercicio, RegistroEjercicio, RecordPersonal,
    Auditoria,
]
assert len(TODOS_LOS_MODELOS_RLS) == 35

VISTAS = [VistaMembresiaEstado, VistaVentaSaldo, VistaCorteDiario]


class AislamientoTenantTestCase(TransactionTestCase):
    """Dos tenants sembrados (A y B); cada prueba verifica una faceta del
    aislamiento por RLS."""

    def setUp(self):
        self.datos_a = crear_tenant_completo('aisla', 'A', using='default')
        self.datos_b = crear_tenant_completo('aislb', 'B', using='default')

    # ------------------------------------------------------------------
    # test por tabla
    # ------------------------------------------------------------------
    def test_aislamiento_por_tabla(self):
        """Para cada tabla sembrada, con el contexto de A solo se ve la fila
        de A (por id, no solo por conteo); ídem para B."""
        for modelo, clave in MODELOS_SEMBRADOS:
            with self.subTest(modelo=modelo.__name__, tenant='A'):
                with tenant_context(self.datos_a['tenant'].id):
                    ids_vistos = set(
                        modelo.objects.using('default').values_list('pk', flat=True),
                    )
                self.assertEqual(ids_vistos, {self.datos_a[clave].pk})

            with self.subTest(modelo=modelo.__name__, tenant='B'):
                with tenant_context(self.datos_b['tenant'].id):
                    ids_vistos = set(
                        modelo.objects.using('default').values_list('pk', flat=True),
                    )
                self.assertEqual(ids_vistos, {self.datos_b[clave].pk})

    # ------------------------------------------------------------------
    # test de vistas
    # ------------------------------------------------------------------
    def test_vistas_respetan_aislamiento(self):
        """v_membresias_estado, v_ventas_saldo y v_corte_diario deben
        filtrar por tenant igual que las tablas base, gracias a
        security_invoker=true (sin eso, PostgreSQL las evalúa con los
        privilegios del dueño de la vista -superusuario- y devuelven filas de
        TODOS los tenants: el fallo real que motivó esta prueba)."""
        with tenant_context(self.datos_a['tenant'].id):
            membresias = list(VistaMembresiaEstado.objects.using('default').all())
            ventas_saldo = list(VistaVentaSaldo.objects.using('default').all())
            corte = list(VistaCorteDiario.objects.using('default').all())

        self.assertEqual({m.id for m in membresias}, {self.datos_a['membresia'].id})
        self.assertEqual({v.venta_id for v in ventas_saldo}, {self.datos_a['venta'].id})
        self.assertEqual(len(corte), 1)
        self.assertEqual(corte[0].tenant_id, self.datos_a['tenant'].id)
        self.assertEqual(corte[0].sede_id, self.datos_a['sede'].id)

        with tenant_context(self.datos_b['tenant'].id):
            membresias = list(VistaMembresiaEstado.objects.using('default').all())
            ventas_saldo = list(VistaVentaSaldo.objects.using('default').all())
            corte = list(VistaCorteDiario.objects.using('default').all())

        self.assertEqual({m.id for m in membresias}, {self.datos_b['membresia'].id})
        self.assertEqual({v.venta_id for v in ventas_saldo}, {self.datos_b['venta'].id})
        self.assertEqual(len(corte), 1)
        self.assertEqual(corte[0].tenant_id, self.datos_b['tenant'].id)
        self.assertEqual(corte[0].sede_id, self.datos_b['sede'].id)

    # ------------------------------------------------------------------
    # test de escritura cruzada
    # ------------------------------------------------------------------
    def test_escritura_cruzada_falla(self):
        """Estando en el contexto de A, insertar una fila cuyo tenant_id es
        el de B debe fallar: viola la política WITH CHECK
        (tenant_id = fn_tenant_actual())."""
        with self.assertRaises(DatabaseError):
            with tenant_context(self.datos_a['tenant'].id):
                # Fila por lo demás perfectamente válida PARA B (usa la sede
                # y sub-referencias de B): lo único "ajeno" es que se intenta
                # crear mientras la sesión cree ser A. Así se aísla que el
                # fallo es RLS y no una FK rota.
                Cliente.objects.using('default').create(
                    tenant=self.datos_b['tenant'],
                    sede_origen=self.datos_b['sede'],
                    nombre='Intruso',
                    cedula='HACKER-0001',
                    telefono='3000000001',
                    direccion='Calle intrusa',
                )

        # La fila NO debe haber quedado creada en ningún lado: el INSERT
        # entero se revirtió junto con la transacción de tenant_context.
        with tenant_context(self.datos_b['tenant'].id):
            cedulas_b = set(
                Cliente.objects.using('default').values_list('cedula', flat=True),
            )
        self.assertNotIn('HACKER-0001', cedulas_b)

    # ------------------------------------------------------------------
    # test sin contexto
    # ------------------------------------------------------------------
    def test_sin_contexto_devuelve_cero_filas(self):
        """Sin app.tenant_id fijado, TODA tabla de negocio (con o sin filas
        sembradas) y las 3 vistas devuelven 0 filas."""
        for modelo in TODOS_LOS_MODELOS_RLS + VISTAS:
            with self.subTest(modelo=modelo.__name__):
                self.assertEqual(modelo.objects.using('default').count(), 0)

    # ------------------------------------------------------------------
    # test de fuga entre transacciones
    # ------------------------------------------------------------------
    def test_fuga_entre_transacciones(self):
        """Tras salir de un tenant_context, current_setting('app.tenant_id')
        vuelve a estar vacío: el valor no sobrevive a la transacción en la
        que se fijó ni puede filtrarse a la siguiente consulta/transacción
        que reutilice la misma conexión."""
        with tenant_context(self.datos_a['tenant'].id):
            with connections['default'].cursor() as cursor:
                cursor.execute("SELECT current_setting('app.tenant_id', true)")
                (valor_dentro,) = cursor.fetchone()
        self.assertEqual(valor_dentro, str(self.datos_a['tenant'].id))

        with connections['default'].cursor() as cursor:
            cursor.execute("SELECT current_setting('app.tenant_id', true)")
            (valor_fuera,) = cursor.fetchone()
        self.assertIn(valor_fuera, (None, ''))

        # Y, coherentemente, sin el valor fijado las consultas vuelven a ver
        # cero filas de negocio.
        self.assertEqual(Cliente.objects.using('default').count(), 0)
