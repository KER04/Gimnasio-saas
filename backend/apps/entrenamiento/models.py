"""
App entrenamiento — secciones 13 y 14 del esquema: medidas corporales,
ejercicios y rutinas (RF-11, RF-12, RF-13).
"""
from django.db import models
from django.db.models import Func

from apps.clientes.models import Cliente
from apps.organizacion.models import Usuario
from apps.plataforma.models import Tenant


class FichaMedidas(models.Model):
    """Proceso de seguimiento corporal abierto para un cliente."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='fichas_medidas',
    )
    cliente = models.ForeignKey(
        Cliente, on_delete=models.CASCADE, db_column='cliente_id', related_name='fichas_medidas',
    )
    entrenador = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, db_column='entrenador_id', related_name='fichas_medidas',
    )
    modalidad = models.CharField(max_length=80, null=True, blank=True)
    fecha_inicio = models.DateField(db_default=Func(function='CURRENT_DATE', template='%(function)s'))
    # Vive en la ficha y no en cada control: en un adulto no cambia entre
    # mediciones mensuales.
    estatura_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    whatsapp = models.CharField(max_length=30, null=True, blank=True)
    activa = models.BooleanField(db_default=True)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'fichas_medidas'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_ficha_id_tenant'),
            models.CheckConstraint(
                condition=models.Q(estatura_cm__isnull=True) | models.Q(estatura_cm__gte=80, estatura_cm__lte=260),
                name='ck_ficha_estatura',
            ),
            # Un cliente tiene como máximo un proceso de medición abierto a la vez.
            models.UniqueConstraint(
                fields=['cliente'], condition=models.Q(activa=True), name='uq_ficha_cliente_activa',
            ),
        ]

    def __str__(self):
        return f'Ficha de {self.cliente} ({self.fecha_inicio})'


class ControlMedida(models.Model):
    """Un control por fila, NO columnas Mes 1..Mes 5. El formulario en papel
    se reconstruye pivotando en la consulta; así el histórico es ilimitado
    sin alterar el esquema. Las 13 medidas son columnas y no filas
    clave-valor: el conjunto es fijo y conocido (decisión 8), y una tabla
    vertical obligaría a 13 filas por control más un PIVOT en cada consulta
    comparativa, que es la vista principal.
    """

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='controles_medidas',
    )
    ficha_medida = models.ForeignKey(
        FichaMedidas, on_delete=models.CASCADE, db_column='ficha_medida_id', related_name='controles',
    )
    numero_control = models.SmallIntegerField()
    fecha = models.DateField(db_default=Func(function='CURRENT_DATE', template='%(function)s'))
    # Se guarda por control y no en clientes porque el sistema no almacena
    # fecha de nacimiento (decisión 19). Al llevar la fecha del control, el
    # dato queda anclado en el tiempo y no se desactualiza.
    edad = models.SmallIntegerField(null=True, blank=True)
    peso_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    cuello = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    hombros = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    pecho_espalda = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    brazos = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    antebrazos = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    muneca = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    abdomen = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    cintura = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    cadera_gluteos = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    piernas_media = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    rodillas_arriba = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    pantorrillas = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    tobillos = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    registrado_por = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, db_column='registrado_por', related_name='controles_medidas',
    )
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'controles_medidas'
        constraints = [
            models.UniqueConstraint(fields=['ficha_medida', 'numero_control'], name='uq_control_numero'),
            models.CheckConstraint(condition=models.Q(numero_control__gt=0), name='ck_control_numero'),
            models.CheckConstraint(
                condition=models.Q(edad__isnull=True) | models.Q(edad__gte=5, edad__lte=120),
                name='ck_control_edad',
            ),
            models.CheckConstraint(
                condition=models.Q(peso_kg__isnull=True) | models.Q(peso_kg__gte=20, peso_kg__lte=400),
                name='ck_control_peso',
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(cuello__isnull=True) | models.Q(cuello__gt=0))
                    & (models.Q(hombros__isnull=True) | models.Q(hombros__gt=0))
                    & (models.Q(pecho_espalda__isnull=True) | models.Q(pecho_espalda__gt=0))
                    & (models.Q(brazos__isnull=True) | models.Q(brazos__gt=0))
                    & (models.Q(antebrazos__isnull=True) | models.Q(antebrazos__gt=0))
                    & (models.Q(muneca__isnull=True) | models.Q(muneca__gt=0))
                    & (models.Q(abdomen__isnull=True) | models.Q(abdomen__gt=0))
                    & (models.Q(cintura__isnull=True) | models.Q(cintura__gt=0))
                    & (models.Q(cadera_gluteos__isnull=True) | models.Q(cadera_gluteos__gt=0))
                    & (models.Q(piernas_media__isnull=True) | models.Q(piernas_media__gt=0))
                    & (models.Q(rodillas_arriba__isnull=True) | models.Q(rodillas_arriba__gt=0))
                    & (models.Q(pantorrillas__isnull=True) | models.Q(pantorrillas__gt=0))
                    & (models.Q(tobillos__isnull=True) | models.Q(tobillos__gt=0))
                ),
                name='ck_control_medidas',
            ),
        ]
        indexes = [
            models.Index(fields=['ficha_medida', '-fecha'], name='ix_control_ficha_fecha'),
        ]

    def __str__(self):
        return f'Control {self.numero_control} de {self.ficha_medida}'


class GrupoMuscular(models.Model):
    """Catálogo de grupos musculares, editable por el gimnasio."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='grupos_musculares',
    )
    nombre = models.CharField(max_length=60)
    orden = models.SmallIntegerField(db_default=0)

    class Meta:
        db_table = 'grupos_musculares'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_grupomusc_id_tenant'),
            models.UniqueConstraint(fields=['tenant', 'nombre'], name='uq_grupomusc_nombre'),
        ]

    def __str__(self):
        return self.nombre


