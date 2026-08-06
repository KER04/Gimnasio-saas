"""Serializers de la API de ventas/POS (Parte D del encargo).

CRÍTICO (§2.1 de los requisitos): ``costo_unitario`` en una línea de venta, y
``costo``/``utilidad`` en un producto, son datos financieros que el
recepcionista NO debe ver. La ocultación se hace AQUÍ, en el serializer
(``to_representation``), nunca dejada al frontend: un cliente HTTP que no sea
el Angular oficial (curl, Postman, un script) recibiría igualmente el campo
si solo se ocultara en la UI. Se consulta ``usuario_tiene_permiso(...,
'costos.ver', request=request)`` (Parte A, con caché por petición) y, si el
usuario no tiene ese permiso, el campo se elimina por completo del diccionario
de salida -- no se serializa como ``null`` (eso seguiría siendo una fuga: un
``null`` explícito confirma la existencia y "forma" del campo).
"""
from decimal import Decimal

from rest_framework import serializers

from apps.clientes.models import Cliente
from apps.core.permissions import usuario_tiene_permiso
from apps.core.serializers import ocultar_campos_de_costo
from apps.inventario.models import Producto
from apps.membresias.models import Plan
from apps.organizacion.models import Sede

from .models import DetalleVenta, Pago, Venta
from .services import VentaError, registrar_venta

# La ocultación de costos se trasladó a `apps.core.serializers`: la aplican
# también los serializers de inventario, y mantener dos copias de la misma
# condición acabaría filtrando un costo por el lado que se olvidase
# actualizar. Se conserva el nombre privado como alias para no tocar los
# `to_representation` que ya lo llaman.
_ocultar_campos_de_costo = ocultar_campos_de_costo


# ---------------------------------------------------------------------------
# Endpoints de apoyo del POS (Parte D): productos, planes, clientes
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Lectura de ventas
# ---------------------------------------------------------------------------

class PagoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pago
        fields = ('id', 'usuario', 'monto', 'forma_pago', 'es_pago_inicial', 'fecha_hora', 'anulado')
        read_only_fields = fields


class DetalleVentaSerializer(serializers.ModelSerializer):
    # `total_linea` es una columna GENERATED de PostgreSQL, y DRF la deduce
    # como float en vez de como DecimalField: salía `60000.0` mientras el
    # resto de importes salían como `"60000.00"`. Se declara explícitamente
    # para que todo el dinero viaje igual, como cadena. Además de la
    # coherencia, evita los artefactos de coma flotante de JavaScript.
    total_linea = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = DetalleVenta
        fields = (
            'id', 'tipo_item', 'producto', 'plan', 'categoria_ingreso',
            'descripcion', 'cantidad', 'precio_unitario', 'costo_unitario', 'total_linea',
        )
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return _ocultar_campos_de_costo(data, self.context.get('request'))


class VentaSerializer(serializers.ModelSerializer):
    """Lectura de una venta con sus líneas y pagos (detalle de
    ``GET /api/ventas/{id}/`` y elemento de lista de ``GET /api/ventas/``).

    ``saldo`` se calcula en Python sobre los pagos ya cargados (no una
    consulta aparte): mismo dato que expone ``v_ventas_saldo``, pero sin
    depender de esa vista para no complicar el ``prefetch_related`` de la
    vista (Parte D).
    """

    detalles = DetalleVentaSerializer(many=True, read_only=True)
    pagos = PagoSerializer(many=True, read_only=True)
    saldo = serializers.SerializerMethodField()
    # Nombres legibles para no obligar a resolver un id por fila del listado
    # (mismo criterio que `AsistenciaSerializer` y `MovimientoInventarioSerializer`).
    cliente_nombre = serializers.SerializerMethodField()
    usuario_nombre = serializers.SerializerMethodField()

    class Meta:
        model = Venta
        fields = (
            'id', 'sede', 'cliente', 'cliente_nombre', 'usuario', 'usuario_nombre',
            'consecutivo', 'fecha_hora',
            'subtotal', 'descuento', 'motivo_descuento', 'total', 'estado',
            'anulada_por', 'motivo_anulacion', 'anulada_en',
            'detalles', 'pagos', 'saldo',
        )
        read_only_fields = fields

    def get_cliente_nombre(self, obj):
        # `None` es un dato, no un hueco: una venta de mostrador pagada al
        # contado no identifica a nadie.
        return obj.cliente.nombre if obj.cliente_id else None

    def get_usuario_nombre(self, obj):
        return obj.usuario.nombre if obj.usuario_id else None

    def get_saldo(self, obj):
        total_pagado = sum(
            (pago.monto for pago in obj.pagos.all() if not pago.anulado),
            Decimal('0'),
        )
        return str(obj.total - total_pagado)


