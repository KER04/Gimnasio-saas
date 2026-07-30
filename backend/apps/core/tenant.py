"""Utilidad compartida para fijar el tenant actual en una transacción de
PostgreSQL, usada tanto por ``TenantMiddleware`` (Parte A) como por scripts,
comandos de gestión y la batería de pruebas de aislamiento (Parte C).

Toda la lógica de aislamiento multi-tenant depende de una única función SQL,
``fn_tenant_actual()`` (creada en ``apps.core`` migración 0001), que las 35
políticas RLS usan para comparar contra la columna ``tenant_id`` de cada
fila:

    SELECT NULLIF(current_setting('app.tenant_id', TRUE), '')::BIGINT;

Este módulo es el ÚNICO lugar del proyecto que debe escribir a esa variable
de sesión, para que la manera de fijarla (y de que deje de existir) sea
siempre la misma.
"""
from contextlib import contextmanager

from django.db import connections, transaction


@contextmanager
def tenant_context(tenant_id, using='default'):
    """Abre una transacción en la conexión ``using`` y fija ``app.tenant_id``
    dentro de ella para que las políticas RLS de PostgreSQL filtren por ese
    tenant durante todo el bloque ``with``.

    Detalles importantes:

    - Se usa ``set_config('app.tenant_id', %s, true)`` — NUNCA ``SET LOCAL``
      con interpolación de cadena. ``SET`` no admite parámetros bind (no hay
      forma de hacer ``SET LOCAL app.tenant_id = %s``), así que construirlo
      con f-strings/format sería inyectable. ``set_config`` sí es una
      función normal y acepta el valor como parámetro.
    - El tercer argumento, ``true``, es el equivalente de ``SET LOCAL``: el
      valor solo vive DENTRO de la transacción actual. Al hacer COMMIT o
      ROLLBACK de esa transacción, PostgreSQL restaura el valor previo
      (típicamente "sin fijar") automáticamente. Por eso, si esta función se
      usa como transacción de nivel superior (no anidada dentro de otro
      ``atomic()`` ya abierto), es imposible que el tenant de una petición
      "se cuele" a la siguiente que reutilice la misma conexión: no hace
      falta limpiar nada al salir, PostgreSQL ya lo hizo.
    - Si se anida dentro de una transacción ya abierta (por ejemplo, dentro
      de una prueba envuelta en ``TestCase``, que usa su propia transacción
      con SAVEPOINTs), el valor sigue siendo válido hasta que la transacción
      EXTERNA termine, no hasta que este ``with`` se cierre — un
      ``RELEASE SAVEPOINT`` no deshace ``set_config``. Esto es exactamente lo
      que documenta ``apps/core/tests/test_aislamiento.py`` sobre por qué esa
      batería usa ``TransactionTestCase`` en vez de ``TestCase``.

    :param tenant_id: id (BIGINT) del tenant a fijar como actual.
    :param using: alias de conexión de Django (``'default'`` en producción;
        también puede usarse con ``'ddl'`` para sembrado con superusuario,
        donde es inocuo porque un superusuario se salta RLS de todas formas).
    """
    with transaction.atomic(using=using):
        with connections[using].cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])
        yield
