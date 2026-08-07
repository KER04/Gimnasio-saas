"""Qué día es HOY para un gimnasio (``apps.core.fechas``).

Este fallo es invisible durante el día y aparece solo de noche, que es
justo cuando nadie está mirando: a partir de las 19:00 en Colombia, la
conexión de PostgreSQL —que Django fuerza a UTC— ya está en el día
siguiente, y todo lo que dependiera de ``db_default=CURRENT_DATE`` quedaba
fechado mañana.
"""
import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings

from apps.core.fechas import hoy_del_gimnasio
from apps.plataforma.models import Tenant


class _TenantFalso:
    def __init__(self, zona):
        self.zona_horaria = zona


class HoyDelGimnasioTestCase(TestCase):

    def test_usa_la_zona_del_gimnasio_y_no_la_del_servidor(self):
        """A las 03:00 UTC del día 7, en Bogotá siguen siendo las 22:00 del 6.

        Es exactamente el caso que se vio en producción: una ficha abierta
        por la noche decía que empezaba al día siguiente.
        """
        instante = datetime.datetime(2026, 8, 7, 3, 0, tzinfo=datetime.timezone.utc)

        with mock.patch('apps.core.fechas.datetime') as reloj:
            reloj.now.side_effect = lambda tz: instante.astimezone(tz)
            hoy = hoy_del_gimnasio(_TenantFalso('America/Bogota'))

        self.assertEqual(hoy, datetime.date(2026, 8, 6))

    def test_un_gimnasio_en_otro_huso_puede_estar_en_otro_dia(self):
        """Dos gimnasios del mismo sistema pueden estar en fechas distintas a
        la vez, y cada uno debe ver la suya."""
        instante = datetime.datetime(2026, 8, 7, 3, 0, tzinfo=datetime.timezone.utc)

        with mock.patch('apps.core.fechas.datetime') as reloj:
            reloj.now.side_effect = lambda tz: instante.astimezone(tz)
            bogota = hoy_del_gimnasio(_TenantFalso('America/Bogota'))
            madrid = hoy_del_gimnasio(_TenantFalso('Europe/Madrid'))

        self.assertEqual(bogota, datetime.date(2026, 8, 6))
        self.assertEqual(madrid, datetime.date(2026, 8, 7))

    def test_sin_tenant_cae_a_la_zona_del_servidor(self):
        self.assertEqual(hoy_del_gimnasio(None), datetime.datetime.now(
            ZoneInfo('America/Bogota'),
        ).date())

    def test_una_zona_invalida_no_tumba_la_peticion(self):
        """Solo puede llegar aquí algo metido por SQL —el panel valida la zona
        al guardarla—, y aun así registrar un cliente no debe fallar."""
        self.assertIsNotNone(hoy_del_gimnasio(_TenantFalso('Marte/Olympus')))


@override_settings(ALLOWED_HOSTS=['testserver', '.testserver'])
class FechasDeAltaTestCase(TestCase):
    """Las columnas con ``db_default=CURRENT_DATE`` ya no deciden la fecha."""

    databases = {'default', 'ddl'}

    def test_el_alta_de_un_gimnasio_no_usa_la_fecha_de_la_conexion(self):
        """`CURRENT_DATE` se evalúa en UTC; `fecha_alta` debe salir de Python."""
        from apps.plataforma.aprovisionamiento import aprovisionar_tenant

        with mock.patch('apps.plataforma.aprovisionamiento.timezone') as reloj:
            reloj.localdate.return_value = datetime.date(2020, 1, 1)
            tenant, _sede, _usuario = aprovisionar_tenant(
                nombre='Gimnasio Fecha',
                subdominio='fechaalta',
                correo_admin='admin@fechaalta.example.com',
                password_admin='una-clave-larga-de-prueba',
                conexion='ddl',
            )

        # Se relee por la MISMA conexión con la que se escribió: en pruebas,
        # 'ddl' es un espejo de 'default' pero con su propia transacción.
        self.assertEqual(
            Tenant.objects.using('ddl').get(pk=tenant.pk).fecha_alta,
            datetime.date(2020, 1, 1),
            'La fecha de alta debe venir de la aplicación, no de CURRENT_DATE.',
        )
