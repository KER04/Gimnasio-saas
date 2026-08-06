"""Suscripciones y facturación del proveedor (Fase 3).

Lo que se comprueba aquí no es que los endpoints respondan, sino que las
CIFRAS salgan bien y que nada se cobre dos veces: una factura es un
documento que se envía a un cliente y que no se puede "arreglar luego".
"""
import datetime
from decimal import Decimal

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.core.tenant import tenant_context
from apps.organizacion.models import Sede
from apps.plataforma.facturacion import emitir_factura, marcar_mora, sumar_ciclo
from apps.plataforma.models import (
    FacturaSuscripcion,
    PlanSuscripcion,
    Suscripcion,
    Tenant,
    UsuarioPlataforma,
)

from .test_panel import PASSWORD_PANEL, _crear_cuenta_panel

_ALLOWED_HOSTS_PRUEBA = ['testserver', '.testserver']


class AritmeticaDeCiclosTestCase(TestCase):
    """`sumar_ciclo` no usa "30 días" a propósito."""

    def test_recorta_al_ultimo_dia_del_mes_destino(self):
        """Un cobro del 31 de enero: "un mes después" no es el 31 de febrero.
        Sumar 30 días desplazaría la fecha de cobro un poco cada mes hasta
        acabar cobrando en otra semana del mes."""
        self.assertEqual(
            sumar_ciclo(datetime.date(2026, 1, 31), 'mensual'), datetime.date(2026, 2, 28),
        )
        # Año bisiesto: el mismo caso da 29.
        self.assertEqual(
            sumar_ciclo(datetime.date(2028, 1, 31), 'mensual'), datetime.date(2028, 2, 29),
        )

    def test_cruza_el_fin_de_ano(self):
        self.assertEqual(
            sumar_ciclo(datetime.date(2026, 12, 15), 'mensual'), datetime.date(2027, 1, 15),
        )

    def test_ciclo_anual(self):
        self.assertEqual(
            sumar_ciclo(datetime.date(2026, 3, 10), 'anual'), datetime.date(2027, 3, 10),
        )

    def test_el_29_de_febrero_no_revienta_al_ano_siguiente(self):
        self.assertEqual(
            sumar_ciclo(datetime.date(2028, 2, 29), 'anual'), datetime.date(2029, 2, 28),
        )


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class BaseFacturacionTestCase(TestCase):
    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.admin = _crear_cuenta_panel('fact.admin@proveedor.example.com')
        cls.soporte = _crear_cuenta_panel(
            'fact.soporte@proveedor.example.com', UsuarioPlataforma.RolPlataforma.SOPORTE,
        )

    def setUp(self):
        cache.clear()
        respuesta = self.client.post(
            '/api/plataforma/tenants/',
            data={
                'nombre_comercial': 'Gimnasio Factura',
                'subdominio': 'facturauno',
                'correo_admin': 'duenio@factura.example.com',
            },
            content_type='application/json', **self._como_admin(),
        )
        self.uuid = respuesta.json()['uuid_publico']
        self.tenant = Tenant.objects.get(uuid_publico=self.uuid)
        self.base = f'/api/plataforma/tenants/{self.uuid}'

        self.plan = PlanSuscripcion.objects.create(
            nombre='Plan de prueba', precio_por_sede=Decimal('80000'), ciclo='mensual',
        )

    def _cabecera(self, correo):
        respuesta = self.client.post(
            '/api/plataforma/login/',
            data={'correo': correo, 'password': PASSWORD_PANEL},
            content_type='application/json',
        )
        return {'HTTP_AUTHORIZATION': f'Bearer {respuesta.json()["access"]}'}

    def _como_admin(self):
        return self._cabecera('fact.admin@proveedor.example.com')

    def _como_soporte(self):
        return self._cabecera('fact.soporte@proveedor.example.com')

    def _contratar(self, corte=None, plan=None):
        cuerpo = {'plan_suscripcion': (plan or self.plan).id}
        if corte is not None:
            cuerpo['fecha_inicio'] = corte.isoformat()
            cuerpo['proximo_corte'] = corte.isoformat()
        return self.client.post(
            f'{self.base}/suscripcion/', data=cuerpo,
            content_type='application/json', **self._como_admin(),
        )


