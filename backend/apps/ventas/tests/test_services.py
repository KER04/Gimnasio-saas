"""Batería de la capa de servicio de ventas (Parte E, escenarios 1, 2, 3, 4,
5, 6, 7, 8, 9, 10 y 11 del encargo). Los escenarios 12, 13 y 14 (costos
ocultos, permiso de anulación, aislamiento) se prueban a nivel HTTP en
``test_api.py``, porque dependen de la vista/serializer, no solo del servicio.

Usa ``TestCase`` (no ``TransactionTestCase``): estas pruebas no comprueban si
``app.tenant_id`` "sobrevive" fuera de una transacción (eso ya lo cubre
``apps/core/tests/test_aislamiento.py``); aquí solo se ejercitan las
funciones de ``services`` bajo un ``tenant_context`` normal, así que el
patrón rápido de ``TestCase`` alcanza.
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from apps.core.tenant import tenant_context
from apps.inventario.models import MovimientoInventario, StockSede
from apps.membresias.models import Membresia
from apps.organizacion.models import SecuenciaComprobante
from apps.ventas.models import DetalleVenta, Pago, Venta
from apps.ventas.services import VentaError, anular_venta, registrar_abono, registrar_venta

from .factories import crear_escenario_pos


def _item_producto(producto, cantidad):
    return {'tipo_item': DetalleVenta.TipoItemVenta.PRODUCTO, 'producto': producto, 'cantidad': cantidad}


def _item_plan(plan, cantidad=Decimal('1')):
    return {'tipo_item': DetalleVenta.TipoItemVenta.PLAN, 'plan': plan, 'cantidad': cantidad}


class RegistrarVentaProductoTestCase(TestCase):
    """Escenario 1: venta de producto."""

    @classmethod
    def setUpTestData(cls):
        cls.datos = crear_escenario_pos('svc-prod', 'P')

    def test_venta_de_producto_baja_stock_y_copia_precio_costo(self):
        datos = self.datos
        with tenant_context(datos['tenant'].id):
            stock_antes = StockSede.objects.get(producto=datos['producto'], sede=datos['sede']).cantidad
            self.assertEqual(stock_antes, Decimal('100.00'))

            venta = registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[_item_producto(datos['producto'], Decimal('3'))],
                monto_pago_inicial=Decimal('180000.00'), forma_pago=Pago.FormaPago.EFECTIVO,
            )

            stock_despues = StockSede.objects.get(producto=datos['producto'], sede=datos['sede']).cantidad
            self.assertEqual(stock_despues, Decimal('97.00'))

            detalle = venta.detalles.get()
            self.assertEqual(detalle.precio_unitario, datos['producto'].precio_venta)
            self.assertEqual(detalle.costo_unitario, datos['producto'].costo)
            self.assertEqual(detalle.total_linea, Decimal('3') * datos['producto'].precio_venta)
            self.assertEqual(venta.estado, Venta.EstadoVenta.PAGADA)

            movimiento = MovimientoInventario.objects.get(venta=venta)
            self.assertEqual(movimiento.tipo, MovimientoInventario.TipoMovimiento.SALIDA_VENTA)
            self.assertEqual(movimiento.cantidad, Decimal('-3.00'))
            self.assertEqual(movimiento.saldo_resultante, Decimal('97.00'))


class RegistrarVentaPlanTestCase(TestCase):
    """Escenarios 2, 3 y 4: planes con vigencia, por sesión y renovación."""

    @classmethod
    def setUpTestData(cls):
        cls.datos = crear_escenario_pos('svc-plan', 'M')

    def test_venta_plan_mensual_crea_membresia(self):
        datos = self.datos
        hoy = datetime.date.today()
        with tenant_context(datos['tenant'].id):
            venta = registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[_item_plan(datos['plan_mensual'])],
                cliente=datos['cliente'],
                monto_pago_inicial=datos['plan_mensual'].precio, forma_pago=Pago.FormaPago.EFECTIVO,
                fecha_inicio_membresia=hoy,
            )

            membresia = Membresia.objects.get(venta=venta)
            self.assertEqual(membresia.fecha_inicio, hoy)
            self.assertEqual(membresia.fecha_fin, hoy + datetime.timedelta(days=30))
            self.assertEqual(membresia.precio_pagado, datos['plan_mensual'].precio)
            self.assertIsNone(membresia.membresia_anterior)

    def test_venta_plan_por_sesion_no_crea_membresia(self):
        datos = self.datos
        with tenant_context(datos['tenant'].id):
            venta = registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[_item_plan(datos['plan_sesion'])],
                monto_pago_inicial=datos['plan_sesion'].precio, forma_pago=Pago.FormaPago.EFECTIVO,
            )

            self.assertEqual(Membresia.objects.filter(venta=venta).count(), 0)
            detalle = venta.detalles.get()
            self.assertEqual(detalle.categoria_ingreso.subcategoria, 'Por sesión')

    def test_renovacion_anticipada_encadena_desde_fecha_fin_anterior(self):
        """Escenario 4: si la membresía vigente todavía no vence, la
        renovación NO empieza hoy: empieza donde terminaba la anterior."""
        datos = self.datos
        hoy = datetime.date.today()
        with tenant_context(datos['tenant'].id):
            venta_1 = registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[_item_plan(datos['plan_mensual'])], cliente=datos['cliente'],
                monto_pago_inicial=datos['plan_mensual'].precio, forma_pago=Pago.FormaPago.EFECTIVO,
                fecha_inicio_membresia=hoy,
            )
            membresia_1 = Membresia.objects.get(venta=venta_1)

            # Renovación anticipada: se paga HOY, mucho antes de que la
            # primera membresía venza (hoy + 30 días).
            venta_2 = registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[_item_plan(datos['plan_mensual'])], cliente=datos['cliente'],
                monto_pago_inicial=datos['plan_mensual'].precio, forma_pago=Pago.FormaPago.EFECTIVO,
                fecha_inicio_membresia=hoy,
            )
            membresia_2 = Membresia.objects.get(venta=venta_2)

            self.assertEqual(membresia_2.fecha_inicio, membresia_1.fecha_fin)
            self.assertEqual(membresia_2.fecha_fin, membresia_1.fecha_fin + datetime.timedelta(days=30))
            self.assertEqual(membresia_2.membresia_anterior_id, membresia_1.id)


class ReglasDeNegocioTestCase(TestCase):
    """Escenarios 5 (crédito sin cliente), 6 (descuento sin motivo) y 8
    (stock insuficiente, sin venta a medias)."""

    @classmethod
    def setUpTestData(cls):
        cls.datos = crear_escenario_pos('svc-reglas', 'R')

    def test_venta_a_credito_sin_cliente_es_rechazada(self):
        datos = self.datos
        with tenant_context(datos['tenant'].id):
            with self.assertRaises(VentaError):
                registrar_venta(
                    tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                    items=[_item_producto(datos['producto'], Decimal('1'))],
                    cliente=None, monto_pago_inicial=Decimal('0'),
                )
            self.assertEqual(Venta.objects.count(), 0)

    def test_descuento_sin_motivo_es_rechazado(self):
        datos = self.datos
        with tenant_context(datos['tenant'].id):
            with self.assertRaises(VentaError):
                registrar_venta(
                    tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                    items=[_item_producto(datos['producto'], Decimal('1'))],
                    cliente=datos['cliente'], descuento=Decimal('1000'), motivo_descuento='',
                    monto_pago_inicial=datos['producto'].precio_venta - Decimal('1000'),
                    forma_pago=Pago.FormaPago.EFECTIVO,
                )
            self.assertEqual(Venta.objects.count(), 0)

    def test_stock_insuficiente_rechaza_y_no_deja_venta_a_medias(self):
        datos = self.datos
        with tenant_context(datos['tenant'].id):
            secuencia_antes = SecuenciaComprobante.objects.get(sede=datos['sede']).ultimo_numero

            with self.assertRaises(VentaError):
                registrar_venta(
                    tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                    items=[_item_producto(datos['producto'], Decimal('1000'))],
                    monto_pago_inicial=Decimal('0'),
                )

            # Nada quedó a medias: ni venta, ni detalle, ni movimiento nuevo,
            # ni siquiera el consecutivo avanzó (la transacción entera revirtió).
            self.assertEqual(Venta.objects.count(), 0)
            self.assertEqual(DetalleVenta.objects.count(), 0)
            self.assertEqual(
                MovimientoInventario.objects.filter(
                    tipo=MovimientoInventario.TipoMovimiento.SALIDA_VENTA,
                ).count(),
                0,
            )
            stock = StockSede.objects.get(producto=datos['producto'], sede=datos['sede'])
            self.assertEqual(stock.cantidad, Decimal('100.00'))
            secuencia_despues = SecuenciaComprobante.objects.get(sede=datos['sede']).ultimo_numero
            self.assertEqual(secuencia_despues, secuencia_antes)


class ConsecutivoTestCase(TestCase):
    """Escenario 7: consecutivo correlativo por sede, sin huecos; dos sedes
    llevan series independientes."""

    @classmethod
    def setUpTestData(cls):
        cls.datos = crear_escenario_pos('svc-consec', 'C')

    def test_consecutivo_por_sede_sin_huecos_y_series_independientes(self):
        datos = self.datos
        with tenant_context(datos['tenant'].id):
            venta_1 = registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[_item_producto(datos['producto'], Decimal('1'))],
                cliente=datos['cliente'], monto_pago_inicial=Decimal('0'),
            )
            self.assertEqual(venta_1.consecutivo, 1)

            # Una venta que falla (stock insuficiente) NO debe consumir un
            # número de la serie.
            with self.assertRaises(VentaError):
                registrar_venta(
                    tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                    items=[_item_producto(datos['producto'], Decimal('999999'))],
                    monto_pago_inicial=Decimal('0'),
                )

            venta_2 = registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[_item_producto(datos['producto'], Decimal('1'))],
                cliente=datos['cliente'], monto_pago_inicial=Decimal('0'),
            )
            self.assertEqual(venta_2.consecutivo, 2)

            # Otra sede del MISMO tenant lleva su propia serie, empezando en 1.
            venta_otra_sede = registrar_venta(
                tenant=datos['tenant'], sede=datos['sede2'], usuario=datos['usuario_admin'],
                items=[_item_plan(datos['plan_sesion'])],
                cliente=datos['cliente'], monto_pago_inicial=Decimal('0'),
            )
            self.assertEqual(venta_otra_sede.consecutivo, 1)


class AnularVentaTestCase(TestCase):
    """Escenario 9: la anulación revierte el stock, la venta sigue
    existiendo con estado 'anulada', y queda en auditoría."""

    @classmethod
    def setUpTestData(cls):
        cls.datos = crear_escenario_pos('svc-anular', 'AN')

    def test_anular_revierte_stock_y_deja_traza(self):
        datos = self.datos
        with tenant_context(datos['tenant'].id):
            venta = registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[_item_producto(datos['producto'], Decimal('10'))],
                cliente=datos['cliente'], monto_pago_inicial=Decimal('0'),
            )
            stock_tras_venta = StockSede.objects.get(producto=datos['producto'], sede=datos['sede']).cantidad
            self.assertEqual(stock_tras_venta, Decimal('90.00'))

            anular_venta(venta=venta, usuario=datos['usuario_admin'], motivo='Cliente se arrepintió')

            venta.refresh_from_db()
            self.assertEqual(venta.estado, Venta.EstadoVenta.ANULADA)
            self.assertEqual(venta.anulada_por_id, datos['usuario_admin'].id)
            self.assertIsNotNone(venta.anulada_en)
            # Nunca se borra: la venta sigue existiendo.
            self.assertTrue(Venta.objects.filter(pk=venta.pk).exists())

            stock_tras_anular = StockSede.objects.get(producto=datos['producto'], sede=datos['sede']).cantidad
            self.assertEqual(stock_tras_anular, Decimal('100.00'))

            reverso = MovimientoInventario.objects.get(
                venta=venta, tipo=MovimientoInventario.TipoMovimiento.REVERSO_ANULACION,
            )
            self.assertEqual(reverso.cantidad, Decimal('10.00'))

            from django.db import connections
            with connections['default'].cursor() as cursor:
                cursor.execute(
                    "SELECT accion FROM auditoria WHERE entidad = 'ventas' AND entidad_id = %s",
                    [venta.id],
                )
                acciones = {fila[0] for fila in cursor.fetchall()}
            self.assertIn('anular', acciones)

    def test_no_se_puede_anular_dos_veces(self):
        datos = self.datos
        with tenant_context(datos['tenant'].id):
            venta = registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[_item_producto(datos['producto'], Decimal('1'))],
                cliente=datos['cliente'], monto_pago_inicial=Decimal('0'),
            )
            anular_venta(venta=venta, usuario=datos['usuario_admin'], motivo='Motivo 1')
            venta.refresh_from_db()
            with self.assertRaises(VentaError):
                anular_venta(venta=venta, usuario=datos['usuario_admin'], motivo='Motivo 2')

    def test_anular_cancela_la_membresia_que_nacio_de_la_venta(self):
        """Si la venta no vale, el acceso que pagó tampoco.

        Dejar la membresía activa significaba que anular la venta de un plan
        le regalaba el mes al cliente: se revertía el dinero pero no el
        servicio.
        """
        from apps.membresias.models import Membresia

        datos = self.datos
        with tenant_context(datos['tenant'].id):
            venta = registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[_item_plan(datos['plan_mensual'])],
                cliente=datos['cliente'], monto_pago_inicial=Decimal('0'),
            )
            membresia = Membresia.objects.get(venta=venta)
            self.assertEqual(membresia.estado, Membresia.EstadoMembresia.ACTIVA)

            anular_venta(venta=venta, usuario=datos['usuario_admin'], motivo='Cobro duplicado')

            membresia.refresh_from_db()
            self.assertEqual(membresia.estado, Membresia.EstadoMembresia.CANCELADA)
            # El motivo tiene que permitir rastrear por qué se revocó el acceso.
            self.assertIn('Cobro duplicado', membresia.motivo_cancelacion)
            self.assertIn(str(venta.consecutivo), membresia.motivo_cancelacion)

            # Revocar el acceso de un cliente queda auditado por sí mismo, no
            # solo como efecto colateral de la anulación de la venta.
            from django.db import connections
            with connections['default'].cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM auditoria "
                    "WHERE entidad = 'membresias' AND entidad_id = %s AND accion = 'anular'",
                    [membresia.id],
                )
                self.assertEqual(cursor.fetchone()[0], 1)


class AbonosTestCase(TestCase):
    """Escenario 10: el saldo baja con cada abono y llega a 'pagada' en cero."""

    @classmethod
    def setUpTestData(cls):
        cls.datos = crear_escenario_pos('svc-abonos', 'AB')

    def test_abonos_bajan_saldo_y_pagan_en_cero(self):
        datos = self.datos
        with tenant_context(datos['tenant'].id):
            venta = registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[_item_producto(datos['producto'], Decimal('10'))],  # 10 * 60000 = 600000
                cliente=datos['cliente'], monto_pago_inicial=Decimal('0'),
            )
            self.assertEqual(venta.estado, Venta.EstadoVenta.PENDIENTE)

            registrar_abono(
                venta=venta, usuario=datos['usuario_admin'],
                monto=Decimal('200000'), forma_pago=Pago.FormaPago.EFECTIVO,
            )
            venta.refresh_from_db()
            self.assertEqual(venta.estado, Venta.EstadoVenta.PARCIAL)

            registrar_abono(
                venta=venta, usuario=datos['usuario_admin'],
                monto=Decimal('400000'), forma_pago=Pago.FormaPago.TRANSFERENCIA,
            )
            venta.refresh_from_db()
            self.assertEqual(venta.estado, Venta.EstadoVenta.PAGADA)

    def test_abono_no_puede_superar_el_saldo(self):
        datos = self.datos
        with tenant_context(datos['tenant'].id):
            venta = registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[_item_producto(datos['producto'], Decimal('1'))],  # 60000
                cliente=datos['cliente'], monto_pago_inicial=Decimal('0'),
            )
            with self.assertRaises(VentaError):
                registrar_abono(
                    venta=venta, usuario=datos['usuario_admin'],
                    monto=Decimal('999999'), forma_pago=Pago.FormaPago.EFECTIVO,
                )

    def test_no_se_puede_abonar_a_venta_anulada(self):
        datos = self.datos
        with tenant_context(datos['tenant'].id):
            venta = registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[_item_producto(datos['producto'], Decimal('1'))],
                cliente=datos['cliente'], monto_pago_inicial=Decimal('0'),
            )
            anular_venta(venta=venta, usuario=datos['usuario_admin'], motivo='Error de cobro')
            venta.refresh_from_db()
            with self.assertRaises(VentaError):
                registrar_abono(
                    venta=venta, usuario=datos['usuario_admin'],
                    monto=Decimal('1000'), forma_pago=Pago.FormaPago.EFECTIVO,
                )


class CajaRealTestCase(TestCase):
    """Escenario 11: el ingreso del día es la suma de `pagos`, no el total
    de las ventas (una venta parcial no aporta su total completo a caja)."""

    @classmethod
    def setUpTestData(cls):
        cls.datos = crear_escenario_pos('svc-caja', 'CJ')

    def test_ingreso_del_dia_es_suma_de_pagos_no_total_de_ventas(self):
        datos = self.datos
        with tenant_context(datos['tenant'].id):
            # Venta 1: de contado, paga el total (600000).
            registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[_item_producto(datos['producto'], Decimal('10'))],
                monto_pago_inicial=Decimal('600000'), forma_pago=Pago.FormaPago.EFECTIVO,
            )
            # Venta 2: a crédito con abono inicial de solo 100000 sobre 300000.
            venta_2 = registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[_item_producto(datos['producto'], Decimal('5'))],  # 300000
                cliente=datos['cliente'], monto_pago_inicial=Decimal('100000'),
                forma_pago=Pago.FormaPago.EFECTIVO,
            )

            total_ventas = sum((v.total for v in Venta.objects.all()), Decimal('0'))
            total_pagos = sum((p.monto for p in Pago.objects.all()), Decimal('0'))

            # 600000 (venta 1) + 300000 (venta 2) = 900000 de VALOR vendido...
            self.assertEqual(total_ventas, Decimal('900000.00'))
            # ...pero lo que efectivamente entró a caja es solo 700000.
            self.assertEqual(total_pagos, Decimal('700000.00'))
            self.assertNotEqual(total_ventas, total_pagos)

            venta_2.refresh_from_db()
            self.assertEqual(venta_2.estado, Venta.EstadoVenta.PARCIAL)
