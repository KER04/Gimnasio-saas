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
from django.db import IntegrityError, transaction
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


# ---------------------------------------------------------------------------
# Gestión del catálogo de planes (CRUD, pantalla "Gestión de Membresías")
# ---------------------------------------------------------------------------

class PlanAdminSerializer(serializers.ModelSerializer):
    """Escritura (y lectura) del catálogo de planes para la pantalla de
    gestión (``PlanViewSet``). ``PlanMiniSerializer``/``PlanSerializer`` de
    arriba son de solo lectura para otras pantallas; este es el único que
    valida entrada.
    """

    class Meta:
        model = Plan
        fields = ('id', 'nombre', 'tipo', 'duracion_dias', 'precio', 'requiere_entrenador', 'sede', 'activo')
        read_only_fields = ('id',)
        extra_kwargs = {
            'duracion_dias': {'required': False, 'allow_null': True},
            # NULL = plan disponible en todas las sedes del tenant.
            'sede': {'required': False, 'allow_null': True},
            # `requiere_entrenador` y `activo` se declaran en el modelo con
            # `db_default=` (el valor lo pone PostgreSQL), NO con `default=`
            # de Python. DRF solo mira el segundo, así que sin esto los daría
            # por obligatorios y un alta que no los mandara se llevaría un 400
            # por dos campos que tienen valor por defecto perfectamente
            # definido. Omitirlos deja que la columna aplique su db_default.
            'requiere_entrenador': {'required': False},
            'activo': {'required': False},
        }

    def validate(self, attrs):
        """Replica ``ck_planes_duracion`` en la capa API: sin esto, un
        payload inválido llega a PostgreSQL y estalla como ``IntegrityError``
        (500 crudo); con esto el usuario recibe un 400 con mensaje en
        español, señalando el campo concreto.

        En un PATCH parcial ``attrs`` solo trae lo que cambió, así que para
        decidir hay que combinar con lo que ya tiene la instancia (si la hay).

        Con el tipo ``por_sesion`` se distinguen DOS situaciones que no
        merecen la misma respuesta:

        - El cliente manda tipo y duración a la vez, en contradicción
          (``{"tipo": "por_sesion", "duracion_dias": 30}``): es un error suyo
          y se rechaza. Anular el valor en silencio guardaría algo distinto
          de lo que pidió, sin avisar.
        - El cliente solo cambia el tipo (``PATCH {"tipo": "por_sesion"}``)
          sobre un plan que hoy tiene 30 días: NO es un error. Pasar a
          venderse sesión a sesión implica renunciar a la vigencia, así que
          la duración se anula aquí en vez de devolver un 400 exigiendo un
          ``duracion_dias: null`` que el cliente no tiene por qué adivinar.
        """
        tipo = attrs.get('tipo', getattr(self.instance, 'tipo', None))
        duracion = attrs.get('duracion_dias', getattr(self.instance, 'duracion_dias', None))

        if tipo == Plan.TipoPlan.POR_SESION:
            # `in attrs` distingue "lo mandó explícitamente" de "viene de la
            # instancia": solo lo primero es una contradicción del cliente.
            if 'duracion_dias' in attrs and attrs['duracion_dias'] is not None:
                raise serializers.ValidationError({
                    'duracion_dias': 'Los planes por sesión no tienen duración: se venden sesión a sesión.',
                })
            attrs['duracion_dias'] = None
        else:
            if duracion is None or duracion <= 0:
                raise serializers.ValidationError({
                    'duracion_dias': 'Indica una duración mayor que cero para este tipo de plan.',
                })

        return attrs

    def _guardar_o_traducir_duplicado(self, guardar):
        """``uq_planes_nombre`` (nombre único por tenant): un ``IntegrityError``
        crudo sería un 500; se envuelve en un SAVEPOINT (``transaction.atomic``
        ANIDADO -- imprescindible porque ``ATOMIC_REQUESTS`` ya tiene la
        petición entera dentro de una transacción: sin el SAVEPOINT, capturar
        la excepción aquí dejaría esa transacción exterior envenenada) para
        poder traducirlo a un 400 con mensaje claro en español. Mismo patrón
        que ``apps.clientes.serializers.ClienteSerializer``.
        """
        try:
            with transaction.atomic():
                return guardar()
        except IntegrityError as exc:
            if 'uq_planes_nombre' in str(exc):
                raise serializers.ValidationError({
                    'nombre': 'Ya existe un plan con este nombre en este gimnasio.',
                })
            raise

    def create(self, validated_data):
        return self._guardar_o_traducir_duplicado(lambda: super(PlanAdminSerializer, self).create(validated_data))

    def update(self, instance, validated_data):
        return self._guardar_o_traducir_duplicado(
            lambda: super(PlanAdminSerializer, self).update(instance, validated_data)
        )
