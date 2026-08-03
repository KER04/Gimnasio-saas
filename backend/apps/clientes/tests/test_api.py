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
from urllib.parse import urlencode

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.asistencia.models import Asistencia
from apps.clientes.models import Cliente
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

    def test_crear_con_sede_origen_en_null_tambien_da_201(self):
        """Regresión de un fallo detectado usando la aplicación.

        Un selector vacío en un formulario representa "sin elegir" como
        `null`, no omitiendo la clave. El campo era opcional pero no admitía
        nulos, así que el alta de clientes fallaba con 400 en cuanto no se
        escogía sede:

            {"sede_origen": ["Este campo no puede ser nulo."]}

        Omitir el campo y enviarlo en `null` significan lo mismo —"no la
        indico"— y ambas formas deben resolver la sede del usuario.
        """
        datos = self.datos_a
        respuesta = self.client.post(
            '/api/clientes/',
            data={
                'nombre': 'Cliente Sin Sede',
                'cedula': 'NULA-0001',
                'telefono': '3009998877',
                'direccion': 'Cra 1 # 2-3',
                'sexo': None,
                'sede_origen': None,
            },
            content_type='application/json',
            **_auth_headers(datos['usuario_admin'], 'cli-crud-a'),
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        self.assertEqual(respuesta.json()['sede_origen'], datos['sede'].id)

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

    def test_membresia_y_asistencia_de_otro_tenant_no_se_filtran_ni_se_cuentan(self):
        """Escenario 10 (ampliación): las anotaciones de membresía/asistencia
        del listado (``Subquery`` correlacionado por ``cliente_id``) deben
        seguir respetando RLS -- ninguna fila de B debe colarse al calcular
        ``membresia_vigente``/``ultima_visita`` de un cliente de A, ni un
        cliente de B debe aparecer al filtrar por ``?estado=``/``?plan=``
        desde A."""
        datos_a, datos_b = self.datos_a, self.datos_b
        hoy = timezone.localdate()

        with tenant_context(datos_b['tenant'].id):
            plan_b = Plan.objects.create(
                tenant=datos_b['tenant'], nombre='Plan de B', tipo=Plan.TipoPlan.MENSUAL,
                duracion_dias=30, precio=Decimal('50000'),
            )
            Membresia.objects.create(
                tenant=datos_b['tenant'], cliente=datos_b['cliente'], plan=plan_b,
                sede=datos_b['sede'], vendedor=datos_b['usuario_admin'],
                fecha_inicio=hoy - datetime.timedelta(days=10),
                fecha_fin=hoy - datetime.timedelta(days=2),  # vencida
                precio_pagado=plan_b.precio,
            )
            Asistencia.objects.create(
                tenant=datos_b['tenant'], sede=datos_b['sede'], cliente=datos_b['cliente'],
                metodo=Asistencia.MetodoAsistencia.MANUAL_CEDULA, con_membresia_vigente=True,
                fecha_hora=timezone.now(),
            )

        # Filtrar por 'vencida' desde el tenant A no debe traer al cliente de B.
        respuesta = self.client.get(
            '/api/clientes/?estado=vencida',
            **_auth_headers(datos_a['usuario_admin'], 'cli-aisla-a'),
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        ids = [c['id'] for c in respuesta.json()['results']]
        self.assertNotIn(datos_b['cliente'].id, ids)

        # El listado normal de A tampoco debe mostrar membresía/asistencia de B.
        respuesta_normal = self.client.get(
            f'/api/clientes/?buscar={datos_a["cliente"].nombre}',
            **_auth_headers(datos_a['usuario_admin'], 'cli-aisla-a'),
        )
        self.assertEqual(respuesta_normal.status_code, 200, respuesta_normal.content)
        cuerpo = respuesta_normal.json()['results'][0]
        self.assertEqual(cuerpo['id'], datos_a['cliente'].id)
        self.assertIsNone(cuerpo['membresia_vigente'])
        self.assertIsNone(cuerpo['ultima_visita'])


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ClienteListadoMembresiaYAsistenciaTestCase(TestCase):
    """Escenarios de la ampliación del listado (``membresia_vigente``,
    ``ultima_visita`` y filtros ``?estado=``/``?plan=`` en
    ``GET /api/clientes/``)."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos = crear_escenario_clientes('cli-list-membr', 'LM')
        # `timezone.localdate()`/`timezone.now()`, nunca `date.today()` ni
        # CURRENT_DATE: la conexión corre en UTC y la app en America/Bogota;
        # a partir de las 19:00 son días distintos.
        hoy = timezone.localdate()
        tenant = cls.datos['tenant']
        sede = cls.datos['sede']
        vendedor = cls.datos['usuario_admin']

        with tenant_context(tenant.id):
            cls.plan_mensual = Plan.objects.create(
                tenant=tenant, nombre='Mensual LM', tipo=Plan.TipoPlan.MENSUAL,
                duracion_dias=30, precio=Decimal('80000'),
            )
            cls.plan_personalizado = Plan.objects.create(
                tenant=tenant, nombre='Personalizado LM', tipo=Plan.TipoPlan.MENSUAL,
                duracion_dias=30, precio=Decimal('150000'), requiere_entrenador=True,
            )
            comun = dict(tenant=tenant, sede=sede, vendedor=vendedor)

            # Cliente sembrado por la fábrica: SIN membresía y SIN
            # asistencia -- cubre los casos "null".
            cls.cliente_sin_membresia = cls.datos['cliente']

            cls.cliente_vigente = Cliente.objects.create(
                tenant=tenant, sede_origen=sede, nombre='Cliente Vigente LM',
                cedula='CED-LM-0002', telefono='3000000002', direccion='Calle 2',
            )
            cls.membresia_vigente = Membresia.objects.create(
                cliente=cls.cliente_vigente, plan=cls.plan_mensual,
                fecha_inicio=hoy - datetime.timedelta(days=5),
                fecha_fin=hoy + datetime.timedelta(days=25),
                precio_pagado=cls.plan_mensual.precio, **comun,
            )

            # Dos membresías activas a la vez (decisión 23): debe ganar la de
            # fecha_fin más lejana (la del plan personalizado).
            cls.cliente_doble = Cliente.objects.create(
                tenant=tenant, sede_origen=sede, nombre='Cliente Doble LM',
                cedula='CED-LM-0003', telefono='3000000003', direccion='Calle 3',
            )
            cls.membresia_doble_corta = Membresia.objects.create(
                cliente=cls.cliente_doble, plan=cls.plan_mensual,
                fecha_inicio=hoy - datetime.timedelta(days=10),
                fecha_fin=hoy + datetime.timedelta(days=20),
                precio_pagado=cls.plan_mensual.precio, **comun,
            )
            cls.membresia_doble_lejana = Membresia.objects.create(
                cliente=cls.cliente_doble, plan=cls.plan_personalizado,
                fecha_inicio=hoy - datetime.timedelta(days=1),
                fecha_fin=hoy + datetime.timedelta(days=60),
                precio_pagado=cls.plan_personalizado.precio, **comun,
            )

            cls.cliente_vencido = Cliente.objects.create(
                tenant=tenant, sede_origen=sede, nombre='Cliente Vencido LM',
                cedula='CED-LM-0004', telefono='3000000004', direccion='Calle 4',
            )
            cls.membresia_vencida = Membresia.objects.create(
                cliente=cls.cliente_vencido, plan=cls.plan_mensual,
                fecha_inicio=hoy - datetime.timedelta(days=40),
                fecha_fin=hoy - datetime.timedelta(days=10),
                precio_pagado=cls.plan_mensual.precio, **comun,
            )

            # Dos asistencias del cliente vigente: debe ganar la más reciente.
            cls.asistencia_antigua = Asistencia.objects.create(
                tenant=tenant, sede=sede, cliente=cls.cliente_vigente,
                metodo=Asistencia.MetodoAsistencia.MANUAL_CEDULA, con_membresia_vigente=True,
                fecha_hora=timezone.now() - datetime.timedelta(days=2),
            )
            cls.asistencia_reciente = Asistencia.objects.create(
                tenant=tenant, sede=sede, cliente=cls.cliente_vigente,
                metodo=Asistencia.MetodoAsistencia.MANUAL_CEDULA, con_membresia_vigente=True,
                fecha_hora=timezone.now() - datetime.timedelta(hours=1),
            )

    def _listar(self, **params):
        query = f'?{urlencode(params)}' if params else ''
        respuesta = self.client.get(
            f'/api/clientes/{query}',
            **_auth_headers(self.datos['usuario_admin'], 'cli-list-membr'),
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        return {c['id']: c for c in respuesta.json()['results']}

    def test_cliente_con_membresia_vigente_trae_plan_y_estado(self):
        """Escenario 1."""
        por_id = self._listar()
        cuerpo = por_id[self.cliente_vigente.id]
        self.assertIsNotNone(cuerpo['membresia_vigente'])
        self.assertEqual(cuerpo['membresia_vigente']['plan_nombre'], 'Mensual LM')
        self.assertEqual(cuerpo['membresia_vigente']['estado_calculado'], 'activa')
        self.assertEqual(
            cuerpo['membresia_vigente']['fecha_fin'],
            self.membresia_vigente.fecha_fin.isoformat(),
        )
        self.assertEqual(cuerpo['membresia_vigente']['dias_restantes'], 25)

    def test_cliente_sin_membresia_trae_null(self):
        """Escenario 2."""
        por_id = self._listar()
        cuerpo = por_id[self.cliente_sin_membresia.id]
        self.assertIsNone(cuerpo['membresia_vigente'])

    def test_cliente_con_dos_membresias_activas_devuelve_la_de_fecha_fin_mas_lejana(self):
        """Escenario 3 (decisión 23)."""
        por_id = self._listar()
        cuerpo = por_id[self.cliente_doble.id]
        self.assertIsNotNone(cuerpo['membresia_vigente'])
        self.assertEqual(cuerpo['membresia_vigente']['plan_nombre'], 'Personalizado LM')
        self.assertEqual(
            cuerpo['membresia_vigente']['fecha_fin'],
            self.membresia_doble_lejana.fecha_fin.isoformat(),
        )

    def test_cliente_con_membresia_vencida(self):
        """Escenario 4."""
        por_id = self._listar()
        cuerpo = por_id[self.cliente_vencido.id]
        self.assertIsNotNone(cuerpo['membresia_vigente'])
        self.assertEqual(cuerpo['membresia_vigente']['estado_calculado'], 'vencida')
        self.assertEqual(cuerpo['membresia_vigente']['dias_restantes'], -10)

    def test_ultima_visita_refleja_la_mas_reciente_o_null(self):
        """Escenario 5."""
        por_id = self._listar()
        self.assertIsNotNone(por_id[self.cliente_vigente.id]['ultima_visita'])
        # La asistencia devuelta corresponde a la MÁS RECIENTE, no a la primera creada.
        self.assertEqual(
            datetime.datetime.fromisoformat(por_id[self.cliente_vigente.id]['ultima_visita']),
            self.asistencia_reciente.fecha_hora,
        )
        self.assertIsNone(por_id[self.cliente_sin_membresia.id]['ultima_visita'])
        self.assertIsNone(por_id[self.cliente_doble.id]['ultima_visita'])

    def test_filtro_estado_vencida_devuelve_solo_esos(self):
        """Escenario 6 (parte 1)."""
        por_id = self._listar(estado='vencida')
        self.assertEqual(set(por_id.keys()), {self.cliente_vencido.id})

    def test_filtro_estado_sin_membresia_devuelve_solo_los_que_no_tienen(self):
        """Escenario 6 (parte 2)."""
        por_id = self._listar(estado='sin_membresia')
        ids = set(por_id.keys())
        self.assertIn(self.cliente_sin_membresia.id, ids)
        self.assertNotIn(self.cliente_vigente.id, ids)
        self.assertNotIn(self.cliente_doble.id, ids)
        self.assertNotIn(self.cliente_vencido.id, ids)

    def test_filtro_plan_devuelve_solo_los_de_ese_plan(self):
        """Escenario 7: el plan del cliente doble es el 'lejano' (personalizado)."""
        por_id = self._listar(plan=self.plan_personalizado.id)
        self.assertEqual(set(por_id.keys()), {self.cliente_doble.id})

        por_id_mensual = self._listar(plan=self.plan_mensual.id)
        self.assertEqual(
            set(por_id_mensual.keys()), {self.cliente_vigente.id, self.cliente_vencido.id},
        )

    def test_filtros_combinados_con_buscar(self):
        """Escenario 8."""
        por_id = self._listar(estado='activa', buscar='Vigente LM')
        self.assertEqual(set(por_id.keys()), {self.cliente_vigente.id})

        # Combinado con un `buscar` que NO calza con el estado -> vacío.
        vacio = self._listar(estado='vencida', buscar='Vigente LM')
        self.assertEqual(vacio, {})


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ClienteListadoRendimientoTestCase(TestCase):
    """Escenario 9 del encargo de ampliación: el número de consultas del
    listado NO debe depender del número de clientes -- las columnas nuevas
    (``membresia_vigente``, ``ultima_visita``) se resuelven con ``Subquery``
    correlacionados dentro de la MISMA sentencia SELECT, no con una consulta
    adicional por fila.

    ``PAGE_SIZE`` (20, en ``config.settings.base``) no tiene
    ``PAGE_SIZE_QUERY_PARAM`` configurado -- ``?page_size=`` no lo sobreescribe
    -- así que la comparación 3 vs. 15 se hace con DOS TENANTS (uno con 3
    clientes, otro con 15, ambos por debajo del tamaño de página) en vez de
    con querystrings, para que la única variable entre ambas llamadas sea,
    de verdad, cuántos clientes trae la respuesta.
    """

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos_3 = cls._crear_tenant_con_clientes('cli-rend-3', 'REND3', total=3)
        cls.datos_15 = cls._crear_tenant_con_clientes('cli-rend-15', 'REND15', total=15)

    @staticmethod
    def _crear_tenant_con_clientes(subdominio, sufijo, total):
        datos = crear_escenario_clientes(subdominio, sufijo)
        tenant = datos['tenant']
        sede = datos['sede']
        vendedor = datos['usuario_admin']
        hoy = timezone.localdate()

        with tenant_context(tenant.id):
            plan = Plan.objects.create(
                tenant=tenant, nombre=f'Plan {sufijo}', tipo=Plan.TipoPlan.MENSUAL,
                duracion_dias=30, precio=Decimal('80000'),
            )
            # La fábrica ya deja un cliente sembrado (sin membresía ni
            # asistencia); se completa hasta `total` con clientes nuevos,
            # alternando con/sin membresía+asistencia para que las
            # anotaciones tengan trabajo real en ambos sentidos (no solo el
            # camino "todo NULL").
            for i in range(total - 1):
                cliente = Cliente.objects.create(
                    tenant=tenant, sede_origen=sede, nombre=f'Cliente {sufijo} {i:02d}',
                    # 'X' + índice: la fábrica ya usa '{sufijo}-0001' para el
                    # cliente sembrado -- este prefijo evita chocar con esa
                    # cédula (uq_clientes_cedula es única por tenant+cédula).
                    cedula=f'CED-{sufijo}-X{i:04d}', telefono='3000000000', direccion='Calle X',
                )
                if i % 2 == 0:
                    Membresia.objects.create(
                        tenant=tenant, cliente=cliente, plan=plan, sede=sede, vendedor=vendedor,
                        fecha_inicio=hoy - datetime.timedelta(days=5),
                        fecha_fin=hoy + datetime.timedelta(days=25),
                        precio_pagado=plan.precio,
                    )
                    Asistencia.objects.create(
                        tenant=tenant, sede=sede, cliente=cliente,
                        metodo=Asistencia.MetodoAsistencia.MANUAL_CEDULA, con_membresia_vigente=True,
                        fecha_hora=timezone.now(),
                    )

        return datos

    def _listar(self, datos, subdominio):
        return self.client.get('/api/clientes/', **_auth_headers(datos['usuario_admin'], subdominio))

    def test_mismo_numero_de_consultas_con_3_que_con_15_clientes(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as capturado_3:
            respuesta_3 = self._listar(self.datos_3, 'cli-rend-3')
        self.assertEqual(respuesta_3.status_code, 200, respuesta_3.content)
        self.assertEqual(len(respuesta_3.json()['results']), 3)

        with CaptureQueriesContext(connection) as capturado_15:
            respuesta_15 = self._listar(self.datos_15, 'cli-rend-15')
        self.assertEqual(respuesta_15.status_code, 200, respuesta_15.content)
        self.assertEqual(len(respuesta_15.json()['results']), 15)

        n_3, n_15 = len(capturado_3), len(capturado_15)
        self.assertEqual(
            n_3, n_15,
            'El número de consultas del listado no debe depender del número de '
            f'clientes de la página (3 clientes: {n_3} consultas; 15 clientes: {n_15} consultas).',
        )
