"""Serializers de la API de clientes (Parte B del encargo, RF-03/RF-09/RF-16).

Estructura:

- ``ClienteSerializer``: lectura completa (ficha) + escritura (crear/editar).
  Incluye el estado de las DOS autorizaciones de la Ley 1581 (Parte B4).
- ``ClienteResumenSerializer``: lectura mínima para listados/buscador (incluye
  el que usa el POS -- Parte B1, mismo campo que antes en
  ``apps.ventas.serializers.ClienteResumenSerializer``, ahora vive aquí).
- ``MembresiaEstadoSerializer``: lectura de ``v_membresias_estado`` (Parte B5).
- ``VentaSaldoSerializer``/``AbonoSerializer``/``DetalleVentaSerializer``:
  cartera del cliente (Parte B6), sin exponer costos (este endpoint no exige
  ``costos.ver``).
"""
from django.db import IntegrityError, transaction
from rest_framework import serializers

from apps.organizacion.models import Sede, UsuarioSede
from apps.ventas.models import DetalleVenta, Pago

from .models import AutorizacionDatos, Cliente

# ---------------------------------------------------------------------------
# Resolución de la sede de origen cuando no viene explícita en el POST
# ---------------------------------------------------------------------------


def _resolver_sede_origen(request, sede_origen_id):
    """``sede_origen`` es "adicional" según RF-03 (el operador no SIEMPRE
    tiene que indicarla a mano), pero la columna real (``clientes.sede_origen_id``)
    es NOT NULL a nivel de base de datos -- no se puede tocar el modelo para
    volverla opcional (el encargo prohíbe cambiar modelos/migraciones). La
    conciliación: si el POST no trae ``sede_origen_id``, se usa la sede en la
    que opera el usuario que está creando el cliente (``UsuarioSede``); si el
    usuario tiene más de una sede asignada o ninguna, no hay forma segura de
    adivinar y se exige el campo explícito con un 400 claro.
    """
    if sede_origen_id:
        sede = Sede.objects.filter(pk=sede_origen_id).first()
        if sede is None:
            raise serializers.ValidationError(
                {'sede_origen': 'La sede indicada no existe.'}
            )
        return sede

    usuario = getattr(request, 'user', None)
    sedes_usuario = list(
        UsuarioSede.objects.filter(usuario=usuario).values_list('sede_id', flat=True)
    ) if usuario is not None else []

    if len(sedes_usuario) == 1:
        return Sede.objects.get(pk=sedes_usuario[0])

    raise serializers.ValidationError({
        'sede_origen': (
            'Debes indicar la sede de origen (no se pudo determinar '
            'automáticamente a partir de tu usuario).'
        ),
    })


# ---------------------------------------------------------------------------
# Autorizaciones (Ley 1581 -- Parte B4)
# ---------------------------------------------------------------------------


def _estado_autorizacion(cliente, tipo):
    """``True``/``False`` si existe una fila de ``AutorizacionDatos`` de ese
    tipo para el cliente, ``None`` si nunca se registró ninguna decisión."""
    fila = cliente.autorizaciones.filter(tipo=tipo).first()
    return fila.otorgada if fila is not None else None


class ClienteResumenSerializer(serializers.ModelSerializer):
    """Lectura mínima para listados y para el buscador del POS (Parte B1: es
    el mismo campo que antes vivía en ``apps.ventas.serializers``, movido
    aquí para no duplicar el endpoint). No expone datos sensibles como
    huellas ni autorizaciones: eso vive en la ficha completa (``ClienteSerializer``)."""

    class Meta:
        model = Cliente
        fields = ('id', 'nombre', 'cedula', 'telefono', 'activo')
        read_only_fields = fields


