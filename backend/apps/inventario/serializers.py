"""Serializers de inventario: catálogo de productos, categorías y kardex.

``costo`` solo lo ve quien tenga ``costos.ver``; la ocultación la aplica
``apps.core.serializers.ocultar_campos_de_costo`` en ``to_representation``,
no el frontend (ver el porqué en ese módulo).
"""
from rest_framework import serializers

from apps.core.serializers import ocultar_campos_de_costo

from .models import CategoriaProducto, MovimientoInventario, Producto, StockSede


class CategoriaProductoSerializer(serializers.ModelSerializer):
    class Meta:
        model = CategoriaProducto
        fields = ('id', 'nombre', 'activa')
        read_only_fields = ('id',)
        extra_kwargs = {
            # `activa` se declara en el modelo con `db_default`, no con
            # `default` de Python: DRF solo mira el segundo, así que sin esto
            # la daría por obligatoria en el alta.
            'activa': {'required': False},
        }


class ProductoSerializer(serializers.ModelSerializer):
    """Lectura del catálogo (POS y pantalla de inventario).

    ``stock`` se calcula para la sede que indique la vista vía
    ``context['sede_id']`` (query param ``sede_id``). Si no se indicó
    ninguna sede sale ``None``, que significa "no se preguntó por ninguna
    sede" -- NO "no hay existencias".
    """

    stock = serializers.SerializerMethodField()
    categoria_nombre = serializers.SerializerMethodField()

    class Meta:
        model = Producto
        fields = (
            'id', 'nombre', 'marca', 'presentacion', 'codigo_barras',
            'categoria_producto', 'categoria_nombre', 'precio_venta', 'costo',
            'stock_minimo', 'activo', 'stock',
        )
        read_only_fields = fields

    def get_stock(self, obj):
        sede_id = self.context.get('sede_id')
        if not sede_id:
            return None
        stock = StockSede.objects.filter(producto=obj, sede_id=sede_id).first()
        return str(stock.cantidad) if stock is not None else '0'

    def get_categoria_nombre(self, obj):
        return obj.categoria_producto.nombre if obj.categoria_producto_id else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return ocultar_campos_de_costo(data, self.context.get('request'))


class ProductoAdminSerializer(serializers.ModelSerializer):
    """Escritura del catálogo (``inventario.gestionar``).

    NO expone ``stock``: las existencias no se editan a mano, se mueven con
    un movimiento de kardex (ver ``services.registrar_movimiento``). Poder
    escribir el stock desde aquí desincronizaría el libro de movimientos, que
    es justo lo que el disparador de la base impide.
    """

    class Meta:
        model = Producto
        fields = (
            'id', 'nombre', 'marca', 'presentacion', 'codigo_barras',
            'categoria_producto', 'precio_venta', 'costo', 'stock_minimo', 'activo',
        )
        read_only_fields = ('id',)
        extra_kwargs = {
            'marca': {'required': False, 'allow_null': True, 'allow_blank': True},
            'presentacion': {'required': False, 'allow_null': True, 'allow_blank': True},
            'codigo_barras': {'required': False, 'allow_null': True, 'allow_blank': True},
            # Los tres se declaran con `db_default` en el modelo, no con
            # `default` de Python (mismo caso que en `CategoriaProducto`).
            'costo': {'required': False},
            'stock_minimo': {'required': False},
            'activo': {'required': False},
        }

    def validate_precio_venta(self, value):
        if value < 0:
            raise serializers.ValidationError('El precio de venta no puede ser negativo.')
        return value

    def validate_costo(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError('El costo no puede ser negativo.')
        return value

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return ocultar_campos_de_costo(data, self.context.get('request'))


class MovimientoInventarioSerializer(serializers.ModelSerializer):
    """Lectura del kardex. Incluye nombres para no obligar a resolver ids
    aparte por cada fila del historial."""

    producto_nombre = serializers.SerializerMethodField()
    sede_nombre = serializers.SerializerMethodField()
    usuario_nombre = serializers.SerializerMethodField()

    class Meta:
        model = MovimientoInventario
        fields = (
            'id', 'producto', 'producto_nombre', 'sede', 'sede_nombre',
            'usuario', 'usuario_nombre', 'tipo', 'cantidad', 'saldo_resultante',
            'costo_unitario', 'motivo', 'venta', 'fecha_hora',
        )
        read_only_fields = fields

    def get_producto_nombre(self, obj):
        return obj.producto.nombre if obj.producto_id else None

    def get_sede_nombre(self, obj):
        return obj.sede.nombre if obj.sede_id else None

    def get_usuario_nombre(self, obj):
        return obj.usuario.nombre if obj.usuario_id else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return ocultar_campos_de_costo(data, self.context.get('request'))


class MovimientoInputSerializer(serializers.Serializer):
    """Entrada de ``POST /api/movimientos-inventario/``. Solo valida FORMA;
    las reglas de negocio (tipos permitidos, signo, motivo del ajuste,
    existencia suficiente) viven en ``services.registrar_movimiento``."""

    producto_id = serializers.IntegerField()
    sede_id = serializers.IntegerField()
    tipo = serializers.ChoiceField(choices=MovimientoInventario.TipoMovimiento.choices)
    #: Con signo: positiva entra, negativa sale.
    cantidad = serializers.DecimalField(max_digits=12, decimal_places=2)
    costo_unitario = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True,
    )
    motivo = serializers.CharField(required=False, allow_blank=True, allow_null=True)
