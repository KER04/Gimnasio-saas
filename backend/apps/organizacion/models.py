"""
App organizacion — secciones 05 y 06 del esquema.

A partir de aquí toda tabla lleva tenant_id (convertido a FK simple, regla 2).

Patrón de integridad multi-tenant del .sql: cada tabla padre declara
UNIQUE (id, tenant_id) — redundante como clave, pero permite que las hijas
referencien (padre_id, tenant_id) con una FK COMPUESTA. Django no soporta FK
compuestas nativamente, así que aquí solo se modela la FK simple por id y se
conserva el UNIQUE (id, tenant) para que la FK compuesta real se añada
después por RunSQL (ver lista de pendientes del informe).
"""
import logging

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models import Func
from django.db.models.functions import Lower

from apps.plataforma.models import Tenant

logger = logging.getLogger(__name__)


class Sede(models.Model):
    """Sede física de un gimnasio (tenant)."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='sedes',
    )
    nombre = models.CharField(max_length=120)
    direccion = models.CharField(max_length=200)
    telefono = models.CharField(max_length=30, null=True, blank=True)
    nit = models.CharField(max_length=30, null=True, blank=True)
    logo_url = models.TextField(null=True, blank=True)
    encabezado_recibo = models.TextField(null=True, blank=True)
    prefijo_comprobante = models.CharField(max_length=10, db_default='F')
    activa = models.BooleanField(db_default=True)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    # No auto_now: el valor lo mantiene el trigger tg_sedes_actualizado
    # (fn_set_actualizado_en), creado en apps.core migración 0001.
    actualizado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'sedes'
        constraints = [
            # Clave compuesta destino de las FK de las tablas hijas; garantiza
            # que una fila no pueda referenciar una sede de otro tenant.
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_sedes_id_tenant'),
            models.UniqueConstraint(fields=['tenant', 'nombre'], name='uq_sedes_nombre'),
        ]
        indexes = [
            models.Index(fields=['tenant'], condition=models.Q(activa=True), name='ix_sedes_tenant'),
        ]

    def __str__(self):
        return self.nombre


class SecuenciaComprobante(models.Model):
    """Consecutivo por sede. No se usa SEQUENCE porque las secuencias de
    PostgreSQL no son transaccionales: un ROLLBACK dejaría huecos, inaceptable
    en numeración de comprobantes.
    """

    sede = models.OneToOneField(
        Sede, on_delete=models.CASCADE, db_column='sede_id', primary_key=True,
        related_name='secuencia_comprobante',
    )
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='secuencias_comprobantes',
    )
    ultimo_numero = models.BigIntegerField(db_default=0)

    class Meta:
        db_table = 'secuencias_comprobantes'
        constraints = [
            models.CheckConstraint(condition=models.Q(ultimo_numero__gte=0), name='ck_secuencias_numero'),
        ]

    def __str__(self):
        return f'Secuencia de {self.sede} (último {self.ultimo_numero})'


class Permiso(models.Model):
    """Catálogo global (sin tenant_id): lo define el proveedor, no el gimnasio."""

    codigo = models.CharField(max_length=60, unique=True)
    modulo = models.CharField(max_length=40)
    descripcion = models.CharField(max_length=200)

    class Meta:
        db_table = 'permisos'

    def __str__(self):
        return self.codigo


class Rol(models.Model):
    """Rol configurable por el dueño del gimnasio (§2.1)."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='roles',
    )
    nombre = models.CharField(max_length=60)
    descripcion = models.CharField(max_length=200, null=True, blank=True)
    # Rol sembrado al crear el tenant (dueño, admin sede, recepcionista,
    # entrenador). No se puede eliminar.
    es_sistema = models.BooleanField(db_default=False)
    activo = models.BooleanField(db_default=True)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'roles'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_roles_id_tenant'),
            models.UniqueConstraint(fields=['tenant', 'nombre'], name='uq_roles_nombre'),
        ]

    def __str__(self):
        return self.nombre


class RolPermiso(models.Model):
    """Relación N:M entre roles y permisos, resuelta con tabla puente."""

    pk = models.CompositePrimaryKey('rol', 'permiso')
    rol = models.ForeignKey(
        Rol, on_delete=models.CASCADE, db_column='rol_id', related_name='roles_permisos',
    )
    permiso = models.ForeignKey(
        Permiso, on_delete=models.CASCADE, db_column='permiso_id', related_name='roles_permisos',
    )
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='roles_permisos',
    )

    class Meta:
        db_table = 'roles_permisos'
        indexes = [
            models.Index(fields=['permiso'], name='ix_rolperm_permiso'),
        ]

    def __str__(self):
        return f'{self.rol} — {self.permiso}'


