"""
App plataforma — sección 04 del esquema.

Tablas del PROVEEDOR del SaaS. No llevan tenant_id: quedan fuera de las
políticas RLS de tenant (esas se aplican solo a partir de sedes en adelante).
"""
from django.db import models
from django.db.models import Func
from django.db.models.functions import Lower


class PlanSuscripcion(models.Model):
    """Plan que el proveedor renta a los gimnasios. El cobro es por sede (decisión 13)."""

    class CicloSuscripcion(models.TextChoices):
        MENSUAL = 'mensual', 'Mensual'
        ANUAL = 'anual', 'Anual'

    nombre = models.CharField(max_length=80, unique=True)
    precio_por_sede = models.DecimalField(max_digits=12, decimal_places=2)
    ciclo = models.CharField(
        max_length=20, choices=CicloSuscripcion.choices, db_default=CicloSuscripcion.MENSUAL,
    )
    # NULL = ilimitado.
    max_sedes = models.SmallIntegerField(null=True, blank=True)
    max_usuarios = models.SmallIntegerField(null=True, blank=True)
    max_clientes_activos = models.IntegerField(null=True, blank=True)
    max_almacenamiento_mb = models.IntegerField(null=True, blank=True)
    # Feature flags por plan: {"biometria": true, "rutinas": false, ...}. JSONB
    # para no migrar el esquema cada vez que se agrega un módulo.
    caracteristicas = models.JSONField(db_default={})
    activo = models.BooleanField(db_default=True)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    # No auto_now: el valor lo mantiene el trigger tg_planes_suscripcion_actualizado
    # (fn_set_actualizado_en), creado en apps.core migración 0001.
    actualizado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'planes_suscripcion'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(precio_por_sede__gte=0),
                name='ck_planes_susc_precio',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(max_sedes__gt=0) | models.Q(max_sedes__isnull=True)
                ) & (
                    models.Q(max_usuarios__gt=0) | models.Q(max_usuarios__isnull=True)
                ) & (
                    models.Q(max_clientes_activos__gt=0) | models.Q(max_clientes_activos__isnull=True)
                ),
                name='ck_planes_susc_limites',
            ),
        ]

    def __str__(self):
        return self.nombre


class Tenant(models.Model):
    """Cada gimnasio contratante. Raíz del aislamiento de datos."""

    class EstadoTenant(models.TextChoices):
        PRUEBA = 'prueba', 'Prueba'
        ACTIVO = 'activo', 'Activo'
        MORA = 'mora', 'Mora'
        SUSPENDIDO = 'suspendido', 'Suspendido'
        CANCELADO = 'cancelado', 'Cancelado'

    # PK BIGINT y no UUID: se replica como tenant_id en todas las tablas de
    # negocio; 8 bytes contra 16 reduce a la mitad el tamaño de cada índice
    # compuesto.
    uuid_publico = models.UUIDField(
        unique=True,
        editable=False,
        db_default=Func(function='gen_random_uuid'),
        help_text='Identificador expuesto en API y URLs; evita enumerar tenants por id secuencial.',
    )
    nombre_comercial = models.CharField(max_length=150)
    nit = models.CharField(max_length=30, null=True, blank=True)
    # CITEXT -> CharField + unicidad funcional (regla 4).
    subdominio = models.CharField(max_length=41)
    responsable = models.CharField(max_length=150)
    correo = models.CharField(max_length=254)
    telefono = models.CharField(max_length=30, null=True, blank=True)
    ciudad = models.CharField(max_length=100, null=True, blank=True)
    logo_url = models.TextField(null=True, blank=True)
    estado = models.CharField(
        max_length=20, choices=EstadoTenant.choices, db_default=EstadoTenant.PRUEBA,
    )
    zona_horaria = models.CharField(max_length=50, db_default='America/Bogota')
    moneda = models.CharField(max_length=3, db_default='COP')
    dias_aviso_vencimiento = models.SmallIntegerField(db_default=5)
    minutos_antipassback = models.SmallIntegerField(db_default=60)
    fecha_alta = models.DateField(db_default=Func(function='CURRENT_DATE', template='%(function)s'))
    fecha_cancelacion = models.DateField(null=True, blank=True)
    # Día 91 tras la cancelación (retención 30+60, RF-21). Un job elimina el
    # tenant en esta fecha.
    fecha_purga_datos = models.DateField(null=True, blank=True)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    # No auto_now: el valor lo mantiene el trigger tg_tenants_actualizado
    # (fn_set_actualizado_en), creado en apps.core migración 0001.
    actualizado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'tenants'
        constraints = [
            models.UniqueConstraint(Lower('subdominio'), name='uq_tenants_subdominio'),
            models.CheckConstraint(
                condition=models.Q(subdominio__regex=r'^[a-z0-9][a-z0-9-]{1,40}$'),
                name='ck_tenants_subdominio',
            ),
            models.CheckConstraint(
                condition=models.Q(dias_aviso_vencimiento__gte=0, dias_aviso_vencimiento__lte=60),
                name='ck_tenants_dias_aviso',
            ),
            models.CheckConstraint(
                condition=models.Q(minutos_antipassback__gte=0, minutos_antipassback__lte=1440),
                name='ck_tenants_antipass',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(fecha_purga_datos__isnull=True)
                    | (
                        models.Q(fecha_cancelacion__isnull=False)
                        & models.Q(fecha_purga_datos__gt=models.F('fecha_cancelacion'))
                    )
                ),
                name='ck_tenants_purga',
            ),
        ]

    def __str__(self):
        return self.nombre_comercial


