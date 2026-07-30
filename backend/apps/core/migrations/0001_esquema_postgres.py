"""
Migración RunSQL que completa el esquema PostgreSQL (esquema_gimnasio_postgres.sql)
sobre lo que Django ya creó vía ORM en las 9 apps de negocio.

Corre al final (dependencies apunta a la última migración de cada app),
porque casi todas sus operaciones (FKs compuestas, RLS, triggers) necesitan
que las tablas ya existan.

Orden de operaciones (mantenido deliberadamente, cada una depende de que la
anterior ya haya corrido):
    1.  Extensiones
    2.  Funciones utilitarias (fn_set_actualizado_en, fn_tenant_actual,
        fn_siguiente_consecutivo)
    3.  FKs compuestas (id, tenant_id) — 61 en total
    4.  PK compuesta real de stock_sedes
    5.  Índices GIN trigram
    6.  Triggers de actualizado_en (14 tablas)
    7.  Tabla auditoria particionada + particiones + índices
    8.  Vistas de negocio (3)
    9.  Row Level Security (35 tablas)
    10. GRANTS a keradmin
    11. Semilla de permisos (19 filas)
"""
from django.db import migrations


# -----------------------------------------------------------------------
# 1. Extensiones
# -----------------------------------------------------------------------
SQL_EXTENSIONES = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gist;
"""

SQL_EXTENSIONES_REVERSE = """
DROP EXTENSION IF EXISTS btree_gist;
DROP EXTENSION IF EXISTS pg_trgm;
DROP EXTENSION IF EXISTS citext;
DROP EXTENSION IF EXISTS pgcrypto;
"""


# -----------------------------------------------------------------------
# 2. Funciones utilitarias (copiadas literalmente de la sección 03 del .sql)
# -----------------------------------------------------------------------
SQL_FUNCIONES = """
CREATE OR REPLACE FUNCTION fn_set_actualizado_en()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.actualizado_en := clock_timestamp();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION fn_tenant_actual()
RETURNS BIGINT
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.tenant_id', TRUE), '')::BIGINT;
$$;

CREATE OR REPLACE FUNCTION fn_siguiente_consecutivo(p_sede_id BIGINT)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    v_numero BIGINT;
BEGIN
    UPDATE secuencias_comprobantes
       SET ultimo_numero = ultimo_numero + 1
     WHERE sede_id = p_sede_id
    RETURNING ultimo_numero INTO v_numero;

    IF v_numero IS NULL THEN
        RAISE EXCEPTION 'La sede % no tiene secuencia de comprobantes configurada', p_sede_id;
    END IF;

    RETURN v_numero;
