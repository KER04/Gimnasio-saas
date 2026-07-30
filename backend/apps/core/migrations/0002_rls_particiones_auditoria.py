"""Extiende Row Level Security a las particiones de `auditoria`.

En PostgreSQL, la política RLS de una tabla particionada se aplica cuando se
consulta **a través del padre**, pero NO cuando se consulta una partición
directamente: para eso la partición necesita su propia política.

Verificado antes de este cambio, con una fila de auditoría por cada uno de dos
tenants y `app.tenant_id` fijado al primero:

    SELECT count(*) FROM auditoria            -> 1   correcto
    SELECT count(*) FROM auditoria_2026_07    -> 2   ambos tenants

No era explotable por HTTP —el modelo de Django apunta al padre y nada consulta
particiones directamente—, pero cualquier consulta cruda, script de
mantenimiento o informe que tocara una partición vería la traza de todos los
gimnasios. Y la auditoría es justo donde viven los datos sensibles: quién
autorizó un ingreso, quién cambió un precio.

Además de arreglar las particiones existentes, se añade
`fn_crear_particion_auditoria()` para que las mensuales futuras nazcan ya
protegidas. Crearlas a mano con un simple CREATE TABLE ... PARTITION OF
reintroduciría el fallo en silencio.
"""

from django.db import migrations


SQL_RLS_PARTICIONES = """
DO $$
DECLARE
    p RECORD;
BEGIN
    FOR p IN
        SELECT c.relname
        FROM pg_class c
        JOIN pg_inherits i ON i.inhrelid = c.oid
        WHERE i.inhparent = 'auditoria'::regclass
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', p.relname);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', p.relname);
        EXECUTE format(
            'DROP POLICY IF EXISTS pol_aislamiento_tenant ON %I', p.relname);
        EXECUTE format(
            'CREATE POLICY pol_aislamiento_tenant ON %I
                 USING (tenant_id = fn_tenant_actual())
                 WITH CHECK (tenant_id = fn_tenant_actual())', p.relname);
    END LOOP;
END;
$$;
"""

SQL_RLS_PARTICIONES_REVERSE = """
DO $$
DECLARE
    p RECORD;
BEGIN
    FOR p IN
        SELECT c.relname
        FROM pg_class c
        JOIN pg_inherits i ON i.inhrelid = c.oid
        WHERE i.inhparent = 'auditoria'::regclass
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS pol_aislamiento_tenant ON %I', p.relname);
        EXECUTE format('ALTER TABLE %I NO FORCE ROW LEVEL SECURITY', p.relname);
        EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', p.relname);
    END LOOP;
END;
$$;
"""


# Crea la partición mensual CON su política ya aplicada. El job que genere las
# particiones futuras debe llamar a esta función y no a un CREATE TABLE suelto.
SQL_FN_CREAR_PARTICION = """
CREATE OR REPLACE FUNCTION fn_crear_particion_auditoria(p_mes DATE)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    v_inicio DATE := date_trunc('month', p_mes)::DATE;
    v_fin    DATE := (date_trunc('month', p_mes) + INTERVAL '1 month')::DATE;
    v_nombre TEXT := 'auditoria_' || to_char(v_inicio, 'YYYY_MM');
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = v_nombre) THEN
        RETURN v_nombre || ' (ya existia)';
    END IF;

    EXECUTE format(
        'CREATE TABLE %I PARTITION OF auditoria FOR VALUES FROM (%L) TO (%L)',
        v_nombre, v_inicio, v_fin);

    -- Sin esto la partición quedaría sin aislamiento entre tenants.
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', v_nombre);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', v_nombre);
    EXECUTE format(
        'CREATE POLICY pol_aislamiento_tenant ON %I
             USING (tenant_id = fn_tenant_actual())
             WITH CHECK (tenant_id = fn_tenant_actual())', v_nombre);

    RETURN v_nombre || ' (creada)';
END;
$$;
"""

SQL_FN_CREAR_PARTICION_REVERSE = """
DROP FUNCTION IF EXISTS fn_crear_particion_auditoria(DATE);
"""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_esquema_postgres'),
    ]

    operations = [
        migrations.RunSQL(SQL_RLS_PARTICIONES, SQL_RLS_PARTICIONES_REVERSE),
        migrations.RunSQL(SQL_FN_CREAR_PARTICION, SQL_FN_CREAR_PARTICION_REVERSE),
    ]
