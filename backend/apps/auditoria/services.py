"""Registro de auditoría (RF-02), compartido entre módulos de negocio.

Antes vivía como una función privada (``_registrar_auditoria``) dentro de
``apps.ventas.services``. Se sube a esta app -- que no depende de ventas ni
de membresías -- porque ``apps.membresias.services`` (endpoints de
membresías: asignación directa y cancelación) también necesita dejar traza
en auditoría, y declarar el INSERT en cualquiera de los dos módulos de
negocio habría creado un import circular con el otro (``ventas`` ya importa
de ``membresias.models``, y la renovación encadenada de ``membresias``
necesita poder ser llamada desde ``ventas``).
"""
import json

from django.db import connections


def registrar_auditoria(
    *, tenant_id, usuario_id, sede_id, entidad, entidad_id, accion,
    valor_anterior, valor_nuevo, using='default',
):
    """Inserta una fila en ``auditoria``.

    Se hace con SQL directo (no ``Auditoria.objects.create()``) porque la
    columna ``id`` real es ``GENERATED ALWAYS AS IDENTITY`` -- Postgres
    rechaza cualquier INSERT que mencione esa columna con un valor explícito
    (incluido NULL) a menos que se use ``OVERRIDING SYSTEM VALUE``. El modelo
    ``Auditoria`` (``managed=False``, PK compuesta ``(id, fecha_hora)``, ver
    ``apps/auditoria/models.py``) no puede declarar ``id`` como ``AutoField``
    por esa misma PK compuesta, así que el ORM siempre incluiría la columna
    en el INSERT. Omitiéndola aquí, Postgres genera el valor solo.
    """
    with connections[using].cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO auditoria
                (tenant_id, usuario_id, sede_id, entidad, entidad_id, accion,
                 valor_anterior, valor_nuevo)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
            """,
            [
                tenant_id, usuario_id, sede_id, entidad, entidad_id, accion,
                json.dumps(valor_anterior) if valor_anterior is not None else None,
                json.dumps(valor_nuevo) if valor_nuevo is not None else None,
            ],
        )