class CatalogoDePlanesTestCase(BaseFacturacionTestCase):

    def test_crea_y_lista_planes(self):
        respuesta = self.client.post(
            '/api/plataforma/planes-suscripcion/',
            data={'nombre': 'Avanzado', 'precio_por_sede': '150000', 'ciclo': 'mensual'},
            content_type='application/json', **self._como_admin(),
        )

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        listado = self.client.get(
            '/api/plataforma/planes-suscripcion/', **self._como_admin(),
        ).json()
        self.assertIn('Avanzado', [p['nombre'] for p in listado['results']])

    def test_un_limite_en_cero_no_significa_nada(self):
        """NULL es "ilimitado"; cero no es un límite, es un error de captura."""
        respuesta = self.client.post(
            '/api/plataforma/planes-suscripcion/',
            data={'nombre': 'Roto', 'precio_por_sede': '1000', 'max_sedes': 0},
            content_type='application/json', **self._como_admin(),
        )

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('max_sedes', respuesta.json())

    def test_la_baja_es_logica_y_reversible(self):
        """`Suscripcion.plan_suscripcion` es PROTECT: borrar de verdad un plan
        con contratos vivos dejaría el histórico sin poder explicarse."""
        respuesta = self.client.delete(
            f'/api/plataforma/planes-suscripcion/{self.plan.id}/', **self._como_admin(),
        )
        self.assertEqual(respuesta.status_code, 204, respuesta.content)

        self.plan.refresh_from_db()
        self.assertFalse(self.plan.activo)

        visibles = self.client.get(
            '/api/plataforma/planes-suscripcion/', **self._como_admin(),
        ).json()['results']
        self.assertNotIn(self.plan.id, [p['id'] for p in visibles])

        con_inactivos = self.client.get(
            '/api/plataforma/planes-suscripcion/?incluir_inactivos=1', **self._como_admin(),
        ).json()['results']
        self.assertIn(self.plan.id, [p['id'] for p in con_inactivos])

    def test_soporte_no_puede_tocar_el_catalogo(self):
        respuesta = self.client.post(
            '/api/plataforma/planes-suscripcion/',
            data={'nombre': 'X', 'precio_por_sede': '1'},
            content_type='application/json', **self._como_soporte(),
        )

        self.assertEqual(respuesta.status_code, 403, respuesta.content)