class UsuarioManager(BaseUserManager):
    """Manager del modelo de autenticación multi-tenant.

    A diferencia del manager estándar de Django (``create_user(username,
    email=None, password=None, ...)``), aquí ``tenant`` y ``rol`` son
    obligatorios: la tabla ``usuarios`` no admite NULL en ninguna de las dos
    columnas (ver ``esquema_gimnasio_postgres.sql``), y no existe un usuario
    "sin gimnasio".
    """

    use_in_migrations = True

    def _crear_usuario(self, correo, nombre, tenant, rol, password, **extra_fields):
        if not correo:
            raise ValueError('El usuario debe tener un correo.')
        if tenant is None:
            raise ValueError('El usuario debe pertenecer a un tenant.')
        if rol is None:
            raise ValueError('El usuario debe tener un rol.')
        # Igual que la restricción de base de datos: único POR TENANT
        # comparando en minúsculas (uq_usuarios_correo usa Lower(correo)).
        correo = correo.strip().lower()
        usuario = self.model(correo=correo, nombre=nombre, tenant=tenant, rol=rol, **extra_fields)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_user(self, correo, nombre, tenant, rol, password=None, **extra_fields):
        extra_fields.setdefault('es_staff', False)
        extra_fields.setdefault('es_superusuario', False)
        return self._crear_usuario(correo, nombre, tenant, rol, password, **extra_fields)

    def create_superuser(self, correo, nombre, tenant, rol, password=None, **extra_fields):
        # Parte B: a diferencia del comentario original (que asumía
        # is_staff/is_superuser siempre False), ahora SÍ son columnas reales
        # -- decisión explícita del usuario para poder dar acceso al panel de
        # Django a un usuario de tenant concreto (el "dueño" del gimnasio),
        # sin que eso lo confunda con "administrador del gimnasio" (ese
        # concepto sigue viviendo enteramente en Rol/RolPermiso). Por eso
        # ``create_superuser`` -- el único método que ``manage.py
        # createsuperuser`` conoce del manager de AUTH_USER_MODEL -- fija
        # ambos campos en True explícitamente.
        extra_fields['es_staff'] = True
        extra_fields['es_superusuario'] = True
        return self._crear_usuario(correo, nombre, tenant, rol, password, **extra_fields)


