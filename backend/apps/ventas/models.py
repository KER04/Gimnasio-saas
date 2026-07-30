"""
App ventas — secciones 10 y 11 del esquema: ventas, pagos, ingresos y gastos.

Modelo de reconocimiento: CAJA REAL (decisión 1). El ingreso del día es la
suma de la tabla pagos, no el total de las ventas. Por eso el pago inicial de
una venta de contado también es una fila en pagos: así "lo que entró hoy" es
siempre una sola consulta sobre una sola tabla.

Nota de dependencias circulares (ver también membresias/models.py e
inventario/models.py): DetalleVenta.producto apunta a inventario.Producto y
DetalleVenta.plan apunta a membresias.Plan; a su vez, movimientos_inventario
y membresias apuntan a Venta. Esta app puede importar Producto y Plan de
forma normal (sin referencia perezosa) porque inventario y membresias
referencian Venta solo mediante la cadena de texto 'ventas.Venta', sin
importar este módulo — así se rompe el ciclo de import de Python aunque las
migraciones sigan teniendo una dependencia circular real entre apps.
"""
from django.db import models
from django.db.models import F, Func

from apps.inventario.models import Producto
from apps.membresias.models import Plan
from apps.organizacion.models import Sede, Usuario
from apps.plataforma.models import Tenant


class CategoriaIngreso(models.Model):
    """Categoría de ingreso, incluida la derivación automática de ventas (RF-07)."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='categorias_ingreso',
    )
    nombre = models.CharField(max_length=80)
    subcategoria = models.CharField(max_length=80, null=True, blank=True)
    # Categorías sembradas al crear el tenant (productos, planes,
    # entrenamiento personalizado, otros). No se eliminan porque la
    # derivación automática de RF-07 depende de ellas.
    es_sistema = models.BooleanField(db_default=False)
    activa = models.BooleanField(db_default=True)

    class Meta:
        db_table = 'categorias_ingreso'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_catingr_id_tenant'),
            models.UniqueConstraint(
                fields=['tenant', 'nombre', 'subcategoria'], name='uq_catingr_nombre',
            ),
        ]

    def __str__(self):
        return self.nombre


class CategoriaGasto(models.Model):
    """Catálogo de categorías de gasto, editable por el gimnasio."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='categorias_gasto',
    )
    nombre = models.CharField(max_length=80)
    activa = models.BooleanField(db_default=True)

    class Meta:
        db_table = 'categorias_gasto'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_catgasto_id_tenant'),
            models.UniqueConstraint(fields=['tenant', 'nombre'], name='uq_catgasto_nombre'),
        ]

    def __str__(self):
        return self.nombre


class Venta(models.Model):
    """Cabecera de una venta (POS). El total se declara redundante respecto a
    subtotal - descuento, pero con un CHECK que garantiza la coherencia; se
    usa así en índices de reporte.
    """

    class EstadoVenta(models.TextChoices):
        PAGADA = 'pagada', 'Pagada'
        PARCIAL = 'parcial', 'Parcial'
        PENDIENTE = 'pendiente', 'Pendiente'
        ANULADA = 'anulada', 'Anulada'

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='ventas',
    )
    sede = models.ForeignKey(
        Sede, on_delete=models.PROTECT, db_column='sede_id', related_name='ventas',
    )
    cliente = models.ForeignKey(
        'clientes.Cliente', on_delete=models.PROTECT, db_column='cliente_id', related_name='ventas',
        null=True, blank=True,
    )
    usuario = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, db_column='usuario_id', related_name='ventas_registradas',
    )
    consecutivo = models.BigIntegerField()
    fecha_hora = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    descuento = models.DecimalField(max_digits=12, decimal_places=2, db_default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    motivo_descuento = models.CharField(max_length=200, null=True, blank=True)
    estado = models.CharField(
        max_length=20, choices=EstadoVenta.choices, db_default=EstadoVenta.PAGADA,
    )
    anulada_por = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, db_column='anulada_por',
        related_name='ventas_anuladas', null=True, blank=True,
    )
    motivo_anulacion = models.TextField(null=True, blank=True)
    anulada_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    # No auto_now: el valor lo mantiene el trigger tg_ventas_actualizado
    # (fn_set_actualizado_en), creado en apps.core migración 0001.
    actualizado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'ventas'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_ventas_id_tenant'),
            models.UniqueConstraint(fields=['sede', 'consecutivo'], name='uq_ventas_consecutivo'),
            models.CheckConstraint(
                condition=(
                    models.Q(subtotal__gte=0)
                    & models.Q(descuento__gte=0)
                    & models.Q(descuento__lte=F('subtotal'))
                    & models.Q(total=F('subtotal') - F('descuento'))
                ),
                name='ck_ventas_montos',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(descuento=0)
                    | (models.Q(motivo_descuento__isnull=False) & ~models.Q(motivo_descuento__regex=r'^\s*$'))
                ),
                name='ck_ventas_descuento',
            ),
            # Venta anónima permitida, pero el crédito exige cliente identificado.
            models.CheckConstraint(
                condition=~models.Q(estado__in=['parcial', 'pendiente']) | models.Q(cliente__isnull=False),
                name='ck_ventas_credito',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        estado='anulada', anulada_por__isnull=False,
                        motivo_anulacion__isnull=False, anulada_en__isnull=False,
                    )
                    | (
                        ~models.Q(estado='anulada')
                        & models.Q(anulada_por__isnull=True, motivo_anulacion__isnull=True, anulada_en__isnull=True)
                    )
                ),
                name='ck_ventas_anulacion',
            ),
        ]
        indexes = [
            models.Index(
                fields=['sede', '-fecha_hora'],
                condition=~models.Q(estado='anulada'),
                name='ix_ventas_sede_fecha',
            ),
            models.Index(
                fields=['cliente', '-fecha_hora'],
                condition=models.Q(cliente__isnull=False),
                name='ix_ventas_cliente',
            ),
            # Cartera: ventas con saldo abierto. Índice parcial pequeño y muy selectivo.
            models.Index(
                fields=['tenant', 'cliente'],
                condition=models.Q(estado__in=['parcial', 'pendiente']),
                name='ix_ventas_cartera',
            ),
            models.Index(fields=['tenant', '-fecha_hora'], name='ix_ventas_tenant_fecha'),
        ]

    def __str__(self):
        return f'Venta {self.consecutivo} — {self.sede}'


