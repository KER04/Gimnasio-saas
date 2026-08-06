"""Gastos e ingresos varios (RF-24 y RF-07), y su efecto en los informes.

Lo que se comprueba no es solo que se guarden, sino las dos consecuencias
que justifican esta entrega: que la utilidad deje de ser margen bruto y
empiece a ser ganancia, y que un apunte de dinero no pueda desaparecer sin
dejar rastro.
"""
import datetime
import json
from decimal import Decimal

from django.core.cache import cache
from django.db import connections
from django.test import TestCase, override_settings

from apps.autenticacion.tests.test_auth import _cabecera_token, _crear_tenant_con_usuario
from apps.core.tenant import tenant_context
from apps.organizacion.models import Sede
from apps.ventas.models import CategoriaGasto, CategoriaIngreso, Gasto, IngresoOtro

_ALLOWED_HOSTS_PRUEBA = ['testserver', '.testserver']
HOY = datetime.date.today().isoformat()


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class BaseCajaTestCase(TestCase):
    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.tenant, cls.rol, cls.usuario = _crear_tenant_con_usuario(
            'cajagastos', 'CG', 'admin@cajagastos.example.com',
            permisos=('gastos.gestionar', 'reportes.ver', 'costos.ver', 'config.sedes'),
        )
        with tenant_context(cls.tenant.id):
            cls.sede = Sede.objects.create(
                tenant=cls.tenant, nombre='Sede Única', direccion='Calle 1',
            )
            cls.categoria = CategoriaGasto.objects.create(tenant=cls.tenant, nombre='Arriendo')
            cls.categoria_ingreso = CategoriaIngreso.objects.create(
                tenant=cls.tenant, nombre='Otros ingresos',
            )

    def setUp(self):
        cache.clear()

    def _peticion(self, metodo, url, datos=None):
        fn = getattr(self.client, metodo)
        kwargs = {'HTTP_HOST': 'cajagastos.testserver', **_cabecera_token(self.usuario)}
        if datos is not None:
            kwargs['data'] = datos
            kwargs['content_type'] = 'application/json'
        return fn(url, **kwargs)

    def _crear_gasto(self, **extra):
        return self._peticion('post', '/api/gastos/', {
            'categoria_gasto': self.categoria.id,
            'sede': self.sede.id,
            'monto': '1500000',
            'descripcion': 'Arriendo del local',
            'fecha': HOY,
            **extra,
        })


class GastosTestCase(BaseCajaTestCase):

    def test_registra_un_gasto(self):
        respuesta = self._crear_gasto()

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        cuerpo = respuesta.json()
        self.assertEqual(Decimal(cuerpo['monto']), Decimal('1500000'))
        self.assertEqual(cuerpo['categoria_nombre'], 'Arriendo')

    def test_el_usuario_sale_del_token_y_no_del_cuerpo(self):
        """Si viniera de fuera se podrían registrar gastos a nombre de otro."""
        respuesta = self._crear_gasto(usuario=99999)

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        with tenant_context(self.tenant.id):
            self.assertEqual(Gasto.objects.get(pk=respuesta.json()['id']).usuario_id, self.usuario.id)

    def test_rechaza_un_monto_no_positivo(self):
        """`ck_gastos_monto` ya lo impide, pero un CHECK violado sale como
        500. Validarlo aquí lo convierte en un 400 que se puede leer."""
        for monto in ('0', '-5'):
            with self.subTest(monto=monto):
                respuesta = self._crear_gasto(monto=monto)
                self.assertEqual(respuesta.status_code, 400, respuesta.content)
                self.assertIn('monto', respuesta.json())

    def test_exige_descripcion(self):
        respuesta = self._crear_gasto(descripcion='')

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('descripcion', respuesta.json())

    def test_filtra_por_rango_de_fechas(self):
        self._crear_gasto(fecha='2026-01-15')
        self._crear_gasto(fecha='2026-06-20')

        respuesta = self._peticion(
            'get', '/api/gastos/?desde=2026-06-01&hasta=2026-06-30',
        )

        self.assertEqual(len(respuesta.json()['results']), 1)

    def test_sin_permiso_no_se_registran_gastos(self):
        _t, _r, sin_permiso = _crear_tenant_con_usuario(
            'cajasinperm', 'CSP', 'nadie@cajasinperm.example.com',
        )

        respuesta = self.client.post(
            '/api/gastos/',
            data={'categoria_gasto': self.categoria.id, 'sede': self.sede.id,
                  'monto': '100', 'descripcion': 'X'},
            content_type='application/json',
            HTTP_HOST='cajasinperm.testserver', **_cabecera_token(sin_permiso),
        )

        self.assertEqual(respuesta.status_code, 403, respuesta.content)


