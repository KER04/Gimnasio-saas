"""
App clientes — sección 07 del esquema: clientes y datos biométricos.
"""
from django.db import models
from django.db.models import Func

from apps.organizacion.models import Sede
from apps.plataforma.models import Tenant


class Cliente(models.Model):
    """Personas que entrenan. No tienen acceso al software (§2.1): no hay
    password ni cuenta.
    """

    class Sexo(models.TextChoices):
        MASCULINO = 'M', 'Masculino'
        FEMENINO = 'F', 'Femenino'
        OTRO = 'O', 'Otro'

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='clientes',
    )
    sede_origen = models.ForeignKey(
        Sede, on_delete=models.PROTECT, db_column='sede_origen_id', related_name='clientes_origen',
    )
    nombre = models.CharField(max_length=150)
    # Única DENTRO del tenant. Nunca global: la misma persona puede estar
    # inscrita en dos gimnasios que sean clientes del SaaS (RF-03).
    cedula = models.CharField(max_length=20)
    telefono = models.CharField(max_length=30)
    direccion = models.CharField(max_length=200)
    sexo = models.CharField(max_length=1, choices=Sexo.choices, null=True, blank=True)
    fecha_registro = models.DateField(db_default=Func(function='CURRENT_DATE', template='%(function)s'))
    activo = models.BooleanField(db_default=True)
    # Borrado lógico. Nunca se hace DELETE: rompería el histórico de ventas.
    eliminado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    # No auto_now: el valor lo mantiene el trigger tg_clientes_actualizado
    # (fn_set_actualizado_en), creado en apps.core migración 0001.
    actualizado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'clientes'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_clientes_id_tenant'),
            models.UniqueConstraint(fields=['tenant', 'cedula'], name='uq_clientes_cedula'),
            models.CheckConstraint(
                condition=models.Q(sexo__isnull=True) | models.Q(sexo__in=['M', 'F', 'O']),
                name='ck_clientes_sexo',
            ),
            models.CheckConstraint(
                condition=models.Q(cedula__regex=r'^[0-9A-Za-z.-]{4,20}$'),
                name='ck_clientes_cedula',
            ),
        ]
        indexes = [
            # Búsqueda por cédula desde el mostrador: el caso de uso más frecuente.
            models.Index(
                fields=['tenant', 'cedula'],
                condition=models.Q(eliminado_en__isnull=True),
                name='ix_clientes_cedula',
            ),
            models.Index(
                fields=['tenant'],
                condition=models.Q(activo=True, eliminado_en__isnull=True),
                name='ix_clientes_activos',
            ),
            # GIN trigram -> va en RunSQL:
            # CREATE INDEX ix_clientes_nombre_trgm ON clientes USING GIN (nombre gin_trgm_ops);
        ]

    def __str__(self):
        return f'{self.nombre} ({self.cedula})'


class AutorizacionDatos(models.Model):
    """Ley 1581 de 2012. La autorización biométrica es independiente de la de
    datos generales: el cliente puede aceptar una y negar la otra, y el
    sistema debe permitir su ingreso igual (RF-15, casos alternos).
    """

    class TipoAutorizacion(models.TextChoices):
        TRATAMIENTO_DATOS = 'tratamiento_datos', 'Tratamiento de datos'
        BIOMETRIA = 'biometria', 'Biometría'

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='autorizaciones_datos',
    )
    cliente = models.ForeignKey(
        Cliente, on_delete=models.CASCADE, db_column='cliente_id', related_name='autorizaciones',
    )
    tipo = models.CharField(max_length=20, choices=TipoAutorizacion.choices)
    otorgada = models.BooleanField()
    fecha = models.DateField(db_default=Func(function='CURRENT_DATE', template='%(function)s'))
    archivo_firmado_url = models.TextField(null=True, blank=True)
    revocada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'autorizaciones_datos'
        constraints = [
            models.UniqueConstraint(fields=['cliente', 'tipo'], name='uq_autoriz_cliente_tipo'),
        ]

    def __str__(self):
        return f'{self.cliente} — {self.get_tipo_display()}'


class HuellaCliente(models.Model):
    """Dato sensible bajo la Ley 1581. Se almacena la PLANTILLA, nunca la
    imagen. ON DELETE CASCADE es intencional aquí, a diferencia del resto del
    modelo: al eliminar un cliente la plantilla debe desaparecer, no
    conservarse.
    """

    class DedoHuella(models.TextChoices):
        INDICE_IZQUIERDO = 'indice_izquierdo', 'Índice izquierdo'
        INDICE_DERECHO = 'indice_derecho', 'Índice derecho'
        PULGAR_IZQUIERDO = 'pulgar_izquierdo', 'Pulgar izquierdo'
        PULGAR_DERECHO = 'pulgar_derecho', 'Pulgar derecho'
        MEDIO_IZQUIERDO = 'medio_izquierdo', 'Medio izquierdo'
        MEDIO_DERECHO = 'medio_derecho', 'Medio derecho'

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='huellas_clientes',
    )
    cliente = models.ForeignKey(
        Cliente, on_delete=models.CASCADE, db_column='cliente_id', related_name='huellas',
    )
    dedo = models.CharField(max_length=20, choices=DedoHuella.choices)
    # Cifrada en la aplicación antes de llegar a la base de datos. La base
    # nunca ve el valor en claro; una copia de seguridad filtrada no expone
    # biometría.
    plantilla_cifrada = models.BinaryField()
    calidad = models.SmallIntegerField()
    # Formato propietario del SDK. Documentado porque un cambio de marca de
    # lector obliga a reenrolar a todos los clientes.
    formato = models.CharField(max_length=30, db_default='ZKFinger10')
    fecha_captura = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'huellas_clientes'
        constraints = [
            models.UniqueConstraint(fields=['cliente', 'dedo'], name='uq_huellas_cliente_dedo'),
            models.CheckConstraint(
                condition=models.Q(calidad__gte=0, calidad__lte=100), name='ck_huellas_calidad',
            ),
        ]
        indexes = [
            models.Index(fields=['cliente'], name='ix_huellas_cliente'),
        ]

    def __str__(self):
        return f'Huella {self.get_dedo_display()} de {self.cliente}'


class DispositivoBiometrico(models.Model):
    """Lector biométrico instalado en una sede."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='dispositivos_biometricos',
    )
    sede = models.ForeignKey(
        Sede, on_delete=models.CASCADE, db_column='sede_id', related_name='dispositivos_biometricos',
    )
    nombre = models.CharField(max_length=80)
    identificador = models.CharField(max_length=120)
    modelo = models.CharField(max_length=60, db_default='ZKTeco ZK9500')
    # Hash del token del agente local, nunca el token en claro: el agente
    # descarga plantillas biométricas y su credencial no puede quedar legible
    # en la base.
    token_hash = models.TextField()
    activo = models.BooleanField(db_default=True)
    ultima_sincronizacion = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'dispositivos_biometricos'
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'identificador'], name='uq_dispositivos_ident'),
        ]

    def __str__(self):
        return f'{self.nombre} ({self.sede})'
