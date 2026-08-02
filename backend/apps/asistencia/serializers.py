"""Serializers de la API de asistencia (RF-15, sin biometría).

- ``AsistenciaInputSerializer``: entrada de ``POST /api/asistencias/`` --
  validación de FORMA únicamente (tipos, campos presentes). Toda regla de
  NEGOCIO (antipassback, autorización, sesión anónima sin venta...) vive en
  ``apps.asistencia.services.registrar_asistencia``, nunca aquí.
- ``AsistenciaSerializer``: lectura, usada tanto por el listado
  (``GET /api/asistencias/``) como por la ficha del cliente
  (``GET /api/clientes/{id}/asistencias/``, ``apps.clientes.views``) y por la
  respuesta de ``POST``.
"""
from rest_framework import serializers

from .models import Asistencia


class AsistenciaInputSerializer(serializers.Serializer):
    """Entrada de ``POST /api/asistencias/``. ``huella`` NO es una opción
    válida todavía: el lector no existe (ver encargo)."""

    metodo = serializers.ChoiceField(choices=[
        (Asistencia.MetodoAsistencia.MANUAL_CEDULA, 'Manual por cédula'),
        (Asistencia.MetodoAsistencia.SESION_ANONIMA, 'Sesión anónima'),
    ])
    # Obligatoria solo si metodo='manual_cedula' (lo valida el servicio, no
    # este serializer: el mismo criterio que el resto de la API, ver
    # apps.ventas/apps.membresias).
    cedula = serializers.CharField(required=False, allow_blank=True)
    # Obligatoria solo si metodo='sesion_anonima'.
    venta_id = serializers.IntegerField(required=False)
    # Obligatorios juntos solo si el cliente NO tiene membresía vigente.
    autorizado_por_id = serializers.IntegerField(required=False)
    motivo_autorizacion = serializers.CharField(required=False, allow_blank=True)


class AsistenciaSerializer(serializers.ModelSerializer):
    """Lectura de una asistencia: incluye nombre/cédula del cliente y el
    nombre de quien autorizó (cuando aplica) para no obligar al frontend a
    hacer una consulta aparte por cada fila del listado."""

    cliente_nombre = serializers.SerializerMethodField()
    cliente_cedula = serializers.SerializerMethodField()
    autorizado_por_nombre = serializers.SerializerMethodField()

    class Meta:
        model = Asistencia
        fields = (
            'id', 'sede', 'cliente', 'cliente_nombre', 'cliente_cedula',
            'venta', 'metodo', 'fecha_hora', 'con_membresia_vigente',
            'autorizado_por', 'autorizado_por_nombre', 'motivo_autorizacion',
        )
        read_only_fields = fields

    def get_cliente_nombre(self, obj):
        return obj.cliente.nombre if obj.cliente_id else None

    def get_cliente_cedula(self, obj):
        return obj.cliente.cedula if obj.cliente_id else None

    def get_autorizado_por_nombre(self, obj):
        return obj.autorizado_por.nombre if obj.autorizado_por_id else None
