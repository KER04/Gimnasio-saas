"""Serializers de la API de membresías (Parte A del encargo de membresías).

El estado calculado (RF-16: ``activa``/``por_vencer``/``vence_hoy``/
``vencida``/``cancelada``) y los días restantes NUNCA se recalculan aquí:
salen de ``v_membresias_estado`` (``VistaMembresiaEstado``,
``apps.auditoria.models``, ``managed=False``) -- la vista ya aplica
``dias_aviso_vencimiento`` del tenant, que es configuración por gimnasio.
``MembresiaSerializer`` acepta un lookup precomputado
(``context['estado_por_id']``) para no hacer una consulta por fila en un
listado paginado; si no se lo pasan (detalle, o resultado de una acción de
escritura), cae a una única consulta puntual.
"""
from rest_framework import serializers

from apps.auditoria.models import VistaMembresiaEstado

from .models import Membresia, Plan


class ClienteMiniSerializer(serializers.Serializer):
    """Datos legibles mínimos del cliente para no obligar a quien consuma
    este endpoint a resolver el id contra ``/api/clientes/`` aparte."""

    id = serializers.IntegerField()
    nombre = serializers.CharField()
    cedula = serializers.CharField()
    telefono = serializers.CharField()


class PlanMiniSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nombre = serializers.CharField()
    tipo = serializers.CharField()
    duracion_dias = serializers.IntegerField(allow_null=True)


class SedeMiniSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nombre = serializers.CharField()


class MembresiaSerializer(serializers.ModelSerializer):
    """Lectura de una membresía para listado/detalle (A1). Incluye datos
    legibles del cliente y del plan (no solo ids): esto pinta una tabla."""

    cliente = ClienteMiniSerializer()
    plan = PlanMiniSerializer()
    sede = SedeMiniSerializer()
    estado_calculado = serializers.SerializerMethodField()
    dias_restantes = serializers.SerializerMethodField()

    class Meta:
        model = Membresia
        fields = (
            'id', 'cliente', 'plan', 'sede', 'venta', 'entrenador', 'vendedor',
            'fecha_inicio', 'fecha_fin', 'precio_pagado', 'membresia_anterior',
            'estado', 'motivo_cancelacion', 'estado_calculado', 'dias_restantes',
            'creado_en',
        )
        read_only_fields = fields

    def _vista_estado(self, obj):
        estado_por_id = self.context.get('estado_por_id')
        if estado_por_id is not None:
            return estado_por_id.get(obj.id)
        return VistaMembresiaEstado.objects.filter(id=obj.id).first()

    def get_estado_calculado(self, obj):
        vista = self._vista_estado(obj)
        return vista.estado_calculado if vista is not None else None

    def get_dias_restantes(self, obj):
        vista = self._vista_estado(obj)
        return vista.dias_restantes if vista is not None else None


# ---------------------------------------------------------------------------
# A2. Asignación directa (entrada)
# ---------------------------------------------------------------------------

class AsignarMembresiaInputSerializer(serializers.Serializer):
    cliente_id = serializers.IntegerField()
    plan_id = serializers.IntegerField()
    sede_id = serializers.IntegerField()
    fecha_inicio = serializers.DateField(required=False, allow_null=True)
    precio_pagado = serializers.DecimalField(max_digits=12, decimal_places=2)
    entrenador_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_precio_pagado(self, value):
        if value < 0:
            raise serializers.ValidationError('El precio pagado no puede ser negativo.')
        return value


# ---------------------------------------------------------------------------
# A3. Renovación (entrada)
# ---------------------------------------------------------------------------

class RenovarMembresiaInputSerializer(serializers.Serializer):
    precio_pagado = serializers.DecimalField(max_digits=12, decimal_places=2)
    plan_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_precio_pagado(self, value):
        if value < 0:
            raise serializers.ValidationError('El precio pagado no puede ser negativo.')
        return value


# ---------------------------------------------------------------------------
# A4. Cancelación (entrada)
# ---------------------------------------------------------------------------

class CancelarMembresiaInputSerializer(serializers.Serializer):
    motivo = serializers.CharField()

    def validate_motivo(self, value):
        if not value.strip():
            raise serializers.ValidationError('El motivo de cancelación no puede estar vacío.')
        return value


# ---------------------------------------------------------------------------
# A5. Tablero de vencimientos
# ---------------------------------------------------------------------------

class MembresiaPorVencerSerializer(serializers.Serializer):
    """Fila del tablero de alertas (A5): cliente + teléfono + días
    restantes, para que recepción llame."""

    id = serializers.IntegerField()
    cliente_id = serializers.IntegerField()
    cliente_nombre = serializers.CharField()
    cliente_telefono = serializers.CharField()
    plan_id = serializers.IntegerField()
    plan_nombre = serializers.CharField()
    sede_id = serializers.IntegerField()
    fecha_fin = serializers.DateField()
    dias_restantes = serializers.IntegerField()
    estado_calculado = serializers.CharField()
