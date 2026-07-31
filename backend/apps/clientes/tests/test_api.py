"""Batería de la API de clientes (Parte C del encargo, RF-03/RF-09/RF-16).

Sigue el patrón de ``apps/ventas/tests/test_api.py``: ``TestCase`` +
``databases = {'default', 'ddl'}`` + tokens construidos a mano con
``AccessToken.for_user`` + ``HTTP_HOST='<subdominio>.testserver'``.

## Por qué TestCase y no TransactionTestCase

Todas las pruebas de aquí (incluida la de aislamiento, C10) ejercitan la API
por HTTP de punta a punta (``self.client.get/post/patch/delete``): en cada
petición, ``TenantMiddleware`` resuelve el tenant desde CERO (JWT/Host) y
abre su PROPIO ``tenant_context`` alrededor de esa petición concreta,
fijando ``app.tenant_id`` al valor correcto para ESA petición -- sin
importar qué haya quedado fijado por una petición anterior dentro del mismo
método de prueba. Por eso RLS se comprueba de verdad en cada llamada aunque
``TestCase`` mantenga la clase entera envuelta en una única transacción
externa (igual que ``TenantCruzadoTestCase`` en
``apps/autenticacion/tests/test_auth.py`` y ``AislamientoApiTestCase`` en
``apps/ventas/tests/test_api.py``, ambas también ``TestCase`` por el mismo
motivo).

``TransactionTestCase`` solo hace falta cuando una prueba fija
``app.tenant_id`` a mano (vía ``tenant_context()``) y luego consulta el ORM
DIRECTAMENTE, sin que una petición HTTP intermedia lo vuelva a fijar -- ese
es el caso de ``apps/core/tests/test_aislamiento.py`` (documentado allí) y
de ``RefrescoDeSesionTestCase``. Ninguna prueba de este archivo hace eso.
"""
import datetime
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.core.tenant import tenant_context
from apps.membresias.models import Membresia, Plan

