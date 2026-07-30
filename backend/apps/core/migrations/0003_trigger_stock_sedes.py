"""Disparador de ``stock_sedes`` (Parte B del encargo de ventas/POS).

El comentario del .sql sobre ``stock_sedes`` (ver ``apps/inventario/models.py``,
docstring de ``StockSede``) dice que la tabla "se mantiene por disparador",
pero ese disparador nunca llegó a escribirse: hasta ahora, insertar un
``MovimientoInventario`` no tocaba ``stock_sedes`` en absoluto.

## Por qué es un único trigger BEFORE INSERT, y no BEFORE + AFTER

El encargo pedía explícitamente un trigger AFTER INSERT, pero deja abierta la
posibilidad de un BEFORE adicional "si hace falta", y aquí SÍ hace falta --
más que eso, hace innecesario el AFTER:

- ``movimientos_inventario.saldo_resultante`` es ``NOT NULL`` y no tiene
  default: alguien tiene que rellenarlo. La única forma de que un trigger
  modifique la fila que se está insertando (``NEW.saldo_resultante := ...``)
  es en un trigger **BEFORE** -- un trigger AFTER ya no puede alterar ``NEW``,
  la fila ya quedó escrita tal cual llegó.
- Ese mismo cálculo (saldo anterior + NEW.cantidad) es exactamente el que
  hace falta para decidir si hay que rechazar el movimiento por stock
  insuficiente, y para saber cuánto UPSERT-ear en ``stock_sedes``. Partirlo
  en dos triggers (uno que calcula y valida antes, otro que escribe
  ``stock_sedes`` después) obligaría a repetir el `SELECT ... FOR UPDATE` o a
  pasar el valor de un trigger a otro por una tabla temporal -- innecesario
  cuando todo cabe, de forma más simple y sin duplicar el bloqueo de fila, en
  un solo BEFORE.

Por eso ``fn_actualizar_stock_sede`` hace las tres cosas en un único trigger
BEFORE INSERT: bloquea/crea la fila de ``stock_sedes``, valida que el
resultado no sea negativo (si lo es, ``RAISE EXCEPTION`` con un mensaje legible
que aborta toda la transacción -- la venta completa se revierte, no solo este
movimiento) y dentro de la misma pasada dejar el nuevo saldo tanto en
``stock_sedes`` como en ``NEW.saldo_resultante``.

## Por qué solo INSERT

``movimientos_inventario`` es un libro inmutable (nunca se hace UPDATE ni
DELETE sobre una fila ya escrita; los errores se corrigen con un movimiento
inverso, tipo ``reverso_anulacion``). El trigger se declara únicamente
``BEFORE INSERT`` -- no existe una versión ``BEFORE UPDATE``/``BEFORE
DELETE`` de este disparador, así que un intento de modificar o borrar una
fila del kardex ni siquiera pasa por esta función (la tabla no tiene RLS de
escritura especial más allá de la política de tenant ya existente, pero
tampoco hace falta: nada en la aplicación emite UPDATE/DELETE sobre esta
tabla).

## Bloqueo de fila (condición de carrera)

``SELECT ... FOR UPDATE`` sobre la fila de ``stock_sedes`` antes de decidir
si hay existencia suficiente evita que dos ventas concurrentes del mismo
producto/sede lean el mismo saldo "de partida" y ambas crean, erróneamente,
que hay unidades de sobra (lost update). La segunda transacción que llegue
espera a que la primera libere el bloqueo (COMMIT o ROLLBACK) y entonces ve
el saldo ya actualizado.
"""
from django.db import migrations

SQL_FN_TRIGGER = """
CREATE OR REPLACE FUNCTION fn_actualizar_stock_sede()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_cantidad_actual  NUMERIC(12,2);
    v_nuevo_saldo      NUMERIC(12,2);
    v_nombre_producto  VARCHAR(120);
    v_nombre_sede      VARCHAR(120);
BEGIN
    -- Asegura que exista una fila de stock_sedes para (producto, sede),
    -- arrancando en 0 -- nunca en NEW.cantidad, para no adelantarnos al
    -- chequeo de saldo negativo que viene más abajo. DO NOTHING si ya
    -- existe: no se toca su valor actual.
    INSERT INTO stock_sedes (producto_id, sede_id, tenant_id, cantidad)
    VALUES (NEW.producto_id, NEW.sede_id, NEW.tenant_id, 0)
    ON CONFLICT (producto_id, sede_id) DO NOTHING;

    -- Bloquea la fila (ver docstring del módulo: evita que dos movimientos
    -- concurrentes del mismo producto/sede lean el mismo saldo de partida).
    SELECT cantidad INTO v_cantidad_actual
      FROM stock_sedes
     WHERE producto_id = NEW.producto_id AND sede_id = NEW.sede_id
       FOR UPDATE;

    v_nuevo_saldo := v_cantidad_actual + NEW.cantidad;

    IF v_nuevo_saldo < 0 THEN
        SELECT nombre INTO v_nombre_producto FROM productos WHERE id = NEW.producto_id;
        SELECT nombre INTO v_nombre_sede FROM sedes WHERE id = NEW.sede_id;
        RAISE EXCEPTION 'Stock insuficiente para el producto % en la sede %',
            COALESCE(v_nombre_producto, NEW.producto_id::TEXT),
            COALESCE(v_nombre_sede, NEW.sede_id::TEXT);
    END IF;

    UPDATE stock_sedes
       SET cantidad = v_nuevo_saldo
     WHERE producto_id = NEW.producto_id AND sede_id = NEW.sede_id;

    -- Solo se puede escribir en un trigger BEFORE: una vez insertada la
    -- fila, NEW ya no se puede modificar (ver docstring del módulo).
    NEW.saldo_resultante := v_nuevo_saldo;

    RETURN NEW;
END;
$$;

CREATE TRIGGER tg_movinv_actualizar_stock
    BEFORE INSERT ON movimientos_inventario
    FOR EACH ROW
    EXECUTE FUNCTION fn_actualizar_stock_sede();
"""

SQL_FN_TRIGGER_REVERSE = """
DROP TRIGGER IF EXISTS tg_movinv_actualizar_stock ON movimientos_inventario;
DROP FUNCTION IF EXISTS fn_actualizar_stock_sede();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_rls_particiones_auditoria'),
    ]

    operations = [
        migrations.RunSQL(sql=SQL_FN_TRIGGER, reverse_sql=SQL_FN_TRIGGER_REVERSE),
    ]