class DetalleVenta(models.Model):
    """Línea de venta. Guarda descripción, precio Y COSTO copiados del
    catálogo en el momento de la operación: sin el costo histórico, cambiar
    el costo de un producto reescribiría la utilidad de meses ya cerrados
    (RF-24).
    """

    class TipoItemVenta(models.TextChoices):
        PRODUCTO = 'producto', 'Producto'
        PLAN = 'plan', 'Plan'

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='detalle_ventas',
    )
    venta = models.ForeignKey(
        Venta, on_delete=models.CASCADE, db_column='venta_id', related_name='detalles',
    )
    tipo_item = models.CharField(max_length=20, choices=TipoItemVenta.choices)
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, db_column='producto_id', related_name='detalle_ventas',
        null=True, blank=True,
    )
    plan = models.ForeignKey(
        Plan, on_delete=models.PROTECT, db_column='plan_id', related_name='detalle_ventas',
        null=True, blank=True,
    )
    # DESNORMALIZACIÓN DELIBERADA (2 de 3). La categoría es derivable del
    # producto o del plan, pero se materializa aquí porque los reportes por
    # categoría son la consulta más frecuente del sistema, y si el gimnasio
    # recategoriza un producto los ingresos históricos no deben moverse de sitio.
    categoria_ingreso = models.ForeignKey(
        CategoriaIngreso, on_delete=models.PROTECT, db_column='categoria_ingreso_id',
        related_name='detalle_ventas',
    )
    # Texto tal como se vendió ("Proteína Pro — 2 lb"). Congelado: renombrar
    # el producto no debe reescribir recibos ya impresos.
    descripcion = models.CharField(max_length=250)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=2, db_default=0)
    total_linea = models.GeneratedField(
        expression=F('cantidad') * F('precio_unitario'),
        output_field=models.DecimalField(max_digits=12, decimal_places=2),
        db_persist=True,
    )

    class Meta:
        db_table = 'detalle_ventas'
        constraints = [
            models.CheckConstraint(condition=models.Q(cantidad__gt=0), name='ck_detven_cantidad'),
            models.CheckConstraint(
                condition=models.Q(precio_unitario__gte=0, costo_unitario__gte=0), name='ck_detven_precio',
            ),
            # Exclusividad de la referencia: o producto, o plan, nunca ambos ni ninguno.
            models.CheckConstraint(
                condition=(
                    models.Q(tipo_item='producto', producto__isnull=False, plan__isnull=True)
                    | models.Q(tipo_item='plan', plan__isnull=False, producto__isnull=True)
                ),
                name='ck_detven_item',
            ),
        ]
        indexes = [
            models.Index(fields=['venta'], name='ix_detven_venta'),
            models.Index(
                fields=['producto'], condition=models.Q(producto__isnull=False), name='ix_detven_producto',
            ),
            models.Index(fields=['tenant', 'categoria_ingreso'], name='ix_detven_categoria'),
        ]

    def __str__(self):
        return self.descripcion