from .factories import PASSWORD, crear_escenario_clientes

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
class ClienteCrudTestCase(TestCase):
    """Escenarios 1, 2, 3, 4, 5, 9 del encargo (Parte C)."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos_a = crear_escenario_clientes('cli-crud-a', 'A')
        cls.datos_b = crear_escenario_clientes('cli-crud-b', 'B')

    def test_crear_cliente_con_obligatorios_da_201(self):
        """Escenario 1."""
        datos = self.datos_a
        respuesta = self.client.post(
            '/api/clientes/',
            data={
                'nombre': 'Kevin Estrada',
                'cedula': 'NUEVO-0001',
                'telefono': '3001234567',
                'direccion': 'Cra 10 # 20-30',
            },
            content_type='application/json',
            **_auth_headers(datos['usuario_admin'], 'cli-crud-a'),
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['nombre'], 'Kevin Estrada')
        self.assertEqual(cuerpo['cedula'], 'NUEVO-0001')
        # sede_origen se resolvió sola (usuario_admin asignado a una única sede).
        self.assertEqual(cuerpo['sede_origen'], datos['sede'].id)
        # Sin autorizaciones enviadas -> ninguna decisión registrada todavía.
        self.assertIsNone(cuerpo['autorizacion_tratamiento_datos'])
        self.assertIsNone(cuerpo['autorizacion_biometria'])

    def test_falta_un_obligatorio_da_400_con_mensaje_claro(self):
        """Escenario 2: falta 'direccion'."""
        datos = self.datos_a
        respuesta = self.client.post(
            '/api/clientes/',
            data={
                'nombre': 'Sin Dirección',
                'cedula': 'NUEVO-0002',
                'telefono': '3001234567',
            },
            content_type='application/json',
            **_auth_headers(datos['usuario_admin'], 'cli-crud-a'),
        )
        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('direccion', respuesta.json())

    def test_cedula_repetida_en_el_mismo_gimnasio_da_400(self):
        """Escenario 3: NO debe ser un 500."""
        datos = self.datos_a
        respuesta = self.client.post(
            '/api/clientes/',
            data={
                'nombre': 'Otro Cliente',
                'cedula': datos['cliente'].cedula,  # ya existe en este tenant
                'telefono': '3009999999',
                'direccion': 'Calle falsa 123',
            },
            content_type='application/json',
            **_auth_headers(datos['usuario_admin'], 'cli-crud-a'),
        )
        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('cedula', respuesta.json())

    def test_misma_cedula_en_otro_gimnasio_da_201(self):
        """Escenario 4: única por tenant, no global."""
        datos_a, datos_b = self.datos_a, self.datos_b
        respuesta = self.client.post(
            '/api/clientes/',
            data={
                'nombre': 'Cliente Homónimo',
                'cedula': datos_a['cliente'].cedula,  # existe en A, NO en B
                'telefono': '3005555555',
                'direccion': 'Calle en el otro gimnasio',
            },
            content_type='application/json',
            **_auth_headers(datos_b['usuario_admin'], 'cli-crud-b'),
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        self.assertEqual(respuesta.json()['cedula'], datos_a['cliente'].cedula)

    def test_buscar_por_nombre_y_por_cedula(self):
        """Escenario 5."""
        datos = self.datos_a
        headers = _auth_headers(datos['usuario_admin'], 'cli-crud-a')

        por_nombre = self.client.get(
            f'/api/clientes/?buscar={datos["cliente"].nombre}', **headers,
        )
        self.assertEqual(por_nombre.status_code, 200, por_nombre.content)
        self.assertEqual(por_nombre.json()['count'], 1)
        self.assertEqual(por_nombre.json()['results'][0]['id'], datos['cliente'].id)

        por_cedula = self.client.get(
            f'/api/clientes/?buscar={datos["cliente"].cedula}', **headers,
        )
        self.assertEqual(por_cedula.status_code, 200, por_cedula.content)
        self.assertEqual(por_cedula.json()['count'], 1)
        self.assertEqual(por_cedula.json()['results'][0]['id'], datos['cliente'].id)

    def test_recepcionista_sin_gestionar_recibe_403_al_crear(self):
        """Escenario 9 (crear)."""
        datos = self.datos_a
        respuesta = self.client.post(
            '/api/clientes/',
            data={
                'nombre': 'Intento Recepción', 'cedula': 'REC-0001',
                'telefono': '3001112233', 'direccion': 'Calle X',
            },
            content_type='application/json',
            **_auth_headers(datos['usuario_recepcion'], 'cli-crud-a'),
        )
        self.assertEqual(respuesta.status_code, 403, respuesta.content)

    def test_recepcionista_sin_gestionar_recibe_403_al_borrar(self):
        """Escenario 9 (borrar)."""
        datos = self.datos_a
        respuesta = self.client.delete(
            f'/api/clientes/{datos["cliente"].id}/',
            **_auth_headers(datos['usuario_recepcion'], 'cli-crud-a'),
        )
        self.assertEqual(respuesta.status_code, 403, respuesta.content)
        with tenant_context(datos['tenant'].id):
            datos['cliente'].refresh_from_db()
        self.assertIsNone(datos['cliente'].eliminado_en)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ClienteBorradoLogicoTestCase(TestCase):
    """Escenario 6 del encargo (Parte C)."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos = crear_escenario_clientes('cli-borrado', 'BOR')

    def test_delete_marca_eliminado_en_y_no_borra_la_fila(self):
        datos = self.datos
        headers = _auth_headers(datos['usuario_admin'], 'cli-borrado')

        respuesta = self.client.delete(f'/api/clientes/{datos["cliente"].id}/', **headers)
        self.assertEqual(respuesta.status_code, 204, respuesta.content)

        # La fila SIGUE existiendo (no fue un DELETE real) y trae eliminado_en.
        with tenant_context(datos['tenant'].id):
            from apps.clientes.models import Cliente
            fila = Cliente.objects.get(pk=datos['cliente'].id)
        self.assertIsNotNone(fila.eliminado_en)

        # Desaparece del listado por defecto.
        listado = self.client.get('/api/clientes/', **headers)
        self.assertEqual(listado.status_code, 200, listado.content)
        ids_listados = [c['id'] for c in listado.json()['results']]
        self.assertNotIn(datos['cliente'].id, ids_listados)

        # Su histórico de ventas SIGUE existiendo.
        with tenant_context(datos['tenant'].id):
            from apps.ventas.models import Venta
            self.assertTrue(Venta.objects.filter(pk=datos['venta'].id, cliente_id=datos['cliente'].id).exists())


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ClienteMembresiasTestCase(TestCase):
    """Escenario 7 del encargo (Parte C, RF-16)."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos = crear_escenario_clientes('cli-membr', 'MEM')
        hoy = datetime.date.today()
        with tenant_context(cls.datos['tenant'].id):
            plan = Plan.objects.create(
                tenant=cls.datos['tenant'], nombre='Mensual MEM', tipo=Plan.TipoPlan.MENSUAL,
                duracion_dias=30, precio=Decimal('80000'),
            )
            comun = dict(
                tenant=cls.datos['tenant'], cliente=cls.datos['cliente'], plan=plan,
                sede=cls.datos['sede'], vendedor=cls.datos['usuario_admin'],
                precio_pagado=plan.precio,
            )
            cls.m_vence_hoy = Membresia.objects.create(
                fecha_inicio=hoy - datetime.timedelta(days=30), fecha_fin=hoy, **comun,
            )
            cls.m_por_vencer = Membresia.objects.create(
                fecha_inicio=hoy - datetime.timedelta(days=27),
                fecha_fin=hoy + datetime.timedelta(days=3),
                **comun,
            )
            cls.m_vencida = Membresia.objects.create(
                fecha_inicio=hoy - datetime.timedelta(days=32),
                fecha_fin=hoy - datetime.timedelta(days=2),
                **comun,
            )

    def test_estado_calculado_de_cada_membresia(self):
        datos = self.datos
        respuesta = self.client.get(
            f'/api/clientes/{datos["cliente"].id}/membresias/',
            **_auth_headers(datos['usuario_admin'], 'cli-membr'),
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        por_id = {m['id']: m for m in respuesta.json()}

        self.assertEqual(por_id[self.m_vence_hoy.id]['estado_calculado'], 'vence_hoy')
        self.assertEqual(por_id[self.m_por_vencer.id]['estado_calculado'], 'por_vencer')
        self.assertEqual(por_id[self.m_vencida.id]['estado_calculado'], 'vencida')
        self.assertEqual(por_id[self.m_vencida.id]['dias_restantes'], -2)
        self.assertEqual(por_id[self.m_por_vencer.id]['dias_restantes'], 3)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ClienteDeudaTestCase(TestCase):
    """Escenario 8 del encargo (Parte C, RF-09)."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos = crear_escenario_clientes('cli-deuda', 'DEU')

    def test_deuda_calcula_bien_el_saldo_tras_abono_parcial(self):
        """La fábrica ya deja la venta con total=60000 y un pago inicial de
        20000 (estado PARCIAL): saldo esperado 40000."""
        datos = self.datos
        respuesta = self.client.get(
            f'/api/clientes/{datos["cliente"].id}/deuda/',
            **_auth_headers(datos['usuario_admin'], 'cli-deuda'),
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        cuerpo = respuesta.json()

        self.assertEqual(Decimal(cuerpo['total_adeudado']), Decimal('40000.00'))
        self.assertEqual(len(cuerpo['ventas']), 1)
        venta = cuerpo['ventas'][0]
        self.assertEqual(venta['venta_id'], datos['venta'].id)
        self.assertEqual(Decimal(venta['total']), Decimal('60000.00'))
        self.assertEqual(Decimal(venta['total_pagado']), Decimal('20000.00'))
        self.assertEqual(Decimal(venta['saldo']), Decimal('40000.00'))
        self.assertEqual(len(venta['abonos']), 1)
        self.assertEqual(Decimal(venta['abonos'][0]['monto']), Decimal('20000.00'))
        self.assertEqual(len(venta['detalles']), 1)
        # No debe filtrar márgenes: el endpoint no exige costos.ver, pero
        # tampoco debe exponer ningún campo de costo.
        self.assertNotIn('costo_unitario', venta['detalles'][0])

        # Registrar un segundo abono que salda la deuda por completo: la
        # venta debe dejar de aparecer en la cartera.
        with tenant_context(datos['tenant'].id):
            from apps.ventas.models import Pago
            Pago.objects.create(
                tenant=datos['tenant'], venta=datos['venta'], usuario=datos['usuario_admin'],
                monto=Decimal('40000'), forma_pago=Pago.FormaPago.EFECTIVO,
            )
        respuesta2 = self.client.get(
            f'/api/clientes/{datos["cliente"].id}/deuda/',
            **_auth_headers(datos['usuario_admin'], 'cli-deuda'),
        )
        self.assertEqual(respuesta2.status_code, 200, respuesta2.content)
        self.assertEqual(Decimal(respuesta2.json()['total_adeudado']), Decimal('0'))
        self.assertEqual(len(respuesta2.json()['ventas']), 0)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ClienteAislamientoTestCase(TestCase):
    """Escenario 10 del encargo (Parte C): un usuario del tenant A no puede
    ver, editar ni borrar un cliente del tenant B."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos_a = crear_escenario_clientes('cli-aisla-a', 'A')
        cls.datos_b = crear_escenario_clientes('cli-aisla-b', 'B')

    def test_no_puede_ver_cliente_de_otro_tenant(self):
        datos_a, datos_b = self.datos_a, self.datos_b
        respuesta = self.client.get(
            f'/api/clientes/{datos_b["cliente"].id}/',
            **_auth_headers(datos_a['usuario_admin'], 'cli-aisla-a'),
        )
        self.assertEqual(respuesta.status_code, 404, respuesta.content)

    def test_no_puede_editar_cliente_de_otro_tenant(self):
        datos_a, datos_b = self.datos_a, self.datos_b
        respuesta = self.client.patch(
            f'/api/clientes/{datos_b["cliente"].id}/',
            data={'telefono': '3000000000'},
            content_type='application/json',
            **_auth_headers(datos_a['usuario_admin'], 'cli-aisla-a'),
        )
        self.assertEqual(respuesta.status_code, 404, respuesta.content)

    def test_no_puede_borrar_cliente_de_otro_tenant(self):
        datos_a, datos_b = self.datos_a, self.datos_b
        respuesta = self.client.delete(
            f'/api/clientes/{datos_b["cliente"].id}/',
            **_auth_headers(datos_a['usuario_admin'], 'cli-aisla-a'),
        )
        self.assertEqual(respuesta.status_code, 404, respuesta.content)

        with tenant_context(datos_b['tenant'].id):
            datos_b['cliente'].refresh_from_db()
        self.assertIsNone(datos_b['cliente'].eliminado_en)

    def test_no_puede_listar_cliente_de_otro_tenant(self):
        datos_a, datos_b = self.datos_a, self.datos_b
        respuesta = self.client.get(
            f'/api/clientes/?buscar={datos_b["cliente"].cedula}',
            **_auth_headers(datos_a['usuario_admin'], 'cli-aisla-a'),
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertEqual(respuesta.json()['count'], 0)