END;
$$;
"""

SQL_FUNCIONES_REVERSE = """
DROP FUNCTION IF EXISTS fn_siguiente_consecutivo(BIGINT);
DROP FUNCTION IF EXISTS fn_tenant_actual();
DROP FUNCTION IF EXISTS fn_set_actualizado_en();
"""


# -----------------------------------------------------------------------
# 3. FKs compuestas (id, tenant_id) — 61 constraints
# -----------------------------------------------------------------------
# (tabla, nombre_constraint, columna_local, tabla_referenciada, on_delete)
_COMPOSITE_FKS = [
    ('secuencias_comprobantes', 'fk_secuencias_sede', 'sede_id', 'sedes', 'CASCADE'),
    ('roles_permisos', 'fk_rolperm_rol', 'rol_id', 'roles', 'CASCADE'),
    ('usuarios', 'fk_usuarios_rol', 'rol_id', 'roles', 'RESTRICT'),
    ('usuarios_sedes', 'fk_usrsede_usuario', 'usuario_id', 'usuarios', 'CASCADE'),
    ('usuarios_sedes', 'fk_usrsede_sede', 'sede_id', 'sedes', 'CASCADE'),
    ('clientes', 'fk_clientes_sede', 'sede_origen_id', 'sedes', 'RESTRICT'),
    ('autorizaciones_datos', 'fk_autoriz_cliente', 'cliente_id', 'clientes', 'CASCADE'),
    ('huellas_clientes', 'fk_huellas_cliente', 'cliente_id', 'clientes', 'CASCADE'),
    ('dispositivos_biometricos', 'fk_dispositivos_sede', 'sede_id', 'sedes', 'CASCADE'),
    ('planes', 'fk_planes_sede', 'sede_id', 'sedes', 'RESTRICT'),
    ('membresias', 'fk_membresias_cliente', 'cliente_id', 'clientes', 'RESTRICT'),
    ('membresias', 'fk_membresias_plan', 'plan_id', 'planes', 'RESTRICT'),
    ('membresias', 'fk_membresias_sede', 'sede_id', 'sedes', 'RESTRICT'),
    ('membresias', 'fk_membresias_entrenador', 'entrenador_id', 'usuarios', 'RESTRICT'),
    ('membresias', 'fk_membresias_vendedor', 'vendedor_id', 'usuarios', 'RESTRICT'),
    ('membresias', 'fk_membresias_anterior', 'membresia_anterior_id', 'membresias', 'RESTRICT'),
    ('membresias', 'fk_membresias_venta', 'venta_id', 'ventas', 'RESTRICT'),
    ('productos', 'fk_productos_categoria', 'categoria_producto_id', 'categorias_producto', 'RESTRICT'),
    ('stock_sedes', 'fk_stock_producto', 'producto_id', 'productos', 'CASCADE'),
    ('stock_sedes', 'fk_stock_sede', 'sede_id', 'sedes', 'CASCADE'),
    ('movimientos_inventario', 'fk_movinv_producto', 'producto_id', 'productos', 'RESTRICT'),
    ('movimientos_inventario', 'fk_movinv_sede', 'sede_id', 'sedes', 'RESTRICT'),
    ('movimientos_inventario', 'fk_movinv_usuario', 'usuario_id', 'usuarios', 'RESTRICT'),
    ('movimientos_inventario', 'fk_movinv_venta', 'venta_id', 'ventas', 'RESTRICT'),
    ('ventas', 'fk_ventas_sede', 'sede_id', 'sedes', 'RESTRICT'),
    ('ventas', 'fk_ventas_cliente', 'cliente_id', 'clientes', 'RESTRICT'),
    ('ventas', 'fk_ventas_usuario', 'usuario_id', 'usuarios', 'RESTRICT'),
    ('ventas', 'fk_ventas_anulador', 'anulada_por', 'usuarios', 'RESTRICT'),
    ('detalle_ventas', 'fk_detven_venta', 'venta_id', 'ventas', 'CASCADE'),
    ('detalle_ventas', 'fk_detven_producto', 'producto_id', 'productos', 'RESTRICT'),
    ('detalle_ventas', 'fk_detven_plan', 'plan_id', 'planes', 'RESTRICT'),
    ('detalle_ventas', 'fk_detven_categoria', 'categoria_ingreso_id', 'categorias_ingreso', 'RESTRICT'),
    ('pagos', 'fk_pagos_venta', 'venta_id', 'ventas', 'RESTRICT'),
    ('pagos', 'fk_pagos_usuario', 'usuario_id', 'usuarios', 'RESTRICT'),
    ('ingresos_otros', 'fk_ingotros_sede', 'sede_id', 'sedes', 'RESTRICT'),
    ('ingresos_otros', 'fk_ingotros_categoria', 'categoria_ingreso_id', 'categorias_ingreso', 'RESTRICT'),
    ('ingresos_otros', 'fk_ingotros_usuario', 'usuario_id', 'usuarios', 'RESTRICT'),
    ('gastos', 'fk_gastos_sede', 'sede_id', 'sedes', 'RESTRICT'),
    ('gastos', 'fk_gastos_categoria', 'categoria_gasto_id', 'categorias_gasto', 'RESTRICT'),
    ('gastos', 'fk_gastos_usuario', 'usuario_id', 'usuarios', 'RESTRICT'),
    ('asistencias', 'fk_asist_sede', 'sede_id', 'sedes', 'RESTRICT'),
    ('asistencias', 'fk_asist_cliente', 'cliente_id', 'clientes', 'RESTRICT'),
    ('asistencias', 'fk_asist_venta', 'venta_id', 'ventas', 'RESTRICT'),
    ('asistencias', 'fk_asist_autorizado', 'autorizado_por', 'usuarios', 'RESTRICT'),
    ('intentos_biometricos_fallidos', 'fk_intfall_sede', 'sede_id', 'sedes', 'CASCADE'),
    ('fichas_medidas', 'fk_ficha_cliente', 'cliente_id', 'clientes', 'CASCADE'),
    ('fichas_medidas', 'fk_ficha_entrenador', 'entrenador_id', 'usuarios', 'RESTRICT'),
    ('controles_medidas', 'fk_control_ficha', 'ficha_medida_id', 'fichas_medidas', 'CASCADE'),
    ('controles_medidas', 'fk_control_usuario', 'registrado_por', 'usuarios', 'RESTRICT'),
    ('ejercicios', 'fk_ejercicios_grupo', 'grupo_muscular_id', 'grupos_musculares', 'RESTRICT'),
    ('rutinas', 'fk_rutinas_cliente', 'cliente_id', 'clientes', 'CASCADE'),
    ('rutinas', 'fk_rutinas_entrenador', 'entrenador_id', 'usuarios', 'RESTRICT'),
    ('rutina_dias', 'fk_rutdia_rutina', 'rutina_id', 'rutinas', 'CASCADE'),
    ('rutina_ejercicios', 'fk_rutejer_dia', 'rutina_dia_id', 'rutina_dias', 'CASCADE'),
    ('rutina_ejercicios', 'fk_rutejer_ejercicio', 'ejercicio_id', 'ejercicios', 'RESTRICT'),
    ('registros_ejercicios', 'fk_regejer_rutejer', 'rutina_ejercicio_id', 'rutina_ejercicios', 'CASCADE'),
    ('registros_ejercicios', 'fk_regejer_cliente', 'cliente_id', 'clientes', 'CASCADE'),
    ('registros_ejercicios', 'fk_regejer_usuario', 'registrado_por', 'usuarios', 'RESTRICT'),
    ('records_personales', 'fk_records_cliente', 'cliente_id', 'clientes', 'CASCADE'),
    ('records_personales', 'fk_records_ejercicio', 'ejercicio_id', 'ejercicios', 'RESTRICT'),
    ('records_personales', 'fk_records_registro', 'registro_ejercicio_id', 'registros_ejercicios', 'SET NULL'),
]

assert len(_COMPOSITE_FKS) == 61

SQL_FKS_COMPUESTAS = '\n'.join(
    f'ALTER TABLE {tabla} ADD CONSTRAINT {nombre}\n'
    f'    FOREIGN KEY ({columna}, tenant_id) REFERENCES {padre} (id, tenant_id)\n'
    f'    ON UPDATE CASCADE ON DELETE {on_delete};'
    for tabla, nombre, columna, padre, on_delete in _COMPOSITE_FKS
)

SQL_FKS_COMPUESTAS_REVERSE = '\n'.join(
    f'ALTER TABLE {tabla} DROP CONSTRAINT IF EXISTS {nombre};'
    for tabla, nombre, _columna, _padre, _on_delete in reversed(_COMPOSITE_FKS)
)


# -----------------------------------------------------------------------
# 3b. FKs simples con ON UPDATE/DELETE explícito (no compuestas: el padre no
#     tiene tenant_id, o el propio tenant_id apunta directo a tenants).
#
# Django ya crea una FK simple para cada ForeignKey del modelo, pero SIN
# cláusula ON DELETE/ON UPDATE a nivel de motor (on_delete=CASCADE/PROTECT/
# SET_NULL de Django se aplica solo a nivel de aplicación, vía el Collector
# del ORM, no como comportamiento del motor). Para las relaciones que el
# .sql declara con ON DELETE explícito y que NO quedan cubiertas por
# ninguna FK compuesta de la sección 3 (relaciones directas a tenants desde
# tablas "raíz" del tenant, y un puñado de FKs simples entre tablas sin
# tenant_id propio: facturas_suscripcion, roles_permisos.permiso_id,
# intentos_biometricos_fallidos.dispositivo_id), se añade aquí la FK con
# nombre y comportamiento reales del .sql, igual que las compuestas: ENCIMA
# de la que ya creó Django, no en su lugar.
_SIMPLE_FKS = [
    ('categorias_producto', 'fk_catprod_tenant', 'tenant_id', 'tenants', 'CASCADE'),
    ('categorias_ingreso', 'fk_catingr_tenant', 'tenant_id', 'tenants', 'CASCADE'),
    ('categorias_gasto', 'fk_catgasto_tenant', 'tenant_id', 'tenants', 'CASCADE'),
    ('clientes', 'fk_clientes_tenant', 'tenant_id', 'tenants', 'CASCADE'),
    ('ejercicios', 'fk_ejercicios_tenant', 'tenant_id', 'tenants', 'CASCADE'),
    ('facturas_suscripcion', 'fk_facturas_susc', 'suscripcion_id', 'suscripciones', 'RESTRICT'),
    ('grupos_musculares', 'fk_grupomusc_tenant', 'tenant_id', 'tenants', 'CASCADE'),
    ('impersonaciones', 'fk_imperson_usuario', 'usuario_plataforma_id', 'usuarios_plataforma', 'RESTRICT'),
    ('impersonaciones', 'fk_imperson_tenant', 'tenant_id', 'tenants', 'CASCADE'),
    ('intentos_biometricos_fallidos', 'fk_intfall_disp', 'dispositivo_id', 'dispositivos_biometricos', 'SET NULL'),
    ('planes', 'fk_planes_tenant', 'tenant_id', 'tenants', 'CASCADE'),
    ('productos', 'fk_productos_tenant', 'tenant_id', 'tenants', 'CASCADE'),
    ('roles_permisos', 'fk_rolperm_permiso', 'permiso_id', 'permisos', 'CASCADE'),
    ('roles', 'fk_roles_tenant', 'tenant_id', 'tenants', 'CASCADE'),
    ('sedes', 'fk_sedes_tenant', 'tenant_id', 'tenants', 'CASCADE'),
    ('suscripciones', 'fk_suscripciones_plan', 'plan_suscripcion_id', 'planes_suscripcion', 'RESTRICT'),
    ('suscripciones', 'fk_suscripciones_tenant', 'tenant_id', 'tenants', 'CASCADE'),
    ('usuarios', 'fk_usuarios_tenant', 'tenant_id', 'tenants', 'CASCADE'),
]

assert len(_SIMPLE_FKS) == 18

SQL_FKS_SIMPLES = '\n'.join(
    f'ALTER TABLE {tabla} ADD CONSTRAINT {nombre}\n'
    f'    FOREIGN KEY ({columna}) REFERENCES {padre} (id)\n'
    f'    ON UPDATE CASCADE ON DELETE {on_delete};'
    for tabla, nombre, columna, padre, on_delete in _SIMPLE_FKS
)

SQL_FKS_SIMPLES_REVERSE = '\n'.join(
    f'ALTER TABLE {tabla} DROP CONSTRAINT IF EXISTS {nombre};'
    for tabla, nombre, _columna, _padre, _on_delete in reversed(_SIMPLE_FKS)
)

# Renombres cosméticos: Django no permite fijar el nombre de una PK
# compuesta (CompositePrimaryKey) ni el de un UniqueConstraint(unique=True)
# simple sobre un solo campo declarado con unique=True; el resultado es
# funcionalmente idéntico al del .sql pero con el nombre autogenerado por
# Postgres/Django. Se renombra para que el catálogo quede idéntico.
SQL_RENOMBRES = """
ALTER TABLE roles_permisos RENAME CONSTRAINT roles_permisos_pkey TO pk_roles_permisos;
ALTER TABLE usuarios_sedes RENAME CONSTRAINT usuarios_sedes_pkey TO pk_usuarios_sedes;
ALTER TABLE tenants RENAME CONSTRAINT tenants_uuid_publico_key TO uq_tenants_uuid;
"""

SQL_RENOMBRES_REVERSE = """
ALTER TABLE tenants RENAME CONSTRAINT uq_tenants_uuid TO tenants_uuid_publico_key;
ALTER TABLE usuarios_sedes RENAME CONSTRAINT pk_usuarios_sedes TO usuarios_sedes_pkey;
ALTER TABLE roles_permisos RENAME CONSTRAINT pk_roles_permisos TO roles_permisos_pkey;
"""


# -----------------------------------------------------------------------
# 4. PK compuesta real de stock_sedes
# -----------------------------------------------------------------------
# Django creó un id autogenerado + UniqueConstraint 'pk_stock_sedes' como
# equivalente funcional (ver comentario en apps/inventario/models.py). Aquí
# se sustituye por la PK compuesta real (producto_id, sede_id) del .sql.
SQL_PK_STOCK_SEDES = """
ALTER TABLE stock_sedes DROP CONSTRAINT pk_stock_sedes;
ALTER TABLE stock_sedes DROP COLUMN id;
ALTER TABLE stock_sedes ADD CONSTRAINT pk_stock_sedes PRIMARY KEY (producto_id, sede_id);
"""

SQL_PK_STOCK_SEDES_REVERSE = """
ALTER TABLE stock_sedes DROP CONSTRAINT pk_stock_sedes;
ALTER TABLE stock_sedes ADD COLUMN id BIGINT GENERATED ALWAYS AS IDENTITY;
ALTER TABLE stock_sedes ADD CONSTRAINT pk_stock_sedes UNIQUE (producto_id, sede_id);
"""


# -----------------------------------------------------------------------
# 5. Índices GIN trigram
# -----------------------------------------------------------------------
SQL_INDICES_TRGM = """
CREATE INDEX ix_clientes_nombre_trgm ON clientes USING GIN (nombre gin_trgm_ops);
CREATE INDEX ix_productos_nombre_trgm ON productos USING GIN (nombre gin_trgm_ops);
"""

SQL_INDICES_TRGM_REVERSE = """
DROP INDEX IF EXISTS ix_productos_nombre_trgm;
DROP INDEX IF EXISTS ix_clientes_nombre_trgm;
"""


# -----------------------------------------------------------------------
# 6. Triggers de actualizado_en (sección 18 del .sql, 14 tablas)
# -----------------------------------------------------------------------
SQL_TRIGGERS = """
DO $$
DECLARE
    t TEXT;
    tablas TEXT[] := ARRAY[
        'planes_suscripcion','tenants','suscripciones','usuarios_plataforma',
        'sedes','usuarios','clientes','planes','membresias','productos',
        'stock_sedes','ventas','gastos','rutinas'
    ];
