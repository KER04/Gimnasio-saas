"""Capa de servicio de membresías (Parte A del encargo de membresías).

Igual que ``apps.ventas.services`` para el POS: la lógica de negocio vive
aquí, las vistas (``apps/membresias/views.py``) solo traducen HTTP <->
Python y delegan por completo en estas funciones.

``calcular_fechas_renovacion`` es la pieza más sensible del módulo (RF-16):
centraliza el cálculo de encadenado de una renovación para que exista en
UN SOLO lugar. Antes de este módulo, esa cuenta vivía duplicada en
``apps.ventas.services._registrar_membresia_si_aplica`` (renovar vendiendo
de nuevo el mismo plan) y hubiera vuelto a aparecer en
``renovar_membresia`` de aquí (endpoint dedicado
``POST /api/membresias/{id}/renovar/``) si no se hubiera extraído: dos
copias de la misma regla que, si un día divergen, hacen que un cliente
pierda días ya pagados sin que nadie lo note. Ahora ``apps.ventas.services``
importa esta función en vez de recalcularla.

``MembresiaError`` es la excepción de negocio de este módulo (equivalente a
``VentaError`` en ventas): la vista la atrapa y la traduce a 400 con
``str(exc)`` como mensaje, en español.
"""
import datetime

from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.auditoria.models import Auditoria
from apps.auditoria.services import registrar_auditoria

from .models import Membresia, Plan


class MembresiaError(Exception):
    """Violación de una regla de negocio del módulo de membresías. Se lanza
    deliberadamente (nunca es un bug); la vista la convierte en un 400 con
    ``str(exc)`` como mensaje."""


def _mensaje_limpio_postgres(exc):
    """Postgres antepone contexto ('CONTEXT: ...') al mensaje real de un
    RAISE EXCEPTION o de un CHECK violado. Nos quedamos con la primera
    línea. (Copia deliberadamente pequeña de la misma utilidad en
    ``apps.ventas.services``: es manipulación de cadenas, no una regla de
    negocio que pueda divergir con consecuencias.)
    """
    texto = str(exc).strip()
    return texto.split('\n')[0].strip()


# ---------------------------------------------------------------------------
# RF-16: cálculo de encadenado de una renovación (punto único, ver docstring
# de módulo).
# ---------------------------------------------------------------------------

def calcular_fechas_renovacion(*, membresia_anterior, plan, fecha_referencia):
    """Calcula ``(fecha_inicio, fecha_fin)`` de una membresía que renueva a
    ``membresia_anterior`` (puede ser ``None``: primera membresía del
    cliente para ese plan, sin nada que encadenar).

    Si ``membresia_anterior`` sigue vigente en ``fecha_referencia`` (su
    ``fecha_fin`` todavía no pasó), la nueva membresía NO arranca en
    ``fecha_referencia``: arranca justo donde terminaba la anterior, para no
    perder días ya pagados. Si ya venció (o no había anterior), arranca en
    ``fecha_referencia``.
    """
    if membresia_anterior is not None and membresia_anterior.fecha_fin >= fecha_referencia:
        nueva_fecha_inicio = membresia_anterior.fecha_fin
    else:
        nueva_fecha_inicio = fecha_referencia

    nueva_fecha_fin = nueva_fecha_inicio + datetime.timedelta(days=plan.duracion_dias)
    return nueva_fecha_inicio, nueva_fecha_fin


# ---------------------------------------------------------------------------
# A2. Asignación directa (sin venta): cortesías, traspasos, correcciones.
# ---------------------------------------------------------------------------

def asignar_membresia(
    *, tenant, sede, cliente, plan, vendedor, precio_pagado,
    fecha_inicio=None, entrenador_id=None, using='default',
):
    """Crea una membresía SIN pasar por una venta (``venta`` queda ``NULL``).

    El camino normal para adquirir una membresía es venderla (eso ya crea la
    membresía vía ``apps.ventas.services.registrar_venta``); esta función
    cubre lo que no pasa por caja: cortesías, traspasos entre sedes,
    correcciones administrativas. Por eso queda registrada en auditoría --
    dar acceso sin que medie un cobro es justo lo que alguien puede tener
    que justificar después.

    :raises MembresiaError: plan ``por_sesion`` (decisión 4: no generan
        membresía) o ``precio_pagado`` negativo.
    """
    if plan.tipo == Plan.TipoPlan.POR_SESION:
        raise MembresiaError(
            'Los planes "por sesión" no tienen vigencia y no generan membresía.'
        )
    if precio_pagado is None or precio_pagado < 0:
        raise MembresiaError('El precio pagado no puede ser negativo.')

    fecha_inicio = fecha_inicio or timezone.localdate()
    fecha_fin = fecha_inicio + datetime.timedelta(days=plan.duracion_dias)

    try:
        with transaction.atomic(using=using):
            membresia = Membresia.objects.using(using).create(
                tenant=tenant,
                cliente=cliente,
                plan=plan,
                sede=sede,
                venta=None,
                entrenador_id=entrenador_id,
                vendedor=vendedor,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                precio_pagado=precio_pagado,
            )

            registrar_auditoria(
                tenant_id=tenant.id,
                usuario_id=vendedor.id,
                sede_id=sede.id,
                entidad='membresias',
                entidad_id=membresia.id,
                accion=Auditoria.AccionAuditoria.CREAR,
                valor_anterior=None,
                valor_nuevo={
                    'asignacion_directa': True,
                    'cliente_id': cliente.id,
                    'plan_id': plan.id,
                    'fecha_inicio': str(fecha_inicio),
                    'fecha_fin': str(fecha_fin),
                    'precio_pagado': str(precio_pagado),
                },
                using=using,
            )
    except DatabaseError as exc:
        raise MembresiaError(_mensaje_limpio_postgres(exc)) from exc

    return membresia


