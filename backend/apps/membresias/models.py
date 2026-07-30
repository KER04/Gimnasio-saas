"""
App membresias — sección 08 del esquema: planes y membresías.

Nota de dependencia circular: Membresia.venta apunta a ventas.Venta, y
ventas.DetalleVenta apunta a membresias.Plan. Para evitar un import circular
de Python entre ``apps.membresias.models`` y ``apps.ventas.models``, la FK a
Venta se declara con referencia perezosa en cadena de texto
('ventas.Venta'); Django la resuelve contra el registro de apps una vez que
ambas apps están cargadas. Esta es también una dependencia circular real a
nivel de migraciones (membresias -> ventas por esta FK, ventas -> membresias
por detalle_ventas.plan_id): el autodetector de Django la resuelve partiendo
una de las dos apps en una migración adicional que añade el campo con
AddField después de que ambas tablas existen.
"""
from django.db import models
from django.db.models import Func

from apps.clientes.models import Cliente
from apps.organizacion.models import Sede, Usuario
from apps.plataforma.models import Tenant


class Plan(models.Model):
    """Catálogo de planes vendibles (mensual, quincenal, por sesión...)."""

    class TipoPlan(models.TextChoices):
        MENSUAL = 'mensual', 'Mensual'
        QUINCENAL = 'quincenal', 'Quincenal'
        POR_SESION = 'por_sesion', 'Por sesión'

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='planes',
    )
    # NULL = plan disponible en todas las sedes del tenant.
    sede = models.ForeignKey(
        Sede, on_delete=models.PROTECT, db_column='sede_id', related_name='planes',
        null=True, blank=True,
    )
    nombre = models.CharField(max_length=120)
    tipo = models.CharField(max_length=20, choices=TipoPlan.choices)
    duracion_dias = models.SmallIntegerField(null=True, blank=True)
    precio = models.DecimalField(max_digits=12, decimal_places=2)
    # El entrenamiento personalizado es un plan más del catálogo (decisión
    # 24), no una entidad aparte: reutiliza venta, membresía y reportes.
    requiere_entrenador = models.BooleanField(db_default=False)
    activo = models.BooleanField(db_default=True)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    # No auto_now: el valor lo mantiene el trigger fn_set_actualizado_en,
    # creado en apps.core migración 0001.
    actualizado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'planes'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_planes_id_tenant'),
            models.UniqueConstraint(fields=['tenant', 'nombre'], name='uq_planes_nombre'),
            models.CheckConstraint(condition=models.Q(precio__gte=0), name='ck_planes_precio'),
            # Regla estructural: solo los planes con vigencia tienen duración.
            # Los planes por sesión no tienen vigencia porque se venden sesión
            # a sesión (decisión 4); no generan membresía.
            models.CheckConstraint(
                condition=(
                    models.Q(tipo='por_sesion', duracion_dias__isnull=True)
                    | (~models.Q(tipo='por_sesion') & models.Q(duracion_dias__gt=0))
                ),
                name='ck_planes_duracion',
            ),
        ]

    def __str__(self):
        return self.nombre


class Membresia(models.Model):
    """Inscripción de un cliente a un plan durante un periodo de vigencia.

    Un cliente puede tener VARIAS membresías activas simultáneas (decisión
    23): p. ej. mensual de acceso + entrenamiento personalizado. Por eso no
    existe restricción de unicidad por cliente y las validaciones de acceso
    preguntan si EXISTE al menos una vigente, no cuál es "la" membresía.
    """

    class EstadoMembresia(models.TextChoices):
        ACTIVA = 'activa', 'Activa'
        CANCELADA = 'cancelada', 'Cancelada'

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='membresias',
    )
    cliente = models.ForeignKey(
        Cliente, on_delete=models.PROTECT, db_column='cliente_id', related_name='membresias',
    )
    plan = models.ForeignKey(
        Plan, on_delete=models.PROTECT, db_column='plan_id', related_name='membresias',
    )
    sede = models.ForeignKey(
        Sede, on_delete=models.PROTECT, db_column='sede_id', related_name='membresias',
    )
    # Referencia perezoga por texto: ver nota de módulo sobre la dependencia
    # circular membresias <-> ventas.
    venta = models.ForeignKey(
        'ventas.Venta', on_delete=models.PROTECT, db_column='venta_id', related_name='membresias',
        null=True, blank=True,
    )
    entrenador = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, db_column='entrenador_id',
        related_name='membresias_como_entrenador', null=True, blank=True,
    )
    vendedor = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, db_column='vendedor_id',
        related_name='membresias_vendidas',
    )
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(
        help_text=(
            'Se calcula en la aplicación como fecha_inicio + planes.duracion_dias. '
            'No es columna generada porque duracion_dias vive en otra tabla.'
        ),
    )
    # Copia histórica: cambiar el precio del catálogo no altera membresías pasadas.
    precio_pagado = models.DecimalField(max_digits=12, decimal_places=2)
    # Encadena la renovación. La nueva fecha_inicio parte de la fecha_fin
    # anterior, no de la fecha de pago, para no perder días pagados (RF-16).
    membresia_anterior = models.ForeignKey(
        'self', on_delete=models.PROTECT, db_column='membresia_anterior_id',
        related_name='renovaciones', null=True, blank=True,
    )
    estado = models.CharField(
        max_length=20, choices=EstadoMembresia.choices, db_default=EstadoMembresia.ACTIVA,
    )
    motivo_cancelacion = models.TextField(null=True, blank=True)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    # No auto_now: el valor lo mantiene el trigger fn_set_actualizado_en,
    # creado en apps.core migración 0001.
    actualizado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'membresias'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_membresias_id_tenant'),
            models.CheckConstraint(
                condition=models.Q(fecha_fin__gte=models.F('fecha_inicio')), name='ck_membresias_fechas',
            ),
            models.CheckConstraint(condition=models.Q(precio_pagado__gte=0), name='ck_membresias_precio'),
            models.CheckConstraint(
                condition=~models.Q(estado='cancelada') | models.Q(motivo_cancelacion__isnull=False),
                name='ck_membresias_cancel',
            ),
        ]
        indexes = [
            # Índice que sostiene el check-in: "¿este cliente tiene alguna membresía viva?"
            models.Index(
                fields=['cliente', '-fecha_fin'],
                condition=models.Q(estado='activa'),
                name='ix_membresias_cliente_vigencia',
            ),
            # Índice que sostiene el tablero de vencimientos por sede.
            models.Index(
                fields=['tenant', 'sede', 'fecha_fin'],
                condition=models.Q(estado='activa'),
                name='ix_membresias_vencimiento',
            ),
            models.Index(
                fields=['entrenador', '-fecha_fin'],
                condition=models.Q(entrenador__isnull=False, estado='activa'),
                name='ix_membresias_entrenador',
            ),
        ]

    def __str__(self):
        return f'{self.cliente} — {self.plan} ({self.fecha_inicio} a {self.fecha_fin})'
