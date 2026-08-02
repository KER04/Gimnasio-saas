"""Batería de la API de asistencia (RF-15, sin biometría: el lector ZK9500
todavía no llegó). Cubre las Partes A (endpoints) y B (11 escenarios) del
encargo.

## Por qué TestCase y no TransactionTestCase

Sigue el mismo patrón (y el mismo razonamiento) que
``apps/clientes/tests/test_api.py``/``apps/membresias/tests/test_api.py``:
todas las pruebas de aquí -- INCLUIDA la de aislamiento (escenario 11) --
pegan a la API por HTTP (``self.client.get/post``). En cada petición,
``TenantMiddleware`` resuelve el tenant desde CERO (JWT) y abre su PROPIO
``tenant_context`` alrededor de ESA petición, fijando ``app.tenant_id``
correctamente sin importar qué haya quedado fijado por una petición
anterior del mismo método de prueba. RLS se comprueba de verdad en cada
llamada aunque ``TestCase`` envuelva la clase entera en una única
transacción externa (ver el comentario largo en
``apps/core/tests/test_aislamiento.py`` sobre quién SÍ necesita
``TransactionTestCase``: solo pruebas que fijan ``app.tenant_id`` a mano vía
``tenant_context()`` y consultan el ORM DIRECTAMENTE después, sin una
petición HTTP intermedia -- las pocas veces que este archivo usa
``tenant_context`` es para SEMBRAR datos o para leer ``auditoria`` al final
de una prueba, nunca para verificar el resultado de un ``POST``/``GET``
anterior).
"""
import datetime
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.auditoria.models import Auditoria
from apps.core.tenant import tenant_context
from apps.membresias.models import Membresia
from apps.plataforma.models import Tenant

from .factories import crear_escenario_asistencia

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