class Suscripcion(models.Model):
    """Contrato vigente de un tenant con un plan de suscripción."""

    class EstadoSuscripcion(models.TextChoices):
        VIGENTE = 'vigente', 'Vigente'
        MORA = 'mora', 'Mora'
        CANCELADA = 'cancelada', 'Cancelada'

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='suscripciones',
    )
    plan_suscripcion = models.ForeignKey(
        PlanSuscripcion, on_delete=models.PROTECT, db_column='plan_suscripcion_id',
        related_name='suscripciones',
    )
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(null=True, blank=True)
    proximo_corte = models.DateField()
    dias_gracia = models.SmallIntegerField(db_default=5)
    estado = models.CharField(
        max_length=20, choices=EstadoSuscripcion.choices, db_default=EstadoSuscripcion.VIGENTE,
    )
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    # No auto_now: el valor lo mantiene el trigger tg_suscripciones_actualizado
    # (fn_set_actualizado_en), creado en apps.core migración 0001.
    actualizado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'suscripciones'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fecha_fin__isnull=True) | models.Q(fecha_fin__gte=models.F('fecha_inicio')),
                name='ck_suscripciones_fechas',
            ),
            models.CheckConstraint(
                condition=models.Q(dias_gracia__gte=0, dias_gracia__lte=90),
                name='ck_suscripciones_gracia',
            ),
            # Un tenant no puede tener dos suscripciones vigentes al mismo tiempo.
            models.UniqueConstraint(
                fields=['tenant'],
                condition=models.Q(estado='vigente'),
                name='uq_suscripciones_vigente',
            ),
        ]
        indexes = [
            models.Index(
                fields=['proximo_corte'],
                condition=~models.Q(estado='cancelada'),
                name='ix_suscripciones_corte',
            ),
        ]

    def __str__(self):
        return f'Suscripción {self.tenant} — {self.plan_suscripcion}'


class FacturaSuscripcion(models.Model):
    """Factura periódica que el proveedor emite a un tenant por su suscripción."""

    class EstadoFactura(models.TextChoices):
        EMITIDA = 'emitida', 'Emitida'
        PAGADA = 'pagada', 'Pagada'
        ANULADA = 'anulada', 'Anulada'

    suscripcion = models.ForeignKey(
        Suscripcion, on_delete=models.PROTECT, db_column='suscripcion_id', related_name='facturas',
    )
    periodo_inicio = models.DateField()
    periodo_fin = models.DateField()
    sedes_facturadas = models.SmallIntegerField()
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    estado = models.CharField(
        max_length=20, choices=EstadoFactura.choices, db_default=EstadoFactura.EMITIDA,
    )
    fecha_emision = models.DateField(db_default=Func(function='CURRENT_DATE', template='%(function)s'))
    fecha_pago = models.DateField(null=True, blank=True)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'facturas_suscripcion'
        constraints = [
            models.UniqueConstraint(
                fields=['suscripcion', 'periodo_inicio'], name='uq_facturas_periodo',
            ),
            models.CheckConstraint(
                condition=models.Q(periodo_fin__gt=models.F('periodo_inicio')),
                name='ck_facturas_periodo',
            ),
            models.CheckConstraint(condition=models.Q(monto__gte=0), name='ck_facturas_monto'),
            models.CheckConstraint(
                condition=models.Q(sedes_facturadas__gt=0), name='ck_facturas_sedes',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(estado='pagada', fecha_pago__isnull=False)
                    | (~models.Q(estado='pagada') & models.Q(fecha_pago__isnull=True))
                ),
                name='ck_facturas_pago',
            ),
        ]

    def __str__(self):
        return f'Factura {self.pk} — {self.suscripcion}'


class UsuarioPlataforma(models.Model):
    """Personal del proveedor (soporte/administración), no del gimnasio."""

    class RolPlataforma(models.TextChoices):
        ADMINISTRADOR = 'administrador', 'Administrador'
        SOPORTE = 'soporte', 'Soporte'

    nombre = models.CharField(max_length=150)
    # CITEXT + UNIQUE global (no está limitado por tenant: es personal del proveedor).
    correo = models.CharField(max_length=254)
    password_hash = models.TextField()
    rol = models.CharField(max_length=20, choices=RolPlataforma.choices)
    activo = models.BooleanField(db_default=True)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    # No auto_now: el valor lo mantiene el trigger tg_usuarios_plataforma_actualizado
    # (fn_set_actualizado_en), creado en apps.core migración 0001.
    actualizado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'usuarios_plataforma'
        constraints = [
            models.UniqueConstraint(Lower('correo'), name='uq_usuarios_plataforma_correo'),
        ]

    def __str__(self):
        return self.nombre


class Impersonacion(models.Model):
    """RF-20: el soporte solo entra con autorización del tenant y queda registrado.

    La tabla es visible para el tenant, por eso el motivo es obligatorio.
    """

    usuario_plataforma = models.ForeignKey(
        UsuarioPlataforma, on_delete=models.PROTECT, db_column='usuario_plataforma_id',
        related_name='impersonaciones',
    )
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='impersonaciones',
    )
    motivo = models.TextField()
    autorizado_por = models.CharField(max_length=150)
    inicio = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    fin = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'impersonaciones'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fin__isnull=True) | models.Q(fin__gte=models.F('inicio')),
                name='ck_imperson_fin',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', '-inicio'], name='ix_imperson_tenant'),
        ]

    def __str__(self):
        return f'Impersonación de {self.tenant} por {self.usuario_plataforma}'