BEGIN
    FOREACH t IN ARRAY tablas LOOP
        EXECUTE format(
            'CREATE TRIGGER tg_%s_actualizado
                 BEFORE UPDATE ON %I
                 FOR EACH ROW EXECUTE FUNCTION fn_set_actualizado_en()', t, t);
    END LOOP;
END;
$$;
"""

SQL_TRIGGERS_REVERSE = """
DO $$
DECLARE
    t TEXT;
    tablas TEXT[] := ARRAY[
        'planes_suscripcion','tenants','suscripciones','usuarios_plataforma',
        'sedes','usuarios','clientes','planes','membresias','productos',
        'stock_sedes','ventas','gastos','rutinas'
    ];
BEGIN
    FOREACH t IN ARRAY tablas LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS tg_%s_actualizado ON %I', t, t);
    END LOOP;
END;
$$;
"""


# -----------------------------------------------------------------------
# 7. Auditoría particionada (sección 15 del .sql)
# -----------------------------------------------------------------------
SQL_AUDITORIA = """
CREATE TABLE auditoria (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,
    tenant_id           BIGINT        NOT NULL,
    usuario_id          BIGINT,
    usuario_plataforma_id BIGINT,
    sede_id             BIGINT,
    entidad             VARCHAR(60)   NOT NULL,
    entidad_id          BIGINT,
    accion              VARCHAR(20)   NOT NULL,
    valor_anterior      JSONB,
    valor_nuevo         JSONB,
    ip                  INET,
    fecha_hora          TIMESTAMPTZ   NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT pk_auditoria PRIMARY KEY (id, fecha_hora),
    CONSTRAINT ck_auditoria_autor CHECK (
        usuario_id IS NOT NULL OR usuario_plataforma_id IS NOT NULL
    )
) PARTITION BY RANGE (fecha_hora);

CREATE TABLE auditoria_2026_07 PARTITION OF auditoria
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE auditoria_2026_08 PARTITION OF auditoria
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE auditoria_2026_09 PARTITION OF auditoria
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE auditoria_default PARTITION OF auditoria DEFAULT;

CREATE INDEX ix_auditoria_tenant_fecha ON auditoria (tenant_id, fecha_hora DESC);
CREATE INDEX ix_auditoria_entidad ON auditoria (tenant_id, entidad, entidad_id);
"""
# NOTA: accion se declara VARCHAR y no ENUM nativo (decisión del usuario:
# ENUMs -> varchar, consistente con el resto del esquema). El modelo
# Auditoria (managed=False) tampoco usa un enum de Postgres, así que no
# hace falta CREATE TYPE aquí.

SQL_AUDITORIA_REVERSE = """
DROP TABLE IF EXISTS auditoria CASCADE;
"""


# -----------------------------------------------------------------------
# 8. Vistas de negocio (sección 16 del .sql)
# -----------------------------------------------------------------------
SQL_VISTAS = """
CREATE VIEW v_membresias_estado AS
SELECT
    m.id,
    m.tenant_id,
    m.sede_id,
    m.cliente_id,
    m.plan_id,
    m.fecha_inicio,
    m.fecha_fin,
    (m.fecha_fin - CURRENT_DATE) AS dias_restantes,
    CASE
        WHEN m.estado = 'cancelada'                        THEN 'cancelada'
        WHEN m.fecha_fin <  CURRENT_DATE                   THEN 'vencida'
        WHEN m.fecha_fin =  CURRENT_DATE                   THEN 'vence_hoy'
        WHEN m.fecha_fin <= CURRENT_DATE + t.dias_aviso_vencimiento THEN 'por_vencer'
        ELSE 'activa'
    END AS estado_calculado
FROM membresias m
JOIN tenants t ON t.id = m.tenant_id;

CREATE VIEW v_ventas_saldo AS
SELECT
    v.id                                       AS venta_id,
    v.tenant_id,
    v.sede_id,
    v.cliente_id,
    v.fecha_hora,
    v.total,
    COALESCE(p.total_pagado, 0)                AS total_pagado,
    v.total - COALESCE(p.total_pagado, 0)      AS saldo
FROM ventas v
LEFT JOIN LATERAL (
    SELECT SUM(monto) AS total_pagado
    FROM pagos
    WHERE venta_id = v.id AND NOT anulado
) p ON TRUE
WHERE v.estado <> 'anulada';

CREATE VIEW v_corte_diario AS
SELECT
    tenant_id,
    sede_id,
    fecha,
    SUM(monto) FILTER (WHERE origen = 'venta')          AS ingreso_ventas,
    SUM(monto) FILTER (WHERE origen = 'otro')           AS ingreso_otros,
    SUM(monto) FILTER (WHERE forma_pago = 'efectivo')   AS efectivo,
    SUM(monto) FILTER (WHERE forma_pago = 'transferencia') AS transferencia,
    SUM(monto) FILTER (WHERE forma_pago = 'tarjeta')    AS tarjeta,
    SUM(monto)                                          AS total_recibido
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

-- CRÍTICO: por defecto Postgres evalúa RLS de una vista con los privilegios
-- del DUEÑO de la vista (aquí 'postgres', vía la conexión 'ddl'), no con los
-- del rol que consulta. Como 'postgres' es superusuario y por tanto se
-- salta RLS, sin este SET las 3 vistas devolverían filas de TODOS los
-- tenants a cualquiera que las consulte, anulando el aislamiento (detectado
-- en la prueba del Paso 6: v_membresias_estado devolvía membresías de
-- ambos tenants). security_invoker (PostgreSQL 15+) hace que la vista
-- evalúe RLS con los privilegios de quien la consulta (keradmin), igual
-- que si consultara la tabla directamente.
ALTER VIEW v_membresias_estado SET (security_invoker = true);
ALTER VIEW v_ventas_saldo SET (security_invoker = true);
ALTER VIEW v_corte_diario SET (security_invoker = true);
"""

SQL_VISTAS_REVERSE = """
DROP VIEW IF EXISTS v_corte_diario;
DROP VIEW IF EXISTS v_ventas_saldo;
DROP VIEW IF EXISTS v_membresias_estado;
"""


# -----------------------------------------------------------------------
# 9. Row Level Security (sección 17 del .sql, 35 tablas)
# -----------------------------------------------------------------------
SQL_RLS = """
DO $$
DECLARE
    t TEXT;
    tablas TEXT[] := ARRAY[
        'sedes','secuencias_comprobantes','roles','roles_permisos','usuarios',
        'usuarios_sedes','clientes','autorizaciones_datos','huellas_clientes',
        'dispositivos_biometricos','planes','membresias','categorias_producto',
        'categorias_ingreso','productos','stock_sedes','movimientos_inventario',
        'ventas','detalle_ventas','pagos','ingresos_otros','categorias_gasto',
        'gastos','asistencias','intentos_biometricos_fallidos','fichas_medidas',
        'controles_medidas','grupos_musculares','ejercicios','rutinas',
        'rutina_dias','rutina_ejercicios','registros_ejercicios',
        'records_personales','auditoria'
    ];
BEGIN
    FOREACH t IN ARRAY tablas LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY pol_aislamiento_tenant ON %I
                 USING (tenant_id = fn_tenant_actual())
                 WITH CHECK (tenant_id = fn_tenant_actual())', t);
    END LOOP;
END;
$$;
"""

SQL_RLS_REVERSE = """
DO $$
DECLARE
    t TEXT;
    tablas TEXT[] := ARRAY[
        'sedes','secuencias_comprobantes','roles','roles_permisos','usuarios',
        'usuarios_sedes','clientes','autorizaciones_datos','huellas_clientes',
        'dispositivos_biometricos','planes','membresias','categorias_producto',
        'categorias_ingreso','productos','stock_sedes','movimientos_inventario',
        'ventas','detalle_ventas','pagos','ingresos_otros','categorias_gasto',
        'gastos','asistencias','intentos_biometricos_fallidos','fichas_medidas',
        'controles_medidas','grupos_musculares','ejercicios','rutinas',
        'rutina_dias','rutina_ejercicios','registros_ejercicios',
        'records_personales','auditoria'
    ];
BEGIN
    FOREACH t IN ARRAY tablas LOOP
        EXECUTE format('DROP POLICY IF EXISTS pol_aislamiento_tenant ON %I', t);
        EXECUTE format('ALTER TABLE %I NO FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', t);
    END LOOP;
END;
$$;
"""


# -----------------------------------------------------------------------
# 10. GRANTS a keradmin (tolerante a que el rol no exista, p. ej. en tests)
# -----------------------------------------------------------------------
SQL_GRANTS = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'keradmin') THEN
        GRANT USAGE ON SCHEMA public TO keradmin;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO keradmin;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO keradmin;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO keradmin;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO keradmin;
    END IF;
END;
$$;
"""

SQL_GRANTS_REVERSE = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'keradmin') THEN
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM keradmin;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM keradmin;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM keradmin;
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM keradmin;
        REVOKE USAGE ON SCHEMA public FROM keradmin;
    END IF;
