"""Serializers de gastos e ingresos varios (RF-24 y RF-07).

Viven aparte de ``serializers.py`` porque no tienen nada que ver con la
venta: son movimientos de caja sueltos, sin cliente, sin líneas y sin
comprobante numerado.
"""
from rest_framework import serializers

from .models import CategoriaGasto, CategoriaIngreso, Gasto, IngresoOtro, Pago


class CategoriaGastoSerializer(serializers.ModelSerializer):
    class Meta:
        model = CategoriaGasto
        fields = ('id', 'nombre', 'activa')
        read_only_fields = ('id',)


class CategoriaIngresoSerializer(serializers.ModelSerializer):
    class Meta:
        model = CategoriaIngreso
        fields = ('id', 'nombre', 'subcategoria', 'es_sistema', 'activa')
        read_only_fields = fields


class GastoSerializer(serializers.ModelSerializer):
    """Un egreso operativo: arriendo, nómina, servicios, mantenimiento...

    ``sede`` SÍ viaja en el cuerpo (igual que en las ventas: un gimnasio con
    varias sedes registra el gasto donde toca). ``usuario`` NO: sale del
    token, porque dejarlo venir de fuera permitiría registrar gastos a
    nombre de otro.

    RLS hace que una sede de otro gimnasio sencillamente no exista para esta
    consulta, así que no hace falta comprobar el tenant a mano.
    """

    categoria_nombre = serializers.CharField(source='categoria_gasto.nombre', read_only=True)
    sede_nombre = serializers.CharField(source='sede.nombre', read_only=True)
    usuario_nombre = serializers.CharField(source='usuario.nombre', read_only=True)

    class Meta:
        model = Gasto
        fields = (
            'id', 'categoria_gasto', 'categoria_nombre', 'monto', 'fecha', 'descripcion',
            'comprobante_url', 'es_recurrente',
            'sede', 'sede_nombre', 'usuario', 'usuario_nombre', 'creado_en',
        )
        read_only_fields = ('id', 'usuario', 'creado_en')
        extra_kwargs = {
            'sede': {'required': True},
            # `db_default` en el modelo: lo pone PostgreSQL. DRF solo mira
            # `default=`, así que sin esto los daría por obligatorios.
            'fecha': {'required': False},
            'es_recurrente': {'required': False},
        }

    def validate_monto(self, valor):
        # `ck_gastos_monto` exige > 0. Validarlo aquí lo convierte en un 400
        # legible en vez de un IntegrityError que sale como 500.
        if valor <= 0:
            raise serializers.ValidationError('El monto debe ser mayor que cero.')
        return valor

    def validate_descripcion(self, valor):
        # Normaliza los espacios. El vacío no llega hasta aquí: `CharField`
        # recorta y rechaza el blanco antes, con su propio mensaje.
        return valor.strip()

    def validate_categoria_gasto(self, valor):
        # RLS ya hace que una categoría de otro gimnasio no exista aquí.
        if not valor.activa:
            raise serializers.ValidationError('Esa categoría está dada de baja.')
        return valor


class IngresoOtroSerializer(serializers.ModelSerializer):
    """Dinero que entra SIN venta asociada: matrícula, casillero, alquiler
    de espacio (RF-07).

    Entra al corte diario junto con los pagos de ventas -- lo hace la propia
    vista ``v_corte_diario`` --, así que en cuanto se registra aparece en el
    informe de caja sin que haya que tocar nada más.
    """

    categoria_nombre = serializers.CharField(source='categoria_ingreso.nombre', read_only=True)
    sede_nombre = serializers.CharField(source='sede.nombre', read_only=True)
    usuario_nombre = serializers.CharField(source='usuario.nombre', read_only=True)

    class Meta:
        model = IngresoOtro
        fields = (
            'id', 'categoria_ingreso', 'categoria_nombre', 'monto', 'forma_pago',
            'descripcion', 'fecha',
            'sede', 'sede_nombre', 'usuario', 'usuario_nombre', 'creado_en',
        )
        read_only_fields = ('id', 'usuario', 'creado_en')
        extra_kwargs = {'sede': {'required': True}, 'fecha': {'required': False}}

    def validate_monto(self, valor):
        if valor <= 0:
            raise serializers.ValidationError('El monto debe ser mayor que cero.')
        return valor

    def validate_descripcion(self, valor):
        return valor.strip()

    def validate_forma_pago(self, valor):
        if valor not in Pago.FormaPago.values:
            raise serializers.ValidationError('Forma de pago desconocida.')
        return valor

    def validate_categoria_ingreso(self, valor):
        if not valor.activa:
            raise serializers.ValidationError('Esa categoría está dada de baja.')
        return valor
