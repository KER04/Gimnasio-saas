"""Batería de la API de ventas/POS (Parte E, escenarios 12, 13 y 14 del
encargo), más un puñado de pruebas de humo end-to-end sobre los cuatro
endpoints de ``/api/ventas/``.

Sigue el patrón de ``apps/autenticacion/tests/test_auth.py``: ``TestCase`` +
``databases = {'default', 'ddl'}`` + tokens construidos a mano con
``AccessToken.for_user`` (más rápido que loguear de verdad por HTTP en cada
prueba) y ``HTTP_HOST='<subdominio>.testserver'`` para que
``TenantMiddleware`` resuelva el tenant del token sin conflicto con el
subdominio de la petición.
"""
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.core.tenant import tenant_context
from apps.ventas.models import DetalleVenta, Pago, Venta
from apps.ventas.services import registrar_venta

from .factories import crear_escenario_pos

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


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class CostosOcultosTestCase(TestCase):
    """Escenario 12: el recepcionista NO ve `costo_unitario`; el
    administrador SÍ."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos = crear_escenario_pos('api-costos', 'CO')
        with tenant_context(cls.datos['tenant'].id):
            cls.venta = registrar_venta(
                tenant=cls.datos['tenant'], sede=cls.datos['sede'], usuario=cls.datos['usuario_admin'],
                items=[{
                    'tipo_item': DetalleVenta.TipoItemVenta.PRODUCTO,
                    'producto': cls.datos['producto'], 'cantidad': Decimal('2'),
                }],
                monto_pago_inicial=Decimal('120000'), forma_pago=Pago.FormaPago.EFECTIVO,
            )

    def test_recepcionista_no_ve_costo_unitario(self):
        datos = self.datos
        respuesta = self.client.get(
            f'/api/ventas/{self.venta.id}/',
            **_auth_headers(datos['usuario_recepcion'], 'api-costos'),
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        detalle = respuesta.json()['detalles'][0]
        self.assertNotIn('costo_unitario', detalle)

    def test_administrador_si_ve_costo_unitario(self):
        datos = self.datos
        respuesta = self.client.get(
            f'/api/ventas/{self.venta.id}/',
            **_auth_headers(datos['usuario_admin'], 'api-costos'),
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        detalle = respuesta.json()['detalles'][0]
        self.assertIn('costo_unitario', detalle)
        self.assertEqual(Decimal(detalle['costo_unitario']), datos['producto'].costo)

    def test_recepcionista_no_ve_costo_en_listado_de_productos(self):
        datos = self.datos
        respuesta = self.client.get(
            '/api/productos/',
            **_auth_headers(datos['usuario_recepcion'], 'api-costos'),
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        producto_json = respuesta.json()['results'][0]
        self.assertNotIn('costo', producto_json)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class PermisoAnularTestCase(TestCase):
    """Escenario 13: un usuario sin `ventas.anular` recibe 403 al intentar anular."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos = crear_escenario_pos('api-anular', 'AN')
        with tenant_context(cls.datos['tenant'].id):
            cls.venta = registrar_venta(
                tenant=cls.datos['tenant'], sede=cls.datos['sede'], usuario=cls.datos['usuario_admin'],
                items=[{
                    'tipo_item': DetalleVenta.TipoItemVenta.PRODUCTO,
                    'producto': cls.datos['producto'], 'cantidad': Decimal('1'),
                }],
                cliente=cls.datos['cliente'], monto_pago_inicial=Decimal('0'),
            )

    def test_recepcionista_sin_permiso_recibe_403(self):
        datos = self.datos
        respuesta = self.client.post(
            f'/api/ventas/{self.venta.id}/anular/',
            data={'motivo': 'Quiero anularla igual'},
            content_type='application/json',
            **_auth_headers(datos['usuario_recepcion'], 'api-anular'),
        )
        self.assertEqual(respuesta.status_code, 403, respuesta.content)

        self.venta.refresh_from_db()
        self.assertNotEqual(self.venta.estado, Venta.EstadoVenta.ANULADA)

    def test_administrador_con_permiso_puede_anular(self):
        datos = self.datos
        respuesta = self.client.post(
            f'/api/ventas/{self.venta.id}/anular/',
            data={'motivo': 'Producto defectuoso'},
            content_type='application/json',
            **_auth_headers(datos['usuario_admin'], 'api-anular'),
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertEqual(respuesta.json()['estado'], Venta.EstadoVenta.ANULADA)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class AislamientoApiTestCase(TestCase):
    """Escenario 14: un usuario del tenant A no puede vender contra una
    sede, producto ni cliente del tenant B, ni ver una venta de B."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos_a = crear_escenario_pos('api-aisla-a', 'A')
        cls.datos_b = crear_escenario_pos('api-aisla-b', 'B')
        with tenant_context(cls.datos_b['tenant'].id):
            cls.venta_b = registrar_venta(
                tenant=cls.datos_b['tenant'], sede=cls.datos_b['sede'],
                usuario=cls.datos_b['usuario_admin'],
                items=[{
                    'tipo_item': DetalleVenta.TipoItemVenta.PRODUCTO,
                    'producto': cls.datos_b['producto'], 'cantidad': Decimal('1'),
                }],
                cliente=cls.datos_b['cliente'], monto_pago_inicial=Decimal('0'),
            )

    def test_no_puede_vender_contra_sede_de_otro_tenant(self):
        datos_a, datos_b = self.datos_a, self.datos_b
        respuesta = self.client.post(
            '/api/ventas/',
            data={
                'sede_id': datos_b['sede'].id,
                'items': [{
                    'tipo_item': 'producto', 'producto_id': datos_a['producto'].id, 'cantidad': '1',
                }],
            },
            content_type='application/json',
            **_auth_headers(datos_a['usuario_admin'], 'api-aisla-a'),
        )
        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        # Explícito con tenant_context (no nos fiamos de qué tenant haya
        # quedado fijado en la conexión tras la petición HTTP anterior):
        # en la sede de B solo debe seguir existiendo la venta sembrada en
        # setUpTestData, ninguna nueva creada por el intruso.
        with tenant_context(datos_b['tenant'].id):
            self.assertEqual(Venta.objects.filter(sede=datos_b['sede']).count(), 1)

    def test_no_puede_vender_producto_de_otro_tenant(self):
        datos_a, datos_b = self.datos_a, self.datos_b
        respuesta = self.client.post(
            '/api/ventas/',
            data={
                'sede_id': datos_a['sede'].id,
                'items': [{
                    'tipo_item': 'producto', 'producto_id': datos_b['producto'].id, 'cantidad': '1',
                }],
            },
            content_type='application/json',
            **_auth_headers(datos_a['usuario_admin'], 'api-aisla-a'),
        )
        self.assertEqual(respuesta.status_code, 400, respuesta.content)

    def test_no_puede_vender_a_cliente_de_otro_tenant(self):
        datos_a, datos_b = self.datos_a, self.datos_b
        respuesta = self.client.post(
            '/api/ventas/',
            data={
                'sede_id': datos_a['sede'].id,
                'cliente_id': datos_b['cliente'].id,
                'items': [{
                    'tipo_item': 'producto', 'producto_id': datos_a['producto'].id, 'cantidad': '1',
                }],
            },
            content_type='application/json',
            **_auth_headers(datos_a['usuario_admin'], 'api-aisla-a'),
        )
        self.assertEqual(respuesta.status_code, 400, respuesta.content)

    def test_no_puede_ver_venta_de_otro_tenant(self):
        datos_a = self.datos_a
        respuesta = self.client.get(
            f'/api/ventas/{self.venta_b.id}/',
            **_auth_headers(datos_a['usuario_admin'], 'api-aisla-a'),
        )
        self.assertEqual(respuesta.status_code, 404)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class VentaApiSmokeTestCase(TestCase):
    """Pruebas de humo end-to-end sobre los cuatro endpoints de
    ``/api/ventas/`` (registrar, listar con filtros, detalle, anular, abonar)
    y los tres de apoyo (productos, planes, clientes)."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos = crear_escenario_pos('api-smoke', 'SM')

    def test_registrar_venta_de_producto_por_http(self):
        datos = self.datos
        respuesta = self.client.post(
            '/api/ventas/',
            data={
                'sede_id': datos['sede'].id,
                'items': [{
                    'tipo_item': 'producto', 'producto_id': datos['producto'].id, 'cantidad': '2',
                }],
                'monto_pago_inicial': '120000',
                'forma_pago': 'efectivo',
            },
            content_type='application/json',
            **_auth_headers(datos['usuario_admin'], 'api-smoke'),
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['estado'], 'pagada')
        self.assertEqual(len(cuerpo['detalles']), 1)
        self.assertEqual(len(cuerpo['pagos']), 1)

    def test_listado_paginado_y_filtro_por_estado(self):
        datos = self.datos
        with tenant_context(datos['tenant'].id):
            registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[{
                    'tipo_item': DetalleVenta.TipoItemVenta.PRODUCTO,
                    'producto': datos['producto'], 'cantidad': Decimal('1'),
                }],
                monto_pago_inicial=Decimal('60000'), forma_pago=Pago.FormaPago.EFECTIVO,
            )
            registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[{
                    'tipo_item': DetalleVenta.TipoItemVenta.PRODUCTO,
                    'producto': datos['producto'], 'cantidad': Decimal('1'),
                }],
                cliente=datos['cliente'], monto_pago_inicial=Decimal('0'),
            )

        respuesta = self.client.get(
            '/api/ventas/', **_auth_headers(datos['usuario_admin'], 'api-smoke'),
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        cuerpo = respuesta.json()
        self.assertIn('results', cuerpo)
        self.assertIn('count', cuerpo)
        self.assertEqual(cuerpo['count'], 2)

        respuesta_filtrada = self.client.get(
            '/api/ventas/?estado=pendiente', **_auth_headers(datos['usuario_admin'], 'api-smoke'),
        )
        self.assertEqual(respuesta_filtrada.status_code, 200, respuesta_filtrada.content)
        cuerpo_filtrado = respuesta_filtrada.json()
        self.assertEqual(cuerpo_filtrado['count'], 1)
        self.assertEqual(cuerpo_filtrado['results'][0]['estado'], 'pendiente')

    def test_abono_por_http_baja_el_saldo(self):
        datos = self.datos
        with tenant_context(datos['tenant'].id):
            venta = registrar_venta(
                tenant=datos['tenant'], sede=datos['sede'], usuario=datos['usuario_admin'],
                items=[{
                    'tipo_item': DetalleVenta.TipoItemVenta.PRODUCTO,
                    'producto': datos['producto'], 'cantidad': Decimal('1'),
                }],
                cliente=datos['cliente'], monto_pago_inicial=Decimal('0'),
            )

        respuesta = self.client.post(
            f'/api/ventas/{venta.id}/abonos/',
            data={'monto': '60000', 'forma_pago': 'efectivo'},
            content_type='application/json',
            **_auth_headers(datos['usuario_admin'], 'api-smoke'),
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['estado'], 'pagada')
        self.assertEqual(Decimal(cuerpo['saldo']), Decimal('0.00'))

    def test_endpoints_de_apoyo_responden(self):
        datos = self.datos
        headers = _auth_headers(datos['usuario_admin'], 'api-smoke')

        respuesta_prod = self.client.get(f'/api/productos/?buscar=Prote', **headers)
        self.assertEqual(respuesta_prod.status_code, 200, respuesta_prod.content)
        self.assertEqual(respuesta_prod.json()['count'], 1)

        respuesta_planes = self.client.get('/api/planes/', **headers)
        self.assertEqual(respuesta_planes.status_code, 200, respuesta_planes.content)
        self.assertEqual(respuesta_planes.json()['count'], 2)

        respuesta_clientes = self.client.get(
            f'/api/clientes/?buscar={datos["cliente"].cedula}', **headers,
        )
        self.assertEqual(respuesta_clientes.status_code, 200, respuesta_clientes.content)
        self.assertEqual(respuesta_clientes.json()['count'], 1)
