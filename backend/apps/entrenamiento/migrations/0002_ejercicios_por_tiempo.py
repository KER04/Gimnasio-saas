"""Ejercicios medidos por TIEMPO además de por repeticiones.

## Por qué se añade una columna

Correr, saltar la cuerda o la caminadora se prescriben en minutos, no en
repeticiones. Con el esquema original solo cabían "series × repeticiones", y
la única forma de anotar "20 minutos" era escribirlo en ``notas``: texto
libre que ya no se puede consultar, ordenar ni sumar, y que obligaría a la
pantalla a adivinar el dato leyéndolo.

Es una desviación DELIBERADA del .sql original, la segunda del proyecto tras
``usuarios.es_staff``/``es_superusuario``, y por el mismo motivo: el esquema
no contemplaba un caso de uso real y meterlo a la fuerza en una columna
existente habría sido peor que añadir una.

## Qué cambia exactamente

1. ``duracion_minutos`` (SMALLINT NULL): los minutos, cuando aplica.
2. ``repeticiones`` pasa a admitir NULL: un ejercicio por tiempo no tiene.
3. ``ck_rutejer_series`` se queda solo con ``series > 0``.
4. ``ck_rutejer_medida`` (nuevo): exactamente UNA de las dos medidas. Sin el
   "y no las dos", una fila podría decir "10 repeticiones durante 5 minutos",
   que no significa nada y dejaría a la pantalla sin saber cuál enseñar.

Las filas existentes cumplen la restricción nueva sin tocarlas: todas tienen
``repeticiones > 0`` y ``duracion_minutos`` en NULL.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('entrenamiento', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='rutinaejercicio',
            name='duracion_minutos',
            field=models.SmallIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='rutinaejercicio',
            name='repeticiones',
            field=models.SmallIntegerField(blank=True, null=True),
        ),
        # El CHECK viejo exigía repeticiones > 0 en la misma condición que
        # series: hay que sustituirlo antes de poder guardar un ejercicio por
        # tiempo.
        migrations.RemoveConstraint(
            model_name='rutinaejercicio',
            name='ck_rutejer_series',
        ),
        migrations.AddConstraint(
            model_name='rutinaejercicio',
            constraint=models.CheckConstraint(
                condition=models.Q(series__gt=0), name='ck_rutejer_series',
            ),
        ),
        migrations.AddConstraint(
            model_name='rutinaejercicio',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(repeticiones__gt=0, duracion_minutos__isnull=True)
                    | models.Q(duracion_minutos__gt=0, repeticiones__isnull=True)
                ),
                name='ck_rutejer_medida',
            ),
        ),
    ]
