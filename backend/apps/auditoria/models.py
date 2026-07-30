"""
App auditoria — secciones 15 y 16 del esquema.

TODOS los modelos de esta app son ``managed = False``:

- ``Auditoria`` refleja una tabla PARTICIONADA que ya existe en la base (o
  existirá) creada por RunSQL directo (``CREATE TABLE ... PARTITION BY
  RANGE``), no por una migración de Django — Django no soporta particionado
  declarativo. Las particiones mensuales (auditoria_2026_07, _08, _09,
  auditoria_default) NO tienen modelo propio: son particiones de esta misma
  tabla, no tablas independientes.
- Las tres ``Vista*`` reflejan VIEWs de solo lectura (sección 16 del .sql).
  Se crean con RunSQL (``CREATE VIEW``); Django solo las necesita para poder
  hacer consultas de lectura sobre ellas vía el ORM.
"""
from django.db import models


class Auditoria(models.Model):
    """RF-02. Sin FK a usuarios/sede/tenant: la traza debe sobrevivir a la
    eliminación del usuario, y una FK sobre una tabla particionada de alta
    escritura penaliza cada INSERT. Por eso tenant_id, usuario_id,
    usuario_plataforma_id, sede_id y entidad_id son enteros planos, no
    ForeignKey, fielmente al .sql.
    """

    class AccionAuditoria(models.TextChoices):
        CREAR = 'crear', 'Crear'
        ACTUALIZAR = 'actualizar', 'Actualizar'
        ANULAR = 'anular', 'Anular'
        ELIMINAR = 'eliminar', 'Eliminar'
        AUTORIZAR = 'autorizar', 'Autorizar'
        LOGIN = 'login', 'Login'
        IMPERSONAR = 'impersonar', 'Impersonar'

    # PK compuesta (id, fecha_hora): requisito de PostgreSQL para tablas
    # particionadas por rango de fecha (la columna de partición debe formar
    # parte de toda clave única/primaria).
    pk = models.CompositePrimaryKey('id', 'fecha_hora')
    # BigIntegerField y no BigAutoField: un AutoField exige primary_key=True
    # en sí mismo (fields.E100), pero eso chocaría con la PK compuesta de
    # arriba (models.E026, solo puede haber un campo primary_key=True). El
    # modelo es managed=False de todas formas: Django nunca genera el DDL de
    # esta columna; en la base real es "BIGINT GENERATED ALWAYS AS IDENTITY".
    id = models.BigIntegerField()
    tenant_id = models.BigIntegerField()
    usuario_id = models.BigIntegerField(null=True, blank=True)
    usuario_plataforma_id = models.BigIntegerField(null=True, blank=True)
    sede_id = models.BigIntegerField(null=True, blank=True)
    entidad = models.CharField(max_length=60)
    entidad_id = models.BigIntegerField(null=True, blank=True)
    accion = models.CharField(max_length=20, choices=AccionAuditoria.choices)
    # JSONB y no columnas fijas: audita entidades heterogéneas con un solo esquema.
    valor_anterior = models.JSONField(null=True, blank=True)
    valor_nuevo = models.JSONField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    fecha_hora = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'auditoria'

    def __str__(self):
        return f'{self.get_accion_display()} sobre {self.entidad}#{self.entidad_id}'


class VistaMembresiaEstado(models.Model):
    """Refleja la vista ``v_membresias_estado``: estado derivado de cada
    membresía (RF-16). No se persiste para que no dependa de que un proceso
    nocturno haya corrido; el estado sale de comparar fecha_fin contra
    CURRENT_DATE y contra dias_aviso_vencimiento del tenant.
    """

    class EstadoCalculado(models.TextChoices):
        CANCELADA = 'cancelada', 'Cancelada'
        VENCIDA = 'vencida', 'Vencida'
        VENCE_HOY = 'vence_hoy', 'Vence hoy'
        POR_VENCER = 'por_vencer', 'Por vencer'
        ACTIVA = 'activa', 'Activa'

    id = models.BigIntegerField(primary_key=True)
    tenant_id = models.BigIntegerField()
    sede_id = models.BigIntegerField()
    cliente_id = models.BigIntegerField()
    plan_id = models.BigIntegerField()
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    dias_restantes = models.IntegerField()
    estado_calculado = models.CharField(max_length=20, choices=EstadoCalculado.choices)

    class Meta:
        managed = False
        db_table = 'v_membresias_estado'

    def __str__(self):
        return f'Membresía {self.id}: {self.estado_calculado}'


class VistaVentaSaldo(models.Model):
    """Refleja la vista ``v_ventas_saldo``: saldo pendiente por venta (RF-09).
    Base de la cartera y del panel de check-in.
    """

    venta_id = models.BigIntegerField(primary_key=True)
    tenant_id = models.BigIntegerField()
    sede_id = models.BigIntegerField()
    cliente_id = models.BigIntegerField(null=True, blank=True)
    fecha_hora = models.DateTimeField()
    total = models.DecimalField(max_digits=12, decimal_places=2)
    total_pagado = models.DecimalField(max_digits=12, decimal_places=2)
    saldo = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        managed = False
        db_table = 'v_ventas_saldo'

    def __str__(self):
        return f'Saldo de venta {self.venta_id}: {self.saldo}'


class VistaCorteDiario(models.Model):
    """Refleja la vista ``v_corte_diario``: corte diario por sede (RF-08),
    calculado sobre caja real (pagos + ingresos_otros).
    """

    pk = models.CompositePrimaryKey('tenant_id', 'sede_id', 'fecha')
    tenant_id = models.BigIntegerField()
    sede_id = models.BigIntegerField()
    fecha = models.DateField()
    ingreso_ventas = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    ingreso_otros = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    efectivo = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    transferencia = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    tarjeta = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    total_recibido = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'v_corte_diario'

    def __str__(self):
        return f'Corte {self.fecha} — sede {self.sede_id}'
