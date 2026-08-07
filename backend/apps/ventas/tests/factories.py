"""Fábrica de datos para la batería de ventas/POS (Parte E del encargo).

``crear_escenario_pos`` siembra, para UN tenant, todo lo que necesita el
módulo de ventas para operar de verdad: DOS sedes (cada una con su propia
``SecuenciaComprobante``, para poder probar que el consecutivo es
independiente por sede), dos roles (uno con todos los permisos relevantes,
otro "recepcionista" sin ``costos.ver`` ni ``ventas.anular``, igual que en
``crear_tenant`` real), un cliente, un producto CON stock inicial sembrado a
través del propio trigger de la Parte B (una ``MovimientoInventario`` de
``entrada_compra``, no un INSERT directo a ``stock_sedes``: así esta fábrica
también ejercita el trigger en cada test que la usa) y dos planes (uno
mensual, uno por sesión).

Las categorías de ingreso sembradas son las MISMAS que ``crear_tenant``
siembra en producción (mismos nombres/subcategorías) -- la derivación
automática de categoría (RF-07, ``services._derivar_categoria_ingreso_*``)
depende de que existan filas con esos nombres exactos.
"""
import datetime
from decimal import Decimal

from apps.clientes.models import Cliente
from apps.core.tenant import tenant_context
from apps.inventario.models import CategoriaProducto, MovimientoInventario, Producto
from apps.membresias.models import Plan
from apps.organizacion.models import Permiso, Rol, RolPermiso, SecuenciaComprobante, Sede, Usuario, UsuarioSede
from apps.plataforma.models import Tenant
from apps.ventas.models import CategoriaIngreso

PASSWORD = 'clave-super-segura-123'

# Igual que RF-07 / crear_tenant.py: subcategorías de producto, plan y
# entrenamiento personalizado.
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

# Subconjunto de PERMISOS_POR_ROL de crear_tenant.py, suficiente para
# ejercitar la API de ventas (incluye 'costos.ver' y 'ventas.anular' SOLO en
# el rol admin, para poder probar exactamente su ausencia en recepcionista).
PERMISOS_ADMIN = (
    'ventas.registrar', 'ventas.anular', 'ventas.descuento',
    'inventario.ver', 'inventario.gestionar', 'costos.ver',
    'clientes.ver', 'clientes.gestionar', 'membresias.gestionar', 'reportes.ver',
)
PERMISOS_RECEPCIONISTA = (
    'ventas.registrar',
    'inventario.ver',
    'clientes.ver',
    'membresias.gestionar',
    'reportes.ver',
)