class Ejercicio(models.Model):
    """Catálogo de ejercicios disponibles para armar rutinas."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='ejercicios',
    )
    grupo_muscular = models.ForeignKey(
        GrupoMuscular, on_delete=models.PROTECT, db_column='grupo_muscular_id', related_name='ejercicios',
    )
    nombre = models.CharField(max_length=120)
    descripcion = models.TextField(null=True, blank=True)
    # RF-12: un ejercicio ya usado en una rutina se DESACTIVA, nunca se
    # elimina. Las FK con ON DELETE RESTRICT lo garantizan aunque la
    # aplicación lo intente.
    activo = models.BooleanField(db_default=True)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'ejercicios'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_ejercicios_id_tenant'),
            models.UniqueConstraint(fields=['tenant', 'nombre'], name='uq_ejercicios_nombre'),
        ]
        indexes = [
            models.Index(
                fields=['tenant', 'grupo_muscular'], condition=models.Q(activo=True), name='ix_ejercicios_grupo',
            ),
        ]

    def __str__(self):
        return self.nombre


class Rutina(models.Model):
    """Plan de entrenamiento asignado por un entrenador a un cliente."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='rutinas',
    )
    cliente = models.ForeignKey(
        Cliente, on_delete=models.CASCADE, db_column='cliente_id', related_name='rutinas',
    )
    entrenador = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, db_column='entrenador_id', related_name='rutinas_asignadas',
    )
    nombre = models.CharField(max_length=120)
    objetivo = models.TextField(null=True, blank=True)
    fecha_inicio = models.DateField(db_default=Func(function='CURRENT_DATE', template='%(function)s'))
    fecha_fin = models.DateField(null=True, blank=True)
    activa = models.BooleanField(db_default=True)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    # No auto_now: el valor lo mantiene el trigger tg_rutinas_actualizado
    # (fn_set_actualizado_en), creado en apps.core migración 0001.
    actualizado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'rutinas'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_rutinas_id_tenant'),
            models.CheckConstraint(
                condition=models.Q(fecha_fin__isnull=True) | models.Q(fecha_fin__gte=models.F('fecha_inicio')),
                name='ck_rutinas_fechas',
            ),
        ]
        indexes = [
            models.Index(fields=['cliente', '-fecha_inicio'], name='ix_rutinas_cliente'),
            models.Index(fields=['entrenador'], condition=models.Q(activa=True), name='ix_rutinas_entrenador'),
        ]

    def __str__(self):
        return self.nombre