class AuditoriaDeCajaTestCase(BaseCajaTestCase):
    """Un gasto no tiene estado "anulado" (la tabla no tiene esa columna), así
    que corregirlo es editar o borrar de verdad. La traza es lo que impide
    que un apunte de dinero desaparezca en silencio."""

    def _trazas(self, entidad='gastos'):
        with tenant_context(self.tenant.id):
            with connections['default'].cursor() as cursor:
                cursor.execute(
                    'SELECT accion, valor_anterior FROM auditoria '
                    'WHERE tenant_id = %s AND entidad = %s ORDER BY fecha_hora',
                    [self.tenant.id, entidad],
                )
                return [
                    (fila[0], json.loads(fila[1]) if isinstance(fila[1], str) else fila[1])
                    for fila in cursor.fetchall()
                ]

    def test_crear_deja_traza(self):
        self._crear_gasto()

        self.assertIn('crear', [accion for accion, _ in self._trazas()])

    def test_editar_guarda_el_valor_anterior(self):
        gasto_id = self._crear_gasto().json()['id']

        self._peticion('patch', f'/api/gastos/{gasto_id}/', {'monto': '1600000'})

        anteriores = [valor for accion, valor in self._trazas() if accion == 'actualizar']
        self.assertEqual(len(anteriores), 1)
        self.assertEqual(Decimal(anteriores[0]['monto']), Decimal('1500000'))

    def test_borrar_guarda_lo_que_habia(self):
        """Para que el descuadre de un cierre se pueda explicar después."""
        gasto_id = self._crear_gasto().json()['id']

        respuesta = self._peticion('delete', f'/api/gastos/{gasto_id}/')

        self.assertEqual(respuesta.status_code, 204, respuesta.content)
        with tenant_context(self.tenant.id):
            self.assertFalse(Gasto.objects.filter(pk=gasto_id).exists())

        borrados = [valor for accion, valor in self._trazas() if accion == 'eliminar']
        self.assertEqual(len(borrados), 1)
        self.assertEqual(Decimal(borrados[0]['monto']), Decimal('1500000'))
        self.assertEqual(borrados[0]['descripcion'], 'Arriendo del local')


class IngresosVariosTestCase(BaseCajaTestCase):

    def _crear_ingreso(self, **extra):
        return self._peticion('post', '/api/ingresos/', {
            'categoria_ingreso': self.categoria_ingreso.id,
            'sede': self.sede.id,
            'monto': '50000',
            'forma_pago': 'efectivo',
            'descripcion': 'Matrícula',
            'fecha': HOY,
            **extra,
        })

    def test_registra_un_ingreso_sin_venta(self):
        respuesta = self._crear_ingreso()

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        self.assertEqual(Decimal(respuesta.json()['monto']), Decimal('50000'))

    def test_entra_en_el_corte_de_caja(self):
        """`v_corte_diario` los suma junto a los pagos de ventas: en cuanto se
        registra, aparece en el informe sin tocar nada más."""
        self._crear_ingreso()

        respuesta = self._peticion('get', f'/api/reportes/caja/?desde={HOY}&hasta={HOY}')

        self.assertEqual(
            Decimal(respuesta.json()['totales']['ingreso_otros']), Decimal('50000'),
        )

    def test_rechaza_una_forma_de_pago_inventada(self):
        respuesta = self._crear_ingreso(forma_pago='bitcoin')

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('forma_pago', respuesta.json())


class UtilidadConGastosTestCase(BaseCajaTestCase):
    """Antes de esta entrega, el informe enseñaba siempre `gastos: 0`, así que
    lo que llamaba utilidad era margen bruto de productos. Con el arriendo y
    la nómina fuera, ese número decía de más."""

    def test_los_gastos_del_periodo_entran_en_el_informe(self):
        self._crear_gasto(monto='300000')

        respuesta = self._peticion('get', f'/api/reportes/utilidad/?desde={HOY}&hasta={HOY}')

        cuerpo = respuesta.json()
        self.assertEqual(Decimal(cuerpo['gastos']['total']), Decimal('300000'))
        self.assertEqual(cuerpo['gastos']['registrados'], 1)

    def test_la_utilidad_neta_resta_los_gastos(self):
        self._crear_gasto(monto='300000')

        cuerpo = self._peticion(
            'get', f'/api/reportes/utilidad/?desde={HOY}&hasta={HOY}',
        ).json()

        esperada = (
            Decimal(cuerpo['productos']['utilidad'])
            + Decimal(cuerpo['planes']['ingresos'])
            - Decimal(cuerpo['gastos']['total'])
        )
        self.assertEqual(Decimal(cuerpo['utilidad_neta']), esperada)
        # Sin ventas, un gasto deja la ganancia en negativo. Es correcto.
        self.assertLess(Decimal(cuerpo['utilidad_neta']), 0)

    def test_un_gasto_fuera_del_rango_no_cuenta(self):
        self._crear_gasto(monto='999999', fecha='2020-01-01')

        cuerpo = self._peticion(
            'get', f'/api/reportes/utilidad/?desde={HOY}&hasta={HOY}',
        ).json()

        self.assertEqual(Decimal(cuerpo['gastos']['total']), Decimal('0'))


class AislamientoDeCajaTestCase(BaseCajaTestCase):

    def test_no_se_ven_los_gastos_de_otro_gimnasio(self):
        self._crear_gasto()
        otro_tenant, _rol, otro_usuario = _crear_tenant_con_usuario(
            'cajaajena', 'CA', 'admin@cajaajena.example.com',
            permisos=('gastos.gestionar',),
        )

        respuesta = self.client.get(
            '/api/gastos/', HTTP_HOST='cajaajena.testserver', **_cabecera_token(otro_usuario),
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertEqual(len(respuesta.json()['results']), 0)
