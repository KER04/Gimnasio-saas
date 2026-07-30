"""
App inventario — sección 09 del esquema: catálogos e inventario.

Nota de dependencia circular: movimientos_inventario.venta_id apunta a
ventas.Venta, y ventas.DetalleVenta apunta a inventario.Producto. Igual que
en membresias, la FK hacia Venta usa referencia perezosa en cadena de texto
('ventas.Venta') para evitar el import circular de Python; a nivel de
migraciones también es una dependencia circular real entre las apps
inventario y ventas, que el autodetector de Django resuelve partiendo una de
las dos en una migración adicional (AddField).
"""
from django.db import models
from django.db.models import Func

from apps.organizacion.models import Sede, Usuario
from apps.plataforma.models import Tenant


class CategoriaProducto(models.Model):
    """Catálogo de categorías de producto, editable por el gimnasio."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='categorias_producto',
    )
    nombre = models.CharField(max_length=80)
    activa = models.BooleanField(db_default=True)

    class Meta:
        db_table = 'categorias_producto'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_catprod_id_tenant'),
            models.UniqueConstraint(fields=['tenant', 'nombre'], name='uq_catprod_nombre'),
        ]

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    """Producto vendible en tienda (suplementos, accesorios, etc.)."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='productos',
    )
    categoria_producto = models.ForeignKey(
        CategoriaProducto, on_delete=models.PROTECT, db_column='categoria_producto_id',
        related_name='productos',
    )
    nombre = models.CharField(max_length=120)
    # Separado del nombre para poder agrupar el listado en pantalla sin
    # parsear cadenas.
    marca = models.CharField(max_length=80, null=True, blank=True)
    presentacion = models.CharField(max_length=60, null=True, blank=True)
    codigo_barras = models.CharField(max_length=50, null=True, blank=True)
    precio_venta = models.DecimalField(max_digits=12, decimal_places=2)
    # Costo ACTUAL de reposición. El costo con el que se calcula la utilidad
    # de una venta se copia a detalle_ventas.
    costo = models.DecimalField(max_digits=12, decimal_places=2, db_default=0)
    stock_minimo = models.DecimalField(max_digits=10, decimal_places=2, db_default=0)
    activo = models.BooleanField(db_default=True)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    # No auto_now: el valor lo mantiene el trigger tg_productos_actualizado
    # (fn_set_actualizado_en), creado en apps.core migración 0001.
    actualizado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'productos'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_productos_id_tenant'),
            # Cada presentación es un producto distinto (decisión 25); la
            # unicidad incluye la presentación para permitir "Proteína Pro 2
            # lb" y "5 lb".
            models.UniqueConstraint(
                fields=['tenant', 'nombre', 'marca', 'presentacion'], name='uq_productos_nombre',
            ),
            models.UniqueConstraint(
                fields=['tenant', 'codigo_barras'],
                condition=models.Q(codigo_barras__isnull=False),
                name='uq_productos_barras',
            ),
            models.CheckConstraint(condition=models.Q(precio_venta__gte=0), name='ck_productos_precio'),
            models.CheckConstraint(condition=models.Q(costo__gte=0), name='ck_productos_costo'),
            models.CheckConstraint(condition=models.Q(stock_minimo__gte=0), name='ck_productos_stockmin'),
        ]
        indexes = [
            # GIN trigram -> va en RunSQL:
            # CREATE INDEX ix_productos_nombre_trgm ON productos USING GIN (nombre gin_trgm_ops);
        ]

    def __str__(self):
        return self.nombre