class RutinaDia(models.Model):
    """Día de entrenamiento dentro de una rutina (día 1, día 2...)."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='rutina_dias',
    )
    rutina = models.ForeignKey(
        Rutina, on_delete=models.CASCADE, db_column='rutina_id', related_name='dias',
    )
    numero = models.SmallIntegerField()
    nombre = models.CharField(max_length=80)

    class Meta:
        db_table = 'rutina_dias'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_rutdia_id_tenant'),
            models.UniqueConstraint(fields=['rutina', 'numero'], name='uq_rutdia_numero'),
            models.CheckConstraint(condition=models.Q(numero__gt=0), name='ck_rutdia_numero'),
        ]

    def __str__(self):
        return f'{self.rutina} — día {self.numero}'


class RutinaEjercicio(models.Model):
    """Tabla puente N:M entre días de rutina y ejercicios, con atributos propios."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='rutina_ejercicios',
    )
    rutina_dia = models.ForeignKey(
        RutinaDia, on_delete=models.CASCADE, db_column='rutina_dia_id', related_name='ejercicios',
    )
    ejercicio = models.ForeignKey(
        Ejercicio, on_delete=models.PROTECT, db_column='ejercicio_id', related_name='rutina_ejercicios',
    )
    orden = models.SmallIntegerField()
    # Peso PLANIFICADO por el entrenador. El ejecutado se registra en registros_ejercicios.
    peso_kg = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    series = models.SmallIntegerField()
    # NULL cuando el ejercicio se mide por TIEMPO en vez de por repeticiones.
    repeticiones = models.SmallIntegerField(null=True, blank=True)
    # Desviación DELIBERADA del .sql original, igual que `es_staff` en
    # `Usuario`: correr, saltar la cuerda o la caminadora se prescriben en
    # minutos, no en repeticiones. Sin esta columna, la única forma de
    # anotarlo era escribirlo en `notas`, donde el dato deja de poder
    # consultarse y la pantalla tendría que adivinarlo leyendo texto libre.
    #
    # Un ejercicio lleva repeticiones O duración, nunca las dos ni ninguna:
    # lo impone `ck_rutejer_medida`.
    duracion_minutos = models.SmallIntegerField(null=True, blank=True)
    descanso_segundos = models.SmallIntegerField(null=True, blank=True)
    notas = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'rutina_ejercicios'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_rutejer_id_tenant'),
            models.UniqueConstraint(fields=['rutina_dia', 'orden'], name='uq_rutejer_orden'),
            models.CheckConstraint(condition=models.Q(series__gt=0), name='ck_rutejer_series'),
            # Exactamente una de las dos medidas. Sin el "y no las dos", una
            # fila podría decir "10 repeticiones durante 5 minutos", que no
            # significa nada y la pantalla no sabría cuál enseñar.
            models.CheckConstraint(
                condition=(
                    models.Q(repeticiones__gt=0, duracion_minutos__isnull=True)
                    | models.Q(duracion_minutos__gt=0, repeticiones__isnull=True)
                ),
                name='ck_rutejer_medida',
            ),
            models.CheckConstraint(
                condition=models.Q(peso_kg__isnull=True) | models.Q(peso_kg__gte=0), name='ck_rutejer_peso',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(descanso_segundos__isnull=True)
                    | models.Q(descanso_segundos__gte=0, descanso_segundos__lte=3600)
                ),
                name='ck_rutejer_descanso',
            ),
        ]

    def __str__(self):
        return f'{self.rutina_dia} — {self.ejercicio}'