# ---------------------------------------------------------------------------
# Escritura: registrar una venta
# ---------------------------------------------------------------------------

class ItemVentaInputSerializer(serializers.Serializer):
    tipo_item = serializers.ChoiceField(choices=DetalleVenta.TipoItemVenta.choices)
    producto_id = serializers.IntegerField(required=False)
    plan_id = serializers.IntegerField(required=False)
    cantidad = serializers.DecimalField(max_digits=10, decimal_places=2)
    entrenador_id = serializers.IntegerField(required=False, allow_null=True)
    descripcion = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        tipo_item = attrs['tipo_item']
        if tipo_item == DetalleVenta.TipoItemVenta.PRODUCTO and not attrs.get('producto_id'):
            raise serializers.ValidationError('Falta "producto_id" en un ítem de tipo producto.')
        if tipo_item == DetalleVenta.TipoItemVenta.PLAN and not attrs.get('plan_id'):
            raise serializers.ValidationError('Falta "plan_id" en un ítem de tipo plan.')
        return attrs


class VentaCreateSerializer(serializers.Serializer):
    """Entrada de ``POST /api/ventas/``. Resuelve los ids recibidos a
    instancias DENTRO del tenant actual (RLS ya filtra: un id de otro tenant
    sencillamente "no existe" para esta consulta) y delega toda la lógica de
    negocio en ``services.registrar_venta`` -- este serializer no calcula
    nada, solo traduce y valida forma.
    """

    sede_id = serializers.IntegerField()
    cliente_id = serializers.IntegerField(required=False, allow_null=True)
    items = ItemVentaInputSerializer(many=True)
    descuento = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True,
    )
    motivo_descuento = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    forma_pago = serializers.ChoiceField(
        choices=Pago.FormaPago.choices, required=False, allow_null=True,
    )
    monto_pago_inicial = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True,
    )
    fecha_inicio_membresia = serializers.DateField(required=False, allow_null=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError('La venta debe tener al menos un ítem.')
        return value

    def create(self, validated_data):
        request = self.context['request']
        tenant = request.tenant

        sede = Sede.objects.filter(pk=validated_data['sede_id']).first()
        if sede is None:
            raise serializers.ValidationError({'sede_id': 'Sede no encontrada.'})

        cliente = None
        cliente_id = validated_data.get('cliente_id')
        if cliente_id:
            cliente = Cliente.objects.filter(pk=cliente_id).first()
            if cliente is None:
                raise serializers.ValidationError({'cliente_id': 'Cliente no encontrado.'})

        items = []
        for item in validated_data['items']:
            tipo_item = item['tipo_item']
            preparado = {
                'tipo_item': tipo_item,
                'cantidad': item['cantidad'],
                'descripcion': item.get('descripcion'),
            }
            if tipo_item == DetalleVenta.TipoItemVenta.PRODUCTO:
                producto = Producto.objects.filter(pk=item['producto_id']).first()
                if producto is None:
                    raise serializers.ValidationError(
                        {'items': f'Producto {item["producto_id"]} no encontrado.'}
                    )
                preparado['producto'] = producto
            else:
                plan = Plan.objects.filter(pk=item['plan_id']).first()
                if plan is None:
                    raise serializers.ValidationError(
                        {'items': f'Plan {item["plan_id"]} no encontrado.'}
                    )
                preparado['plan'] = plan
                preparado['entrenador_id'] = item.get('entrenador_id')
            items.append(preparado)

        try:
            venta = registrar_venta(
                tenant=tenant,
                sede=sede,
                usuario=request.user,
                items=items,
                cliente=cliente,
                descuento=validated_data.get('descuento'),
                motivo_descuento=validated_data.get('motivo_descuento'),
                forma_pago=validated_data.get('forma_pago'),
                monto_pago_inicial=validated_data.get('monto_pago_inicial'),
                fecha_inicio_membresia=validated_data.get('fecha_inicio_membresia'),
            )
        except VentaError as exc:
            raise serializers.ValidationError({'detail': str(exc)})

        return venta


class AnularVentaInputSerializer(serializers.Serializer):
    motivo = serializers.CharField()

    def validate_motivo(self, value):
        if not value.strip():
            raise serializers.ValidationError('El motivo de anulación no puede estar vacío.')
        return value


class AbonoInputSerializer(serializers.Serializer):
    monto = serializers.DecimalField(max_digits=12, decimal_places=2)
    forma_pago = serializers.ChoiceField(choices=Pago.FormaPago.choices)
