"""Batería de los informes: ventas, caja, cartera, productos y utilidad.

Mismo patrón que ``apps/ventas/tests/test_api.py`` y reutilizando su fábrica.

Lo que se protege aquí son sobre todo DECISIONES, no cálculos:

- **Facturado y cobrado no son el mismo número.** Con abonos divergen, y el
  informe devuelve los dos por separado en vez de elegir uno y llamarlo
  "ventas".
- **La utilidad cuenta al VENDER, no al cobrar.** El producto ya salió del
  inventario, así que su costo ya se cargó; medir el ingreso más tarde
  inventaría una pérdida en el periodo de la venta y una ganancia en el del
  cobro. ``pendiente_de_cobro`` existe para que esa cifra no se lea como
  dinero disponible.
- **Productos y planes no se suman.** Un plan no tiene costo de adquisición;
  lo que cuesta prestarlo son los gastos operativos.
- **Las anuladas no cuentan** en ningún informe.
- **``/reportes/utilidad/`` exige ``costos.ver``**, no ``reportes.ver``: es
  el permiso que separa a quien puede ver márgenes, y este informe no es más
  que esos costos agregados.
"""
from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.core.tenant import tenant_context
from apps.ventas.models import DetalleVenta
from apps.ventas.services import anular_venta, registrar_abono, registrar_venta
from apps.ventas.tests.factories import crear_escenario_pos

_ALLOWED_HOSTS_PRUEBA = ['testserver', '.testserver']


def _token_para(usuario):
    access = AccessToken.for_user(usuario)
    access['tenant_id'] = usuario.tenant_id
    return str(access)


def _auth_headers(usuario, subdominio):
    return {
        'HTTP_HOST': f'{subdominio}.testserver',
        'HTTP_AUTHORIZATION': f'Bearer {_token_para(usuario)}',
    }