class SuscripcionDeGimnasioTestCase(BaseFacturacionTestCase):

    def test_contrata_un_plan(self):
        respuesta = self._contratar()

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['plan_nombre'], 'Plan de prueba')
        self.assertEqual(cuerpo['estado'], 'vigente')

    def test_cambiar_de_plan_cierra_el_anterior_y_deja_uno_solo_vigente(self):
        """`uq_suscripciones_vigente` lo exige, y además así queda el
        histórico: qué plan tenía antes y hasta cuándo."""
        self._contratar()
        otro = PlanSuscripcion.objects.create(
            nombre='Pro', precio_por_sede=Decimal('150000'), ciclo='mensual',
        )

        respuesta = self._contratar(plan=otro)

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        self.assertEqual(self.tenant.suscripciones.count(), 2)
        self.assertEqual(self.tenant.suscripciones.filter(estado='vigente').count(), 1)
        vieja = self.tenant.suscripciones.filter(estado='cancelada').get()
        self.assertIsNotNone(vieja.fecha_fin)

    def test_cancelar_el_contrato_no_apaga_el_gimnasio(self):
        """Dejar de cobrarle y cortarle el servicio son decisiones distintas.
        La segunda tiene su propia acción, con confirmación."""
        self._contratar()
        estado_antes = Tenant.objects.get(pk=self.tenant.id).estado

        respuesta = self.client.post(
            f'{self.base}/cancelar-suscripcion/',
            content_type='application/json', **self._como_admin(),
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertEqual(respuesta.json()['estado'], 'cancelada')
        self.assertEqual(Tenant.objects.get(pk=self.tenant.id).estado, estado_antes)

    def test_el_primer_cobro_no_puede_ser_anterior_al_contrato(self):
        respuesta = self.client.post(
            f'{self.base}/suscripcion/',
            data={
                'plan_suscripcion': self.plan.id,
                'fecha_inicio': '2026-06-01',
                'proximo_corte': '2026-05-01',
            },
            content_type='application/json', **self._como_admin(),
        )

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('proximo_corte', respuesta.json())

    def test_soporte_ve_la_suscripcion_pero_no_la_cambia(self):
        self._contratar()

        self.assertEqual(
            self.client.get(f'{self.base}/suscripcion/', **self._como_soporte()).status_code, 200,
        )
        self.assertEqual(
            self.client.post(
                f'{self.base}/suscripcion/', data={'plan_suscripcion': self.plan.id},
                content_type='application/json', **self._como_soporte(),
            ).status_code,
            403,
        )


class EmisionDeFacturasTestCase(BaseFacturacionTestCase):

    def _suscripcion(self, dias_atras=0):
        corte = datetime.date.today() - datetime.timedelta(days=dias_atras)
        self._contratar(corte=corte)
        return self.tenant.suscripciones.get(estado='vigente')

    def test_el_importe_es_precio_por_sede_por_sedes_activas(self):
        """La decisión 13 del esquema: se cobra por sede."""
        suscripcion = self._suscripcion()
        with tenant_context(self.tenant.id):
            Sede.objects.create(tenant=self.tenant, nombre='Segunda', direccion='X')

        respuesta = self.client.post(
            f'{self.base}/emitir-factura/', content_type='application/json', **self._como_admin(),
        )

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['sedes_facturadas'], 2)
        self.assertEqual(Decimal(cuerpo['monto']), Decimal('160000'))

    def test_las_sedes_facturadas_son_una_foto_del_momento(self):
        """Si el gimnasio abre otra sede después, la factura ya emitida NO
        cambia: se emitió y probablemente ya se envió."""
        self._suscripcion()
        factura_id = self.client.post(
            f'{self.base}/emitir-factura/', content_type='application/json', **self._como_admin(),
        ).json()['id']

        with tenant_context(self.tenant.id):
            Sede.objects.create(tenant=self.tenant, nombre='Nueva', direccion='X')

        factura = FacturaSuscripcion.objects.get(pk=factura_id)
        self.assertEqual(factura.sedes_facturadas, 1)
        self.assertEqual(factura.monto, Decimal('80000'))

    def test_no_factura_un_periodo_que_todavia_no_llego(self):
        self._contratar(corte=datetime.date.today() + datetime.timedelta(days=10))

        respuesta = self.client.post(
            f'{self.base}/emitir-factura/', content_type='application/json', **self._como_admin(),
        )

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('todavía no hay nada que facturar', respuesta.json()['detail'].lower())

    def test_emitir_avanza_el_corte_y_no_repite_periodo(self):
        """Emitir y avanzar el corte van en la misma transacción: si no, o se
        cobraría dos veces el mismo mes o se saltaría un cobro."""
        suscripcion = self._suscripcion()
        corte_original = suscripcion.proximo_corte

        self.client.post(
            f'{self.base}/emitir-factura/', content_type='application/json', **self._como_admin(),
        )

        suscripcion.refresh_from_db()
        self.assertEqual(suscripcion.proximo_corte, sumar_ciclo(corte_original, 'mensual'))
        self.assertEqual(
            suscripcion.facturas.filter(periodo_inicio=corte_original).count(), 1,
        )

    def test_un_gimnasio_sin_sedes_activas_no_se_factura(self):
        """`ck_facturas_sedes` exige más de cero, y cobrarle a quien no usa
        nada sería un error, no un caso que resolver con un mínimo de uno."""
        suscripcion = self._suscripcion()
        with tenant_context(self.tenant.id):
            Sede.objects.filter(tenant=self.tenant).update(activa=False)

        respuesta = self.client.post(
            f'{self.base}/emitir-factura/', content_type='application/json', **self._como_admin(),
        )

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertEqual(suscripcion.facturas.count(), 0)

    def test_una_suscripcion_cancelada_no_se_factura(self):
        suscripcion = self._suscripcion()
        suscripcion.estado = Suscripcion.EstadoSuscripcion.CANCELADA
        suscripcion.save(update_fields=['estado'])

        respuesta = self.client.post(
            f'{self.base}/emitir-factura/', content_type='application/json', **self._como_admin(),
        )

        self.assertEqual(respuesta.status_code, 400, respuesta.content)