class ClienteSerializer(serializers.ModelSerializer):
    """Ficha completa del cliente: lectura (con el estado de ambas
    autorizaciones) y escritura (alta/edición).

    Campos de entrada exclusivos de la creación (``write_only``):
    ``autoriza_tratamiento_datos`` y ``autoriza_biometria`` -- booleanos
    independientes (Parte B4: el cliente puede aceptar uno y negar el otro).
    Si no se envían, sencillamente no se registra ninguna autorización
    todavía (``autorizacion_tratamiento_datos``/``autorizacion_biometria``
    saldrán en ``None`` en la respuesta, no en ``False``: "no se sabe" es
    distinto de "negó").
    """

    autorizacion_tratamiento_datos = serializers.SerializerMethodField()
    autorizacion_biometria = serializers.SerializerMethodField()

    autoriza_tratamiento_datos = serializers.BooleanField(
        write_only=True, required=False, allow_null=True, default=None,
    )
    autoriza_biometria = serializers.BooleanField(
        write_only=True, required=False, allow_null=True, default=None,
    )

    class Meta:
        model = Cliente
        fields = (
            'id', 'nombre', 'cedula', 'telefono', 'direccion', 'sexo',
            'sede_origen', 'fecha_registro', 'activo', 'eliminado_en',
            'creado_en', 'actualizado_en',
            'autorizacion_tratamiento_datos', 'autorizacion_biometria',
            'autoriza_tratamiento_datos', 'autoriza_biometria',
        )
        read_only_fields = (
            'id', 'fecha_registro', 'activo', 'eliminado_en', 'creado_en', 'actualizado_en',
        )
        extra_kwargs = {
            # Obligatorios en la creación según RF-03; ver Meta.fields de
            # abajo para sexo/sede_origen ("adicionales").
            'nombre': {'required': True},
            'cedula': {'required': True},
            'telefono': {'required': True},
            'direccion': {'required': True},
            'sede_origen': {'required': False},
        }

    def get_autorizacion_tratamiento_datos(self, obj):
        return _estado_autorizacion(obj, AutorizacionDatos.TipoAutorizacion.TRATAMIENTO_DATOS)

    def get_autorizacion_biometria(self, obj):
        return _estado_autorizacion(obj, AutorizacionDatos.TipoAutorizacion.BIOMETRIA)

    def validate(self, attrs):
        # PATCH parcial: no exigir los obligatorios si no vienen en el
        # cuerpo (ya existen en la fila). En creación (POST), `required=True`
        # en extra_kwargs ya los exige.
        return attrs

    def create(self, validated_data):
        request = self.context['request']

        autoriza_tratamiento = validated_data.pop('autoriza_tratamiento_datos', None)
        autoriza_biometria = validated_data.pop('autoriza_biometria', None)

        sede_origen = validated_data.pop('sede_origen', None)
        sede_origen = _resolver_sede_origen(
            request, sede_origen.id if sede_origen is not None else None,
        )

        # Parte B3: cédula única POR TENANT (`uq_clientes_cedula`). Un
        # IntegrityError crudo sería un 500; se envuelve en un SAVEPOINT
        # (transaction.atomic ANIDADO -- imprescindible porque
        # ATOMIC_REQUESTS ya tiene la petición entera dentro de una
        # transacción: sin el SAVEPOINT, capturar la excepción aquí dejaría
        # esa transacción exterior "envenenada" y CUALQUIER instrucción SQL
        # posterior fallaría con TransactionManagementError) para poder
        # traducirlo a un 400 con mensaje claro en español.
        try:
            with transaction.atomic():
                cliente = Cliente.objects.create(
                    tenant=request.tenant,
                    sede_origen=sede_origen,
                    **validated_data,
                )
        except IntegrityError as exc:
            if 'uq_clientes_cedula' in str(exc):
                raise serializers.ValidationError({
                    'cedula': 'Ya existe un cliente con esta cédula en este gimnasio.',
                })
            raise

        if autoriza_tratamiento is not None:
            AutorizacionDatos.objects.create(
                tenant=request.tenant, cliente=cliente,
                tipo=AutorizacionDatos.TipoAutorizacion.TRATAMIENTO_DATOS,
                otorgada=autoriza_tratamiento,
            )
        if autoriza_biometria is not None:
            AutorizacionDatos.objects.create(
                tenant=request.tenant, cliente=cliente,
                tipo=AutorizacionDatos.TipoAutorizacion.BIOMETRIA,
                otorgada=autoriza_biometria,
            )

        return cliente

    def update(self, instance, validated_data):
        # Las autorizaciones no se editan por este endpoint (fuera del
        # alcance de la Parte B: solo se registran al crear el cliente).
        validated_data.pop('autoriza_tratamiento_datos', None)
        validated_data.pop('autoriza_biometria', None)

        try:
            with transaction.atomic():
                return super().update(instance, validated_data)
        except IntegrityError as exc:
            if 'uq_clientes_cedula' in str(exc):
                raise serializers.ValidationError({
                    'cedula': 'Ya existe un cliente con esta cédula en este gimnasio.',
                })
            raise


# ---------------------------------------------------------------------------
# Membresías con estado calculado (Parte B5, RF-16)
# ---------------------------------------------------------------------------


class MembresiaEstadoSerializer(serializers.Serializer):
    """Lectura de una fila de ``v_membresias_estado`` (``VistaMembresiaEstado``,
    ``apps.auditoria.models``, ``managed=False``). El estado y los días
    restantes salen YA CALCULADOS de la vista -- este serializer no
    reimplementa esa lógica en Python (ver encargo: "Existe la vista
    v_membresias_estado que ya calcula esto")."""

    id = serializers.IntegerField()
    plan_id = serializers.IntegerField()
    sede_id = serializers.IntegerField()
    fecha_inicio = serializers.DateField()
    fecha_fin = serializers.DateField()
    dias_restantes = serializers.IntegerField()
    estado_calculado = serializers.CharField()


# ---------------------------------------------------------------------------
# Cartera del cliente (Parte B6, RF-09)
# ---------------------------------------------------------------------------


class AbonoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pago
        fields = ('id', 'monto', 'forma_pago', 'es_pago_inicial', 'fecha_hora', 'usuario')
        read_only_fields = fields


class DetalleConceptoSerializer(serializers.ModelSerializer):
    """Líneas de la venta, SIN costo (este endpoint no exige `costos.ver`,
    ver encargo Parte B6: "no debe filtrar márgenes" -- en este caso
    sencillamente no se incluyen los campos de costo en absoluto)."""

    # `total_linea` es una columna GENERATED de PostgreSQL, y DRF la deduce
    # como float en vez de como DecimalField: salía `60000.0` mientras el
    # resto de importes salían como `"60000.00"`. Se declara explícitamente
    # para que todo el dinero viaje igual, como cadena. Además de la
    # coherencia, evita los artefactos de coma flotante de JavaScript al
    # operar con importes.
    total_linea = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = DetalleVenta
        fields = ('id', 'tipo_item', 'descripcion', 'cantidad', 'precio_unitario', 'total_linea')
        read_only_fields = fields


class VentaSaldoSerializer(serializers.Serializer):
    """Una venta con saldo pendiente, con sus líneas (concepto) y sus abonos
    en orden cronológico (RF-09)."""

    venta_id = serializers.IntegerField()
    fecha_hora = serializers.DateTimeField()
    total = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_pagado = serializers.DecimalField(max_digits=12, decimal_places=2)
    saldo = serializers.DecimalField(max_digits=12, decimal_places=2)
    detalles = DetalleConceptoSerializer(many=True)
    abonos = AbonoSerializer(many=True)
