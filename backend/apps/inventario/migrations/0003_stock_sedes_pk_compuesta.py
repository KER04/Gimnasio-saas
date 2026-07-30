"""Alinea el estado de Django con la PK compuesta real de `stock_sedes`.

El esquema define `PRIMARY KEY (producto_id, sede_id)` sin columna `id`, y esa
estructura ya la crea `apps.core.0001_esquema_postgres` (sección "PK
compuesta real de stock_sedes"). La migración 0001_initial de esta app, en
cambio, tuvo que declarar un `id` BigAutoField implícito porque, en ese punto
de la migración, las columnas `producto_id`/`sede_id` (necesarias para
`CompositePrimaryKey`) todavía no existían: se añaden recién en
0002_initial, debido a la dependencia circular Producto<->StockSede que el
autodetector de Django resuelve dividiendo la app en dos migraciones
iniciales.

Por eso las operaciones van dentro de `SeparateDatabaseAndState` con
`database_operations=[]`: la base real ya quedó en el estado correcto
gracias a `core.0001_esquema_postgres` (que corre después de
`inventario.0002_initial`); lo único que falta es que el ORM lo sepa.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventario', '0002_initial'),
        # La PK compuesta real la crea la migración de esquema: esta va después.
        ('core', '0001_esquema_postgres'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name='stocksede',
                    name='pk_stock_sedes',
                ),
                migrations.RemoveField(
                    model_name='stocksede',
                    name='id',
                ),
                migrations.AddField(
                    model_name='stocksede',
                    name='pk',
                    field=models.CompositePrimaryKey(
                        'producto', 'sede',
                        blank=True, editable=False, primary_key=True, serialize=False,
                    ),
                ),
            ],
        ),
    ]
