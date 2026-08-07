"""Qué día es HOY para un gimnasio.

## El problema que resuelve

Varias columnas del esquema declaran ``db_default=CURRENT_DATE``, es decir,
la fecha la pone PostgreSQL. Y ``CURRENT_DATE`` se evalúa en la zona horaria
de la CONEXIÓN, que Django fuerza a UTC cuando ``USE_TZ = True``.

Consecuencia medida en esta misma base:

    CURRENT_DATE de la conexión -> 2026-08-07   (UTC)
    fecha real en Colombia      -> 2026-08-06

A partir de las 19:00 en Bogotá, todo lo que dependa de ese valor por
defecto queda fechado AL DÍA SIGUIENTE: una ficha de medidas abierta el
martes por la noche dice que empezó el miércoles, un cliente registrado a las
ocho aparece dado de alta mañana.

Es el mismo fallo que ya se corrigió en las vistas de negocio (``apps.core``
migración 0004), donde las membresías vencían un día antes por esta misma
razón. Allí se arregló con ``now() AT TIME ZONE t.zona_horaria``; aquí no se
puede, porque un ``db_default`` no tiene acceso a la fila del tenant.

## La solución

Calcular la fecha en Python, en la zona del GIMNASIO, y mandarla explícita en
el INSERT en vez de dejar que la base la invente. Cada vista que cree una
fila con fecha "de hoy" debe usar esto.
"""
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone


def hoy_del_gimnasio(tenant=None):
    """La fecha de hoy en la zona horaria de ``tenant``.

    Sin tenant —o con uno cuya zona no se pueda resolver— cae a la del
    servidor (``settings.TIME_ZONE``), que es lo que hacía antes de existir
    esta función y sigue siendo correcto mientras el gimnasio esté en esa
    misma zona. Nunca lanza: una zona mal escrita no debe impedir registrar
    un cliente.
    """
    zona = getattr(tenant, 'zona_horaria', None)
    if not zona:
        return timezone.localdate()

    try:
        return datetime.now(ZoneInfo(zona)).date()
    except (ZoneInfoNotFoundError, ValueError):
        # El panel del proveedor valida la zona al guardarla, así que llegar
        # aquí significa que se metió por SQL. Se sigue adelante con la del
        # servidor en vez de tumbar la petición.
        return timezone.localdate()


def hoy_de_la_peticion(request):
    """Atajo para las vistas: ``request.tenant`` lo publica el middleware."""
    return hoy_del_gimnasio(getattr(request, 'tenant', None))
