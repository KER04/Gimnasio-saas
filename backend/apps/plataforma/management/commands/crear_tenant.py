"""Comando de arranque de un tenant nuevo (Parte D).

    python manage.py crear_tenant --nombre "Gimnasio X" --subdominio gimx \
        --correo admin@gimx.com --password <clave> --sede "Sede Principal"

Crea, en una sola transacción:

1. El ``Tenant``.
2. Una ``Sede`` y su fila en ``secuencias_comprobantes``.
3. Los 4 roles del sistema (``es_sistema=True``): administrador,
   administrador_sede, recepcionista, entrenador.
4. La asignación de permisos a esos roles (§2.1 de los requisitos).
5. Semillas base (RF-17): categorías de producto, categorías de ingreso
   (RF-07), categorías de gasto y grupos musculares.
6. El usuario administrador (``es_staff=True``, ``es_superusuario=True``,
   rol ``administrador``), para que además de la API pueda entrar al admin.
7. La asignación de ese usuario a la sede recién creada.

## Por qué todo se hace por la conexión 'ddl'

Este comando corre fuera de cualquier petición HTTP: no hay
``TenantMiddleware`` que abra una transacción con ``app.tenant_id`` fijado.
'ddl' es la conexión de superusuario (``postgres``) reservada para DDL y
sembrado (ver settings/base.py); un superusuario de PostgreSQL ignora RLS
incluso con FORCE ROW LEVEL SECURITY, así que puede insertar libremente en
las tablas de negocio sin necesitar ningún tenant fijado de antemano. Aun
así se envuelve todo en ``tenant_context`` (inocuo aquí, ver el docstring de
``apps.core.tenant.tenant_context``) para dejar explícito bajo qué tenant se
siembra cada fila y para que el mismo código sirva, sin cambios, si algún
día se ejecutase por una conexión sin privilegios de superusuario.

## Idempotencia

No es idempotente en el sentido de "se puede correr dos veces con los
mismos argumentos y no pasa nada": el segundo intento con el mismo
``--subdominio`` falla limpio (``CommandError``) porque el subdominio ya
existe -- nunca deja una fila a medias ni un tenant duplicado.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.db.utils import DataError

from apps.core.tenant import tenant_context
from apps.entrenamiento.models import GrupoMuscular
from apps.inventario.models import CategoriaProducto
from apps.organizacion.models import Permiso, Rol, RolPermiso, SecuenciaComprobante, Sede, UsuarioSede
from apps.plataforma.models import Tenant
from apps.ventas.models import CategoriaGasto, CategoriaIngreso

Usuario = get_user_model()

# ---------------------------------------------------------------------------
# Semillas (RF-17 y §2.1 de los requisitos)
# ---------------------------------------------------------------------------

# Los 4 roles del sistema, en el orden en que se crean.
ROLES_SISTEMA = ('administrador', 'administrador_sede', 'recepcionista', 'entrenador')

# Catálogo completo (19 permisos, sección 19 del .sql / apps.core migración 0001).
TODOS_LOS_PERMISOS = (
    'clientes.ver', 'clientes.gestionar', 'clientes.biometria',
    'ventas.registrar', 'ventas.anular', 'ventas.descuento',
    'inventario.ver', 'inventario.gestionar',
    'costos.ver', 'gastos.gestionar',
    'reportes.ver', 'reportes.exportar',
    'membresias.gestionar',
    'asistencia.autorizar',
    'medidas.gestionar', 'rutinas.gestionar',
    'config.sedes', 'config.usuarios', 'config.planes',
)
assert len(TODOS_LOS_PERMISOS) == 19

# Permisos por rol (§2.1). Decisiones de interpretación, documentadas porque
# los requisitos solo detallan EXPLÍCITAMENTE la exclusión del recepcionista:
#
# - administrador (dueño): los 19, sin excepción -- "todas las sedes...
#   configuración, sedes, usuarios, precios, reportes consolidados, costos y
#   utilidad".
# - administrador_sede: todo lo operativo de SU sede, salvo config.sedes y
#   config.usuarios -- la tabla de §2.1 reserva "sedes" y "usuarios"
#   explícitamente a la fila del dueño/administrador, no a la del
#   administrador de sede.
# - recepcionista: "Registrar clientes, vender, cobrar abonos, check-in. Sin
#   acceso a costos ni utilidad" -- la única exclusión que el encargo pide
#   verificar EXPLÍCITAMENTE es costos.ver/gastos.gestionar (cumplida aquí).
#   Se excluyen además las operaciones de mayor autorización (anular ventas,
#   aplicar descuentos, gestionar inventario/planes/exportar reportes) por
#   ser, en cualquier separación de funciones de un POS, atribuciones de un
#   perfil superior al de caja -- no hay una tabla explícita en los
#   requisitos que las asigne al recepcionista.
# - entrenador: "Ficha de medidas, catálogo de ejercicios, rutinas y
#   progreso" + ver clientes (para poder atenderlos).
PERMISOS_POR_ROL = {
    'administrador': TODOS_LOS_PERMISOS,
    'administrador_sede': tuple(
        codigo for codigo in TODOS_LOS_PERMISOS
        if codigo not in ('config.sedes', 'config.usuarios')
    ),
    'recepcionista': (
        'clientes.ver', 'clientes.gestionar', 'clientes.biometria',
        'ventas.registrar',
        'inventario.ver',
        'membresias.gestionar',
        'asistencia.autorizar',
        'reportes.ver',
    ),
    'entrenador': (
        'clientes.ver',
        'medidas.gestionar', 'rutinas.gestionar',
    ),
}

# RF-07: subcategorías de venta de productos, de planes, entrenamiento
# personalizado y otros ingresos manuales.
CATEGORIAS_INGRESO = (
    ('Productos', 'Bebidas'),
    ('Productos', 'Suplementos'),
    ('Productos', 'Accesorios'),
    ('Productos', 'Otros'),
    ('Planes', 'Mensual'),
    ('Planes', 'Quincenal'),
    ('Planes', 'Por sesión'),
    ('Entrenamiento personalizado', None),
    ('Otros ingresos', None),
)

CATEGORIAS_PRODUCTO = ('Bebidas', 'Suplementos', 'Accesorios', 'Otros')

# RF-24: "arriendo, nómina, servicios públicos, compra de mercancía,
# mantenimiento, otros".
CATEGORIAS_GASTO = (
    'Arriendo', 'Nómina', 'Servicios públicos',
    'Compra de mercancía', 'Mantenimiento', 'Otros',
)

# RF-12: "pecho, espalda, pierna, hombro, brazo, core, cardio".
GRUPOS_MUSCULARES = ('Pecho', 'Espalda', 'Pierna', 'Hombro', 'Brazo', 'Core', 'Cardio')


class Command(BaseCommand):
    help = (
        'Crea un tenant nuevo, listo para usar: sede, roles del sistema con '
        'sus permisos, semillas base (RF-17) y el usuario administrador '
        '(con acceso al admin de Django).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--nombre', required=True, help='Nombre comercial del gimnasio.')
        parser.add_argument('--subdominio', required=True, help='Subdominio único (minúsculas).')
        parser.add_argument('--correo', required=True, help='Correo del usuario administrador.')
        parser.add_argument('--password', required=True, help='Contraseña del usuario administrador.')
        parser.add_argument(
            '--sede', default='Sede Principal',
            help='Nombre de la primera sede (por defecto "Sede Principal").',
        )

    def handle(self, *args, **options):
        nombre = options['nombre'].strip()
        subdominio = options['subdominio'].strip().lower()
        correo = options['correo'].strip().lower()
        password = options['password']
        nombre_sede = options['sede'].strip()

        if Tenant.objects.using('ddl').filter(subdominio__iexact=subdominio).exists():
            raise CommandError(
                f'Ya existe un tenant con el subdominio "{subdominio}". '
                'Elige otro o borra el tenant existente antes de reintentar.'
            )

        try:
            with transaction.atomic(using='ddl'):
                tenant = Tenant.objects.using('ddl').create(
                    nombre_comercial=nombre,
                    subdominio=subdominio,
                    responsable=nombre,
                    correo=correo,
                )

                with tenant_context(tenant.id, using='ddl'):
                    sede = Sede.objects.using('ddl').create(
                        tenant=tenant, nombre=nombre_sede, direccion='Por definir',
                    )
                    SecuenciaComprobante.objects.using('ddl').create(sede=sede, tenant=tenant)

                    roles = {
                        nombre_rol: Rol.objects.using('ddl').create(
                            tenant=tenant, nombre=nombre_rol, es_sistema=True,
                        )
                        for nombre_rol in ROLES_SISTEMA
                    }

                    permisos_por_codigo = {
                        permiso.codigo: permiso
                        for permiso in Permiso.objects.using('ddl').all()
                    }
                    faltantes = set(TODOS_LOS_PERMISOS) - set(permisos_por_codigo)
                    if faltantes:
                        raise CommandError(
                            f'Faltan permisos en el catálogo global: {sorted(faltantes)}. '
                            '¿Se aplicó la migración de apps.core (siembra de `permisos`)?'
                        )

                    total_asignaciones = 0
                    for nombre_rol, codigos in PERMISOS_POR_ROL.items():
                        RolPermiso.objects.using('ddl').bulk_create([
                            RolPermiso(
                                rol=roles[nombre_rol],
                                permiso=permisos_por_codigo[codigo],
                                tenant=tenant,
                            )
                            for codigo in codigos
                        ])
                        total_asignaciones += len(codigos)

                    for nombre_categoria in CATEGORIAS_PRODUCTO:
                        CategoriaProducto.objects.using('ddl').create(
                            tenant=tenant, nombre=nombre_categoria,
                        )

                    for nombre_cat, subcategoria in CATEGORIAS_INGRESO:
                        CategoriaIngreso.objects.using('ddl').create(
                            tenant=tenant, nombre=nombre_cat, subcategoria=subcategoria,
                            es_sistema=True,
                        )

                    for nombre_categoria in CATEGORIAS_GASTO:
                        CategoriaGasto.objects.using('ddl').create(
                            tenant=tenant, nombre=nombre_categoria,
                        )

                    for orden, nombre_grupo in enumerate(GRUPOS_MUSCULARES):
                        GrupoMuscular.objects.using('ddl').create(
                            tenant=tenant, nombre=nombre_grupo, orden=orden,
                        )

                    usuario_admin = Usuario.objects.db_manager('ddl').create_superuser(
                        correo=correo,
                        nombre=f'Administrador de {nombre}',
                        tenant=tenant,
                        rol=roles['administrador'],
                        password=password,
                    )

                    UsuarioSede.objects.using('ddl').create(
                        usuario=usuario_admin, sede=sede, tenant=tenant,
                    )
        except (IntegrityError, DataError) as exc:
            raise CommandError(f'No se pudo crear el tenant: {exc}') from exc

        url_admin = f'http://{subdominio}.localhost:8000/admin/'
        self.stdout.write(self.style.SUCCESS(
            f'Tenant "{nombre}" creado correctamente (id={tenant.id}, subdominio="{subdominio}").'
        ))
        self.stdout.write(f'  Sede:               {sede.nombre} (id={sede.id})')
        self.stdout.write(f'  Roles del sistema:  {", ".join(roles)}')
        self.stdout.write(f'  Permisos asignados: {total_asignaciones}')
        self.stdout.write(
            f'  Semillas:           {len(CATEGORIAS_PRODUCTO)} categorías de producto, '
            f'{len(CATEGORIAS_INGRESO)} categorías de ingreso, '
            f'{len(CATEGORIAS_GASTO)} categorías de gasto, '
            f'{len(GRUPOS_MUSCULARES)} grupos musculares.'
        )
        self.stdout.write(f'  Usuario admin:      {usuario_admin.correo} (rol administrador, es_staff=True)')
        self.stdout.write(self.style.SUCCESS(f'  Admin de Django:    {url_admin}'))