END;
$$;
"""


# -----------------------------------------------------------------------
# 11. Semilla del catálogo global de permisos (sección 19 del .sql)
# -----------------------------------------------------------------------
SQL_SEED_PERMISOS = """
INSERT INTO permisos (codigo, modulo, descripcion) VALUES
    ('clientes.ver',        'clientes',   'Consultar clientes'),
    ('clientes.gestionar',  'clientes',   'Crear y editar clientes'),
    ('clientes.biometria',  'clientes',   'Enrolar y eliminar huellas'),
    ('ventas.registrar',    'ventas',     'Registrar ventas y cobrar abonos'),
    ('ventas.anular',       'ventas',     'Anular ventas'),
    ('ventas.descuento',    'ventas',     'Aplicar descuentos'),
    ('inventario.ver',      'inventario', 'Consultar existencias y kardex'),
    ('inventario.gestionar','inventario', 'Entradas, ajustes y edición de productos'),
    ('costos.ver',          'finanzas',   'Ver costos y utilidad'),
    ('gastos.gestionar',    'finanzas',   'Registrar gastos'),
    ('reportes.ver',        'reportes',   'Ver reportes y corte diario'),
    ('reportes.exportar',   'reportes',   'Exportar a Excel'),
    ('membresias.gestionar','membresias', 'Vender y renovar planes'),
    ('asistencia.autorizar','asistencia', 'Autorizar ingreso con plan vencido'),
    ('medidas.gestionar',   'entreno',    'Registrar fichas y controles de medidas'),
    ('rutinas.gestionar',   'entreno',    'Crear rutinas y registrar progreso'),
    ('config.sedes',        'config',     'Administrar sedes'),
    ('config.usuarios',     'config',     'Administrar usuarios y roles'),
    ('config.planes',       'config',     'Administrar catálogo de planes y precios')