class Pago(models.Model):
    """Todo dinero recibido contra una venta, incluidos el pago de contado y
    cada abono posterior. Unificar ambos en una sola tabla hace que el
    ingreso del día (caja real, decisión 1) sea SUM(monto) sobre un único
    origen, en lugar de sumar ventas de contado más abonos de ventas a crédito.
    """

    class FormaPago(models.TextChoices):
        EFECTIVO = 'efectivo', 'Efectivo'
        TRANSFERENCIA = 'transferencia', 'Transferencia'
        TARJETA = 'tarjeta', 'Tarjeta'

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='pagos',
    )
    venta = models.ForeignKey(
        Venta, on_delete=models.PROTECT, db_column='venta_id', related_name='pagos',
    )
    usuario = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, db_column='usuario_id', related_name='pagos_registrados',
    )
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    forma_pago = models.CharField(max_length=20, choices=FormaPago.choices)
    # Distingue el pago hecho en el momento de la venta de los abonos
    # posteriores, para el listado cronológico de RF-09.
    es_pago_inicial = models.BooleanField(db_default=False)
    fecha_hora = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    anulado = models.BooleanField(db_default=False)

    class Meta:
        db_table = 'pagos'
        constraints = [
            models.CheckConstraint(condition=models.Q(monto__gt=0), name='ck_pagos_monto'),
        ]
        indexes = [
            models.Index(fields=['venta', 'fecha_hora'], name='ix_pagos_venta'),
            # Corte diario: el índice cubre el filtro por día y la suma por forma de pago.
            models.Index(
                fields=['tenant', '-fecha_hora'], condition=~models.Q(anulado=True), name='ix_pagos_tenant_fecha',
            ),
        ]

    def __str__(self):
        return f'Pago {self.monto} — {self.venta}'


class IngresoOtro(models.Model):
    """Ingresos sin venta asociada (RF-07: matrícula, casillero, alquiler).
    Entran al corte diario junto con pagos.
    """

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='ingresos_otros',
    )
    sede = models.ForeignKey(
        Sede, on_delete=models.PROTECT, db_column='sede_id', related_name='ingresos_otros',
    )
    categoria_ingreso = models.ForeignKey(
        CategoriaIngreso, on_delete=models.PROTECT, db_column='categoria_ingreso_id',
        related_name='ingresos_otros',
    )
    usuario = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, db_column='usuario_id', related_name='ingresos_otros_registrados',
    )
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    forma_pago = models.CharField(max_length=20, choices=Pago.FormaPago.choices)
    descripcion = models.CharField(max_length=250)
    fecha = models.DateField(db_default=Func(function='CURRENT_DATE', template='%(function)s'))
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'ingresos_otros'
        constraints = [
            models.CheckConstraint(condition=models.Q(monto__gt=0), name='ck_ingotros_monto'),
        ]
        indexes = [
            models.Index(fields=['sede', '-fecha'], name='ix_ingotros_sede_fecha'),
        ]

    def __str__(self):
        return f'{self.descripcion} — {self.monto}'


class Gasto(models.Model):
    """Egreso operativo del gimnasio (RF-24)."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='gastos',
    )
    sede = models.ForeignKey(
        Sede, on_delete=models.PROTECT, db_column='sede_id', related_name='gastos',
    )
    categoria_gasto = models.ForeignKey(
        CategoriaGasto, on_delete=models.PROTECT, db_column='categoria_gasto_id', related_name='gastos',
    )
    usuario = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, db_column='usuario_id', related_name='gastos_registrados',
    )
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    fecha = models.DateField(db_default=Func(function='CURRENT_DATE', template='%(function)s'))
    descripcion = models.CharField(max_length=250)
    comprobante_url = models.TextField(null=True, blank=True)
    es_recurrente = models.BooleanField(db_default=False)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    # No auto_now: el valor lo mantiene el trigger tg_gastos_actualizado
    # (fn_set_actualizado_en), creado en apps.core migración 0001.
    actualizado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'gastos'
        constraints = [
            models.CheckConstraint(condition=models.Q(monto__gt=0), name='ck_gastos_monto'),
        ]
        indexes = [
            models.Index(fields=['sede', '-fecha'], name='ix_gastos_sede_fecha'),
            models.Index(fields=['tenant', 'categoria_gasto', '-fecha'], name='ix_gastos_categoria'),
        ]

    def __str__(self):
        return f'{self.descripcion} — {self.monto}'