def _crear_membresia(datos, *, fecha_inicio, fecha_fin):
    with tenant_context(datos['tenant'].id):
        return Membresia.objects.create(
            tenant=datos['tenant'], cliente=datos['cliente'], plan=datos['plan_mensual'],
            sede=datos['sede'], vendedor=datos['usuario_admin'],
            precio_pagado=datos['plan_mensual'].precio,
            fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
        )


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class VerificarTestCase(TestCase):
    """Escenarios 1, 2, 3 y 4: el panel de check-in (``GET /verificar/``)."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos = crear_escenario_asistencia('asis-verif', 'AV')

    def _verificar(self, cedula):
        return self.client.get(
            f'/api/asistencias/verificar/?cedula={cedula}',
            **_auth_headers(self.datos['usuario_admin'], 'asis-verif'),
        )

    def test_cedula_inexistente_da_404_con_mensaje_claro(self):
        """Escenario 1."""
        respuesta = self._verificar('NO-EXISTE-0001')
        self.assertEqual(respuesta.status_code, 404, respuesta.content)
        self.assertIn('NO-EXISTE-0001', respuesta.json()['detail'])

    def test_dos_membresias_activas_devuelve_las_dos(self):
        """Escenario 2 (decisión 23: un cliente puede tener varias vigentes
        a la vez; no se devuelve "la" membresía)."""
        hoy = datetime.date.today()
        m1 = _crear_membresia(self.datos, fecha_inicio=hoy, fecha_fin=hoy + datetime.timedelta(days=30))
        m2 = _crear_membresia(
            self.datos, fecha_inicio=hoy, fecha_fin=hoy + datetime.timedelta(days=15),
        )
        respuesta = self._verificar(self.datos['cliente'].cedula)
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        cuerpo = respuesta.json()
        ids = {m['id'] for m in cuerpo['membresias']}
        self.assertEqual(ids, {m1.id, m2.id})
        self.assertTrue(cuerpo['puede_ingresar'])
        self.assertFalse(cuerpo['requiere_autorizacion'])

    def test_muestra_saldo_pendiente(self):
        """Escenario 3: se muestra porque quien mira esta pantalla es el
        cajero, no el público."""
        from apps.ventas.models import Venta

        with tenant_context(self.datos['tenant'].id):
            Venta.objects.create(
                tenant=self.datos['tenant'], sede=self.datos['sede'], cliente=self.datos['cliente'],
                usuario=self.datos['usuario_admin'], consecutivo=99,
                subtotal=Decimal('50000.00'), total=Decimal('50000.00'),
                estado=Venta.EstadoVenta.PENDIENTE,
            )
        respuesta = self._verificar(self.datos['cliente'].cedula)
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertEqual(Decimal(respuesta.json()['saldo_pendiente']), Decimal('50000.00'))

    def test_todas_vencidas_no_puede_ingresar_y_requiere_autorizacion(self):
        """Escenario 4."""
        hoy = datetime.date.today()
        _crear_membresia(
            self.datos, fecha_inicio=hoy - datetime.timedelta(days=40),
            fecha_fin=hoy - datetime.timedelta(days=10),
        )
        respuesta = self._verificar(self.datos['cliente'].cedula)
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        cuerpo = respuesta.json()
        self.assertFalse(cuerpo['puede_ingresar'])
        self.assertTrue(cuerpo['requiere_autorizacion'])


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class RegistrarIngresoTestCase(TestCase):
    """Escenarios 5, 6, 7, 8, 9 y 10: ``POST /api/asistencias/``."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos = crear_escenario_asistencia('asis-registro', 'AR')

    def _post(self, usuario, payload):
        return self.client.post(
            '/api/asistencias/', data=payload, content_type='application/json',
            **_auth_headers(usuario, 'asis-registro'),
        )

    def test_ingreso_con_membresia_vigente_da_201(self):
        """Escenario 5."""
        hoy = datetime.date.today()
        _crear_membresia(self.datos, fecha_inicio=hoy, fecha_fin=hoy + datetime.timedelta(days=30))

        respuesta = self._post(self.datos['usuario_admin'], {
            'metodo': 'manual_cedula', 'cedula': self.datos['cliente'].cedula,
        })
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        cuerpo = respuesta.json()
        self.assertTrue(cuerpo['con_membresia_vigente'])
        self.assertEqual(cuerpo['cliente'], self.datos['cliente'].id)

    def test_antipassback_rechaza_el_segundo_ingreso_y_permite_con_ventana_cero(self):
        """Escenario 6."""
        hoy = datetime.date.today()
        _crear_membresia(self.datos, fecha_inicio=hoy, fecha_fin=hoy + datetime.timedelta(days=30))
        payload = {'metodo': 'manual_cedula', 'cedula': self.datos['cliente'].cedula}

        primero = self._post(self.datos['usuario_admin'], payload)
        self.assertEqual(primero.status_code, 201, primero.content)

        segundo = self._post(self.datos['usuario_admin'], payload)
        self.assertEqual(segundo.status_code, 409, segundo.content)
        self.assertIn('minuto', segundo.json()['detail'])

        with tenant_context(self.datos['tenant'].id):
            Tenant.objects.filter(pk=self.datos['tenant'].id).update(minutos_antipassback=0)

        tercero = self._post(self.datos['usuario_admin'], payload)
        self.assertEqual(tercero.status_code, 201, tercero.content)

    def test_sin_membresia_vigente_y_sin_autorizacion_da_400(self):
        """Escenario 7 (sin ninguna membresía en absoluto: tampoco vencida)."""
        respuesta = self._post(self.datos['usuario_admin'], {
            'metodo': 'manual_cedula', 'cedula': self.datos['cliente'].cedula,
        })
        self.assertEqual(respuesta.status_code, 400, respuesta.content)

    def test_sin_membresia_vigente_con_autorizacion_valida_da_201_y_queda_en_auditoria(self):
        """Escenario 8."""
        respuesta = self._post(self.datos['usuario_admin'], {
            'metodo': 'manual_cedula', 'cedula': self.datos['cliente'].cedula,
            'autorizado_por_id': self.datos['usuario_admin'].id,
            'motivo_autorizacion': 'Pagó en efectivo, aún no se refleja el plan',
        })
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        cuerpo = respuesta.json()
        self.assertFalse(cuerpo['con_membresia_vigente'])
        self.assertEqual(cuerpo['autorizado_por'], self.datos['usuario_admin'].id)

        with tenant_context(self.datos['tenant'].id):
            filas = list(
                Auditoria.objects.filter(entidad='asistencias', entidad_id=cuerpo['id']),
            )
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0].valor_nuevo['autorizado_por'], self.datos['usuario_admin'].id)
        self.assertEqual(filas[0].accion, Auditoria.AccionAuditoria.AUTORIZAR)

    def test_usuario_sin_permiso_no_puede_autorizar(self):
        """Escenario 9: ``usuario_sin_autorizar`` no tiene
        ``asistencia.autorizar``, aunque sea un usuario válido del mismo
        tenant."""
        respuesta = self._post(self.datos['usuario_admin'], {
            'metodo': 'manual_cedula', 'cedula': self.datos['cliente'].cedula,
            'autorizado_por_id': self.datos['usuario_sin_autorizar'].id,
            'motivo_autorizacion': 'Intento sin el permiso adecuado',
        })
        self.assertEqual(respuesta.status_code, 403, respuesta.content)

    def test_sesion_anonima_sin_venta_id_da_400(self):
        """Escenario 10."""
        respuesta = self._post(self.datos['usuario_admin'], {'metodo': 'sesion_anonima'})
        self.assertEqual(respuesta.status_code, 400, respuesta.content)

    def test_sesion_anonima_con_venta_id_da_201_sin_cliente(self):
        """Camino feliz complementario al escenario 10: con `venta_id` sí
        se registra, sin cliente y sin exigir membresía."""
        respuesta = self._post(self.datos['usuario_admin'], {
            'metodo': 'sesion_anonima', 'venta_id': self.datos['venta'].id,
        })
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        cuerpo = respuesta.json()
        self.assertIsNone(cuerpo['cliente'])
        self.assertEqual(cuerpo['venta'], self.datos['venta'].id)
        self.assertFalse(cuerpo['con_membresia_vigente'])


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class AislamientoAsistenciaTestCase(TestCase):
    """Escenario 11: un usuario del tenant A no puede verificar ni
    registrar la asistencia de un cliente del tenant B."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.datos_a = crear_escenario_asistencia('asis-aisla-a', 'A')
        cls.datos_b = crear_escenario_asistencia('asis-aisla-b', 'B')
        hoy = datetime.date.today()
        cls.membresia_b = _crear_membresia(
            cls.datos_b, fecha_inicio=hoy, fecha_fin=hoy + datetime.timedelta(days=30),
        )

    def test_no_puede_verificar_cliente_de_otro_tenant(self):
        respuesta = self.client.get(
            f'/api/asistencias/verificar/?cedula={self.datos_b["cliente"].cedula}',
            **_auth_headers(self.datos_a['usuario_admin'], 'asis-aisla-a'),
        )
        self.assertEqual(respuesta.status_code, 404, respuesta.content)

    def test_no_puede_registrar_asistencia_de_cliente_de_otro_tenant(self):
        respuesta = self.client.post(
            '/api/asistencias/',
            data={'metodo': 'manual_cedula', 'cedula': self.datos_b['cliente'].cedula},
            content_type='application/json',
            **_auth_headers(self.datos_a['usuario_admin'], 'asis-aisla-a'),
        )
        self.assertEqual(respuesta.status_code, 400, respuesta.content)

        with tenant_context(self.datos_b['tenant'].id):
            from apps.asistencia.models import Asistencia
            self.assertEqual(
                Asistencia.objects.filter(cliente=self.datos_b['cliente']).count(), 0,
            )