# ---------------------------------------------------------------------------
# A3. Renovación por endpoint dedicado.
# ---------------------------------------------------------------------------

def renovar_membresia(*, membresia_anterior, usuario, precio_pagado, plan=None, using='default'):
    """Crea una membresía NUEVA encadenada a ``membresia_anterior``
    (``membresia_anterior_id``); nunca modifica la anterior.

    ``plan`` es opcional (por defecto, el mismo de ``membresia_anterior``).
    La fecha de inicio se calcula con ``calcular_fechas_renovacion`` (RF-16):
    si ``membresia_anterior`` sigue vigente hoy, la nueva arranca desde su
    ``fecha_fin``; si ya venció, arranca hoy.

    :raises MembresiaError: membresía ya cancelada, plan destino
        ``por_sesion``, o ``precio_pagado`` negativo.
    """
    if membresia_anterior.estado == Membresia.EstadoMembresia.CANCELADA:
        raise MembresiaError('No se puede renovar una membresía cancelada.')
    if precio_pagado is None or precio_pagado < 0:
        raise MembresiaError('El precio pagado no puede ser negativo.')

    plan = plan or membresia_anterior.plan
    if plan.tipo == Plan.TipoPlan.POR_SESION:
        raise MembresiaError(
            'Los planes "por sesión" no tienen vigencia y no generan membresía.'
        )

    fecha_referencia = timezone.localdate()
    nueva_fecha_inicio, nueva_fecha_fin = calcular_fechas_renovacion(
        membresia_anterior=membresia_anterior, plan=plan, fecha_referencia=fecha_referencia,
    )

    try:
        with transaction.atomic(using=using):
            membresia = Membresia.objects.using(using).create(
                tenant=membresia_anterior.tenant,
                cliente=membresia_anterior.cliente,
                plan=plan,
                sede=membresia_anterior.sede,
                venta=None,
                entrenador_id=membresia_anterior.entrenador_id,
                vendedor=usuario,
                fecha_inicio=nueva_fecha_inicio,
                fecha_fin=nueva_fecha_fin,
                precio_pagado=precio_pagado,
                membresia_anterior=membresia_anterior,
            )
    except DatabaseError as exc:
        raise MembresiaError(_mensaje_limpio_postgres(exc)) from exc

    return membresia


# ---------------------------------------------------------------------------
# A4. Cancelación.
# ---------------------------------------------------------------------------

def cancelar_membresia(*, membresia, usuario, motivo, using='default'):
    """Cancela una membresía (revoca el acceso). ``motivo`` es obligatorio
    (hay además un CHECK en la base, ``ck_membresias_cancel``, que lo exige a
    nivel de fila). No se puede cancelar una membresía ya cancelada.

    Queda registrada en auditoría: revocar el acceso de un cliente es una
    operación sensible que alguien puede tener que justificar.

    :raises MembresiaError: motivo vacío o membresía ya cancelada.
    """
    if not motivo or not motivo.strip():
        raise MembresiaError('Cancelar una membresía exige indicar un motivo.')
    if membresia.estado == Membresia.EstadoMembresia.CANCELADA:
        raise MembresiaError('Esta membresía ya está cancelada; no se puede cancelar dos veces.')

    estado_anterior = membresia.estado

    try:
        with transaction.atomic(using=using):
            membresia.estado = Membresia.EstadoMembresia.CANCELADA
            membresia.motivo_cancelacion = motivo
            membresia.save(using=using, update_fields=['estado', 'motivo_cancelacion'])

            registrar_auditoria(
                tenant_id=membresia.tenant_id,
                usuario_id=usuario.id,
                sede_id=membresia.sede_id,
                entidad='membresias',
                entidad_id=membresia.id,
                accion=Auditoria.AccionAuditoria.ANULAR,
                valor_anterior={'estado': str(estado_anterior)},
                valor_nuevo={
                    'estado': str(Membresia.EstadoMembresia.CANCELADA),
                    'motivo_cancelacion': motivo,
                },
                using=using,
            )
    except DatabaseError as exc:
        raise MembresiaError(_mensaje_limpio_postgres(exc)) from exc

    return membresia
