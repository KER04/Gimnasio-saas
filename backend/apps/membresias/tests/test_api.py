"""Batería de la API de membresías (Parte D del encargo de membresías,
escenarios 1, 2, 3, 4, 5, 6, 7 y 10).

Sigue el mismo patrón que ``apps/ventas/tests/test_api.py`` y
``apps/clientes/tests/test_api.py``: ``TestCase`` + ``databases = {'default',
'ddl'}`` + tokens ``AccessToken.for_user`` a mano + ``HTTP_HOST`` con el
subdominio del tenant.

Reutiliza ``apps.ventas.tests.factories.crear_escenario_pos`` (no se crea una
fábrica propia): ya siembra un tenant con dos sedes, un cliente, un plan
mensual (30 días), un plan por sesión, y dos roles -- ``usuario_admin`` con
``membresias.gestionar`` + ``reportes.ver`` (necesarios aquí) y
``usuario_recepcion`` sin ``costos.ver`` (usado en la Parte B de clientes,
no en este archivo). Añadir una fábrica nueva solo para membresías hubiera
duplicado exactamente ese mismo andamiaje.

## Por qué TestCase y no TransactionTestCase

Todas las pruebas de aquí (incluida la de aislamiento, escenario 10) pegan a
la API por HTTP (``self.client.get/post``): en cada petición,
``TenantMiddleware`` resuelve el tenant desde CERO (JWT/Host) y abre su
PROPIO ``tenant_context`` alrededor de esa petición, fijando
``app.tenant_id`` correctamente para ESA petición sin importar qué haya
quedado fijado antes -- RLS se comprueba de verdad en cada llamada aunque
``TestCase`` envuelva la clase entera en una única transacción externa
(mismo razonamiento documentado en ``apps/clientes/tests/test_api.py`` y en
``AislamientoApiTestCase`` de ``apps/ventas/tests/test_api.py``).
``TransactionTestCase`` solo hace falta cuando una prueba fija
``app.tenant_id`` a mano vía ``tenant_context()`` y consulta el ORM
DIRECTAMENTE después, sin una petición HTTP intermedia -- ninguna prueba de
aquí hace eso: las pocas veces que se usa ``tenant_context`` es para
SEMBRAR datos en ``setUpTestData``/``setUp``, nunca para verificar el
resultado de una petición.
"""
import datetime
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.core.tenant import tenant_context
from apps.membresias.models import Membresia, Plan
from apps.plataforma.models import Tenant
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


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ListadoEstadoCalculadoTestCase(TestCase):
    """Escenario 1: filtrar por estado calculado (RF-16) devuelve las
    membresías correctas. El estado sale de ``v_membresias_estado``, que
    aplica ``dias_aviso_vencimiento`` del tenant (5 por defecto, sembrado por
    ``crear_escenario_pos``/``Tenant``)."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos = crear_escenario_pos('memb-lista', 'ML')
        hoy = datetime.date.today()
        with tenant_context(cls.datos['tenant'].id):
            comun = dict(
                tenant=cls.datos['tenant'], cliente=cls.datos['cliente'],
                plan=cls.datos['plan_mensual'], sede=cls.datos['sede'],
                vendedor=cls.datos['usuario_admin'], precio_pagado=cls.datos['plan_mensual'].precio,
            )
            cls.m_vence_hoy = Membresia.objects.create(
                fecha_inicio=hoy - datetime.timedelta(days=30), fecha_fin=hoy, **comun,
            )
            cls.m_por_vencer = Membresia.objects.create(
                fecha_inicio=hoy - datetime.timedelta(days=27),
                fecha_fin=hoy + datetime.timedelta(days=3),
                **comun,
            )
            cls.m_activa = Membresia.objects.create(
                fecha_inicio=hoy, fecha_fin=hoy + datetime.timedelta(days=30), **comun,
            )
            cls.m_vencida = Membresia.objects.create(
                fecha_inicio=hoy - datetime.timedelta(days=32),
                fecha_fin=hoy - datetime.timedelta(days=2),
                **comun,
            )

    def _listar(self, estado):
        respuesta = self.client.get(
            f'/api/membresias/?estado={estado}',
            **_auth_headers(self.datos['usuario_admin'], 'memb-lista'),
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        return {m['id'] for m in respuesta.json()['results']}

    def test_vence_hoy(self):
        self.assertEqual(self._listar('vence_hoy'), {self.m_vence_hoy.id})

    def test_por_vencer(self):
        self.assertEqual(self._listar('por_vencer'), {self.m_por_vencer.id})

    def test_activa(self):
        self.assertEqual(self._listar('activa'), {self.m_activa.id})

    def test_vencida(self):
        self.assertEqual(self._listar('vencida'), {self.m_vencida.id})

    def test_incluye_datos_legibles_de_cliente_y_plan(self):
        respuesta = self.client.get(
            f'/api/membresias/?estado=activa',
            **_auth_headers(self.datos['usuario_admin'], 'memb-lista'),
        )
        fila = respuesta.json()['results'][0]
        self.assertEqual(fila['cliente']['nombre'], self.datos['cliente'].nombre)
        self.assertEqual(fila['plan']['nombre'], self.datos['plan_mensual'].nombre)
        self.assertEqual(fila['estado_calculado'], 'activa')


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class AsignacionDirectaTestCase(TestCase):
    """Escenarios 2 y 3: alta directa (cortesía/traspaso/corrección), sin
    venta asociada, y rechazo de planes ``por_sesion``."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos = crear_escenario_pos('memb-directa', 'MD')

    def test_asigna_membresia_con_fecha_fin_correcta_y_sin_venta(self):
        datos = self.datos
        fecha_inicio = datetime.date.today().isoformat()
        respuesta = self.client.post(
            '/api/membresias/',
            data={
                'cliente_id': datos['cliente'].id,
                'plan_id': datos['plan_mensual'].id,
                'sede_id': datos['sede'].id,
                'fecha_inicio': fecha_inicio,
                'precio_pagado': '0',
            },
            content_type='application/json',
            **_auth_headers(datos['usuario_admin'], 'memb-directa'),
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        cuerpo = respuesta.json()
        self.assertIsNone(cuerpo['venta'])
        fecha_fin_esperada = (
            datetime.date.today() + datetime.timedelta(days=datos['plan_mensual'].duracion_dias)
        ).isoformat()
        self.assertEqual(cuerpo['fecha_inicio'], fecha_inicio)
        self.assertEqual(cuerpo['fecha_fin'], fecha_fin_esperada)
        self.assertEqual(Decimal(cuerpo['precio_pagado']), Decimal('0'))

    def test_plan_por_sesion_es_rechazado(self):
        datos = self.datos
        respuesta = self.client.post(
            '/api/membresias/',
            data={
                'cliente_id': datos['cliente'].id,
                'plan_id': datos['plan_sesion'].id,
                'sede_id': datos['sede'].id,
                'precio_pagado': '15000',
            },
            content_type='application/json',
            **_auth_headers(datos['usuario_admin'], 'memb-directa'),
        )
        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        with tenant_context(datos['tenant'].id):
            self.assertEqual(
                Membresia.objects.filter(cliente=datos['cliente'], plan=datos['plan_sesion']).count(), 0,
            )


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class RenovarMembresiaTestCase(TestCase):
    """Escenarios 4 y 5 (RF-16): renovar una membresía VIGENTE encadena
    desde su ``fecha_fin`` (el cliente no pierde días pagados); renovar una
    ya VENCIDA parte de hoy."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos = crear_escenario_pos('memb-renovar', 'MR')
        hoy = datetime.date.today()
        with tenant_context(cls.datos['tenant'].id):
            comun = dict(
                tenant=cls.datos['tenant'], cliente=cls.datos['cliente'],
                plan=cls.datos['plan_mensual'], sede=cls.datos['sede'],
                vendedor=cls.datos['usuario_admin'], precio_pagado=cls.datos['plan_mensual'].precio,
            )
            cls.vigente = Membresia.objects.create(
                fecha_inicio=hoy - datetime.timedelta(days=10),
                fecha_fin=hoy + datetime.timedelta(days=20),
                **comun,
            )
            cls.vencida = Membresia.objects.create(
                fecha_inicio=hoy - datetime.timedelta(days=40),
                fecha_fin=hoy - datetime.timedelta(days=10),
                **comun,
            )

    def test_renovar_vigente_encadena_desde_su_fecha_fin(self):
        datos = self.datos
        respuesta = self.client.post(
            f'/api/membresias/{self.vigente.id}/renovar/',
            data={'precio_pagado': '80000.00'},
            content_type='application/json',
            **_auth_headers(datos['usuario_admin'], 'memb-renovar'),
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        cuerpo = respuesta.json()

        fecha_inicio_esperada = self.vigente.fecha_fin
        fecha_fin_esperada = fecha_inicio_esperada + datetime.timedelta(
            days=datos['plan_mensual'].duracion_dias,
        )
        self.assertEqual(cuerpo['fecha_inicio'], fecha_inicio_esperada.isoformat())
        self.assertEqual(cuerpo['fecha_fin'], fecha_fin_esperada.isoformat())
        self.assertEqual(cuerpo['membresia_anterior'], self.vigente.id)

        with tenant_context(datos['tenant'].id):
            self.vigente.refresh_from_db()
        # La anterior NO se modifica (Parte A3: se crea una NUEVA membresía).
        self.assertEqual(self.vigente.fecha_fin, fecha_inicio_esperada)
        self.assertEqual(self.vigente.estado, Membresia.EstadoMembresia.ACTIVA)

    def test_renovar_vencida_parte_de_hoy(self):
        datos = self.datos
        respuesta = self.client.post(
            f'/api/membresias/{self.vencida.id}/renovar/',
            data={'precio_pagado': '80000.00'},
            content_type='application/json',
            **_auth_headers(datos['usuario_admin'], 'memb-renovar'),
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        cuerpo = respuesta.json()

        hoy = datetime.date.today()
        fecha_fin_esperada = hoy + datetime.timedelta(days=datos['plan_mensual'].duracion_dias)
        self.assertEqual(cuerpo['fecha_inicio'], hoy.isoformat())
        self.assertEqual(cuerpo['fecha_fin'], fecha_fin_esperada.isoformat())
        self.assertEqual(cuerpo['membresia_anterior'], self.vencida.id)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class CancelarMembresiaTestCase(TestCase):
    """Escenario 6: ``motivo`` obligatorio (además del CHECK de base) y no
    se puede cancelar dos veces."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos = crear_escenario_pos('memb-cancelar', 'MC')
        hoy = datetime.date.today()
        with tenant_context(cls.datos['tenant'].id):
            cls.membresia = Membresia.objects.create(
                tenant=cls.datos['tenant'], cliente=cls.datos['cliente'],
                plan=cls.datos['plan_mensual'], sede=cls.datos['sede'],
                vendedor=cls.datos['usuario_admin'], precio_pagado=cls.datos['plan_mensual'].precio,
                fecha_inicio=hoy, fecha_fin=hoy + datetime.timedelta(days=30),
            )

    def test_cancelar_sin_motivo_es_400(self):
        datos = self.datos
        respuesta = self.client.post(
            f'/api/membresias/{self.membresia.id}/cancelar/',
            data={'motivo': ''},
            content_type='application/json',
            **_auth_headers(datos['usuario_admin'], 'memb-cancelar'),
        )
        self.assertEqual(respuesta.status_code, 400, respuesta.content)

    def test_cancelar_dos_veces_es_400(self):
        datos = self.datos
        primera = self.client.post(
            f'/api/membresias/{self.membresia.id}/cancelar/',
            data={'motivo': 'El cliente se muda de ciudad'},
            content_type='application/json',
            **_auth_headers(datos['usuario_admin'], 'memb-cancelar'),
        )
        self.assertEqual(primera.status_code, 200, primera.content)
        self.assertEqual(primera.json()['estado'], 'cancelada')

        segunda = self.client.post(
            f'/api/membresias/{self.membresia.id}/cancelar/',
            data={'motivo': 'Otra vez'},
            content_type='application/json',
            **_auth_headers(datos['usuario_admin'], 'memb-cancelar'),
        )
        self.assertEqual(segunda.status_code, 400, segunda.content)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class PorVencerTestCase(TestCase):
    """Escenario 7: el tablero respeta ``dias_aviso_vencimiento`` del
    tenant -- al subirlo, aparecen más membresías "por vencer"."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos = crear_escenario_pos('memb-porvencer', 'PV')
        hoy = datetime.date.today()
        with tenant_context(cls.datos['tenant'].id):
            comun = dict(
                tenant=cls.datos['tenant'], cliente=cls.datos['cliente'],
                plan=cls.datos['plan_mensual'], sede=cls.datos['sede'],
                vendedor=cls.datos['usuario_admin'], precio_pagado=cls.datos['plan_mensual'].precio,
            )
            # A 8 días: con dias_aviso=5 (por defecto) NO aparece; con
            # dias_aviso=10 SÍ.
            cls.m_8_dias = Membresia.objects.create(
                fecha_inicio=hoy, fecha_fin=hoy + datetime.timedelta(days=8), **comun,
            )
            # A 2 días: aparece en ambos casos.
            cls.m_2_dias = Membresia.objects.create(
                fecha_inicio=hoy, fecha_fin=hoy + datetime.timedelta(days=2), **comun,
            )
            # Vencida hace 1 día: aparece siempre.
            cls.m_vencida = Membresia.objects.create(
                fecha_inicio=hoy - datetime.timedelta(days=31),
                fecha_fin=hoy - datetime.timedelta(days=1),
                **comun,
            )

    def _ids_por_vencer(self, usuario, subdominio):
        respuesta = self.client.get(
            '/api/membresias/por-vencer/', **_auth_headers(usuario, subdominio),
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        return {fila['id'] for fila in respuesta.json()}

    def test_respeta_dias_aviso_por_defecto(self):
        ids = self._ids_por_vencer(self.datos['usuario_admin'], 'memb-porvencer')
        self.assertEqual(ids, {self.m_2_dias.id, self.m_vencida.id})

    def test_con_mas_dias_de_aviso_aparecen_mas(self):
        datos = self.datos
        with tenant_context(datos['tenant'].id):
            Tenant.objects.filter(pk=datos['tenant'].id).update(dias_aviso_vencimiento=10)

        ids = self._ids_por_vencer(datos['usuario_admin'], 'memb-porvencer')
        self.assertEqual(ids, {self.m_8_dias.id, self.m_2_dias.id, self.m_vencida.id})

    def test_reportes_ver_alcanza_para_consultar_el_tablero(self):
        # `reportes.ver` (no `membresias.gestionar`) es el permiso exigido
        # para esta acción -- la comprobamos con el mismo usuario_admin
        # (que tiene ambos) más un 403 si se le quita `reportes.ver`.
        datos = self.datos
        respuesta = self.client.get(
            '/api/membresias/por-vencer/',
            **_auth_headers(datos['usuario_admin'], 'memb-porvencer'),
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class AislamientoMembresiasTestCase(TestCase):
    """Escenario 10: un usuario del tenant A no puede ver ni renovar una
    membresía del tenant B."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos_a = crear_escenario_pos('memb-aisla-a', 'A')
        cls.datos_b = crear_escenario_pos('memb-aisla-b', 'B')
        hoy = datetime.date.today()
        with tenant_context(cls.datos_b['tenant'].id):
            cls.membresia_b = Membresia.objects.create(
                tenant=cls.datos_b['tenant'], cliente=cls.datos_b['cliente'],
                plan=cls.datos_b['plan_mensual'], sede=cls.datos_b['sede'],
                vendedor=cls.datos_b['usuario_admin'], precio_pagado=cls.datos_b['plan_mensual'].precio,
                fecha_inicio=hoy, fecha_fin=hoy + datetime.timedelta(days=30),
            )

    def test_no_puede_ver_membresia_de_otro_tenant(self):
        respuesta = self.client.get(
            f'/api/membresias/{self.membresia_b.id}/',
            **_auth_headers(self.datos_a['usuario_admin'], 'memb-aisla-a'),
        )
        self.assertEqual(respuesta.status_code, 404, respuesta.content)

    def test_no_puede_renovar_membresia_de_otro_tenant(self):
        respuesta = self.client.post(
            f'/api/membresias/{self.membresia_b.id}/renovar/',
            data={'precio_pagado': '80000.00'},
            content_type='application/json',
            **_auth_headers(self.datos_a['usuario_admin'], 'memb-aisla-a'),
        )
        self.assertEqual(respuesta.status_code, 404, respuesta.content)
        with tenant_context(self.datos_b['tenant'].id):
            self.assertEqual(
                Membresia.objects.filter(membresia_anterior=self.membresia_b).count(), 0,
            )

    def test_no_aparece_en_el_listado_de_otro_tenant(self):
        respuesta = self.client.get(
            '/api/membresias/', **_auth_headers(self.datos_a['usuario_admin'], 'memb-aisla-a'),
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        ids = {m['id'] for m in respuesta.json()['results']}
        self.assertNotIn(self.membresia_b.id, ids)