class Usuario(AbstractBaseUser):
    """Usuario operativo del gimnasio (recepcionista, entrenador, admin de
    sede...) y, a la vez, el modelo de autenticación de Django
    (``AUTH_USER_MODEL = 'organizacion.Usuario'``).

    Hereda de ``AbstractBaseUser`` (NO de ``AbstractUser`` ni de
    ``PermissionsMixin``):

    - ``AbstractUser`` trae ``username``/``first_name``/``last_name``/
      ``email``/``is_staff``/``is_superuser``/``groups``/
      ``user_permissions`` -- columnas que no existen en la tabla
      ``usuarios`` del esquema. No se añaden columnas nuevas para acomodar
      a Django (regla del encargo): el esquema manda. La ÚNICA excepción,
      documentada explícitamente, son ``es_staff``/``es_superusuario``
      (Parte B): dos columnas añadidas a propósito, por decisión del
      usuario, para separar "administrar el gimnasio" (Rol/RolPermiso) de
      "entrar al panel de Django" (estas dos columnas).
    - ``PermissionsMixin`` añade ``is_superuser`` como columna real más M2M
      a ``auth.group``/``auth.permission`` -- esas tablas de grupos/permisos
      de Django siguen sin usarse aquí; ``es_superusuario`` se declara a
      mano más abajo, no vía ``PermissionsMixin``.

    ``password`` y ``last_login`` sí vienen de ``AbstractBaseUser`` (el
    framework de auth los necesita para ``set_password``/``check_password``/
    ``update_last_login``), pero se sobrescriben aquí con ``db_column`` para
    que apunten a las columnas reales del esquema (``password_hash`` y
    ``ultimo_acceso``) en vez de crear columnas nuevas ``password``/
    ``last_login``. Django permite sobrescribir así campos heredados de una
    clase abstracta (verificado).
    """

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='usuarios',
    )
    rol = models.ForeignKey(
        Rol, on_delete=models.PROTECT, db_column='rol_id', related_name='usuarios',
    )
    nombre = models.CharField(max_length=150)
    # CITEXT -> CharField + unicidad funcional (regla 4). Único DENTRO del
    # tenant: la misma persona puede trabajar en dos gimnasios clientes. El
    # login resuelve primero el tenant (por subdominio/JWT) y después el
    # usuario dentro de ese tenant (ver apps.organizacion.backends).
    correo = models.CharField(max_length=254)
    # Sobrescribe AbstractBaseUser.password (CharField(128)) para que la
    # columna real se llame password_hash, como exige el esquema.
    password = models.TextField(db_column='password_hash')
    telefono = models.CharField(max_length=30, null=True, blank=True)
    activo = models.BooleanField(db_default=True)
    # Sobrescribe AbstractBaseUser.last_login para que la columna real se
    # llame ultimo_acceso, como exige el esquema.
    last_login = models.DateTimeField(db_column='ultimo_acceso', null=True, blank=True)
    creado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    # No auto_now: el valor lo mantiene el trigger tg_usuarios_actualizado
    # (fn_set_actualizado_en), creado en apps.core migración 0001.
    actualizado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))
    # Parte B: desviación DELIBERADA y documentada del .sql -- dos columnas
    # nuevas que el esquema original no tiene. Decisión explícita del
    # usuario: separar "ser administrador del gimnasio" (que sigue viviendo
    # enteramente en Rol/RolPermiso, sin relación con esto) de "tener acceso
    # al panel técnico de Django". Ambas son False por defecto: ningún
    # usuario de tenant entra al admin salvo que se le conceda explícitamente
    # (lo hace `crear_tenant` para el usuario administrador inicial, Parte D).
    es_staff = models.BooleanField(
        db_default=False,
        help_text=(
            'Acceso al panel de administración de Django. NO es lo mismo que '
            'ser administrador del gimnasio: se concede explícitamente.'
        ),
    )
    es_superusuario = models.BooleanField(db_default=False)

    objects = UsuarioManager()

    USERNAME_FIELD = 'correo'
    REQUIRED_FIELDS = ['nombre']

    class Meta:
        db_table = 'usuarios'
        constraints = [
            models.UniqueConstraint(fields=['id', 'tenant'], name='uq_usuarios_id_tenant'),
            models.UniqueConstraint(Lower('correo'), 'tenant', name='uq_usuarios_correo'),
        ]
        indexes = [
            models.Index(fields=['tenant'], condition=models.Q(activo=True), name='ix_usuarios_tenant'),
        ]

    def __str__(self):
        return self.nombre

    @property
    def is_active(self):
        # AbstractBaseUser no declara is_active (lo declara AbstractUser, que
        # no usamos), pero el framework de auth lo necesita (p. ej.
        # ModelBackend.user_can_authenticate). La columna real se llama
        # `activo`: se expone como propiedad de solo lectura en vez de
        # duplicar el campo.
        return self.activo

    @property
    def is_staff(self):
        # Parte B: expone la columna real `es_staff` bajo el nombre que
        # espera el framework de auth/admin de Django. Antes esto era
        # siempre False (el admin no era para usuarios de tenant); ahora es
        # una concesión explícita por usuario -- normalmente solo el
        # administrador del gimnasio creado por `crear_tenant` (Parte D).
        return self.es_staff

    @property
    def is_superuser(self):
        # Ídem que is_staff, expone `es_superusuario`.
        return self.es_superusuario

    def has_perm(self, perm, obj=None):
        # Un superusuario de tenant lo puede todo dentro del admin (igual que
        # el superusuario clásico de Django). Para un usuario `es_staff` sin
        # `es_superusuario` no existe (todavía) un mapeo entre los permisos
        # de negocio (Permiso/RolPermiso, que gobiernan la API) y los
        # codenames de `django.contrib.auth` -- construir ese mapeo es un
        # esfuerzo aparte, fuera de esta etapa. Mientras tanto, cualquier
        # usuario con acceso al admin (`es_staff=True`) puede operar todo lo
        # que el admin expone: es la única forma de que el admin sea
        # utilizable sin ese mapeo, y sigue estando acotado por RLS/tenant
        # (Parte C1) y por que `es_staff` NUNCA se concede por defecto.
        return self.es_superusuario or self.es_staff

    def has_module_perms(self, app_label):
        return self.es_superusuario or self.es_staff


class UsuarioSede(models.Model):
    """Un usuario opera en una o varias sedes: relación N:M."""

    pk = models.CompositePrimaryKey('usuario', 'sede')
    usuario = models.ForeignKey(
        Usuario, on_delete=models.CASCADE, db_column='usuario_id', related_name='usuarios_sedes',
    )
    sede = models.ForeignKey(
        Sede, on_delete=models.CASCADE, db_column='sede_id', related_name='usuarios_sedes',
    )
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, db_column='tenant_id', related_name='usuarios_sedes',
    )
    asignado_en = models.DateTimeField(db_default=Func(function='clock_timestamp'))

    class Meta:
        db_table = 'usuarios_sedes'
        indexes = [
            models.Index(fields=['sede'], name='ix_usrsede_sede'),
        ]

    def __str__(self):
        return f'{self.usuario} en {self.sede}'