def _vender_producto(datos, cantidad, pagado, cliente=None):
    """Vende ``cantidad`` unidades del producto de la fábrica cobrando
    ``pagado``. Con ``pagado`` menor que el total, la venta queda con saldo."""
    with tenant_context(datos['tenant'].id):
        return registrar_venta(
            tenant=datos['tenant'],
            sede=datos['sede'],
            usuario=datos['usuario_admin'],
            cliente=cliente if cliente is not None else datos['cliente'],
            items=[{
                'tipo_item': DetalleVenta.TipoItemVenta.PRODUCTO,
                'producto': datos['producto'],
                'cantidad': Decimal(cantidad),
            }],
            forma_pago='efectivo' if Decimal(pagado) > 0 else None,
            monto_pago_inicial=Decimal(pagado),
        )


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ReporteVentasTestCase(TestCase):
    databases = {'default', 'ddl'}
    SUBDOMINIO = 'rep-ventas'

    @classmethod
    def setUpTestData(cls):
        cls.datos = crear_escenario_pos(cls.SUBDOMINIO, 'RV')
        # 2 unidades a 60.000 = 120.000, de los que se cobran 50.000.
        cls.venta = _vender_producto(cls.datos, '2', '50000')

    def _informe(self):
        return self.client.get(
            '/api/reportes/ventas/',
            **_auth_headers(self.datos['usuario_admin'], self.SUBDOMINIO),
        ).json()

    def test_facturado_y_cobrado_divergen_con_una_venta_a_credito(self):
        informe = self._informe()

        self.assertEqual(Decimal(informe['facturado']), Decimal('120000.00'))
        self.assertEqual(Decimal(informe['cobrado']), Decimal('50000.00'))
        self.assertEqual(Decimal(informe['diferencia']), Decimal('70000.00'))

    def test_el_abono_mueve_lo_cobrado_pero_no_lo_facturado(self):
        with tenant_context(self.datos['tenant'].id):
            registrar_abono(
                venta=self.venta, usuario=self.datos['usuario_admin'],
                monto=Decimal('70000'), forma_pago='efectivo',
            )

        informe = self._informe()
        self.assertEqual(Decimal(informe['facturado']), Decimal('120000.00'))
        self.assertEqual(Decimal(informe['cobrado']), Decimal('120000.00'))
        self.assertEqual(Decimal(informe['diferencia']), Decimal('0.00'))

    def test_la_venta_anulada_no_cuenta(self):
        with tenant_context(self.datos['tenant'].id):
            anular_venta(
                venta=self.venta, usuario=self.datos['usuario_admin'], motivo='Prueba',
            )

        informe = self._informe()
        self.assertEqual(Decimal(informe['facturado']), Decimal('0.00'))
        self.assertEqual(Decimal(informe['cobrado']), Decimal('0.00'))
        self.assertEqual(informe['numero_ventas'], 0)

    def test_un_periodo_sin_ventas_devuelve_cero_y_no_nulo(self):
        informe = self.client.get(
            '/api/reportes/ventas/?desde=2000-01-01&hasta=2000-01-31',
            **_auth_headers(self.datos['usuario_admin'], self.SUBDOMINIO),
        ).json()

        self.assertEqual(Decimal(informe['facturado']), Decimal('0'))
        self.assertEqual(informe['numero_ventas'], 0)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ReporteCajaTestCase(TestCase):
    databases = {'default', 'ddl'}
    SUBDOMINIO = 'rep-caja'

    @classmethod
    def setUpTestData(cls):
        cls.datos = crear_escenario_pos(cls.SUBDOMINIO, 'RC')
        _vender_producto(cls.datos, '1', '60000')

    def _caja(self, agrupar='dia'):
        return self.client.get(
            f'/api/reportes/caja/?agrupar={agrupar}',
            **_auth_headers(self.datos['usuario_admin'], self.SUBDOMINIO),
        ).json()

    def test_cuenta_el_dinero_recibido_por_forma_de_pago(self):
        caja = self._caja()

        self.assertEqual(Decimal(caja['totales']['total_recibido']), Decimal('60000.00'))
        self.assertEqual(Decimal(caja['totales']['efectivo']), Decimal('60000.00'))
        self.assertEqual(Decimal(caja['totales']['tarjeta']), Decimal('0'))

    def test_agrupar_por_mes_conserva_el_total(self):
        """Agrupar es repartir las mismas filas: el total no puede cambiar."""
        por_dia = self._caja('dia')
        por_mes = self._caja('mes')

        self.assertEqual(por_mes['agrupar'], 'mes')
        self.assertEqual(
            Decimal(por_mes['totales']['total_recibido']),
            Decimal(por_dia['totales']['total_recibido']),
        )

    def test_una_venta_a_credito_no_entra_en_caja(self):
        antes = Decimal(self._caja()['totales']['total_recibido'])

        _vender_producto(self.datos, '1', '0')

        self.assertEqual(Decimal(self._caja()['totales']['total_recibido']), antes)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ReporteCarteraTestCase(TestCase):
    databases = {'default', 'ddl'}
    SUBDOMINIO = 'rep-cartera'

    @classmethod
    def setUpTestData(cls):
        cls.datos = crear_escenario_pos(cls.SUBDOMINIO, 'RCa')
        cls.venta = _vender_producto(cls.datos, '2', '20000')  # debe 100.000

    def _cartera(self):
        return self.client.get(
            '/api/reportes/cartera/',
            **_auth_headers(self.datos['usuario_admin'], self.SUBDOMINIO),
        ).json()

    def test_agrupa_la_deuda_por_cliente(self):
        cartera = self._cartera()

        self.assertEqual(Decimal(cartera['totales']['saldo']), Decimal('100000.00'))
        self.assertEqual(cartera['totales']['clientes'], 1)
        deudor = cartera['deudores'][0]
        self.assertEqual(deudor['cliente_id'], self.datos['cliente'].id)
        # El número visible es el consecutivo del recibo, no el id interno.
        self.assertEqual(deudor['ventas'][0]['consecutivo'], self.venta.consecutivo)

    def test_al_cobrar_desaparece_de_la_cartera(self):
        with tenant_context(self.datos['tenant'].id):
            registrar_abono(
                venta=self.venta, usuario=self.datos['usuario_admin'],
                monto=Decimal('100000'), forma_pago='efectivo',
            )

        cartera = self._cartera()
        self.assertEqual(Decimal(cartera['totales']['saldo']), Decimal('0'))
        self.assertEqual(cartera['deudores'], [])

    def test_anular_la_venta_retira_la_deuda(self):
        """Cancelar una membresía NO borra la deuda; anular la venta sí. Es la
        confusión que la interfaz advierte y aquí queda fijada."""
        with tenant_context(self.datos['tenant'].id):
            anular_venta(
                venta=self.venta, usuario=self.datos['usuario_admin'], motivo='Cobro por error',
            )

        self.assertEqual(Decimal(self._cartera()['totales']['saldo']), Decimal('0'))


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ReporteUtilidadTestCase(TestCase):
    databases = {'default', 'ddl'}
    SUBDOMINIO = 'rep-util'

    @classmethod
    def setUpTestData(cls):
        cls.datos = crear_escenario_pos(cls.SUBDOMINIO, 'RU')

    def _utilidad(self, usuario=None):
        return self.client.get(
            '/api/reportes/utilidad/',
            **_auth_headers(usuario or self.datos['usuario_admin'], self.SUBDOMINIO),
        )

    def test_exige_costos_ver_y_no_reportes_ver(self):
        """El recepcionista TIENE ``reportes.ver`` y aun así no puede entrar:
        si bastara con ese permiso, sería una puerta trasera a los costos que
        el resto de la API le oculta."""
        respuesta = self._utilidad(self.datos['usuario_recepcion'])

        self.assertEqual(respuesta.status_code, 403)

    def test_utilidad_es_ingresos_menos_costo_copiado_en_la_linea(self):
        # 2 unidades: precio 60.000, costo 35.000 -> utilidad 50.000.
        _vender_producto(self.datos, '2', '120000')

        informe = self._utilidad().json()

        productos = informe['productos']
        self.assertEqual(Decimal(productos['ingresos']), Decimal('120000.00'))
        self.assertEqual(Decimal(productos['costo']), Decimal('70000.00'))
        self.assertEqual(Decimal(productos['utilidad']), Decimal('50000.00'))
        self.assertEqual(productos['margen_pct'], '41.7')

    def test_cuenta_al_vender_aunque_no_se_haya_cobrado(self):
        """Una venta fiada suma a la utilidad desde el momento de la venta: el
        costo ya salió del inventario. Lo que avisa de que ese dinero no está
        en caja es ``pendiente_de_cobro``."""
        _vender_producto(self.datos, '2', '0')

        informe = self._utilidad().json()

        self.assertEqual(Decimal(informe['productos']['utilidad']), Decimal('50000.00'))
        self.assertEqual(Decimal(informe['pendiente_de_cobro']), Decimal('120000.00'))

    def test_cobrar_no_cambia_la_utilidad_pero_vacia_lo_pendiente(self):
        venta = _vender_producto(self.datos, '2', '0')
        utilidad_antes = self._utilidad().json()['productos']['utilidad']

        with tenant_context(self.datos['tenant'].id):
            registrar_abono(
                venta=venta, usuario=self.datos['usuario_admin'],
                monto=Decimal('120000'), forma_pago='efectivo',
            )

        despues = self._utilidad().json()
        self.assertEqual(despues['productos']['utilidad'], utilidad_antes)
        self.assertEqual(Decimal(despues['pendiente_de_cobro']), Decimal('0'))

    def test_los_planes_van_aparte_y_sin_utilidad(self):
        """Un plan no tiene costo de adquisición. Sumar sus ingresos como
        ganancia daría una cifra falsa: lo que cuesta prestarlo son los gastos
        operativos, que van por su lado."""
        with tenant_context(self.datos['tenant'].id):
            registrar_venta(
                tenant=self.datos['tenant'], sede=self.datos['sede'],
                usuario=self.datos['usuario_admin'], cliente=self.datos['cliente'],
                items=[{
                    'tipo_item': DetalleVenta.TipoItemVenta.PLAN,
                    'plan': self.datos['plan_mensual'],
                    'cantidad': Decimal('1'),
                }],
                forma_pago='efectivo', monto_pago_inicial=Decimal('80000'),
            )

        informe = self._utilidad().json()

        self.assertEqual(Decimal(informe['planes']['ingresos']), Decimal('80000.00'))
        # El plan no ensucia la utilidad de productos.
        self.assertEqual(Decimal(informe['productos']['ingresos']), Decimal('0'))
        self.assertEqual(Decimal(informe['productos']['costo']), Decimal('0'))

    def test_sin_gastos_registrados_lo_dice(self):
        informe = self._utilidad().json()

        self.assertEqual(informe['gastos']['registrados'], 0)
        self.assertEqual(Decimal(informe['gastos']['total']), Decimal('0'))

    def test_margen_sin_ventas_no_es_cero_por_ciento(self):
        """Sin base sobre la que calcular se devuelve '—': un margen del 0% y
        "no hubo ventas" no son lo mismo."""
        informe = self._utilidad().json()

        self.assertEqual(informe['productos']['margen_pct'], '—')

    def test_el_detalle_va_ordenado_por_ingresos(self):
        _vender_producto(self.datos, '1', '60000')

        detalle = self._utilidad().json()['detalle']

        self.assertEqual(len(detalle), 1)
        self.assertEqual(detalle[0]['producto_id'], self.datos['producto'].id)
        self.assertEqual(Decimal(detalle[0]['utilidad']), Decimal('25000.00'))


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ReporteProductosTestCase(TestCase):
    databases = {'default', 'ddl'}
    SUBDOMINIO = 'rep-prod'

    @classmethod
    def setUpTestData(cls):
        cls.datos = crear_escenario_pos(cls.SUBDOMINIO, 'RP')
        _vender_producto(cls.datos, '3', '180000')

    def test_unidades_importe_y_existencias_actuales(self):
        informe = self.client.get(
            '/api/reportes/productos/',
            **_auth_headers(self.datos['usuario_admin'], self.SUBDOMINIO),
        ).json()

        fila = informe['productos'][0]
        self.assertEqual(Decimal(fila['unidades']), Decimal('3'))
        self.assertEqual(Decimal(fila['importe']), Decimal('180000.00'))
        # 100 sembradas menos 3 vendidas.
        self.assertEqual(Decimal(fila['stock_actual']), Decimal('97.00'))


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class AislamientoReportesTestCase(TestCase):
    """Los informes de un gimnasio no incluyen las ventas de otro."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cls.uno = crear_escenario_pos('rep-uno', 'RUno')
        cls.otro = crear_escenario_pos('rep-otro', 'ROtro')
        _vender_producto(cls.uno, '1', '60000')
        _vender_producto(cls.otro, '2', '120000')

    def test_cada_tenant_ve_solo_lo_suyo(self):
        informe = self.client.get(
            '/api/reportes/ventas/', **_auth_headers(self.uno['usuario_admin'], 'rep-uno'),
        ).json()

        self.assertEqual(Decimal(informe['facturado']), Decimal('60000.00'))
        self.assertEqual(informe['numero_ventas'], 1)
