"""Alta completa de un gimnasio: tenant, sede, roles, permisos y semillas.

Vivía dentro de ``crear_tenant`` (comando de consola). Se sacó aquí al añadir
el alta desde el panel del proveedor: son dos puertas a la MISMA operación, y
duplicarla habría garantizado que tarde o temprano una sembrara algo que la
otra no -- un rol de menos, una categoría de menos, y el gimnasio nace roto de
una forma que no se nota hasta semanas después.

## La conexión

``crear_tenant`` sembraba por la conexión ``ddl`` (``postgres``, superusuario)
porque corre fuera de cualquier petición: no hay middleware que fije
``app.tenant_id`` y un superusuario ignora RLS.

Desde una vista web eso sería un mal negocio: bastaría un error en esta
función para escribir en cualquier tenant saltándose el aislamiento entero.
Por eso ``conexion`` es un parámetro y el panel usa ``'default'`` (el rol de
la aplicación, sujeto a RLS): con ``tenant_context`` fijado al tenant recién
creado, la política ``WITH CHECK`` de cada INSERT se cumple sola y el
aislamiento sigue siendo el de siempre. El comando conserva ``'ddl'``, que es
lo correcto para un arranque desde consola.
"""
import secrets
import string

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.core.tenant import tenant_context
from apps.entrenamiento.models import GrupoMuscular
from apps.inventario.models import CategoriaProducto
from apps.organizacion.models import (
    Permiso,
    Rol,
    RolPermiso,
    SecuenciaComprobante,
    Sede,
    UsuarioSede,
)
from apps.plataforma.models import Tenant
from apps.ventas.models import CategoriaGasto, CategoriaIngreso

Usuario = get_user_model()


class AprovisionamientoError(Exception):
    """Fallo de negocio al dar de alta un gimnasio (catálogo incompleto...)."""


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


# Sin caracteres ambiguos (I/l/1, O/0): la contraseña se enseña una vez y se
# dicta por teléfono o se copia a mano; una "l" que parece un "1" convierte el
# alta en una llamada de soporte.
_ALFABETO_CLAVE = (
    ''.join(c for c in string.ascii_letters if c not in 'IlO')
    + ''.join(c for c in string.digits if c not in '01')
)


def generar_password(longitud=16):
    """Contraseña aleatoria para el administrador del gimnasio nuevo.

    ``secrets`` y no ``random``: este último es un generador predecible
    pensado para simulaciones, no para credenciales.
    """
    return ''.join(secrets.choice(_ALFABETO_CLAVE) for _ in range(longitud))


def aprovisionar_tenant(
    *,
    nombre,
    subdominio,
    correo_admin,
    password_admin,
    nombre_sede='Sede Principal',
    responsable=None,
    telefono=None,
    ciudad=None,
    nit=None,
    conexion='default',
    con_admin_django=False,
):
    """Crea un gimnasio listo para usar y devuelve ``(tenant, sede, usuario)``.

    Todo ocurre en UNA transacción: si algo falla no queda un gimnasio a
    medias (sin roles, sin sede o sin usuario), que sería peor que no tenerlo.

    ``con_admin_django`` concede ``es_staff``/``es_superusuario``, es decir,
    acceso a ``/admin/``. Por defecto NO: el admin de Django enseña las tablas
    en crudo y permite saltarse las validaciones de la aplicación, así que no
    es una herramienta para el cliente. Se deja como opción para arranques
    desde consola donde a veces hace falta esa puerta.

    NO valida el subdominio ni comprueba que esté libre: de eso se encargan
    quienes llaman (comando y API), cada uno con sus mensajes de error.
    """
    with transaction.atomic(using=conexion):
        tenant = Tenant.objects.using(conexion).create(
            nombre_comercial=nombre,
            subdominio=subdominio,
            responsable=responsable or nombre,
            correo=correo_admin,
            telefono=telefono,
            ciudad=ciudad,
            nit=nit,
            # Explícita: el `db_default=CURRENT_DATE` se evalúa en la
            # conexión, que va en UTC, y de noche daría la fecha de mañana
            # (ver `apps.core.fechas`). Aquí no se puede usar la zona del
            # gimnasio porque todavía no existe, así que se usa la del
            # servidor -- que es también la que el tenant tendrá por defecto.
            fecha_alta=timezone.localdate(),
        )

        # A partir de aquí todo son tablas con RLS: sin el contexto fijado,
        # la política WITH CHECK de cada INSERT rechazaría las filas (o, por
        # la conexión 'ddl', pasarían por ser superusuario -- pero entonces
        # el mismo código no serviría para ambas conexiones).
        with tenant_context(tenant.id, using=conexion):
            sede = Sede.objects.using(conexion).create(
                tenant=tenant, nombre=nombre_sede, direccion='Por definir',
            )
            SecuenciaComprobante.objects.using(conexion).create(sede=sede, tenant=tenant)

            roles = {
                nombre_rol: Rol.objects.using(conexion).create(
                    tenant=tenant, nombre=nombre_rol, es_sistema=True,
                )
                for nombre_rol in ROLES_SISTEMA
            }

            permisos_por_codigo = {
                permiso.codigo: permiso for permiso in Permiso.objects.using(conexion).all()
            }
            faltantes = set(TODOS_LOS_PERMISOS) - set(permisos_por_codigo)
            if faltantes:
                raise AprovisionamientoError(
                    f'Faltan permisos en el catálogo global: {sorted(faltantes)}. '
                    '¿Se aplicó la migración de apps.core (siembra de `permisos`)?',
                )

            for nombre_rol, codigos in PERMISOS_POR_ROL.items():
                RolPermiso.objects.using(conexion).bulk_create([
                    RolPermiso(rol=roles[nombre_rol], permiso=permisos_por_codigo[codigo], tenant=tenant)
                    for codigo in codigos
                ])

            for nombre_categoria in CATEGORIAS_PRODUCTO:
                CategoriaProducto.objects.using(conexion).create(
                    tenant=tenant, nombre=nombre_categoria,
                )

            for nombre_cat, subcategoria in CATEGORIAS_INGRESO:
                CategoriaIngreso.objects.using(conexion).create(
                    tenant=tenant, nombre=nombre_cat, subcategoria=subcategoria, es_sistema=True,
                )

            for nombre_categoria in CATEGORIAS_GASTO:
                CategoriaGasto.objects.using(conexion).create(tenant=tenant, nombre=nombre_categoria)

            for orden, nombre_grupo in enumerate(GRUPOS_MUSCULARES):
                GrupoMuscular.objects.using(conexion).create(
                    tenant=tenant, nombre=nombre_grupo, orden=orden,
                )

            crear = (
                Usuario.objects.db_manager(conexion).create_superuser
                if con_admin_django
                else Usuario.objects.db_manager(conexion).create_user
            )
            usuario_admin = crear(
                correo=correo_admin,
                nombre=f'Administrador de {nombre}',
                tenant=tenant,
                rol=roles['administrador'],
                password=password_admin,
            )

            UsuarioSede.objects.using(conexion).create(
                usuario=usuario_admin, sede=sede, tenant=tenant,
            )

    return tenant, sede, usuario_admin
