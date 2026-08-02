"""Las vistas de negocio calculan las fechas en la zona horaria del gimnasio.

Las dos vistas dependían de la zona horaria de la CONEXIÓN, no de la del
gimnasio. Django fuerza UTC en sus conexiones cuando ``USE_TZ = True``, así
que a partir de las 19:00 en Bogotá la base ya está en el día siguiente:

    Python (America/Bogota):  2026-08-01
    Conexión de la base (UTC): 2026-08-02

Dos consecuencias reales, ambas en horario de máxima afluencia de un gimnasio:

1. ``v_membresias_estado`` clasificaba como "vencida" toda membresía que
   venciera ese mismo día. Un cliente que pagó hasta hoy se encontraba con
   que recepción no lo dejaba entrar a partir de las siete de la tarde.

2. ``v_corte_diario`` agrupaba los pagos por su fecha en UTC, así que todo lo
   cobrado después de las 19:00 caía en el corte del día siguiente. El cierre
   de caja de un gimnasio que cierra a las diez perdía sus últimas tres horas.

El esquema ya modela ``tenants.zona_horaria`` (con America/Bogota por
defecto), así que la corrección usa la zona de cada gimnasio en vez de la de
la conexión: es correcta independientemente de cómo se conecte la aplicación,
y sigue siendo correcta el día que haya un gimnasio en otro huso.

Nota: ``ingresos_otros.fecha`` ya es una columna DATE, no un timestamp, así
que no necesita conversión — se guarda la fecha que el usuario registró.
"""

from django.db import migrations


SQL_VISTAS_CON_ZONA_HORARIA = """
CREATE OR REPLACE VIEW v_membresias_estado AS
SELECT
    m.id,
    m.tenant_id,
    m.sede_id,
    m.cliente_id,
    m.plan_id,
    m.fecha_inicio,
    m.fecha_fin,
    (m.fecha_fin - (now() AT TIME ZONE t.zona_horaria)::date) AS dias_restantes,
    CASE
        WHEN m.estado = 'cancelada' THEN 'cancelada'
        WHEN m.fecha_fin <  (now() AT TIME ZONE t.zona_horaria)::date THEN 'vencida'
        WHEN m.fecha_fin =  (now() AT TIME ZONE t.zona_horaria)::date THEN 'vence_hoy'
        WHEN m.fecha_fin <= ((now() AT TIME ZONE t.zona_horaria)::date
                             + t.dias_aviso_vencimiento::integer) THEN 'por_vencer'
        ELSE 'activa'
    END AS estado_calculado
FROM membresias m
JOIN tenants    t ON t.id = m.tenant_id;

CREATE OR REPLACE VIEW v_corte_diario AS
SELECT
    tenant_id,
    sede_id,
    fecha,
    SUM(monto) FILTER (WHERE origen = 'venta')              AS ingreso_ventas,
    SUM(monto) FILTER (WHERE origen = 'otro')               AS ingreso_otros,
    SUM(monto) FILTER (WHERE forma_pago = 'efectivo')       AS efectivo,
    SUM(monto) FILTER (WHERE forma_pago = 'transferencia')  AS transferencia,
    SUM(monto) FILTER (WHERE forma_pago = 'tarjeta')        AS tarjeta,
    SUM(monto)                                              AS total_recibido
FROM (
    SELECT p.tenant_id,
           v.sede_id,
           (p.fecha_hora AT TIME ZONE t.zona_horaria)::date AS fecha,
           p.monto,
           p.forma_pago,
           'venta'::TEXT AS origen
    FROM pagos p
    JOIN ventas  v ON v.id = p.venta_id
    JOIN tenants t ON t.id = p.tenant_id
    WHERE NOT p.anulado AND v.estado <> 'anulada'
    UNION ALL
    SELECT i.tenant_id, i.sede_id, i.fecha, i.monto, i.forma_pago, 'otro'
    FROM ingresos_otros i
) movimientos
GROUP BY tenant_id, sede_id, fecha;

-- Sin security_invoker, PostgreSQL evalúa la vista con los privilegios de su
-- propietario -- que es superusuario y se salta RLS, filtrando datos de todos
-- los gimnasios. CREATE OR REPLACE conserva las opciones existentes, pero se
-- reafirma aquí para que quede explícito y no dependa de eso.
ALTER VIEW v_membresias_estado SET (security_invoker = true);
ALTER VIEW v_corte_diario      SET (security_invoker = true);
"""


SQL_VISTAS_REVERSE = """
CREATE OR REPLACE VIEW v_membresias_estado AS
SELECT
    m.id, m.tenant_id, m.sede_id, m.cliente_id, m.plan_id,
    m.fecha_inicio, m.fecha_fin,
    (m.fecha_fin - CURRENT_DATE) AS dias_restantes,
    CASE
        WHEN m.estado = 'cancelada'                                  THEN 'cancelada'
        WHEN m.fecha_fin <  CURRENT_DATE                             THEN 'vencida'
        WHEN m.fecha_fin =  CURRENT_DATE                             THEN 'vence_hoy'
        WHEN m.fecha_fin <= CURRENT_DATE + t.dias_aviso_vencimiento  THEN 'por_vencer'
        ELSE 'activa'
    END AS estado_calculado
FROM membresias m
JOIN tenants    t ON t.id = m.tenant_id;

CREATE OR REPLACE VIEW v_corte_diario AS
SELECT
    tenant_id, sede_id, fecha,
    SUM(monto) FILTER (WHERE origen = 'venta')             AS ingreso_ventas,
    SUM(monto) FILTER (WHERE origen = 'otro')              AS ingreso_otros,
    SUM(monto) FILTER (WHERE forma_pago = 'efectivo')      AS efectivo,
    SUM(monto) FILTER (WHERE forma_pago = 'transferencia') AS transferencia,
    SUM(monto) FILTER (WHERE forma_pago = 'tarjeta')       AS tarjeta,
    SUM(monto)                                             AS total_recibido
FROM (
    SELECT p.tenant_id, v.sede_id, p.fecha_hora::DATE AS fecha,
           p.monto, p.forma_pago, 'venta'::TEXT AS origen
    FROM pagos p
    JOIN ventas v ON v.id = p.venta_id
    WHERE NOT p.anulado AND v.estado <> 'anulada'
    UNION ALL
    SELECT i.tenant_id, i.sede_id, i.fecha, i.monto, i.forma_pago, 'otro'
    FROM ingresos_otros i
) movimientos
GROUP BY tenant_id, sede_id, fecha;

ALTER VIEW v_membresias_estado SET (security_invoker = true);
ALTER VIEW v_corte_diario      SET (security_invoker = true);
"""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_trigger_stock_sedes'),
    ]

    operations = [
        migrations.RunSQL(SQL_VISTAS_CON_ZONA_HORARIA, SQL_VISTAS_REVERSE),
    ]
