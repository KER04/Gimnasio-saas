"""Lógica de negocio de inventario: movimientos del kardex.

## Por qué todo pasa por ``movimientos_inventario``

``stock_sedes`` es una desnormalización mantenida por el disparador
``fn_actualizar_stock_sede`` (``apps.core`` migración 0003), que es
``BEFORE INSERT`` sobre ``movimientos_inventario`` y hace tres cosas en una
sola pasada: crea la fila de stock si no existe, la bloquea con
``SELECT ... FOR UPDATE`` (evita el *lost update* entre dos movimientos
concurrentes del mismo producto y sede), y valida que el saldo resultante no
quede negativo -- si lo queda, lanza ``RAISE EXCEPTION`` y revierte la
transacción entera.

Corolario: esta capa **nunca** escribe en ``stock_sedes`` ni calcula
``saldo_resultante``. Insertar la fila del kardex es la única forma de mover
existencias, y hacerlo de otro modo desincronizaría justo lo que el diseño
protege.
"""
from decimal import Decimal

from django.db import DatabaseError, transaction

from .models import MovimientoInventario


class InventarioError(Exception):
    """Violación de una regla de negocio de inventario, con mensaje en
    español listo para mostrar. La vista la traduce a 400."""


#: Tipos que se pueden registrar desde ESTA API. ``salida_venta`` y
#: ``reverso_anulacion`` quedan fuera a propósito: los emite
#: ``apps.ventas.services`` como parte de una venta o de su anulación, y
#: dejarlos abiertos aquí permitiría fabricar movimientos de venta sin venta
#: detrás, rompiendo la trazabilidad del kardex.
TIPOS_MANUALES = (
    MovimientoInventario.TipoMovimiento.ENTRADA_COMPRA,
    MovimientoInventario.TipoMovimiento.AJUSTE_MANUAL,
)


def _mensaje_limpio_postgres(exc):
    """Extrae la primera línea del error de PostgreSQL, que es la del
    ``RAISE EXCEPTION`` del disparador; el resto es contexto de plpgsql que
    no le dice nada a quien está en el mostrador."""
    return str(exc).strip().splitlines()[0]


def registrar_movimiento(
    *, tenant, producto, sede, usuario, tipo, cantidad,
    costo_unitario=None, motivo=None, using='default',
):
    """Registra un movimiento manual de inventario (entrada o ajuste).

    :param cantidad: CON SIGNO. Positiva entra, negativa sale. Es la
        convención de la tabla (``ck_movinv_cantidad`` prohíbe el cero) y
        hace que el saldo sea una simple suma.
    :raises InventarioError: tipo no permitido desde esta API, cantidad cero,
        entrada con cantidad negativa, ajuste sin motivo, o existencia
        insuficiente (esto último lo detecta el disparador).
    """
    if tipo not in TIPOS_MANUALES:
        raise InventarioError(
            'Desde aquí solo se pueden registrar entradas por compra y '
            'ajustes manuales: las salidas por venta y los reversos los '
            'genera la propia venta.'
        )

    if cantidad is None or cantidad == 0:
        raise InventarioError('La cantidad del movimiento no puede ser cero.')

    if tipo == MovimientoInventario.TipoMovimiento.ENTRADA_COMPRA and cantidad < 0:
        raise InventarioError(
            'Una entrada por compra suma existencias: su cantidad debe ser '
            'positiva. Para descontar, usa un ajuste manual.'
        )

    # Un ajuste sin motivo es inauditable, y así lo exige también
    # `ck_movinv_ajuste_motivo` en la base: se valida aquí para devolver un
    # 400 legible en vez de un IntegrityError convertido en 500.
    if tipo == MovimientoInventario.TipoMovimiento.AJUSTE_MANUAL and (
        not motivo or not motivo.strip()
    ):
        raise InventarioError('Un ajuste manual exige indicar el motivo.')

    if costo_unitario is not None and costo_unitario < 0:
        raise InventarioError('El costo unitario no puede ser negativo.')

    try:
        with transaction.atomic(using=using):
            movimiento = MovimientoInventario.objects.using(using).create(
                tenant=tenant,
                producto=producto,
                sede=sede,
                usuario=usuario,
                tipo=tipo,
                cantidad=cantidad,
                # El disparador es BEFORE INSERT y sobrescribe este valor con
                # el saldo real antes de que la fila llegue a persistirse;
                # este cero nunca se guarda.
                saldo_resultante=Decimal('0'),
                costo_unitario=costo_unitario,
                motivo=motivo,
            )
    except DatabaseError as exc:
        # Aquí cae el RAISE EXCEPTION del disparador cuando el ajuste dejaría
        # el stock en negativo.
        raise InventarioError(_mensaje_limpio_postgres(exc)) from exc

    movimiento.refresh_from_db(using=using)
    return movimiento