ON CONFLICT (codigo) DO NOTHING;
"""

_PERMISOS_CODIGOS = [
    'clientes.ver', 'clientes.gestionar', 'clientes.biometria',
    'ventas.registrar', 'ventas.anular', 'ventas.descuento',
    'inventario.ver', 'inventario.gestionar',
    'costos.ver', 'gastos.gestionar',
    'reportes.ver', 'reportes.exportar',
    'membresias.gestionar', 'asistencia.autorizar',
    'medidas.gestionar', 'rutinas.gestionar',
    'config.sedes', 'config.usuarios', 'config.planes',
]
assert len(_PERMISOS_CODIGOS) == 19

SQL_SEED_PERMISOS_REVERSE = (
    "DELETE FROM permisos WHERE codigo IN ("
    + ', '.join(f"'{c}'" for c in _PERMISOS_CODIGOS)
    + ");"
)


class Migration(migrations.Migration):

    dependencies = [
        ('plataforma', '0001_initial'),
        ('organizacion', '0001_initial'),
        ('clientes', '0001_initial'),
        ('membresias', '0002_initial'),
        ('inventario', '0002_initial'),
        ('ventas', '0001_initial'),
        ('asistencia', '0002_initial'),
        ('entrenamiento', '0001_initial'),
        ('auditoria', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(sql=SQL_EXTENSIONES, reverse_sql=SQL_EXTENSIONES_REVERSE),
        migrations.RunSQL(sql=SQL_FUNCIONES, reverse_sql=SQL_FUNCIONES_REVERSE),
        migrations.RunSQL(sql=SQL_FKS_COMPUESTAS, reverse_sql=SQL_FKS_COMPUESTAS_REVERSE),
        migrations.RunSQL(sql=SQL_FKS_SIMPLES, reverse_sql=SQL_FKS_SIMPLES_REVERSE),
        migrations.RunSQL(sql=SQL_RENOMBRES, reverse_sql=SQL_RENOMBRES_REVERSE),
        migrations.RunSQL(sql=SQL_PK_STOCK_SEDES, reverse_sql=SQL_PK_STOCK_SEDES_REVERSE),
        migrations.RunSQL(sql=SQL_INDICES_TRGM, reverse_sql=SQL_INDICES_TRGM_REVERSE),
        migrations.RunSQL(sql=SQL_TRIGGERS, reverse_sql=SQL_TRIGGERS_REVERSE),
        migrations.RunSQL(sql=SQL_AUDITORIA, reverse_sql=SQL_AUDITORIA_REVERSE),
        migrations.RunSQL(sql=SQL_VISTAS, reverse_sql=SQL_VISTAS_REVERSE),
        migrations.RunSQL(sql=SQL_RLS, reverse_sql=SQL_RLS_REVERSE),
        migrations.RunSQL(sql=SQL_GRANTS, reverse_sql=SQL_GRANTS_REVERSE),
        migrations.RunSQL(sql=SQL_SEED_PERMISOS, reverse_sql=SQL_SEED_PERMISOS_REVERSE),
    ]
