"""
App asistencia — sección 12 del esquema (RF-15).
"""
from django.db import models
from django.db.models import Func

from apps.clientes.models import Cliente, DispositivoBiometrico
from apps.organizacion.models import Sede, Usuario
from apps.plataforma.models import Tenant
from apps.ventas.models import Venta


class Asistencia(models.Model):
    """Registro de ingreso al gimnasio.

    No referencia una membresía concreta: un cliente puede tener varias
    activas (decisión 23) y el check-in solo valida que EXISTA alguna
    vigente. Ligarla a una en particular obligaría a una decisión arbitraria
    cuando hay dos.
    """

    class MetodoAsistencia(models.TextChoices):
        HUELLA = 'huella', 'Huella'
        MANUAL_CEDULA = 'manual_cedula', 'Manual por cédula'
        SESION_ANONIMA = 'sesion_anonima', 'Sesión anónima'

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='asistencias',
    )
    sede = models.ForeignKey(
        Sede, on_delete=models.PROTECT, db_column='sede_id', related_name='asistencias',
    )
    cliente = models.ForeignKey(
        Cliente, on_delete=models.PROTECT, db_column='cliente_id', related_name='asistencias',
        null=True, blank=True,
    )
    venta = models.ForeignKey(
        Venta, on_delete=models.PROTECT, db_column='venta_id', related_name='asistencias',
        null=True, blank=True,
    )
    metodo = models.CharField(max_length=20, choices=MetodoAsistencia.choices)
    fecha_hora = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    # Se congela el resultado de la validación en el momento del ingreso.
    # Reconstruirlo después daría un resultado distinto al vencer la membresía.
    con_membresia_vigente = models.BooleanField()
    autorizado_por = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, db_column='autorizado_por',
        related_name='asistencias_autorizadas', null=True, blank=True,
    )
    motivo_autorizacion = models.TextField(null=True, blank=True)
    # El agente local encola asistencias cuando no hay internet y las envía
    # al reconectar; fecha_hora es la del hecho, sincronizado_en la de llegada.
    registrado_offline = models.BooleanField(db_default=False)
    sincronizado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'asistencias'
        constraints = [
            # Una asistencia anónima solo existe si viene de una sesión vendida.
            models.CheckConstraint(
                condition=(
                    models.Q(metodo='sesion_anonima', cliente__isnull=True, venta__isnull=False)
                    | (~models.Q(metodo='sesion_anonima') & models.Q(cliente__isnull=False))
                ),
                name='ck_asist_anonima',
            ),
            # Ingresar sin membresía vigente exige autorización nominal (decisión 12).
            models.CheckConstraint(
                condition=(
                    models.Q(con_membresia_vigente=True)
                    | models.Q(metodo='sesion_anonima')
                    | models.Q(autorizado_por__isnull=False, motivo_autorizacion__isnull=False)
                ),
                name='ck_asist_autorizacion',
            ),
        ]
        indexes = [
            # Índice del antipassback: busca la última marca del cliente en la sede.
            models.Index(
                fields=['cliente', '-fecha_hora'], condition=models.Q(cliente__isnull=False),
                name='ix_asist_cliente_fecha',
            ),
            models.Index(fields=['sede', '-fecha_hora'], name='ix_asist_sede_fecha'),
        ]

    def __str__(self):
        return f'Asistencia de {self.cliente or "anónimo"} en {self.sede}'


class IntentoBiometricoFallido(models.Model):
    """RF-15. No guarda la captura fallida — solo el hecho y su calidad —
    porque almacenar biometría de alguien no identificado no tendría base legal.
    """

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='intentos_biometricos_fallidos',
    )
    sede = models.ForeignKey(
        Sede, on_delete=models.CASCADE, db_column='sede_id', related_name='intentos_biometricos_fallidos',
    )
    dispositivo = models.ForeignKey(
        DispositivoBiometrico, on_delete=models.SET_NULL, db_column='dispositivo_id',
        related_name='intentos_fallidos', null=True, blank=True,
    )
    calidad_captura = models.SmallIntegerField(null=True, blank=True)
    fecha_hora = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'intentos_biometricos_fallidos'
        indexes = [
            models.Index(fields=['sede', '-fecha_hora'], name='ix_intfall_sede_fecha'),
        ]

    def __str__(self):
        return f'Intento fallido en {self.sede} ({self.fecha_hora})'