def crear_escenario_pos(subdominio, sufijo, using='default'):
    """Crea un tenant listo para probar ventas.

    :return: dict con las instancias creadas: ``tenant``, ``sede``, ``sede2``
        (segunda sede del MISMO tenant, para probar consecutivos
        independientes), ``rol_admin``, ``rol_recepcion``, ``usuario_admin``
        (con TODOS los permisos, incluido ``costos.ver``/``ventas.anular``),
        ``usuario_recepcion`` (sin esos dos), ``cliente``,
        ``categoria_producto``, ``producto`` (con 100 unidades de stock ya
        sembradas EN ``sede``, ninguna en ``sede2``), ``plan_mensual``
        (30 días de duración) y ``plan_sesion`` (``tipo='por_sesion'``, sin
        duración: nunca genera membresía).
    """
    tenant = Tenant.objects.using(using).create(
        nombre_comercial=f'Gimnasio {sufijo}',
        subdominio=subdominio,
        responsable=f'Responsable {sufijo}',
        correo=f'contacto.{subdominio}@example.com',
    )

    with tenant_context(tenant.id, using=using):
        sede = Sede.objects.using(using).create(
            tenant=tenant, nombre=f'Sede {sufijo} 1', direccion=f'Calle {sufijo} 1-11',
        )
        SecuenciaComprobante.objects.using(using).create(sede=sede, tenant=tenant)

        sede2 = Sede.objects.using(using).create(
            tenant=tenant, nombre=f'Sede {sufijo} 2', direccion=f'Calle {sufijo} 2-22',
        )
        SecuenciaComprobante.objects.using(using).create(sede=sede2, tenant=tenant)

        rol_admin = Rol.objects.using(using).create(
            tenant=tenant, nombre=f'Administrador {sufijo}', es_sistema=True,
        )
        rol_recepcion = Rol.objects.using(using).create(
            tenant=tenant, nombre=f'Recepcionista {sufijo}', es_sistema=True,
        )

        permisos_por_codigo = {p.codigo: p for p in Permiso.objects.using(using).all()}
        RolPermiso.objects.using(using).bulk_create([
            RolPermiso(rol=rol_admin, permiso=permisos_por_codigo[codigo], tenant=tenant)
            for codigo in PERMISOS_ADMIN
        ])
        RolPermiso.objects.using(using).bulk_create([
            RolPermiso(rol=rol_recepcion, permiso=permisos_por_codigo[codigo], tenant=tenant)
            for codigo in PERMISOS_RECEPCIONISTA
        ])

        usuario_admin = Usuario.objects.db_manager(using).create_user(
            correo=f'admin.{subdominio}@example.com', nombre=f'Admin {sufijo}',
            tenant=tenant, rol=rol_admin, password=PASSWORD,
        )
        usuario_recepcion = Usuario.objects.db_manager(using).create_user(
            correo=f'recepcion.{subdominio}@example.com', nombre=f'Recepción {sufijo}',
            tenant=tenant, rol=rol_recepcion, password=PASSWORD,
        )

        # Ambos trabajan en `sede`, como cualquier usuario real: el alta de un
        # gimnasio (`aprovisionar_tenant`) también asigna al administrador a
        # su sede inicial.
        #
        # Es imprescindible desde que la lectura se acota por sede
        # (`apps.core.sedes`): un usuario sin ninguna sede asignada no ve
        # ventas ni informes, y estas pruebas se quedarían comprobando ceros.
        UsuarioSede.objects.using(using).bulk_create([
            UsuarioSede(usuario=usuario_admin, sede=sede, tenant=tenant),
            UsuarioSede(usuario=usuario_recepcion, sede=sede, tenant=tenant),
        ])

        cliente = Cliente.objects.using(using).create(
            tenant=tenant, sede_origen=sede, nombre=f'Cliente {sufijo}',
            cedula=f'CED-{sufijo}-0001', telefono='3000000000', direccion='Calle 1 # 2-3',
        )

        categoria_producto = CategoriaProducto.objects.using(using).create(
            tenant=tenant, nombre='Suplementos',
        )
        producto = Producto.objects.using(using).create(
            tenant=tenant, categoria_producto=categoria_producto,
            nombre=f'Proteína {sufijo}', precio_venta=Decimal('60000.00'), costo=Decimal('35000.00'),
        )
        # Siembra el stock inicial vía el trigger de la Parte B (no un
        # INSERT directo a stock_sedes): así queda ejercitado también aquí.
        MovimientoInventario.objects.using(using).create(
            tenant=tenant, producto=producto, sede=sede, usuario=usuario_admin,
            tipo=MovimientoInventario.TipoMovimiento.ENTRADA_COMPRA,
            cantidad=Decimal('100'), saldo_resultante=Decimal('0'), costo_unitario=producto.costo,
        )

        for nombre_cat, subcategoria in CATEGORIAS_INGRESO:
            CategoriaIngreso.objects.using(using).create(
                tenant=tenant, nombre=nombre_cat, subcategoria=subcategoria, es_sistema=True,
            )

        plan_mensual = Plan.objects.using(using).create(
            tenant=tenant, nombre=f'Mensual {sufijo}', tipo=Plan.TipoPlan.MENSUAL,
            duracion_dias=30, precio=Decimal('80000.00'),
        )
        plan_sesion = Plan.objects.using(using).create(
            tenant=tenant, nombre=f'Sesión {sufijo}', tipo=Plan.TipoPlan.POR_SESION,
            precio=Decimal('15000.00'),
        )

    return {
        'tenant': tenant,
        'sede': sede,
        'sede2': sede2,
        'rol_admin': rol_admin,
        'rol_recepcion': rol_recepcion,
        'usuario_admin': usuario_admin,
        'usuario_recepcion': usuario_recepcion,
        'cliente': cliente,
        'categoria_producto': categoria_producto,
        'producto': producto,
        'plan_mensual': plan_mensual,
        'plan_sesion': plan_sesion,
    }