class RegistroEjercicio(models.Model):
    """Una fila por serie ejecutada. Es la tabla que más crece del módulo de
    entrenamiento y la que se escribe desde el celular, entre series: la
    inserción debe ser una sola sentencia sin lecturas previas.
    """

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='registros_ejercicios',
    )
    rutina_ejercicio = models.ForeignKey(
        RutinaEjercicio, on_delete=models.CASCADE, db_column='rutina_ejercicio_id', related_name='registros',
    )
    # Redundante (se alcanza vía rutina_ejercicio -> rutina_dia -> rutina),
    # pero evita tres JOIN en la consulta de progreso por cliente, que es la
    # principal de este módulo. La integridad la sostiene el mismo tenant_id
    # en ambas FK.
    cliente = models.ForeignKey(
        Cliente, on_delete=models.CASCADE, db_column='cliente_id', related_name='registros_ejercicios',
    )
    fecha = models.DateField(db_default=Func(function='CURRENT_DATE', template='%(function)s'))
    numero_serie = models.SmallIntegerField()
    peso_real = models.DecimalField(max_digits=6, decimal_places=2)
    repeticiones_reales = models.SmallIntegerField()
    registrado_por = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, db_column='registrado_por', related_name='registros_ejercicios',
    )
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'registros_ejercicios'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_regejer_id_tenant'),
            models.UniqueConstraint(
                fields=['rutina_ejercicio', 'fecha', 'numero_serie'], name='uq_regejer_serie',
            ),
            models.CheckConstraint(
                condition=models.Q(peso_real__gte=0, repeticiones_reales__gt=0, numero_serie__gt=0),
                name='ck_regejer_valores',
            ),
        ]
        indexes = [
            models.Index(fields=['cliente', '-fecha'], name='ix_regejer_cliente_fecha'),
            models.Index(fields=['rutina_ejercicio', '-fecha'], name='ix_regejer_rutejer'),
        ]

    def __str__(self):
        return f'Serie {self.numero_serie} de {self.rutina_ejercicio} ({self.fecha})'


class RecordPersonal(models.Model):
    """DESNORMALIZACIÓN DELIBERADA (3 de 3). El PR es MAX(peso_real) sobre
    registros_ejercicios, pero se materializa una fila por cliente y
    ejercicio porque se muestra en cada pantalla de rutina y calcularlo
    requeriría un agregado sobre la tabla más grande del módulo. Se actualiza
    por disparador (RunSQL, pendiente).
    """

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='records_personales',
    )
    cliente = models.ForeignKey(
        Cliente, on_delete=models.CASCADE, db_column='cliente_id', related_name='records_personales',
    )
    ejercicio = models.ForeignKey(
        Ejercicio, on_delete=models.PROTECT, db_column='ejercicio_id', related_name='records_personales',
    )
    peso = models.DecimalField(max_digits=6, decimal_places=2)
    repeticiones = models.SmallIntegerField()
    fecha = models.DateField()
    registro_ejercicio = models.ForeignKey(
        RegistroEjercicio, on_delete=models.SET_NULL, db_column='registro_ejercicio_id',
        related_name='records_personales', null=True, blank=True,
    )

    class Meta:
        db_table = 'records_personales'
        constraints = [
            models.UniqueConstraint(fields=['cliente', 'ejercicio'], name='uq_records_cliente_ejercicio'),
            models.CheckConstraint(
                condition=models.Q(peso__gte=0, repeticiones__gt=0), name='ck_records_valores',
            ),
        ]

    def __str__(self):
        return f'PR de {self.cliente} en {self.ejercicio}: {self.peso}kg x {self.repeticiones}'