class StockSede(models.Model):
    """Existencias por sede: relación N:M entre productos y sedes con atributos.

    DESNORMALIZACIÓN DELIBERADA (1 de 3). La existencia es derivable sumando
    movimientos_inventario, pero esa suma se consulta en cada venta y en cada
    pantalla de producto. Con millones de movimientos el agregado sería el
    cuello de botella del POS. Se mantiene por disparador (RunSQL, pendiente)
    para que no pueda desincronizarse desde la aplicación.
    """

    # PK compuesta (producto_id, sede_id), sin columna id, igual que el .sql.
    # La tabla la crea así apps.core.0001_esquema_postgres; esta declaración
    # existe para que el ORM no intente seleccionar una columna `id` que no
    # existe en la base.
    pk = models.CompositePrimaryKey('producto', 'sede')
    producto = models.ForeignKey(
        Producto, on_delete=models.CASCADE, db_column='producto_id', related_name='stock_sedes',
    )
    sede = models.ForeignKey(
        Sede, on_delete=models.CASCADE, db_column='sede_id', related_name='stock_productos',
    )
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='stock_sedes',
    )
    cantidad = models.DecimalField(max_digits=12, decimal_places=2, db_default=0)
    # No auto_now: el valor lo mantiene el trigger tg_stock_sedes_actualizado
    # (fn_set_actualizado_en), creado en apps.core migración 0001.
    actualizado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'stock_sedes'
        constraints = [
            # La unicidad (producto, sede) la garantiza la PK compuesta.
            models.CheckConstraint(condition=models.Q(cantidad__gte=0), name='ck_stock_cantidad'),
        ]

    def __str__(self):
        return f'{self.producto} en {self.sede}: {self.cantidad}'


class MovimientoInventario(models.Model):
    """Kardex. Libro inmutable: nunca se actualiza ni se elimina una fila; los
    errores se corrigen con un movimiento inverso.
    """

    class TipoMovimiento(models.TextChoices):
        ENTRADA_COMPRA = 'entrada_compra', 'Entrada por compra'
        SALIDA_VENTA = 'salida_venta', 'Salida por venta'
        AJUSTE_MANUAL = 'ajuste_manual', 'Ajuste manual'
        REVERSO_ANULACION = 'reverso_anulacion', 'Reverso por anulación'

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='movimientos_inventario',
    )
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, db_column='producto_id', related_name='movimientos',
    )
    sede = models.ForeignKey(
        Sede, on_delete=models.PROTECT, db_column='sede_id', related_name='movimientos_inventario',
    )
    usuario = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, db_column='usuario_id', related_name='movimientos_inventario',
    )
    tipo = models.CharField(max_length=20, choices=TipoMovimiento.choices)
    # Con signo: positivo entra, negativo sale. Evita una columna extra de
    # dirección y hace que el saldo sea una simple suma.
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    saldo_resultante = models.DecimalField(max_digits=12, decimal_places=2)
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    motivo = models.TextField(null=True, blank=True)
    venta = models.ForeignKey(
        'ventas.Venta', on_delete=models.PROTECT, db_column='venta_id',
        related_name='movimientos_inventario', null=True, blank=True,
    )
    fecha_hora = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'movimientos_inventario'
        constraints = [
            models.CheckConstraint(condition=~models.Q(cantidad=0), name='ck_movinv_cantidad'),
            # Un ajuste manual sin motivo es inauditable. length(btrim(motivo)) > 0
            # se aproxima con un regex que excluye vacío y solo-espacios.
            models.CheckConstraint(
                condition=(
                    ~models.Q(tipo='ajuste_manual')
                    | (models.Q(motivo__isnull=False) & ~models.Q(motivo__regex=r'^\s*$'))
                ),
                name='ck_movinv_motivo',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(tipo__in=['entrada_compra', 'reverso_anulacion'], cantidad__gt=0)
                    | models.Q(tipo='salida_venta', cantidad__lt=0)
                    | models.Q(tipo='ajuste_manual')
                ),
                name='ck_movinv_signo',
            ),
        ]
        indexes = [
            models.Index(fields=['producto', 'sede', '-fecha_hora'], name='ix_movinv_producto_fecha'),
            models.Index(fields=['tenant', '-fecha_hora'], name='ix_movinv_tenant_fecha'),
        ]

    def __str__(self):
        return f'{self.get_tipo_display()} de {self.producto} ({self.cantidad})'