class CobrosYMoraTestCase(BaseFacturacionTestCase):

    def _factura_vencida(self, dias_vencida=30):
        """Una factura emitida hace tiempo y sin pagar."""
        self._contratar(corte=datetime.date.today())
        suscripcion = self.tenant.suscripciones.get(estado='vigente')
        factura = emitir_factura(suscripcion)
        # Se retrasa la emisión para que el plazo de gracia haya pasado: el
        # plazo cuenta desde que se emite, no desde el inicio del periodo,
        # porque nadie puede pagar una factura que aún no ha recibido.
        factura.fecha_emision = datetime.date.today() - datetime.timedelta(days=dias_vencida)
        factura.save(update_fields=['fecha_emision'])
        return suscripcion, factura

    def test_marca_en_mora_cuando_se_pasa_el_plazo_de_gracia(self):
        suscripcion, _factura = self._factura_vencida()

        self.assertTrue(marcar_mora(suscripcion))

        suscripcion.refresh_from_db()
        self.assertEqual(suscripcion.estado, Suscripcion.EstadoSuscripcion.MORA)

    def test_la_mora_NO_suspende_el_gimnasio(self):
        """La decisión de fondo de toda esta parte: deber dinero y dejar de
        poder trabajar son cosas distintas. Cortar el servicio se decide a
        mano, mirando el caso."""
        suscripcion, _factura = self._factura_vencida()
        estado_antes = Tenant.objects.get(pk=self.tenant.id).estado

        marcar_mora(suscripcion)

        self.assertEqual(Tenant.objects.get(pk=self.tenant.id).estado, estado_antes)
        # Y sus usuarios siguen pudiendo entrar.
        login = self.client.post(
            '/api/auth/login/',
            data={'correo': 'duenio@factura.example.com', 'password': 'lo-que-sea'},
            content_type='application/json', HTTP_HOST='facturauno.testserver',
        )
        self.assertNotEqual(login.status_code, 403)

    def test_dentro_del_plazo_de_gracia_no_hay_mora(self):
        self._contratar(corte=datetime.date.today())
        suscripcion = self.tenant.suscripciones.get(estado='vigente')
        emitir_factura(suscripcion)

        marcar_mora(suscripcion)

        suscripcion.refresh_from_db()
        self.assertEqual(suscripcion.estado, Suscripcion.EstadoSuscripcion.VIGENTE)

    def test_pagar_saca_de_la_mora_en_el_acto(self):
        """Esperar a la siguiente pasada del comando dejaría marcado como
        moroso a quien acaba de pagar."""
        suscripcion, factura = self._factura_vencida()
        marcar_mora(suscripcion)

        respuesta = self.client.post(
            f'{self.base}/facturas/{factura.id}/pagar/',
            content_type='application/json', **self._como_admin(),
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertEqual(respuesta.json()['estado'], 'pagada')
        self.assertIsNotNone(respuesta.json()['fecha_pago'])
        suscripcion.refresh_from_db()
        self.assertEqual(suscripcion.estado, Suscripcion.EstadoSuscripcion.VIGENTE)

    def test_no_se_puede_cobrar_dos_veces_la_misma_factura(self):
        _suscripcion, factura = self._factura_vencida()
        self.client.post(
            f'{self.base}/facturas/{factura.id}/pagar/',
            content_type='application/json', **self._como_admin(),
        )

        respuesta = self.client.post(
            f'{self.base}/facturas/{factura.id}/pagar/',
            content_type='application/json', **self._como_admin(),
        )

        self.assertEqual(respuesta.status_code, 400, respuesta.content)

    def test_no_se_anula_una_factura_ya_pagada(self):
        """Eso sería una devolución, que es otra operación y no está modelada."""
        _suscripcion, factura = self._factura_vencida()
        self.client.post(
            f'{self.base}/facturas/{factura.id}/pagar/',
            content_type='application/json', **self._como_admin(),
        )

        respuesta = self.client.post(
            f'{self.base}/facturas/{factura.id}/anular/',
            content_type='application/json', **self._como_admin(),
        )

        self.assertEqual(respuesta.status_code, 400, respuesta.content)

    def test_anular_quita_la_deuda_y_la_mora(self):
        suscripcion, factura = self._factura_vencida()
        marcar_mora(suscripcion)

        self.client.post(
            f'{self.base}/facturas/{factura.id}/anular/',
            content_type='application/json', **self._como_admin(),
        )

        suscripcion.refresh_from_db()
        self.assertEqual(suscripcion.estado, Suscripcion.EstadoSuscripcion.VIGENTE)
        cobros = self.client.get('/api/plataforma/cobros/', **self._como_admin()).json()
        self.assertEqual(Decimal(cobros['totales']['saldo']), Decimal('0'))

    def test_el_listado_de_cobros_suma_lo_pendiente(self):
        _suscripcion, factura = self._factura_vencida()

        cobros = self.client.get('/api/plataforma/cobros/', **self._como_admin()).json()

        self.assertEqual(cobros['totales']['gimnasios'], 1)
        self.assertEqual(Decimal(cobros['totales']['saldo']), factura.monto)
        deudor = cobros['deudores'][0]
        self.assertEqual(deudor['tenant']['subdominio'], 'facturauno')
        self.assertGreater(deudor['dias_de_atraso'], 0)

    def test_el_atraso_nunca_es_negativo(self):
        """Una factura recién emitida y dentro de su plazo no está atrasada,
        está al día. "-5 días de atraso" no significa nada."""
        self._contratar(corte=datetime.date.today())
        emitir_factura(self.tenant.suscripciones.get(estado='vigente'))

        cobros = self.client.get('/api/plataforma/cobros/', **self._como_admin()).json()

        self.assertEqual(cobros['deudores'][0]['dias_de_atraso'], 0)

    def test_una_factura_de_otro_gimnasio_devuelve_404(self):
        _suscripcion, factura = self._factura_vencida()
        otro = self.client.post(
            '/api/plataforma/tenants/',
            data={
                'nombre_comercial': 'Gimnasio Ajeno Factura',
                'subdominio': 'facturajeno',
                'correo_admin': 'duenio@facturajeno.example.com',
            },
            content_type='application/json', **self._como_admin(),
        ).json()

        respuesta = self.client.post(
            f'/api/plataforma/tenants/{otro["uuid_publico"]}/facturas/{factura.id}/pagar/',
            content_type='application/json', **self._como_admin(),
        )

        self.assertEqual(respuesta.status_code, 404, respuesta.content)
        factura.refresh_from_db()
        self.assertEqual(factura.estado, FacturaSuscripcion.EstadoFactura.EMITIDA)

    def test_soporte_no_puede_cobrar(self):
        _suscripcion, factura = self._factura_vencida()

        respuesta = self.client.post(
            f'{self.base}/facturas/{factura.id}/pagar/',
            content_type='application/json', **self._como_soporte(),
        )

        self.assertEqual(respuesta.status_code, 403, respuesta.content)


class ComandoEmitirFacturasTestCase(BaseFacturacionTestCase):

    def test_se_pone_al_dia_con_los_atrasos(self):
        """Un gimnasio con tres meses sin facturar debe tres meses. Emitir
        solo uno por pasada escondería la deuda y cobraría de menos."""
        hace_tres_meses = datetime.date.today() - datetime.timedelta(days=95)
        self._contratar(corte=hace_tres_meses)

        call_command('emitir_facturas', verbosity=0)

        suscripcion = self.tenant.suscripciones.get()
        self.assertGreaterEqual(suscripcion.facturas.count(), 3)
        self.assertGreater(suscripcion.proximo_corte, datetime.date.today())

    def test_simular_no_escribe_nada(self):
        self._contratar(corte=datetime.date.today() - datetime.timedelta(days=40))

        call_command('emitir_facturas', simular=True, verbosity=0)

        self.assertEqual(FacturaSuscripcion.objects.count(), 0)

    def test_no_factura_lo_que_todavia_no_vence(self):
        self._contratar(corte=datetime.date.today() + datetime.timedelta(days=15))

        call_command('emitir_facturas', verbosity=0)

        self.assertEqual(FacturaSuscripcion.objects.count(), 0)
